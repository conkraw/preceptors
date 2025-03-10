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
        st.dataframe(df_grouped)

        # Further aggregate so that each unique evaluator is summarized on one row.
        # We will group by Evaluator and Evaluator Email.
        final_group_cols = ["Evaluator", "Evaluator Email"]
        
        # Define aggregation functions for each column:
        agg_funcs = {
            # For Rotation Period: join unique periods with a comma
            "Rotation Period": lambda x: ", ".join(sorted(set(x.dropna()))),
            # For strengths and improvements: join unique responses with a newline
            "strengths_preceptor": lambda x: "\n".join(x.dropna().unique()),
            "improvement_preceptor": lambda x: "\n".join(x.dropna().unique())
        }
        
        # Identify the evaluation score columns (all numeric columns other than the ones we already aggregated)
        score_columns = [col for col in df_grouped.columns 
                         if col not in ["Evaluator", "Evaluator Email", "Rotation Period", 
                                        "strengths_preceptor", "improvement_preceptor", "Form Record"]]
        
        # For each score column, take the mean (this will average the score for each question)
        for col in score_columns:
            agg_funcs[col] = "mean"
        
        # Optionally, if you want to aggregate the Form Record (or you can drop it), do something similar:
        if "Form Record" in df_grouped.columns:
            agg_funcs["Form Record"] = lambda x: ", ".join(x.dropna().unique())
        
        # Group the DataFrame by Evaluator and Evaluator Email using the defined aggregation functions.
        df_final = df_grouped.groupby(final_group_cols, as_index=False).agg(agg_funcs)
        
        # Display the final, aggregated DataFrame.
        st.dataframe(df_final)

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



