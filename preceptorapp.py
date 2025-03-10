import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import io
import re
import pytz
import firebase_admin
from firebase_admin import credentials, firestore
import openai

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

        selected_indices = [4, 5, 16, 19, 23, 27, 30, 34, 37, 41, 44, 48, 51, 55, 58, 62,65, 69, 72, 76, 79, 83, 86, 90, 93, 97, 100, 104, 107, 111, 114, 118, 121, 125, 128, 132, 135, 139, 143, 146, 147, 153, 154]
        dfa = dfa.iloc[:, selected_indices]
        st.dataframe(dfa)
        st.write(list(dfa.columns))

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
        st.write(list(df.columns))
        st.dataframe(df)
        # 1. Create a new column 'Rotation Period' from 'Start Date'
        #    Format the date as "Month Year" (e.g., "July 2024")
        df['Rotation Period'] = pd.to_datetime(df['Start Date'], errors='coerce').dt.strftime('%B %Y')
        
        # 2. Compute the average score for the evaluation columns (columns 5 to 20)
        score_columns = [
            "Checked to see where my current knowledge and skills were.",
            "Built on my knowledge and skill base.",
            "Demonstrated respect for me as a learner.",
            "Demonstrated respect for patients, staff, care providers, and other specialties.",
            "Used high value, cost conscious care considerations in clinical decision making.",
            "Encouraged me to integrate high value, cost conscious care in my clinical decision making (e.g., note writing, assessment and plan, presentations).",
            "Created a safe environment for me to ask questions and voice uncertainty.",
            "Asked me to include my differential diagnosis, assessment and plan in my case presentations.",
            "Asked me to provide the rationale for my clinical decisions in my case presentations.",
            "Asked me to investigate a relevant clinical topic and report back.",
            "Directly observed me (e.g., taking a history, doing a physical exam, communicating with patients).",
            "Provided feedback by giving specific examples of what I did well.",
            "Provided feedback by giving specific examples of how I could improve.",
            "Helped me develop a plan to improve my knowledge or skills.",
            "My preceptor was a positive role model for me.",
            "(FQ) Overall, this faculty/preceptor/resident helped me to further my clinical learning."
        ]
        
        # Convert score columns to numeric (if they aren't already) and compute the row-wise mean
        df['Average Score'] = df[score_columns].apply(pd.to_numeric, errors='coerce').mean(axis=1)
        
        # 3. Drop the original date columns
        df.drop(columns=["Start Date", "End Date"], inplace=True)
        
        # 4. Drop the evaluation score columns (columns 5 to 20)
        df.drop(columns=score_columns, inplace=True)
        
        # 5. Drop column 21: "Please indicate the amount of time you worked with this preceptor in this rotation."
        df.drop(columns=["Please indicate the amount of time you worked with this preceptor in this rotation."], inplace=True)
        
        # 6. Rename column 22 ("Please indicate this educator's strengths") to 'strengths_preceptor'
        df.rename(columns={"Please indicate this educator's strengths": "strengths_preceptor"}, inplace=True)
        
        # 7. Rename column 23 ("Areas for Improvement") to 'improvement_preceptor'
        df.rename(columns={"Areas for Improvement": "improvement_preceptor"}, inplace=True)
        
        # (Optional) Reorder columns if you want a specific order:
        desired_order = ['Rotation Period', 'Evaluator', 'Evaluator Email', 'Form Record', 'Average Score', 'strengths_preceptor', 'improvement_preceptor']
        df = df[[col for col in desired_order if col in df.columns]]
        
        # Now you can display the final DataFrame
        st.dataframe(df)

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



