import streamlit as st
import pandas as pd
import re
import platform
from supabase import create_client

st.set_page_config(page_title="IHSG Audit & Scrape", layout="wide")

st.title("🔍 System Auditor & Connection Test")

# --- 1. ENVIRONMENT AUDIT (FIXED) ---
col1, col2 = st.columns(2)
with col1:
    st.info(f"**Python Version:** {platform.python_version()}")
with col2:
    # Fixed the version call
    st.info(f"**Streamlit Version:** {st.version.get_version()}")

# --- 2. SECRETS & REGEX AUDIT ---
st.header("1. Key Validation")
# Using .get() to avoid crashes if keys are missing
url = str(st.secrets.get("SUPABASE_URL", "")).strip()
key = str(st.secrets.get("SUPABASE_KEY", "")).strip()

# The exact regex the Supabase library uses internally
supabase_regex = r"^[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*$"
is_valid_regex = bool(re.match(supabase_regex, key))

if is_valid_regex:
    st.success("✅ Key format passed RegEx validation.")
else:
    st.error("❌ Key format FAILED RegEx validation.")
    st.write(f"**Detected Key Length:** {len(key)}")
    if len(key) < 100:
        st.warning("Your key looks too short. Are you sure you copied the 'anon' 'public' key?")

# --- 3. CONNECTION TEST (WITH PLAN B) ---
st.header("2. Database Connection")
if st.button("🔌 Test Supabase Connection"):
    if not url or not key:
        st.warning("Missing URL or Key in Secrets.")
    else:
        try:
            # Plan A: Standard Client
            client = create_client(url, key)
            st.success("🚀 Connection Successful!")
            
            # Try to fetch count from your table
            res = client.table("ihsg_stocks").select("ticker").limit(1).execute()
            st.write("Successfully reached the database table.")
            
        except Exception as e:
            st.error(f"Connection Error: {e}")
            st.info("Trying to debug... If the error is 'Invalid API Key', check if your key contains special characters like '+' or '/' that were mangled during copy-paste.")

# --- 4. DATA PROCESSING TEST ---
st.header("3. CSV File Ticker Test")
uploaded_file = st.file_uploader("Upload your IHSG CSV", type=['csv'])

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file)
        st.write("First 5 rows of your file:")
        st.dataframe(df.head())
        
        # In your file, the column is 'Kode'
        if 'Kode' in df.columns:
            tickers = df['Kode'].dropna().unique().tolist()
            st.success(f"Found {len(tickers)} unique tickers.")
            st.write(f"Sample: {tickers[:5]}")
        else:
            st.error(f"Column 'Kode' not found. Available columns: {list(df.columns)}")
    except Exception as e:
        st.error(f"File error: {e}")
