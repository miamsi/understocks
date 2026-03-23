import streamlit as st
import pandas as pd
import yfinance as yf
from supabase import create_client, Client
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

# --- CONFIG & UI SETUP ---
st.set_page_config(page_title="IHSG Hidden Gems Finder", page_icon="💎", layout="wide")
st.title("💎 IHSG Hidden Gems Finder")
st.markdown("Find undervalued stocks in the Indonesian Stock Exchange (IHSG) while avoiding YFinance rate limits.")

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_connection() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- YFINANCE RATE LIMIT HANDLER ---
# We create a custom session to automatically retry on failures/rate limits
def get_yf_session():
    session = requests.Session()
    # Retry 3 times, with exponential backoff (e.g., 0.5s, 1s, 2s) for 429 (Too Many Requests)
    retry = Retry(connect=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# --- TABS ---
tab_screener, tab_updater = st.tabs(["📊 Screener (Fast)", "⚙️ Data Updater (Admin)"])

# ==========================================
# TAB 1: SCREENER (READS FROM SUPABASE)
# ==========================================
with tab_screener:
    st.sidebar.header("🛠️ Tweak Your Gem Parameters")
    
    # Tweakable Filters
    max_pe = st.sidebar.slider("Max P/E Ratio (Lower is cheaper)", 0.0, 50.0, 15.0, 0.5)
    max_pb = st.sidebar.slider("Max P/B Ratio", 0.0, 10.0, 1.5, 0.1)
    max_debt = st.sidebar.slider("Max Debt-to-Equity", 0.0, 500.0, 100.0, 10.0, help="Below 100 is generally safer.")
    min_market_cap = st.sidebar.number_input("Min Market Cap (Rp Billions)", value=100.0, step=100.0)
    
    st.sidebar.markdown("---")
    st.sidebar.info("💡 **Tip:** A P/E below 15 and P/B below 1.5 is a classic Ben Graham value investing baseline.")

    # Fetch data from Supabase
    @st.cache_data(ttl=3600) # Cache for 1 hour to prevent excessive DB calls
    def fetch_database_stocks():
        response = supabase.table("ihsg_stocks").select("*").execute()
        return pd.DataFrame(response.data)

    df_db = fetch_database_stocks()

    if df_db.empty:
        st.warning("No data found in Supabase! Please go to the 'Data Updater' tab to scrape YFinance first.")
    else:
        # Data Cleaning & Conversion for filtering
        df_db['market_cap'] = pd.to_numeric(df_db['market_cap'], errors='coerce') / 1_000_000_000 # Convert to Billions
        df_db['pe_ratio'] = pd.to_numeric(df_db['pe_ratio'], errors='coerce')
        df_db['pb_ratio'] = pd.to_numeric(df_db['pb_ratio'], errors='coerce')
        df_db['debt_to_equity'] = pd.to_numeric(df_db['debt_to_equity'], errors='coerce')
        
        # Apply Tweakable Filters
        filtered_df = df_db[
            (df_db['pe_ratio'] > 0) & (df_db['pe_ratio'] <= max_pe) & # Exclude negative PE (loss-making)
            (df_db['pb_ratio'] > 0) & (df_db['pb_ratio'] <= max_pb) &
            (df_db['debt_to_equity'] <= max_debt) &
            (df_db['market_cap'] >= min_market_cap)
        ]

        # UI: Display Results
        st.subheader(f"Found {len(filtered_df)} Potential Hidden Gems")
        
        # Select columns to show
        display_cols = ['ticker', 'company_name', 'sector', 'current_price', 'pe_ratio', 'pb_ratio', 'debt_to_equity', 'market_cap', 'last_updated']
        
        # Sort by cheapest valuation (P/E * P/B Graham Number proxy)
        filtered_df['value_score'] = filtered_df['pe_ratio'] * filtered_df['pb_ratio']
        filtered_df = filtered_df.sort_values(by='value_score', ascending=True)

        st.dataframe(
            filtered_df[display_cols].style.format({
                "pe_ratio": "{:.2f}",
                "pb_ratio": "{:.2f}",
                "debt_to_equity": "{:.2f}",
                "market_cap": "{:,.0f}B",
                "current_price": "Rp {:,.0f}"
            }),
            use_container_width=True,
            hide_index=True
        )


# ==========================================
# TAB 2: DATA UPDATER (WRITES TO SUPABASE)
# ==========================================
with tab_updater:
    st.header("⚙️ Sync Data from YFinance")
    st.write("Fetch data from YFinance and store it in Supabase to bypass rate limits.")
    
    # File Uploader for the CSV
    uploaded_file = st.file_uploader("Upload 'Daftar Saham' CSV File", type=['csv'])
    
    batch_size = st.number_input("Batch Size (How many to update at once?)", min_value=1, max_value=50, value=20, help="Keep this low to avoid YFinance IP bans.")
    sleep_time = st.slider("Delay between requests (Seconds)", 0.5, 5.0, 1.5, help="Pauses between tickers to trick YFinance anti-bot.")
    
    if uploaded_file and st.button("🚀 Start Scraping & Updating"):
        try:
            # Load tickers
            raw_data = pd.read_csv(uploaded_file)
            
            # Find the column containing the ticker symbols. 
            # Looking for 'Kode' based on typical IDX data format
            kode_col = [col for col in raw_data.columns if 'Kode' in col]
            if not kode_col:
                st.error("Could not find the ticker column ('Kode') in the CSV.")
                st.stop()
                
            tickers = raw_data[kode_col[0]].dropna().astype(str).tolist()
            
            # Append .JK for YFinance Indonesian stocks
            yf_tickers = [f"{t.strip()}.JK" for t in tickers]
            
            st.info(f"Loaded {len(yf_tickers)} tickers. Processing the first {batch_size}...")
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            session = get_yf_session()
            success_count = 0
            
            for i in range(min(batch_size, len(yf_tickers))):
                ticker = yf_tickers[i]
                status_text.text(f"Fetching {ticker}... ({i+1}/{batch_size})")
                
                try:
                    # Fetch data using our custom retry session
                    stock = yf.Ticker(ticker, session=session)
                    info = stock.info
                    
                    # Extract safe metrics (handle missing data gracefully)
                    data_to_upsert = {
                        "ticker": ticker,
                        "company_name": info.get("longName", "Unknown"),
                        "sector": info.get("sector", "Unknown"),
                        "market_cap": info.get("marketCap", None),
                        "pe_ratio": info.get("trailingPE", None),
                        "pb_ratio": info.get("priceToBook", None),
                        "peg_ratio": info.get("pegRatio", None),
                        "debt_to_equity": info.get("debtToEquity", None),
                        "free_cash_flow": info.get("freeCashflow", None),
                        "dividend_yield": info.get("dividendYield", None),
                        "current_price": info.get("currentPrice", info.get("regularMarketPrice", None)),
                        "last_updated": datetime.now().isoformat()
                    }
                    
                    # Upsert to Supabase
                    supabase.table("ihsg_stocks").upsert(data_to_upsert, returning='minimal').execute()
                    success_count += 1
                    
                except Exception as e:
                    st.toast(f"Error fetching {ticker}: {str(e)[:50]}")
                
                # Update progress and sleep to prevent rate limiting
                progress_bar.progress((i + 1) / batch_size)
                time.sleep(sleep_time) # The crucial part to avoid IP blocks
                
            status_text.success(f"✅ Successfully updated {success_count}/{batch_size} stocks in Supabase!")
            st.balloons()
            
            # Clear cache so the new data shows up on the Screener tab
            fetch_database_stocks.clear()
            
        except Exception as e:
            st.error(f"An error occurred: {e}")
