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
import zipfile

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
# Helper function to parse "time worked" values
########################################

def parse_week_value(value):
    """
    Attempt to extract a numeric value from a string such as '1 week', '1/2 week', etc.
    Returns a float if possible, otherwise None.
    """
    try:
        # If already numeric, return as float.
        return float(value)
    except Exception:
        try:
            # Look for numbers, fractions, or decimals in the string.
            match = re.search(r'([\d./]+)', str(value))
            if match:
                num_str = match.group(1)
                if '/' in num_str:
                    numerator, denominator = num_str.split('/')
                    return float(numerator) / float(denominator)
                else:
                    return float(num_str)
        except Exception:
            return None

########################################
# 2) DISPLAY UPLOAD SECTIONS
########################################

st.title("Faculty Analysis Report & Evaluation Due Dates Upload")

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
        # Load the file based on extension
        if analysis_report_file.name.endswith("csv"):
            dfa = pd.read_csv(analysis_report_file)
        elif analysis_report_file.name.endswith("xlsx"):
            dfa = pd.read_excel(analysis_report_file)
        else:
            st.error("Unsupported file type for analysis report.")
            dfa = None

        if dfa is not None:
            # Select only the desired columns (assumed to be 0-indexed)
            selected_indices = [4, 5, 16, 19, 23, 27, 30, 34, 37, 41, 44, 48, 51, 55, 58, 62,
                                65, 69, 72, 76, 79, 83, 86, 90, 93, 97, 100, 104, 107, 111,
                                114, 118, 121, 125, 128, 132, 135, 139, 143, 146, 147, 153, 154]
            dfa_selected = dfa.iloc[:, selected_indices].copy()
            df = dfa_selected.copy()

            # If evaluator and date info are missing in the selected data, add them from full data.
            for col in ["Evaluator", "Evaluator Email", "Start Date", "End Date"]:
                if col not in df.columns and col in dfa.columns:
                    df[col] = dfa[col]

            # Rename answer columns using the corresponding question column’s first row text.
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

            # Drop the question columns if no longer needed.
            question_columns = [col for col in df.columns if re.match(r'^\d+\s+Question$', col)]
            df.drop(columns=question_columns, inplace=True)

            st.subheader("Processed Data")
            st.dataframe(df)

            ########################################
            # 4) GENERATE REPORTS FOR EACH EVALUATOR AND CREATE ZIP
            ########################################

            if "Evaluator" not in df.columns:
                st.error("Evaluator column not found in data.")
            else:
                evaluator_groups = df.groupby("Evaluator")
                st.write(f"Found {len(evaluator_groups)} evaluator(s).")

                # Create an in-memory zip file to store all documents.
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                    # Process each evaluator.
                    for evaluator_name, group in evaluator_groups:
                        doc = Document()
                        evaluator_email = group["Evaluator Email"].iloc[0] if "Evaluator Email" in group.columns else "N/A"
                        doc.add_heading(f"Evaluator: {evaluator_name}", level=1)
                        doc.add_paragraph(f"Email: {evaluator_email}")

                        # For each evaluator, compute the average for each numeric question.
                        ignore_cols = {"Evaluator", "Evaluator Email", "Form Record", "Start Date", "End Date"}
                        avg_results = {}
                        strengths_improvement_responses = []

                        for col in group.columns:
                            if col in ignore_cols:
                                continue
                            # If the column header indicates a strengths/areas for improvement question, gather responses.
                            if "strength" in col.lower() and "improv" in col.lower():
                                for val in group[col]:
                                    if pd.notna(val) and str(val).strip().lower() != "nan":
                                        strengths_improvement_responses.append(str(val))
                                continue

                            # Otherwise, try to average numeric responses.
                            numeric_values = []
                            for val in group[col]:
                                try:
                                    # Special handling for time worked column.
                                    if "please indicate the amount of time" in col.lower():
                                        parsed = parse_week_value(val)
                                    else:
                                        parsed = float(val)
                                    if parsed is not None:
                                        numeric_values.append(parsed)
                                except Exception:
                                    pass
                            if numeric_values:
                                avg_results[col] = sum(numeric_values) / len(numeric_values)

                        # Add a heading for the average scores.
                        doc.add_heading("Average Scores by Question", level=2)
                        # Create a table for averages.
                        table = doc.add_table(rows=1, cols=2)
                        hdr_cells = table.rows[0].cells
                        hdr_cells[0].text = "Question"
                        hdr_cells[1].text = "Average Score"
                        for question, avg in avg_results.items():
                            row_cells = table.add_row().cells
                            row_cells[0].text = question
                            row_cells[1].text = f"{avg:.2f}"

                        # Generate a summary of strengths/areas for improvement if available.
                        if strengths_improvement_responses:
                            combined_text = "\n".join(str(resp) for resp in strengths_improvement_responses)
                            prompt = (
                                "Please provide a professional and formative summary of the following strengths "
                                "and areas for improvement responses. The summary should be upbeat, constructive, "
                                "and written in a professional tone:\n\n"
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

                        # Save the document to a BytesIO stream.
                        doc_io = BytesIO()
                        doc.save(doc_io)
                        doc_io.seek(0)
                        filename = f"{evaluator_name.replace(' ', '_')}_report.docx"
                        # Add this document to the ZIP file.
                        zipf.writestr(filename, doc_io.getvalue())

                # Finalize the ZIP buffer.
                zip_buffer.seek(0)
                st.download_button(
                    label="Download All Evaluator Reports (ZIP)",
                    data=zip_buffer,
                    file_name="evaluator_reports.zip",
                    mime="application/zip"
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



