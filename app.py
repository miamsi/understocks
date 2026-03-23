import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import time
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
# FILE LOADER (CSV + XLSX)
# ==========================================
def load_file(uploaded_file):
    if uploaded_file.name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    elif uploaded_file.name.endswith(".xlsx"):
        return pd.read_excel(uploaded_file, engine="openpyxl")
    else:
        st.error("Unsupported file format")
        st.stop()

# ==========================================
# DETECT TICKER COLUMN (ROBUST)
# ==========================================
def detect_ticker_column(df):
    possible = ["kode", "ticker", "symbol", "code"]
    for col in df.columns:
        for key in possible:
            if key in col.lower():
                return col
    return None

# ==========================================
# SAFE FETCH (FIXED YFINANCE)
# ==========================================
def safe_fetch_info(ticker):
    try:
        stock = yf.Ticker(ticker)

        # ✅ PRIMARY (STABLE)
        fast = stock.fast_info
        if fast and fast.get("lastPrice"):
            return {
                "currentPrice": fast.get("lastPrice"),
                "marketCap": fast.get("marketCap"),
                "source": "fast_info"
            }

        # 🔄 FALLBACK
        info = stock.info
        if info and ("currentPrice" in info or "regularMarketPrice" in info):
            return {
                "currentPrice": info.get("currentPrice") or info.get("regularMarketPrice"),
                "marketCap": info.get("marketCap"),
                "sector": info.get("sector"),
                "longName": info.get("longName"),
                "trailingPE": info.get("trailingPE"),
                "priceToBook": info.get("priceToBook"),
                "debtToEquity": info.get("debtToEquity"),
                "source": "info"
            }

        return None

    except Exception as e:
        return {"error": str(e)}

# ==========================================
# FETCH DB
# ==========================================
@st.cache_data(ttl=600)
def fetch_db():
    res = supabase.table("ihsg_stocks").select("*").execute()
    return pd.DataFrame(res.data)

# ==========================================
# SMART FILTER
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
# UI
# ==========================================
tab1, tab2 = st.tabs(["📊 Screener", "⚙️ Updater"])

# ==========================================
# SCREENER
# ==========================================
with tab1:
    st.subheader("📊 Stock Screener")

    df = fetch_db()

    if df.empty:
        st.warning("No data available. Run updater first.")
    else:
        df["pe_ratio"] = pd.to_numeric(df["pe_ratio"], errors="coerce")
        df["pb_ratio"] = pd.to_numeric(df["pb_ratio"], errors="coerce")

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
    sleep_time = st.slider("Delay (sec)", 0.5, 3.0, 1.5)

    if uploaded_file and st.button("🚀 Start Sync"):

        raw = load_file(uploaded_file)

        ticker_col = detect_ticker_column(raw)
        if not ticker_col:
            st.error("Ticker column not found")
            st.stop()

        tickers = raw[ticker_col].dropna().astype(str).str.strip().tolist()
        yf_tickers = [f"{t}.JK" for t in tickers]

        df_db = fetch_db()

        to_update = filter_tickers_to_update(df_db, yf_tickers)

        st.info(f"""
        Total: {len(yf_tickers)}
        Need update: {len(to_update)}
        Skipped: {len(yf_tickers) - len(to_update)}
        """)

        success, failed = 0, 0
        buffer = []

        progress = st.progress(0)
        status = st.empty()

        for i, ticker in enumerate(to_update[:batch_size]):

            status.text(f"Fetching {ticker} ({i+1}/{batch_size})")

            info = safe_fetch_info(ticker)

            # ❌ DEBUG VISIBILITY
            if not info or "error" in info:
                failed += 1
                st.write(f"❌ {ticker} failed:", info)
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

                # ✅ BULK UPSERT
                if len(buffer) >= 10:
                    supabase.table("ihsg_stocks").upsert(buffer).execute()
                    buffer = []

            except Exception as e:
                failed += 1
                st.write(f"DB error {ticker}:", str(e))

            progress.progress((i + 1) / batch_size)
            time.sleep(sleep_time)

        # flush remaining
        if buffer:
            supabase.table("ihsg_stocks").upsert(buffer).execute()

        st.success(f"""
        ✅ Sync Complete

        ✔ Success: {success}
        ❌ Failed: {failed}
        ⏭ Skipped: {len(yf_tickers) - len(to_update)}
        """)

        fetch_db.clear()
