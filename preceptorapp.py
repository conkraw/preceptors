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
    st.subheader("Setup Analysis Report")
    # Embed the website so users can view it directly
    st.markdown("[View Setup Analysis Report](https://oasis.hersheymed.net/admin/course/e_manage/faculty/setup_analysis_report.html)")

    analysis_report_file = st.file_uploader("Upload Analysis Report", type=["pdf", "docx", "csv"])

with col2:
    st.subheader("Evaluation Due Dates")
    # File uploader for evaluation due dates (adjust allowed types as needed)
    evaluation_due_dates_file = st.file_uploader("Upload Evaluation Due Dates", type=["csv", "xlsx", "pdf"])

if analysis_report_file is not None:
    try:
        # Determine the file type and load accordingly
        if analysis_report_file.name.endswith("csv"):
            dfa = pd.read_csv(analysis_report_file)
        elif analysis_report_file.name.endswith("xlsx"):
            dfa = pd.read_excel(analysis_report_file)
        # Display the DataFrame in the app

        dfa = dfa[~dfa["Form Record"].apply(lambda record: check_and_add_record(record))]


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

        #df_final["strengths_summary"] = df_final.apply(lambda row: strengths(row["strengths_preceptor"], row["Evaluator"]), axis=1)
        #df_final["improvement_summary"] = df_final.apply(lambda row: improvement(row["improvement_preceptor"], row["Evaluator"]), axis=1)

        # Display the final aggregated DataFrame with the count of evaluations
        st.dataframe(df_final)

        # Create an in-memory zip file
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            # Loop through each evaluator in df_final
            for idx, row in df_final.iterrows():
                # Create a new Word document for each evaluator
                document = docx.Document()
                
                # Write header info: evaluator's name, email, and number of evaluations
                document.add_heading(f"Evaluator: {row['Evaluator']}", level=1)
                document.add_paragraph(f"Email: {row['Evaluator Email']}")
                document.add_paragraph(f"Number of Evaluations: {row['num_evaluations']}")
                
                # Write evaluation question scores.
                # Assume that the remaining numeric columns (not part of the known text fields) are the evaluation questions.
                known_cols = {"Evaluator", "Evaluator Email", "Rotation Period", 
                              "strengths_preceptor", "improvement_preceptor", 
                              "strengths_summary", "improvement_summary", 
                              "num_evaluations", "Form Record"}
                document.add_heading("Evaluation Scores", level=2)
                for col in df_final.columns:
                    if col not in known_cols and pd.api.types.is_numeric_dtype(df_final[col]):
                        # Write each question on one line with its average score formatted to 2 decimals
                        clean_col = col.rstrip('.')
                        document.add_paragraph(f"{col}: {row[col]:.2f}")
                
                # Write rotation period(s)
                document.add_heading("Rotation Period(s)", level=2)
                document.add_paragraph(str(row["Rotation Period"]))
                
                # Write all strengths and opportunities for improvement comments
                #document.add_heading("Strengths Comments", level=2)
                #document.add_paragraph(str(row["strengths_preceptor"]))
                #document.add_heading("Opportunities for Improvement Comments", level=2)
                #document.add_paragraph(str(row["improvement_preceptor"]))
                
                # Write the summary fields
                #document.add_heading("Strengths Summary", level=2)
                #document.add_paragraph(str(row["strengths_summary"]))
                #document.add_heading("Opportunities for Improvement Summary", level=2)
                #document.add_paragraph(str(row["improvement_summary"]))
                
                # Save the document to a temporary in-memory buffer
                doc_buffer = io.BytesIO()
                document.save(doc_buffer)
                doc_buffer.seek(0)
                
                # Create a filename safe for the evaluator (using evaluator's name)
        #        safe_name = "".join(c for c in row['Evaluator'] if c.isalnum() or c in (' ', '_')).rstrip().replace(" ", "_")
        #        filename = f"{safe_name}.docx"
                
                # Write the Word file to the zip archive
        #        zipf.writestr(filename, doc_buffer.read())
        
        # Finalize the zip file and get its binary content
        #zip_buffer.seek(0)
        #zip_data = zip_buffer.getvalue()
        
        # Provide a download button for the zip file (Streamlit)
        #st.download_button(label="Download Evaluator Word Files",data=zip_data,file_name="evaluators.zip",mime="application/zip")

    except Exception as e:
        st.error(f"Error loading file: {e}")
        
if evaluation_due_dates_file is not None:
    try:
        # Determine the file type and load accordingly
        if evaluation_due_dates_file.name.endswith("csv"):
            dfe = pd.read_csv(evaluation_due_dates_file)
        elif evaluation_due_dates_file.name.endswith("xlsx"):
            dfe = pd.read_excel(evaluation_due_dates_file)
        # Display the DataFrame in the app
        st.dataframe(dfe)
    except Exception as e:
        st.error(f"Error loading file: {e}")



