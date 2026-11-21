"""Portfolio creation and editing screens."""

import csv
import io
import math
import sqlite3

import pandas as pd
import streamlit as st

from equity_portfolio import builder_securities, portfolio_csv
from load_holdings import parse_holdings
from portfolio_store import validate_positions, write_portfolio


def listing_catalog(db):
    catalog = {("ASX", ticker): (company, "EQUITY", in_index)
               for ticker, (company, _, in_index) in builder_securities(db).items()}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='instruments'").fetchone():
        for exchange, ticker, kind in db.execute("SELECT exchange,ticker,kind FROM instruments"):
            company, _, in_index = catalog.get((exchange, ticker), ("", kind, False))
            catalog[exchange, ticker] = (company, kind, in_index)
    return catalog


def csv_positions(catalog):
    st.caption("Use the columns ticker, exchange and weight_pct. Enter 10 for a 10% weight.")
    st.download_button("Download CSV template", portfolio_csv(), "portfolio_template.csv", "text/csv")
    uploaded = st.file_uploader("Portfolio holdings CSV", type="csv")
    if uploaded is None:
        return None
    try:
        rows = parse_holdings(io.StringIO(uploaded.getvalue().decode("utf-8-sig")))
        validate_positions(rows)
    except (ValueError, csv.Error) as error:
        st.error(str(error))
        return None
    unmapped = [f"{exchange}:{ticker}" for ticker, exchange, _ in rows if (exchange, ticker) not in catalog]
    if unmapped:
        preview = ", ".join(unmapped[:8])
        if len(unmapped) > 8:
            preview += f" and {len(unmapped) - 8} more"
        st.warning(f"Check these listings before saving. They will appear as unresolved in analysis: {preview}")
    st.dataframe(pd.DataFrame(rows, columns=["Ticker", "Exchange", "Weight (%)"]), hide_index=True,
                 column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%")})
    return rows


def entered_positions(catalog, holdings):
    initial = {(exchange, ticker): weight for ticker, exchange, weight in holdings}
    draft = st.session_state.setdefault("portfolio_draft", {"weights": initial.copy(), "revision": 0})
    choices = sorted(set(catalog) | set(initial))
    if any(in_index for _, _, in_index in catalog.values()):
        filtered = st.checkbox("Filter ASX shares to All Ordinaries", value=True)
        if filtered:
            retained = set(st.session_state.get("draft_symbols", initial)) | set(initial)
            choices = [listing for listing in choices
                       if listing in retained or catalog[listing][2] or catalog[listing][1] != "EQUITY"]

    def label(listing):
        exchange, ticker = listing
        company, kind, _ = catalog.get(listing, ("", "Unmapped", False))
        return f"{ticker} · {company or kind}" if exchange == "ASX" else f"{exchange}:{ticker} · {company or kind}"

    symbols = st.multiselect("Find holdings by ticker or company", choices, default=list(initial),
                             format_func=label, key="draft_symbols")
    if not symbols:
        st.info("Select at least one holding to enter weights.")
        return None
    if draft.get("symbols") != symbols:
        draft.update(symbols=list(symbols), base=[draft["weights"].get(symbol, 0.0) for symbol in symbols])
        draft["revision"] += 1
    if st.button("Allocate equally"):
        equal = round(100 / len(symbols), 6)
        draft["base"] = [equal] * (len(symbols) - 1) + [round(100 - equal * (len(symbols) - 1), 6)]
        draft["revision"] += 1
    frame = pd.DataFrame({
        "Holding": [label(symbol) for symbol in symbols],
        "Weight (%)": draft["base"],
    })
    edited = st.data_editor(
        frame, hide_index=True, disabled=["Holding"], key=f"portfolio_weights_{draft['revision']}",
        column_config={"Weight (%)": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, required=True,
                                                                   format="%.4f")},
    )
    weights = edited["Weight (%)"].fillna(0).tolist()
    draft["weights"].update(zip(symbols, weights))
    total = math.fsum(weights)
    st.caption(f"Total weight {total:.2f}% of 100%")
    return [(ticker, exchange, weight) for (exchange, ticker), weight in zip(symbols, weights) if weight != 0]


def show_builder(db, portfolio_id, starting_method):
    current = st.session_state.get("portfolio_editor_input")
    name, holdings = current or ("", [])
    methods = ["Upload CSV", "Enter holdings"]
    method = st.radio("Add holdings", methods, index=methods.index(starting_method), horizontal=True,
                      key="portfolio_entry_method", label_visibility="collapsed")
    if portfolio_id is None:
        name = st.text_input("Portfolio name", max_chars=80, placeholder="e.g. Australian equities")
    catalog = listing_catalog(db)
    rows = csv_positions(catalog) if method == "Upload CSV" else entered_positions(catalog, holdings)
    if st.button("Save and open portfolio" if portfolio_id is None else "Save changes",
                 type="primary", disabled=not rows or (portfolio_id is None and not name.strip())):
        try:
            return write_portfolio(db, rows, name=name, portfolio_id=portfolio_id)
        except (ValueError, sqlite3.Error) as error:
            st.error(str(error))
    return None
