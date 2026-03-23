import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client
from datetime import datetime, timedelta
import time

# ==========================================
# CONFIG
# ==========================================
st.set_page_config(page_title="IHSG Hidden Gems Finder", layout="wide")
st.title("💎 IHSG Hidden Gems Finder")

# ==========================================
# SUPABASE (NO CACHE = FIXED)
# ==========================================
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

supabase = get_supabase()

# ==========================================
# FILE LOADER
# ==========================================
def load_file(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file)
    elif file.name.endswith(".xlsx"):
        return pd.read_excel(file, engine="openpyxl")
    else:
        st.error("Upload CSV or XLSX only")
        st.stop()

# ==========================================
# FIND TICKER COLUMN
# ==========================================
def get_ticker_col(df):
    for c in df.columns:
        if any(x in c.lower() for x in ["kode", "ticker", "symbol"]):
            return c
    return None

# ==========================================
# CLEANERS (FIX BIGINT + NAN)
# ==========================================
def clean_float(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except:
        return None

def clean_int(v):
    try:
        if v is None or pd.isna(v):
            return None
        return int(float(v))
    except:
        return None

# ==========================================
# FETCH FROM YAHOO (SAFE)
# ==========================================
def fetch_stock(t):
    try:
        s = yf.Ticker(t)

        fast = s.fast_info
        if fast and fast.get("lastPrice"):
            return {
                "price": fast.get("lastPrice"),
                "market_cap": fast.get("marketCap")
            }

        info = s.info
        if not info:
            return None

        return {
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "market_cap": info.get("marketCap"),
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "de": info.get("debtToEquity"),
        }

    except Exception as e:
        return {"error": str(e)}

# ==========================================
# GET DB DATA
# ==========================================
@st.cache_data(ttl=600)
def get_db():
    res = supabase.table("ihsg_stocks").select("*").execute()
    return pd.DataFrame(res.data)

# ==========================================
# FILTER UPDATE (SMART)
# ==========================================
def need_update(df_db, tickers):
    now = datetime.utcnow()
    limit = now - timedelta(hours=24)

    last_map = {}
    if not df_db.empty:
        for _, r in df_db.iterrows():
            last_map[r["ticker"]] = r.get("last_updated")

    out = []
    for t in tickers:
        last = last_map.get(t)

        if not last:
            out.append(t)
        else:
            try:
                if datetime.fromisoformat(last) < limit:
                    out.append(t)
            except:
                out.append(t)

    return out

# ==========================================
# SAFE UPSERT (NO CRASH)
# ==========================================
def upsert_rows(rows):
    ok, fail = 0, 0

    for r in rows:
        try:
            supabase.table("ihsg_stocks").upsert(r).execute()
            ok += 1
        except Exception as e:
            fail += 1
            st.write("❌", r["ticker"], str(e))

    return ok, fail

# ==========================================
# UI
# ==========================================
tab1, tab2 = st.tabs(["📊 Screener", "⚙️ Updater"])

# ==========================================
# SCREENER
# ==========================================
with tab1:
    df = get_db()

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
    file = st.file_uploader("Upload IDX file", type=["csv", "xlsx"])
    batch = st.slider("Batch", 5, 50, 20)
    delay = st.slider("Delay", 0.5, 3.0, 1.0)

    if file and st.button("Start Sync"):

        raw = load_file(file)
        col = get_ticker_col(raw)

        if not col:
            st.error("Ticker column not found")
            st.stop()

        tickers = raw[col].dropna().astype(str).str.strip().tolist()
        yf_tickers = [f"{t}.JK" for t in tickers]

        df_db = get_db()
        update_list = need_update(df_db, yf_tickers)

        st.info(f"Updating {len(update_list)} / {len(yf_tickers)}")

        buffer = []
        total_ok, total_fail = 0, 0

        for t in update_list[:batch]:

            st.write("Fetching", t)

            d = fetch_stock(t)

            if not d or "error" in d:
                total_fail += 1
                continue

            row = {
                "ticker": t,
                "company_name": d.get("name"),
                "sector": d.get("sector"),
                "market_cap": clean_int(d.get("market_cap")),
                "pe_ratio": clean_float(d.get("pe")),
                "pb_ratio": clean_float(d.get("pb")),
                "debt_to_equity": clean_float(d.get("de")),
                "current_price": clean_int(d.get("price")),
                "last_updated": datetime.utcnow().isoformat()
            }

            buffer.append(row)

            if len(buffer) >= 10:
                ok, fail = upsert_rows(buffer)
                total_ok += ok
                total_fail += fail
                buffer = []

            time.sleep(delay)

        if buffer:
            ok, fail = upsert_rows(buffer)
            total_ok += ok
            total_fail += fail

        st.success(f"Done ✅ | Success: {total_ok} | Failed: {total_fail}")
