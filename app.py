import streamlit as st
import pandas as pd
import re
import platform
from supabase import create_client

st.set_page_config(page_title="IHSG Audit", layout="wide")

st.title("🔍 Final Connection Audit")

# 1. ENVIRONMENT (No fancy version calls to avoid AttributeErrors)
st.info(f"Python: {platform.python_version()} | Streamlit: {st.__version__}")

# 2. THE KEYS
url = str(st.secrets.get("SUPABASE_URL", "")).strip()
key = str(st.secrets.get("SUPABASE_KEY", "")).strip()

# 3. REGEX VALIDATION
# This is the exact check that causes the "Invalid API Key" error
supabase_regex = r"^[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*$"
is_valid_regex = bool(re.match(supabase_regex, key))

if is_valid_regex:
    st.success("✅ Key format is VALID (Passed Library RegEx)")
else:
    st.error("❌ Key format is INVALID")
    st.write(f"Length: {len(key)} chars")
    st.write("If length is ~150-200, you likely have a hidden character (like a space or symbol) that doesn't belong in a JWT.")

# 4. THE CONNECTION
if st.button("⚡ Connect to Supabase"):
    if not url or not key:
        st.error("Missing Secrets!")
    else:
        try:
            # We use the cleaned variables
            client = create_client(url, key)
            st.success("🚀 CONNECTION SUCCESSFUL!")
            
            # Simple check to see if the table exists
            check = client.table("ihsg_stocks").select("ticker").limit(1).execute()
            st.write("Database is reachable and table 'ihsg_stocks' is ready.")
        except Exception as e:
            st.error(f"Failed: {e}")

# 5. TICKER PREVIEW
st.divider()
uploaded_file = st.file_uploader("Upload CSV to verify 'Kode' column", type=['csv'])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    if 'Kode' in df.columns:
        st.write(f"Found {len(df)} rows. Sample tickers: {df['Kode'].head().tolist()}")
    else:
        st.warning(f"Column 'Kode' not found. Available: {list(df.columns)}")
