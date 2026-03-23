import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta

# ==========================================
# CONFIG
# ==========================================
st.set_page_config(page_title="IHSG Hidden Gems Finder", page_icon="💎", layout="wide")
st.title("💎 IHSG Hidden Gems Finder")

# ==========================================
# SUPABASE
# ==========================================
@st.cache_resource
def init_connection() -> Client:
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

supabase = init_connection()

# ==========================================
# FILE LOADER (FIXED XLSX + CSV SUPPORT)
# ==========================================
def load_file(uploaded_file):
    if uploaded_file.name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    elif uploaded_file.name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file, engine="openpyxl")
    else:
        st.error("Unsupported file format. Use CSV or XLSX.")
        st.stop()

# ==========================================
# ROBUST TICKER COLUMN DETECTION (FIXED)
# ==========================================
def detect_ticker_column(df):
    possible_names = ["kode", "ticker", "symbol", "code"]

    for col in df.columns:
        for key in possible_names:
            if key in col.lower():
                return col

    return None

# ==========================================
# YFINANCE SESSION
# ==========================================
def get_yf_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session

# ==========================================
# SAFE FETCH (FIXES YF FAILURES)
# ==========================================
def safe_fetch_info(ticker, session):
    try:
        stock = yf.Ticker(ticker, session=session)

        info = stock.info

        # fallback if broken
        if not info or "currentPrice" not in info:
            fast = stock.fast_info
            info = {
                "currentPrice": fast.get("lastPrice"),
                "marketCap": fast.get("marketCap")
            }

        return info

    except Exception:
        return None

# ==========================================
# DATABASE FETCH
# ==========================================
@st.cache_data(ttl=600)
def fetch_db():
    res = supabase.table("ihsg_stocks").select("*").execute()
    return pd.DataFrame(res.data)

# ==========================================
# SMART UPDATE FILTER (KEY FEATURE)
# ==========================================
def filter_tickers_to_update(df_db, tickers):
    now = datetime.now()
    threshold = now - timedelta(hours=24)

    db_map = {}
    if not df_db.empty:
        for _, row in df_db.iterrows():
            db_map[row["ticker"]] = row.get("last_updated")

    to_update = []

    for t in tickers:
        last = db_map.get(t)

        if not last:
            to_update.append(t)
        else:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt < threshold:
                    to_update.append(t)
            except:
                to_update.append(t)

    return to_update

# ==========================================
# UI TABS
# ==========================================
tab1, tab2 = st.tabs(["📊 Screener", "⚙️ Updater"])

# ==========================================
# SCREENER
# ==========================================
with tab1:
    st.subheader("📊 Stock Screener")

    df = fetch_db()

    if df.empty:
        st.warning("No data available. Please run updater first.")
    else:
        # Safe numeric conversion
        df["pe_ratio"] = pd.to_numeric(df["pe_ratio"], errors="coerce")
        df["pb_ratio"] = pd.to_numeric(df["pb_ratio"], errors="coerce")

        # Value score
        df["value_score"] = df["pe_ratio"] * df["pb_ratio"]

        df = df.sort_values("value_score")

        st.dataframe(df, use_container_width=True)

# ==========================================
# UPDATER
# ==========================================
with tab2:
    st.header("⚙️ Smart Data Sync")

    uploaded_file = st.file_uploader(
        "Upload IDX Stock List",
        type=["csv", "xlsx"]
    )

    batch_size = st.slider("Batch size", 5, 50, 20)
    sleep_time = st.slider("Delay between requests (sec)", 0.5, 3.0, 1.0)

    if uploaded_file and st.button("🚀 Start Smart Sync"):

        raw = load_file(uploaded_file)

        ticker_col = detect_ticker_column(raw)

        if not ticker_col:
            st.error("Could not detect ticker column (Kode/Ticker/Symbol)")
            st.stop()

        tickers = raw[ticker_col].dropna().astype(str).str.strip().tolist()
        yf_tickers = [f"{t}.JK" for t in tickers]

        df_db = fetch_db()

        # SMART FILTER
        to_update = filter_tickers_to_update(df_db, yf_tickers)

        st.info(f"""
        Total tickers: {len(yf_tickers)}
        Need update: {len(to_update)}
        Skipped (cached): {len(yf_tickers) - len(to_update)}
        """)

        session = get_yf_session()

        success, failed = 0, 0
        buffer = []

        progress = st.progress(0)
        status = st.empty()

        for i, ticker in enumerate(to_update[:batch_size]):

            status.text(f"Fetching {ticker} ({i+1}/{batch_size})")

            info = safe_fetch_info(ticker, session)

            if not info:
                failed += 1
                continue

            try:
                data = {
                    "ticker": ticker,
                    "company_name": info.get("longName"),
                    "sector": info.get("sector"),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "pb_ratio": info.get("priceToBook"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_price": info.get("currentPrice"),
                    "last_updated": datetime.now().isoformat()
                }

                buffer.append(data)
                success += 1

                # BULK UPSERT
                if len(buffer) >= 10:
                    supabase.table("ihsg_stocks").upsert(buffer).execute()
                    buffer = []

            except:
                failed += 1

            progress.progress((i + 1) / batch_size)
            time.sleep(sleep_time)

        # Flush remaining
        if buffer:
            supabase.table("ihsg_stocks").upsert(buffer).execute()

        st.success(f"""
        ✅ Sync Complete!

        ✔ Success: {success}  
        ❌ Failed: {failed}  
        ⏭ Skipped: {len(yf_tickers) - len(to_update)}
        """)

        fetch_db.clear()
