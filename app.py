import streamlit as st
import pandas as pd
import re
import platform
from supabase import create_client

st.set_page_config(page_title="IHSG Audit & Scrape", layout="wide")

st.title("🔍 System Auditor & Connection Test")

# --- 1. ENVIRONMENT AUDIT ---
col1, col2 = st.columns(2)
with col1:
    st.info(f"**Python Version:** {platform.python_version()}")
with col2:
    st.info(f"**Streamlit Version:** {st.version.__version__}")

# --- 2. SECRETS & REGEX AUDIT ---
st.header("1. Key Validation")
raw_url = st.secrets.get("SUPABASE_URL", "")
raw_key = st.secrets.get("SUPABASE_KEY", "")

# Clean strings
url = str(raw_url).strip()
key = str(raw_key).strip()

# The exact regex the Supabase library uses
supabase_regex = r"^[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*$"
is_valid_regex = re.match(supabase_regex, key) is not None

if is_valid_regex:
    st.success("✅ Key format passed RegEx validation.")
else:
    st.error("❌ Key format FAILED RegEx validation.")
    st.write(f"**Key Length:** {len(key)} (Should be >100)")
    st.write("Ensure you copied the 'anon' 'public' key, NOT the 'service_role' or 'JWT Secret'.")

# --- 3. CONNECTION TEST ---
st.header("2. Database Connection")
if st.button("🔌 Test Supabase Connection"):
    if not url or not key:
        st.warning("Missing URL or Key in Secrets.")
    else:
        try:
            client = create_client(url, key)
            st.success("🚀 Connection Successful!")
            
            # Try to fetch count from your table
            res = client.table("ihsg_stocks").select("count", count="exact").limit(1).execute()
            st.write(f"Current rows in 'ihsg_stocks': {res.count}")
        except Exception as e:
            st.error(f"Connection Error: {e}")

# --- 4. DATA PROCESSING TEST ---
st.header("3. CSV File Ticker Test")
uploaded_file = st.file_uploader("Upload your IHSG CSV", type=['csv'])

if uploaded_file:
    try:
        df = pd.read_csv(uploaded_file)
        st.write("First 5 rows of your file:")
        st.dataframe(df.head())
        
        if 'Kode' in df.columns:
            tickers = df['Kode'].dropna().unique().tolist()
            st.success(f"Found {len(tickers)} unique tickers.")
            st.write(f"Sample: {tickers[:5]}")
        else:
            st.error("Column 'Kode' not found in CSV. Check your file headers.")
    except Exception as e:
        st.error(f"File error: {e}")

st.divider()
st.caption("Fixing the SyntaxError: Removed loose text from the bottom of the script.")
