"""Portfolio landing page and workspace routing."""

import sqlite3
from contextlib import closing

import pandas as pd
import streamlit as st

from analysis_dashboard import show_benchmark_analysis
from equity_dashboard import show_asx_overview
from equity_portfolio import initialise_portfolio, sample_weights
from exposure_dashboard import show_etf_paths
from load_holdings import ROOT, read_holdings
from lookthrough import exposure_paths, load_reference
from portfolio_builder import listing_catalog, show_builder
from portfolio_store import list_portfolios, load_portfolio, migrate_legacy_portfolios


EXAMPLES = {"asx": "10-share ASX example", "mixed": "Shares and ETF example"}


def go_to_workspace(selected):
    st.session_state["active_portfolio"] = selected
    st.session_state.pop("building_portfolio", None)
    st.session_state.pop("portfolio_editor_input", None)
    st.session_state.pop("portfolio_draft", None)
    st.rerun()


def start_builder(method, current=None):
    st.session_state["portfolio_editor_input"] = current
    st.session_state["building_portfolio"] = method
    st.session_state.pop("portfolio_draft", None)
    st.rerun()


def show_home(db):
    _, content, _ = st.columns([1, 6, 1])
    with content:
        st.title("Your portfolios")
        st.caption("No portfolio open")
        saved_column, create_column = st.columns(2, gap="medium")
        with saved_column, st.container(border=True):
            st.subheader("Open a saved portfolio")
            saved = list_portfolios(db)
            if saved:
                labels = {key: f"{name} · {count} {'holding' if count == 1 else 'holdings'}"
                          for key, name, count, _ in saved}
                selected = st.selectbox("Saved portfolio", list(labels), index=None, format_func=labels.get,
                                        placeholder="Select a portfolio", label_visibility="collapsed")
                if st.button("Open portfolio", type="primary", disabled=selected is None, width="stretch"):
                    go_to_workspace(selected)
            else:
                st.write("Your saved portfolios will appear here.")
        with create_column, st.container(border=True):
            st.subheader("Create a portfolio")
            st.write("Upload a CSV or search for holdings and enter weights.")
            if st.button("Upload CSV", type="primary", width="stretch"):
                start_builder("Upload CSV")
            if st.button("Enter holdings", width="stretch"):
                start_builder("Enter holdings")
        with st.expander("Try an example"):
            for key, name in EXAMPLES.items():
                if st.button(name):
                    go_to_workspace(key)


def show_market_data(db):
    st.subheader("ASX market data")
    market = pd.read_sql_query("""
        SELECT ticker AS Ticker, name AS Company, trade_date AS 'Price date', close AS Close,
               currency AS Currency, sector AS 'EODHD GICS sector',
               observed_date AS 'Sector checked', source AS Source
        FROM latest_asx_market_data ORDER BY ticker
    """, db)
    if market.empty:
        st.info("Price records will appear here when available.")
    else:
        st.dataframe(market, hide_index=True)


def show_workspace(db, selected, name, holdings):
    st.title(name)
    st.caption(f"{len(holdings)} {'holding' if len(holdings) == 1 else 'holdings'}"
               + (" · Illustrative portfolio" if selected in EXAMPLES else ""))
    back, edit, _ = st.columns([1, 1, 3])
    if back.button("All portfolios", width="stretch"):
        go_to_workspace(None)
    if isinstance(selected, int) and edit.button("Edit holdings", width="stretch"):
        start_builder("Enter holdings", (name, holdings))
    catalog = listing_catalog(db)
    asx_equities = {key for key, (_, kind, _) in catalog.items() if key[0] == "ASX" and kind == "EQUITY"}
    direct_only = all((exchange, ticker) in asx_equities for ticker, exchange, _ in holdings)
    if selected == "mixed":
        direct_only = False
        catalog["ASX", "VAS"] = ("Vanguard Australian Shares Index ETF", "ETF", False)
    pages = ["Overview", "Benchmark & scenarios", "Market data"]
    if not direct_only:
        pages.insert(1, "ETF look-through")
    page = st.radio("Portfolio view", pages, horizontal=True, key=f"workspace_view_{selected}",
                    label_visibility="collapsed")
    if page == "Market data":
        show_market_data(db)
    elif page == "Overview":
        if direct_only:
            show_asx_overview(db, holdings)
        else:
            st.subheader("Holdings")
            rows = [(ticker, exchange, catalog.get((exchange, ticker), ("", "Unmapped", False))[1].title(), weight)
                    for ticker, exchange, weight in holdings]
            st.dataframe(pd.DataFrame(rows, columns=["Ticker", "Exchange", "Type", "Weight (%)"]),
                         hide_index=True, column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%")})
    else:
        if selected == "mixed":
            with closing(sqlite3.connect(":memory:")) as example_db:
                load_reference(example_db, ROOT / "examples/instruments.csv", ROOT / "examples/constituents.csv")
                paths = exposure_paths(example_db, holdings)
        else:
            paths = exposure_paths(db, holdings, asx_equities)
        if page == "ETF look-through":
            if selected == "mixed":
                st.caption("The VAS holdings are illustrative and intentionally partial.")
            show_etf_paths(pd.DataFrame(paths))
        else:
            show_benchmark_analysis(db, name, paths)


def show_dashboard(path):
    st.set_page_config(page_title="Portfolio analytics", layout="wide")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        initialise_portfolio(db)
        migrate_legacy_portfolios(db)
        selected = st.session_state.get("active_portfolio")
        method = st.session_state.get("building_portfolio")
        if method:
            current = st.session_state.get("portfolio_editor_input")
            st.title(f"Edit {current[0]}" if current else "New portfolio")
            if st.button("Cancel and go back"):
                go_to_workspace(selected)
            saved = show_builder(db, selected if current else None, method)
            if saved is not None:
                go_to_workspace(saved)
            return
        if selected == "asx":
            portfolio = EXAMPLES[selected], sample_weights()
        elif selected == "mixed":
            portfolio = EXAMPLES[selected], read_holdings(ROOT / "holdings.csv")
        elif selected is not None:
            portfolio = load_portfolio(db, selected)
        else:
            portfolio = None
        if portfolio:
            show_workspace(db, selected, *portfolio)
        else:
            show_home(db)
