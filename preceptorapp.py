import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import re
import pytz
import firebase_admin
from firebase_admin import credentials, firestore
import openai
from docx import Document
from io import BytesIO
from datetime import datetime

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
    st.markdown("[View Setup Analysis Report](https://oasis.hersheymed.net/admin/course/e_manage/faculty/setup_analysis_report.html)")
    analysis_report_file = st.file_uploader("Upload Analysis Report", type=["pdf", "docx", "csv", "xlsx"])

with col2:
    st.subheader("Evaluation Due Dates")
    evaluation_due_dates_file = st.file_uploader("Upload Evaluation Due Dates", type=["csv", "xlsx", "pdf"])

########################################
# 3) PROCESS ANALYSIS REPORT FILE
########################################

if analysis_report_file is not None:
    try:
        # Load the file based on its extension
        if analysis_report_file.name.endswith("csv"):
            dfa = pd.read_csv(analysis_report_file)
        elif analysis_report_file.name.endswith("xlsx"):
            dfa = pd.read_excel(analysis_report_file)
        else:
            st.error("Unsupported file type for analysis report.")
            dfa = None

        if dfa is not None:
            # Select only the desired columns (these are assumed to be 0-indexed)
            selected_indices = [4, 5, 16, 19, 23, 27, 30, 34, 37, 41, 44, 48, 51, 55, 58, 62,
                                65, 69, 72, 76, 79, 83, 86, 90, 93, 97, 100, 104, 107, 111,
                                114, 118, 121, 125, 128, 132, 135, 139, 143, 146, 147, 153, 154]
            dfa_selected = dfa.iloc[:, selected_indices].copy()
            df = dfa_selected.copy()

            # If evaluator and date info are missing in the selected data, add them from the full DataFrame.
            for col in ["Evaluator", "Evaluator Email", "Start Date", "End Date"]:
                if col not in df.columns and col in dfa.columns:
                    df[col] = dfa[col]

            # Rename answer columns based on the corresponding question column's first row text.
            rename_mapping = {}
            for col in df.columns:
                m = re.match(r'^(\d+)\s+Question$', col)
                if m:
                    num = m.group(1)
                    for suffix in ["Multiple Choice Value", "Multiple Choice Label", "Answer text"]:
                        answer_col = f"{num} {suffix}"
                        if answer_col in df.columns:
                            question_text = df[col].iloc[0] if not df[col].empty else col
                            rename_mapping[answer_col] = question_text
                            break
            df.rename(columns=rename_mapping, inplace=True)

            # Optionally, remove the question columns if no longer needed.
            question_columns = [col for col in df.columns if re.match(r'^\d+\s+Question$', col)]
            df.drop(columns=question_columns, inplace=True)

            st.subheader("Processed Data")
            st.dataframe(df)

            ########################################
            # 4) GENERATE WORD DOCUMENTS FOR EACH EVALUATOR
            ########################################

            if "Evaluator" not in df.columns:
                st.error("Evaluator column not found in data.")
            else:
                evaluators = df.groupby("Evaluator")
                st.write(f"Found {len(evaluators)} evaluator(s).")

                for evaluator_name, group in evaluators:
                    doc = Document()
                    evaluator_email = group["Evaluator Email"].iloc[0] if "Evaluator Email" in group.columns else "N/A"
                    doc.add_heading(f"Evaluator: {evaluator_name}", level=1)
                    doc.add_paragraph(f"Email: {evaluator_email}")

                    strengths_improvement_responses = []

                    # Process each evaluation row for the evaluator
                    for idx, row in group.iterrows():
                        # Determine evaluation period using "Start Date"
                        if "Start Date" in row:
                            try:
                                start_date = pd.to_datetime(row["Start Date"])
                                eval_period = start_date.strftime("%B %Y")
                            except Exception:
                                eval_period = str(row["Start Date"])
                        else:
                            eval_period = "Evaluation Period Not Provided"

                        doc.add_heading(f"Evaluation Period: {eval_period}", level=2)

                        # Create a table for questions and responses
                        table = doc.add_table(rows=1, cols=2)
                        hdr_cells = table.rows[0].cells
                        hdr_cells[0].text = "Question"
                        hdr_cells[1].text = "Response"

                        numeric_scores = []
                        ignore_cols = {"Form Record", "Start Date", "End Date", "Evaluator", "Evaluator Email"}

                        for col in df.columns:
                            if col in ignore_cols:
                                continue
                            answer = row[col]
                            # Collect responses for strengths/areas for improvement.
                            if isinstance(col, str) and "strength" in col.lower() and "improv" in col.lower():
                                strengths_improvement_responses.append(str(answer))
                            # Try to convert to a numeric score.
                            try:
                                score = float(answer)
                                numeric_scores.append(score)
                                answer_text = str(score)
                            except:
                                answer_text = str(answer)
                            # Add a row to the table
                            row_cells = table.add_row().cells
                            row_cells[0].text = col
                            row_cells[1].text = answer_text

                        # Add the average score if available.
                        if numeric_scores:
                            avg_score = sum(numeric_scores) / len(numeric_scores)
                            doc.add_paragraph(f"Average Score: {avg_score:.2f}")

                        # Add a blank paragraph to separate evaluations.
                        doc.add_paragraph()

                    # Generate a summary for strengths/areas for improvement using OpenAI.
                    if strengths_improvement_responses:
                        combined_text = "\n".join(
                            [str(resp) for resp in strengths_improvement_responses if pd.notna(resp) and str(resp).lower() != "nan"]
                        )
                        prompt = (
                            "Please provide a professional and formative summary of the following strengths and areas for improvement responses. "
                            "The summary should be upbeat, constructive, and written in a professional tone:\n\n"
                            f"{combined_text}\n\nSummary:"
                        )
                        try:
                            response = openai.Completion.create(
                                engine="text-davinci-003",
                                prompt=prompt,
                                max_tokens=150,
                                temperature=0.7,
                            )
                            summary = response.choices[0].text.strip()
                        except Exception as e:
                            summary = f"Error generating summary: {e}"
                        doc.add_heading("Summary of Strengths and Areas for Improvement", level=2)
                        doc.add_paragraph(summary)

                    # Insert a page break between evaluators
                    doc.add_page_break()

                    # Save the document to a BytesIO object and provide a download button.
                    doc_io = BytesIO()
                    doc.save(doc_io)
                    doc_io.seek(0)
                    st.download_button(
                        label=f"Download Report for {evaluator_name}",
                        data=doc_io,
                        file_name=f"{evaluator_name.replace(' ', '_')}_report.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
    except Exception as e:
        st.error(f"Error loading file: {e}")

########################################
# 5) PROCESS EVALUATION DUE DATES FILE (if needed)
########################################

if evaluation_due_dates_file is not None:
    try:
        if evaluation_due_dates_file.name.endswith("csv"):
            dfe = pd.read_csv(evaluation_due_dates_file)
        elif evaluation_due_dates_file.name.endswith("xlsx"):
            dfe = pd.read_excel(evaluation_due_dates_file)
        else:
            st.error("Unsupported file type for evaluation due dates.")
            dfe = None

        if dfe is not None:
            st.subheader("Evaluation Due Dates Data")
            st.dataframe(dfe)
    except Exception as e:
        st.error(f"Error loading evaluation due dates file: {e}")




