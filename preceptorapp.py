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



