import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import re
import pytz
import firebase_admin
from firebase_admin import credentials, firestore
import openai
import zipfile
import docx
import random 
import numpy as np
from docx.shared import Inches
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Pt

def set_cell_border(cell, top=None, bottom=None, left=None, right=None):
    """
    Set cell borders. Each argument (top/bottom/left/right) is a dict of border attributes:
      {
        "sz": "12",       # border width
        "val": "single",  # single, double, etc.
        "color": "000000" # hex color code (omit #)
      }
    Example usage:
      set_cell_border(cell,
                      top={"sz": "12", "val": "single", "color": "000000"},
                      left={"sz": "12", "val": "single", "color": "000000"})
    """
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    
    # Map python-docx edge names to the w: tag names
    # "left" -> "w:left", etc.
    borders = {
        'top': 'w:top',
        'bottom': 'w:bottom',
        'left': 'w:left',
        'right': 'w:right'
    }
    
    for edge, edge_data in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        if edge_data:
            tag = borders[edge]
            element = tcPr.find(qn(tag))
            if element is None:
                element = OxmlElement(tag)
                tcPr.append(element)
            
            for key, value in edge_data.items():
                element.set(qn(f"w:{key}"), str(value))



def generate_spotlight_summary(strengths_preceptor, Evaluator):
    prompt = f"""
    You are an expert in pediatric medical education.

    Based on the following strengths feedback for {Evaluator}:
    {strengths_preceptor}

    Provide a concise summary of why this preceptor deserves to be in the spotlight.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert in pediatric medical education."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=150,
    )
    return response['choices'][0]['message']['content'].strip()


def check_and_add_record(record_id):
    # Ensure the record_id is a string
    record_id_str = str(record_id)
    doc_ref = db.collection("preceptors").document(record_id_str)
    
    # If the record does not exist, add it
    if not doc_ref.get().exists:
        # Optionally, you can add additional data (like a timestamp) in the document
        doc_ref.set({"processed": True})
        return False  # Indicates the record was not previously processed
    else:
        return True  # Indicates the record already exists

        
def strengths(strengths_preceptor, Evaluator):
    prompt = f"""
    You are an expert in pediatric medical education.

    {Evaluator} received the following feedback regarding their performance as a preceptor in a pediatric clerkship:
    {strengths_preceptor}

    Please provide a concise summary of {Evaluator}'s strengths.
    In your summary, refer to the individual by name (using their first and last name and/or “Dr. Lastname”) when describing actions or behaviors.
    Assume that the feedback pertains exclusively to one individual.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert in pediatric medical education."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=500,
    )
    return response['choices'][0]['message']['content'].strip()

def improvement(improvement_preceptor, Evaluator):
    prompt = f"""
    You are an expert in pediatric medical education.

    {Evaluator} received the following feedback regarding opportunities for improvement as a preceptor in a pediatric clerkship:
    {improvement_preceptor}

    Please provide a concise summary of {Evaluator}'s opportunities for improvement.
    In your summary, refer to the individual by name (using their first and last name and/or “Dr. Lastname”) when describing actions or behaviors.
    Assume that the feedback pertains exclusively to one individual.
    """
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert in pediatric medical education."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=500,
    )
    return response['choices'][0]['message']['content'].strip()


    
########################################
# 1) OPENAI & FIREBASE SETUP
########################################

openai.api_key = st.secrets["openai"]["api_key"]

firebase_creds = st.secrets["firebase_service_account"].to_dict()
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

########################################
# 2) DISPLAY UPLOAD SECTIONS
########################################

st.title("Faculty Analysis Report & Evaluation Due Dates Upload")

# Create two columns to display both upload buttons side by side
col1, col2 = st.columns(2)

with col1:
    st.subheader("Evaluation Due Dates")
    st.markdown("[Student Performance Report](https://oasis.hersheymed.net/admin/course/e_manage/student_performance/setup_analysis_report.html)")
    # File uploader for evaluation due dates (adjust allowed types as needed)
    evaluation_due_dates_file = st.file_uploader("Upload Evaluation Due Dates", type=["csv", "xlsx", "pdf"])
    
with col2:
    st.subheader("Setup Analysis Report")
    # Embed the website so users can view it directly
    st.markdown("[Faculty Evaluations](https://oasis.hersheymed.net/admin/course/e_manage/faculty/setup_analysis_report.html)")
    analysis_report_file = st.file_uploader("Upload Analysis Report", type=["pdf", "docx", "csv"])

if evaluation_due_dates_file is not None:
    try:
        # Determine the file type and load accordingly
        if evaluation_due_dates_file.name.endswith("csv"):
            dfe = pd.read_csv(evaluation_due_dates_file)
        elif evaluation_due_dates_file.name.endswith("xlsx"):
            dfe = pd.read_excel(evaluation_due_dates_file)
        # Display the DataFrame in the app
        dfe = dfe.loc[dfe['Location'] != "LIC - Kaiser Permanente"]
        dfe = dfe[['Evaluator', 'Submit Date', 'End Date']]

        # Convert the date columns to datetime format
        dfe['Submit Date'] = pd.to_datetime(dfe['Submit Date'])
        dfe['End Date'] = pd.to_datetime(dfe['End Date'])
        
        # Calculate the difference in days between Submit Date and End Date
        dfe['diff_days'] = (dfe['Submit Date'] - dfe['End Date']).dt.days
        
        # Create a boolean flag for evaluations that are less than or equal to 14 days
        dfe['on_time'] = dfe['diff_days'] <= 14
        
        grouped = dfe.groupby('Evaluator').agg(total_evaluations=('Evaluator', 'size'),on_time_evaluations=('on_time', 'sum'))
        
        # Calculate the percentage of on-time evaluations per evaluator
        grouped['percentage_on_time'] = ((grouped['on_time_evaluations'] / grouped['total_evaluations']) * 100).round(1)

        st.dataframe(grouped)
        grouped = grouped.reset_index()
        # Now, if you still need to set it as the index for further operations:
        grouped = grouped.set_index('Evaluator')

        

    except Exception as e:
        st.error(f"Error loading file: {e}")

if analysis_report_file is not None:
    try:
        # Determine the file type and load accordingly
        if analysis_report_file.name.endswith("csv"):
            dfa = pd.read_csv(analysis_report_file)
        elif analysis_report_file.name.endswith("xlsx"):
            dfa = pd.read_excel(analysis_report_file)
        # Display the DataFrame in the app

        ###########################################################################################
        # First, filter the DataFrame based on Firebase:
        #dfa = dfa[~dfa["Form Record"].apply(lambda record: check_and_add_record(record))]
        ###########################################################################################
        
        selected_indices = [4, 5, 16, 19, 23, 27, 30, 34, 37, 41, 44, 48, 51, 55, 58, 62,65, 69, 72, 76, 79, 83, 86, 90, 93, 97, 100, 104, 107, 111, 114, 118, 121, 125, 128, 132, 135, 139, 143, 146, 147, 153, 154]
        dfa = dfa.iloc[:, selected_indices]
        #st.dataframe(dfa)
        #st.write(list(dfa.columns))

        df = dfa.copy()
        rename_mapping = {}
        # Loop through columns to find ones with the pattern "<number> Question"
        for col in df.columns:
            m = re.match(r'^(\d+)\s+Question$', col)
            if m:
                num = m.group(1)
                # Try different possible suffixes for the corresponding answer column
                for suffix in ["Multiple Choice Value", "Multiple Choice Label", "Answer text"]:
                    answer_col = f"{num} {suffix}"
                    if answer_col in df.columns:
                        # Use the question text from the first row of the question column
                        question_text = df[col].iloc[0] if not df[col].empty else col
                        rename_mapping[answer_col] = question_text
                        break  # stop after the first matching answer column

        # Rename the answer columns with the question text
        df.rename(columns=rename_mapping, inplace=True)

        # Optionally, remove the question columns if they are no longer needed
        question_columns = [col for col in df.columns if re.match(r'^\d+\s+Question$', col)]
        df.drop(columns=question_columns, inplace=True)
        #st.write(list(df.columns))
        #st.dataframe(df)

        df['Rotation Period'] = pd.to_datetime(df.iloc[:, 0], errors='coerce').dt.strftime('%B %Y')
    
        # --- Step 2. Drop Unneeded Date Columns ---
        # Drop 'Start Date' (col 0) and 'End Date' (col 1)
        df.drop(df.columns[[0, 1]], axis=1, inplace=True)
        
        # --- Step 3. Drop the Unwanted Time Column ---
        df.drop(df.columns[19], axis=1, inplace=True)
        
        # --- Step 4. Rename the Text Columns ---
        # After dropping one column, the strengths and improvement columns are now at positions 19 and 20 respectively.
        df.columns.values[19] = "strengths_preceptor"
        df.columns.values[20] = "improvement_preceptor"
        
        # --- Step 5. Convert Evaluation Score Columns to Numeric ---
        # The evaluation questions are now columns 3 to 18. We refer to them by position.
        score_cols = df.columns[3:19]
        df[score_cols] = df[score_cols].apply(pd.to_numeric, errors='coerce')
        
        # --- Step 6. Group by Evaluator (and Rotation Period) and Aggregate ---
        # If an evaluator appears more than once for a given rotation period, we’ll compute the mean for each question.
        # We also include Evaluator Email and Form Record as identifying columns.
        group_cols = ["Evaluator", "Evaluator Email", "Rotation Period", "Form Record"]
        
        # For the score columns, take the mean.
        agg_dict = {col: 'mean' for col in score_cols}
        # For text responses, combine unique responses (ignoring NaN) using a separator.
        agg_dict["strengths_preceptor"] = lambda x: ' | '.join(x.dropna().unique())
        agg_dict["improvement_preceptor"] = lambda x: ' | '.join(x.dropna().unique())
        
        # Group the DataFrame by the identifying columns and aggregate
        df_grouped = df.groupby(group_cols, as_index=False).agg(agg_dict)
        
        # --- (Optional) Reorder Columns for Clarity ---
        ordered_columns = group_cols + list(score_cols) + ["strengths_preceptor", "improvement_preceptor"]
        df_grouped = df_grouped[ordered_columns]
        
        # Display the final aggregated DataFrame in your Streamlit app
        #st.dataframe(df_grouped)

        final_group_cols = ["Evaluator", "Evaluator Email"]
        
        agg_funcs = {
            # For Rotation Period: convert each unique item to a string before joining with a comma
            "Rotation Period": lambda x: ", ".join([str(item) for item in sorted(set(x.dropna()))]),
            # For strengths and improvements: convert each unique item to a string before joining with a newline
            "strengths_preceptor": lambda x: "\n".join([str(item) for item in x.dropna().unique()]),
            "improvement_preceptor": lambda x: "\n".join([str(item) for item in x.dropna().unique()])
        }
        
        # Identify the evaluation score columns (all numeric columns not already in our aggregation)
        score_columns = [col for col in df_grouped.columns 
                         if col not in ["Evaluator", "Evaluator Email", "Rotation Period", 
                                        "strengths_preceptor", "improvement_preceptor", "Form Record"]]
        
        # For each score column, take the mean (this will average the score for each question)
        for col in score_columns:
            agg_funcs[col] = "mean"
        
        # Optionally, aggregate the Form Record if needed (or drop it)
        if "Form Record" in df_grouped.columns:
            agg_funcs["Form Record"] = lambda x: ", ".join([str(item) for item in x.dropna().unique()])
            
        df_grouped["num_evaluations"] = 1

        # Extend your aggregation dictionary to sum the number of evaluations
        agg_funcs["num_evaluations"] = "sum"
        
        # Group by Evaluator and Evaluator Email using the updated aggregation functions
        final_group_cols = ["Evaluator", "Evaluator Email"]
        df_final = df_grouped.groupby(final_group_cols, as_index=False).agg(agg_funcs)

        #############################################################################################################################
        df_final["strengths_summary"] = "test"
        df_final["improvement_summary"] = "test"
        
        #df_final["strengths_summary"] = df_final.apply(lambda row: strengths(row["strengths_preceptor"], row["Evaluator"]), axis=1)
        #df_final["improvement_summary"] = df_final.apply(lambda row: improvement(row["improvement_preceptor"], row["Evaluator"]), axis=1)
        #############################################################################################################################
        
        # Map the values to df_final
        df_final['total_evaluations'] = df_final['Evaluator'].map(grouped['total_evaluations'])
        df_final['percentage_on_time'] = df_final['Evaluator'].map(grouped['percentage_on_time'])

        
        # Display the final aggregated DataFrame with the count of evaluations
        st.dataframe(df_final)
        
        # --- STEP 1: Identify Eligible Preceptors ---
        # Define the known text fields to identify numeric score columns.
        known_cols = {"Evaluator", "Evaluator Email", "Rotation Period", "strengths_preceptor", "improvement_preceptor", "strengths_summary", "improvement_summary", "num_evaluations", "Form Record", "total_evaluations", "percentage_on_time"}
        
        # Identify evaluation score columns as those numeric columns not in known_cols.
        score_cols = [col for col in df_final.columns if col not in known_cols and pd.api.types.is_numeric_dtype(df_final[col])]
        
        # Filter for eligible preceptors: every evaluation score must be 4.5 or above.
        eligible_df = df_final[df_final[score_cols].ge(4.5).all(axis=1)].copy()

        ###########################################################################################
        # Retrieve already spotlighted evaluators from Firebase.
        #spotlight_docs = db.collection("spotlight").stream()
        #spotlight_evaluators = {doc.to_dict().get("Evaluator") for doc in spotlight_docs}        
        # Exclude evaluators already in the spotlight.
        #eligible_df = eligible_df[~eligible_df["Evaluator"].isin(spotlight_evaluators)]
        ###########################################################################################
        
        if eligible_df.empty:
            st.info("No eligible preceptors found for the spotlight this month.")
        else:
            # --- STEP 2: Randomly Select a Spotlight Candidate ---
            selected_candidate = eligible_df.sample(n=1).iloc[0]

            ###########################################################################################
            # Generate a spotlight summary using ChatGPT (based on the strengths feedback)
            #spotlight_reason = generate_spotlight_summary(selected_candidate["strengths_preceptor"], selected_candidate["Evaluator"])
            spotlight_reason = "test"
            ###########################################################################################
            
            # Add the spotlight summary to the DataFrame (if desired)
            df_final.loc[df_final["Evaluator"] == selected_candidate["Evaluator"], "spotlight_summary"] = spotlight_reason
            
            # --- STEP 3: Upload the Spotlight Record to Firebase ---
            # Use the evaluator's name as the document ID.
            record = {
                "Evaluator": selected_candidate["Evaluator"],
                "Evaluator Email": selected_candidate["Evaluator Email"],
                "Form Record": str(selected_candidate["Form Record"]),
                "spotlight_summary": spotlight_reason,
                "Rotation Period": selected_candidate["Rotation Period"],
                "num_evaluations": int(selected_candidate["num_evaluations"]),  # convert to Python int
                "strengths_preceptor": selected_candidate["strengths_preceptor"],
                "improvement_preceptor": selected_candidate["improvement_preceptor"]
            }


            ###########################################################################################
            #db.collection("spotlight").document(selected_candidate["Evaluator"]).set(record)
            #st.success(f"Spotlight selected: {selected_candidate['Evaluator']}")
            ###########################################################################################
            
            # --- STEP 4: Create a Word Document for the Spotlight Candidate ---
            document = docx.Document()
            
            document.add_heading(f"Spotlight Preceptor: {selected_candidate['Evaluator']}", level=1)
            document.add_paragraph(f"Email: {selected_candidate['Evaluator Email']}")
            document.add_paragraph(f"Number of Evaluations: {selected_candidate['num_evaluations']}")
            document.add_paragraph(f"Rotation Period(s): {selected_candidate['Rotation Period']}")
            
            document.add_heading("Evaluation Scores", level=2)
            for col in df_final.columns:
                if col not in known_cols and pd.api.types.is_numeric_dtype(df_final[col]):
                    # Remove any trailing period from the column name.
                    clean_col = col.rstrip('.')
                    document.add_paragraph(f"{clean_col}: {selected_candidate[col]:.2f}")
            
            document.add_heading("Strengths Comments", level=2)
            document.add_paragraph(str(selected_candidate["strengths_preceptor"]))
            
            document.add_heading("Opportunities for Improvement Comments", level=2)
            document.add_paragraph(str(selected_candidate["improvement_preceptor"]))
            
            document.add_heading("Spotlight Summary", level=2)
            document.add_paragraph(spotlight_reason)
            
            # --- STEP 5: Provide a Download Button for the Word Document ---
            doc_buffer = io.BytesIO()
            document.save(doc_buffer)
            doc_buffer.seek(0)
            
            st.download_button(label="Download Spotlight Word Document", data=doc_buffer, file_name=f"{selected_candidate['Evaluator']}_spotlight.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",key="download_spotlight_doc")


        # Create an in-memory zip file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Loop through each evaluator in df_final
            for idx, row in df_final.iterrows():
                # Create a new Word document for each evaluator
                document = docx.Document()
                document.styles['Normal'].paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
                document.styles['Normal'].paragraph_format.space_before = Pt(0)
                document.styles['Normal'].paragraph_format.space_after = Pt(0)

                
                table = document.add_table(rows=1, cols=2)
                table.style = 'Table Grid'
                #table.autofit = False  # Prevent automatic adjustment of column widths
                
                # Set each column to 3 inches wide
                table.columns[0].width = Inches(3)
                table.columns[1].width = Inches(3.14)
                
                # Access the cells of the first row
                cell_label = table.rows[0].cells[0]
                cell_value = table.rows[0].cells[1]
                
                # Add bolded "Preceptor:" in the first cell
                p_label = cell_label.paragraphs[0]
                run_label = p_label.add_run("Preceptor: ")
                run_label.bold = True
                
                # Add the preceptor name from your data in the second cell
                p_value = cell_value.paragraphs[0]
                p_value.add_run(row['Evaluator'])
                
                document.add_paragraph("")
                
                # Create a 4-row, 2-column table
                details_table = document.add_table(rows=5, cols=2)
                details_table.style = 'Table Grid'  # Or use your custom border logic
                
                # Define column widths if desired
                col_width_left = Inches(3.0)
                col_width_right = Inches(3.14)
                
                # Row 0: Email
                #details_table.cell(0, 0).text = "Email:"
                #details_table.cell(0, 1).text = str(row['Evaluator Email'])

                header_row = details_table.rows[0]
                header_cells = header_row.cells
                header_cells[0].text = "Evaluation Metric"
                header_cells[1].text = "Result"
                
                # Bold the header text
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.bold = True
                

                # Row 1: Rotation Periods
                details_table.cell(1, 0).text = "Rotation Period:"
                details_table.cell(1, 1).text = str(row['Rotation Period'])

                # Row 2: Number of Evaluations
                details_table.cell(2, 0).text = "Number of Evaluations:"
                details_table.cell(2, 1).text = str(row['num_evaluations'])
                
                # Row 3: Number of Student Evaluations Completed by Evaluator
                details_table.cell(3, 0).text = "Number of Student Evaluations Completed by Evaluator:"
                details_table.cell(3, 1).text = str(row['total_evaluations'])
                
                # Row 4: Percentage of Student Evaluations Completed within 14 days
                details_table.cell(4, 0).text = "Percentage of Student Evaluations Completed within 14 days:"
                details_table.cell(4, 1).text = f"{row['percentage_on_time']:.1f}%"

                
                # Optionally set column widths
                for row_idx in range(4):
                    details_table.cell(row_idx, 0).width = col_width_left
                    details_table.cell(row_idx, 1).width = col_width_right
    
                # Write evaluation question scores.
                # Assume that the remaining numeric columns (not part of the known text fields) are the evaluation questions.
                known_cols = {
                    "Evaluator", "Evaluator Email", "Rotation Period", "strengths_preceptor",
                    "improvement_preceptor", "strengths_summary", "improvement_summary",
                    "num_evaluations", "Form Record"
                }
                #document.add_heading("Evaluation Average Scores", level=2)
                
                document.add_paragraph("")
                
                # Define a standard border style
                border_style = {"sz": "12", "val": "single", "color": "000000"}
                
                # Create the table (1 header row, 2 columns)
                table = document.add_table(rows=1, cols=2)
                # Do NOT set table.style = 'Table Grid' because we want to manually control borders
                
                # Define column widths
                evaluator_col_width = Inches(6.45)
                score_col_width = Inches(0.63)
                
                # 1) Configure the header row
                header_row = table.rows[0]
                header_cells = header_row.cells
                header_cells[0].text = "Evaluation Question"
                header_cells[1].text = "Average Score"
                
                # Bold the header text
                for cell in header_cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.bold = True
                
                # Set the header cell widths
                header_cells[0].width = evaluator_col_width
                header_cells[1].width = score_col_width
                
                # For the header row:
                # - keep top/bottom/left/right, but remove the vertical line in the middle
                set_cell_border(header_cells[0],
                    top=border_style,
                    bottom=border_style,
                    left=border_style
                    # no right border here => removes middle line
                )
                set_cell_border(header_cells[1],
                    top=border_style,
                    bottom=border_style,
                    right=border_style
                    # no left border => removes middle line
                )
                
                # 2) Add data rows
                # Suppose 'question_columns' is a list of the columns that hold numeric data
                question_columns = [col for col in df_final.columns 
                                    if col not in known_cols 
                                    and pd.api.types.is_numeric_dtype(df_final[col])]
                
                for i, col in enumerate(question_columns):
                    row_cells = table.add_row().cells
                    row_cells[0].text = col.rstrip('.')  # question
                    row_cells[1].text = f"{row[col]:.2f}"  # average score
                    
                    # Set widths
                    row_cells[0].width = evaluator_col_width
                    row_cells[1].width = score_col_width
                    
                    # For each data row: remove top/bottom to avoid horizontal lines between rows
                    # Keep left and right borders. 
                    # We'll add a bottom border only if it's the last row, to "close" the table.
                    is_last_row = (i == len(question_columns) - 1)
                    
                    set_cell_border(row_cells[0],
                        left=border_style,
                        bottom=border_style if is_last_row else None
                    )
                    set_cell_border(row_cells[1],
                        right=border_style,
                        bottom=border_style if is_last_row else None
                    )
                # Write rotation period(s)
                #document.add_heading("Rotation Period(s)", level=2)
                
                
                # Write all strengths and opportunities for improvement comments
                document.add_heading("Strengths Comments", level=2)
                document.add_paragraph(str(row["strengths_preceptor"]))
                document.add_heading("Opportunities for Improvement Comments", level=2)
                document.add_paragraph(str(row["improvement_preceptor"]))
                
                # Write the summary fields
                document.add_heading("Strengths Summary", level=2)
                document.add_paragraph(str(row["strengths_summary"]))
                document.add_heading("Opportunities for Improvement Summary", level=2)
                document.add_paragraph(str(row["improvement_summary"]))
                
                # Save the document to a temporary in-memory buffer
                doc_buffer = io.BytesIO()
                document.save(doc_buffer)
                doc_buffer.seek(0)
                
                # Create a filename safe for the evaluator (using evaluator's name)
                safe_name = "".join(c for c in row['Evaluator'] if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
                filename = f"{safe_name}.docx"
                
                # Write the Word file to the zip archive
                zipf.writestr(filename, doc_buffer.read())
        
        # Finalize the zip file and get its binary content
        zip_buffer.seek(0)
        zip_data = zip_buffer.getvalue()
        
        # Provide a download button for the zip file (Streamlit)
        st.download_button(label="Download Evaluator Word Files",data=zip_data,file_name="evaluators.zip",mime="application/zip",key="download_evaluators_zip")

    except Exception as e:
        st.error(f"Error loading file: {e}")
        


