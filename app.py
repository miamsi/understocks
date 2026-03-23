import streamlit as st
import re
import platform
from supabase import create_client

st.title("🔍 Supabase Connection Auditor")

# 1. Environment Audit
st.header("1. Environment Check")
st.write(f"**Python Version:** {platform.python_version()}")
st.write(f"**Streamlit Version:** {st.version.__version__}")

# 2. Secrets Audit
st.header("2. Secrets Check")
url = st.secrets.get("SUPABASE_URL", "MISSING")
key = st.secrets.get("SUPABASE_KEY", "MISSING")

# We use repr() to see hidden characters like \n or \r
st.write(f"**URL Length:** {len(str(url))}")
st.write(f"**Key Length:** {len(str(key))}")

# Check for common invisible culprits
has_newline = "\n" in str(key) or "\r" in str(key)
has_spaces = str(key).startswith(" ") or str(key).endswith(" ")

st.write(f"**Has hidden Newlines?** {has_newline}")
st.write(f"**Has leading/trailing spaces?** {has_spaces}")

# 3. Manual RegEx Validation (This is what triggers the error)
st.header("3. Library Validation Simulation")
# This is the exact regex used by the Supabase library
supabase_regex = r"^[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*$"

clean_key = str(key).strip()
is_valid = re.match(supabase_regex, clean_key) is not None

if is_valid:
    st.success("✅ The Key format passed the RegEx validation.")
else:
    st.error("❌ The Key format FAILED the RegEx validation.")
    st.info("This means your key string contains characters that shouldn't be there, or it's not a valid JWT (anon key).")

# 4. Attempt Connection
st.header("4. Connection Attempt")
if st.button("Try Connect Now"):
    try:
        # We use the cleaned versions
        test_client = create_client(str(url).strip(), str(key).strip())
        st.success("🚀 SUCCESS! The client was initialized.")
        
        # Test a simple query
        res = test_client.table("ihsg_stocks").select("count", count="exact").limit(1).execute()
        st.write("Database Ping Successful!")
    except Exception as e:
        st.error(f"Connection failed: {type(e).__name__}")
        st.code(str(e))

st.markdown("---")
st.write("### How to read these results:")
st.write("- If **Python Version** still says 3.14: Your Streamlit settings didn't save. Reboot the app.")
- If **FAILED RegEx**: Your key has a character like `+`, `/`, or `=` in a place the library doesn't like, or it's truncated.
- If **Success here but fails in your main app**: There is a logic error in how the main app handles the client object.
