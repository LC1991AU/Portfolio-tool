import sqlite3
from contextlib import closing

import pandas as pd
import streamlit as st

from load_holdings import ROOT, read_holdings
from lookthrough import exposure_paths, load_reference


st.set_page_config(page_title="Portfolio exposures", layout="wide")
st.title("Portfolio exposures")
if st.sidebar.checkbox("Show ASX market data"):
    st.subheader("ASX share prices and GICS sectors")
    path = ROOT / "data" / "portfolio.db"
    market = pd.DataFrame()
    if path.exists():
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='view' AND name='latest_asx_market_data'").fetchone():
                market = pd.read_sql_query("""SELECT ticker AS Ticker, name AS Company, trade_date AS 'Price date',
                    close AS Close, currency AS Currency, sector AS 'GICS sector',
                    observed_date AS 'Sector checked', source AS Source
                    FROM latest_asx_market_data ORDER BY ticker""", db)
    if market.empty:
        st.info("No ASX prices have been imported. Refresh selected tickers with asx_market.py.")
    else:
        market["GICS sector"] = market["GICS sector"].fillna("Unclassified")
        st.dataframe(market, hide_index=True, width="stretch")
    st.stop()
mode = st.sidebar.radio("Portfolio", ["Illustrative example", "Local portfolio"])

if mode == "Illustrative example":
    st.caption("Synthetic holdings and ETF weights for demonstration. VAS coverage is intentionally partial.")
    db = sqlite3.connect(":memory:")
else:
    path = ROOT / "data" / "portfolio.db"
    if not path.exists():
        st.info("Import your portfolio with load_holdings.py first. The README lists the commands.")
        st.stop()
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    st.caption("Source: local SQLite portfolio and the latest imported constituent snapshot.")

with closing(db):
    if mode == "Illustrative example":
        db.execute("CREATE TABLE holdings (ticker TEXT, exchange TEXT, weight_pct REAL)")
        db.executemany("INSERT INTO holdings VALUES (?,?,?)", read_holdings(ROOT / "holdings.csv"))
        load_reference(db, ROOT / "examples/instruments.csv", ROOT / "examples/constituents.csv")
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"holdings", "instruments", "constituents"} <= tables:
        st.info("Import the holdings and ETF reference CSVs first. See the README for both commands.")
        st.stop()
    paths = pd.DataFrame(exposure_paths(db))

if paths.empty:
    st.info("This snapshot has no positions.")
    st.stop()

known = paths[paths["Issue"] == ""]
unknown = paths[paths["Issue"] != ""]
left, middle, right = st.columns(3)
left.metric("Identified exposure", f"{known['Weight'].sum():.2f}%")
middle.metric("Unresolved exposure", f"{unknown['Weight'].sum():.2f}%")
right.metric("Portfolio total", f"{paths['Weight'].sum():.2f}%")
st.subheader("Underlying holdings")
summary = known.pivot_table(index="Exposure", columns="Route", values="Weight", aggfunc="sum", fill_value=0)
summary = summary.reindex(columns=["Direct", "Via ETF"], fill_value=0)
summary["Total"] = summary.sum(axis=1)
summary = summary.sort_values("Total", ascending=False)
percent = st.column_config.NumberColumn(format="%.2f%%")
if not summary.empty:
    st.dataframe(summary, column_config={c: percent for c in summary.columns}, width="stretch")
    st.bar_chart(summary.head(10)[["Direct", "Via ETF"]], horizontal=True, stack=True,
                 x_label="Portfolio weight (%)", color=["#20776e", "#77b6cf"])
if not unknown.empty:
    st.subheader("Unresolved holdings")
    st.dataframe(unknown[["Source path", "Issue", "Weight"]], hide_index=True,
                 column_config={"Weight": percent}, width="stretch")

st.subheader("Trace an exposure")
choice = st.selectbox("Underlying holding", summary.index.tolist() + sorted(unknown["Exposure"].unique()))
st.dataframe(paths.loc[paths["Exposure"] == choice, ["Source path", "Route", "Weight"]],
             hide_index=True, column_config={"Weight": percent}, width="stretch")
