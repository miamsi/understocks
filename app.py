import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import time

# ==========================================
# CONFIG
# ==========================================
st.set_page_config(page_title="IHSG Hidden Gems Finder", page_icon="💎", layout="wide")
st.title("💎 IHSG Hidden Gems Finder")

# ==========================================
# SUPABASE (FIX: NO CACHE)
# ==========================================
def init_connection():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

supabase = init_connection()

# ==========================================
# FILE LOADER (CSV + XLSX)
# ==========================================
def load_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    elif file.name.endswith(".xlsx"):
        return pd.read_excel(file, engine="openpyxl")
    else:
        st.error("Unsupported file format")
        st.stop()

# ==========================================
# DETECT TICKER COLUMN
# ==========================================
def detect_ticker_column(df):
    for col in df.columns:
        if any(k in col.lower() for k in ["kode", "ticker", "symbol"]):
            return col
    return None

# ==========================================
# CLEANING FUNCTIONS (CRITICAL)
# ==========================================
def clean_float(val):
    try:
        if val is None or pd.isna(val):
            return None
        return float(val)
    except:
        return None

def clean_int(val):
    try:
        if val is None or pd.isna(val):
            return None
        return int(float(val))
    except:
        return None

# ==========================================
# SAFE FETCH (FIXED YFINANCE)
# ==========================================
def safe_fetch(ticker):
    try:
        stock = yf.Ticker(ticker)

        # FAST (stable)
        fast = stock.fast_info
        if fast and fast.get("lastPrice"):
            return {
                "price": fast.get("lastPrice"),
                "market_cap": fast.get("marketCap")
            }

        # FALLBACK
        info = stock.info
        if info:
            return {
                "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "market_cap": info.get("marketCap"),
                "sector": info.get("sector"),
                "name": info.get("longName"),
                "pe": info.get("trailingPE"),
                "pb": info.get("priceToBook"),
                "de": info.get("debtToEquity")
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
def filter_update(df_db, tickers):
    now = datetime.utcnow()
    threshold = now - timedelta(hours=24)

    db_map = {}
    if not df_db.empty:
        for _, r in df_db.iterrows():
            db_map[r["ticker"]] = r.get("last_updated")

    result = []
    for t in tickers:
        last = db_map.get(t)

        if not last:
            result.append(t)
        else:
            try:
                if datetime.fromisoformat(last) < threshold:
                    result.append(t)
            except:
                result.append(t)

    return result

# ==========================================
# SAFE UPSERT (NO CRASH)
# ==========================================
def safe_upsert(rows):
    success, failed = 0, 0

    for r in rows:
        try:
            supabase.table("ihsg_stocks").upsert(r).execute()
            success += 1
        except Exception as e:
            failed += 1
            st.write("❌ DB error:", r["ticker"], str(e))

    return success, failed

# ==========================================
# UI
# ==========================================
tab1, tab2 = st.tabs(["📊 Screener", "⚙️ Updater"])

# ==========================================
# SCREENER
# ==========================================
with tab1:
    st.subheader("📊 Screener")

    df = fetch_db()

    if df.empty:
        st.warning("No data yet")
    else:
        df["pe_ratio"] = pd.to_numeric(df["pe_ratio"], errors="coerce")
        df["pb_ratio"] = pd.to_numeric(df["pb_ratio"], errors="coerce")

        df["score"] = df["pe_ratio"] * df["pb_ratio"]
        df = df.sort_values("score")

        st.dataframe(df, use_container_width=True)

# ==========================================
# UPDATER
# ==========================================
with tab2:
    st.header("⚙️ Smart Sync")

    file = st.file_uploader("Upload IDX file", type=["csv", "xlsx"])

    batch_size = st.slider("Batch size", 5, 50, 20)
    delay = st.slider("Delay (sec)", 0.5, 3.0, 1.0)

    if file and st.button("🚀 Start Sync"):

        raw = load_file(file)
        col = detect_ticker_column(raw)

        if not col:
            st.error("Ticker column not found")
            st.stop()

        tickers = raw[col].dropna().astype(str).str.strip().tolist()
        yf_tickers = [f"{t}.JK" for t in tickers]

        df_db = fetch_db()
        to_update = filter_update(df_db, yf_tickers)

        st.info(f"Updating {len(to_update)} / {len(yf_tickers)} tickers")

        buffer = []
        total_success, total_failed = 0, 0

        for i, t in enumerate(to_update[:batch_size]):

            st.write(f"Fetching {t}")

            data = safe_fetch(t)

            if not data or "error" in data:
                total_failed += 1
                continue

            row = {
                "ticker": t,
                "company_name": data.get("name"),
                "sector": data.get("sector"),
                "market_cap": clean_int(data.get("market_cap")),
                "pe_ratio": clean_float(data.get("pe")),
                "pb_ratio": clean_float(data.get("pb")),
                "debt_to_equity": clean_float(data.get("de")),
                "current_price": clean_int(data.get("price")),
                "last_updated": datetime.utcnow().isoformat()
            }

            buffer.append(row)

            if len(buffer) >= 10:
                s, f = safe_upsert(buffer)
                total_success += s
                total_failed += f
                buffer = []

            time.sleep(delay)

        if buffer:
            s, f = safe_upsert(buffer)
            total_success += s
            total_failed += f

        st.success(f"""
        ✅ Done

        ✔ Success: {total_success}  
        ❌ Failed: {total_failed}  
        """)
