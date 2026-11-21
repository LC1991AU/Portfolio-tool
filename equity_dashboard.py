"""Streamlit pages for the 10-share ASX portfolio."""

import csv
import io
import sqlite3
from contextlib import closing

import pandas as pd
import streamlit as st

from asx_market import FeedUnavailable, api_token, refresh_prices
from equity_portfolio import (
    initialise_portfolio, performance, portfolio_csv, portfolio_overview,
    sample_reference, sample_weights, save_portfolio, saved_weights, validate_portfolio,
)


def edit_portfolio(db, holdings):
    upload, manual = st.tabs(["Upload CSV", "Enter weights"])
    with upload:
        st.caption("Use ticker, exchange and weight_pct columns. Enter 10 for a 10% weight.")
        st.download_button("Download CSV template", portfolio_csv(), "asx_portfolio.csv", "text/csv")
        uploaded = st.file_uploader("Portfolio CSV", type="csv")
        if uploaded is not None:
            try:
                content = uploaded.getvalue().decode("utf-8-sig")
                rows = validate_portfolio(io.StringIO(content))
                st.dataframe(pd.DataFrame(rows, columns=["Ticker", "Exchange", "Weight (%)"]), hide_index=True)
                if st.button("Save uploaded portfolio"):
                    save_portfolio(db, io.StringIO(content))
                    return True
            except (ValueError, csv.Error, sqlite3.Error) as error:
                st.error(str(error))

    with manual:
        st.caption("Set unused shares to zero. Positive weights must add up to 100%.")
        current = {ticker: weight for ticker, _, weight in holdings}
        editable = pd.DataFrame(
            [(row["ticker"], current.get(row["ticker"], 0.0)) for row in sample_reference()],
            columns=["Ticker", "Weight (%)"],
        )
        with st.form("manual_weights"):
            edited = st.data_editor(
                editable, hide_index=True, disabled=["Ticker"],
                column_config={"Weight (%)": st.column_config.NumberColumn(min_value=0, max_value=100, required=True)},
            )
            submitted = st.form_submit_button("Save entered weights")
        if submitted:
            content = io.StringIO()
            writer = csv.writer(content)
            writer.writerow(["ticker", "exchange", "weight_pct"])
            writer.writerows((ticker, "ASX", weight) for ticker, weight in edited.itertuples(index=False, name=None)
                             if weight != 0)
            content.seek(0)
            try:
                save_portfolio(db, content)
                return True
            except (ValueError, csv.Error, sqlite3.Error) as error:
                st.error(str(error))
    return False


def refresh_market(db, holdings, token):
    progress = st.progress(0, text="Downloading daily prices")
    updated, failures = [], []
    for index, (ticker, _, _) in enumerate(holdings, 1):
        try:
            refresh_prices(db, ticker, token)
            updated.append(ticker)
        except FeedUnavailable as error:
            failures.append(str(error))
            break
        except (ValueError, TypeError, KeyError, sqlite3.Error):
            failures.append(f"{ticker}: could not load valid daily price data.")
        progress.progress(index / len(holdings), text=f"Processed {ticker}")
    progress.empty()
    if updated:
        st.success(f"Refreshed prices for {len(updated)} of {len(holdings)} shares.")
    for failure in failures:
        st.warning(failure)


def show_asx_portfolio(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db:
        initialise_portfolio(db)
        saved = saved_weights(db)
        label = "10-share example"
        if st.session_state.pop("portfolio_saved", False):
            st.session_state["asx_view"] = "Saved portfolio"
            st.success("Portfolio saved.")
        if saved:
            label = st.radio("Portfolio", ["Saved portfolio", "10-share example"], horizontal=True, key="asx_view")
        else:
            st.caption("10-share example · 10% per stock")

        with st.expander("Upload or edit a portfolio"):
            if edit_portfolio(db, saved or sample_weights()):
                st.session_state["portfolio_saved"] = True
                st.rerun()

        holdings = saved if label == "Saved portfolio" else sample_weights()
        token = api_token()
        if st.button("Refresh daily prices", type="primary", disabled=not token):
            refresh_market(db, holdings, token)
        if not token:
            st.info("Set EODHD_API_TOKEN on this computer to enable price refresh.")
        positions = portfolio_overview(db, holdings)
        curve, daily = performance(db, holdings)

    priced = positions.loc[positions["close"].notna(), "Weight (%)"].sum()
    left, middle, right = st.columns(3)
    left.metric("Holdings", len(positions))
    middle.metric("Weight with prices", f"{priced:.1f}%")
    right.metric("Cumulative return", "—" if curve.empty else f"{curve.iloc[-1, 0] / 100 - 1:+.2%}")

    if curve.empty:
        st.info("A return chart needs at least two consecutive trading sessions with adjusted prices for every holding.")
    else:
        st.subheader("Portfolio performance")
        first, last = curve.index[[0, -1]]
        st.caption(f"{first:%d %b %Y} to {last:%d %b %Y} · Modelled portfolio rebalanced daily to the entered weights.")
        st.line_chart(curve, y_label="Growth of $100", x_label="Trading date", color="#20776e")

    allocation, holdings_column = st.columns([1, 2])
    with allocation:
        st.subheader("GICS sector allocation")
        sectors = positions.groupby("Sector")["Weight (%)"].sum().sort_values(ascending=False)
        st.bar_chart(sectors, horizontal=True, x_label="Portfolio weight (%)", color="#20776e")
    with holdings_column:
        st.subheader("Holdings")
        table = positions.reset_index().rename(columns={"close": "Close", "price_date": "Price date",
                                                        "daily_return": "Daily return (%)",
                                                        "sector_url": "Sector source"})
        table["Daily return (%)"] *= 100
        st.dataframe(
            table[["Ticker", "Company", "Weight (%)", "Sector", "Close", "Price date", "Daily return (%)", "Sector source"]],
            hide_index=True,
            column_config={
                "Weight (%)": st.column_config.NumberColumn(format="%.2f%%"),
                "Close": st.column_config.NumberColumn(format="$%.2f"),
                "Daily return (%)": st.column_config.NumberColumn(format="%.2f%%"),
                "Sector source": st.column_config.LinkColumn(display_text="Market Index"),
            },
        )
        st.caption("Closing prices in AUD. A blank sector link means an EODHD GICS observation was available.")

    if not daily.empty:
        with st.expander("Daily stock returns"):
            st.dataframe(daily.sort_index(ascending=False).mul(100), column_config={
                "trade_date": st.column_config.DateColumn("Trading date", format="YYYY-MM-DD"),
                **{ticker: st.column_config.NumberColumn(format="%.2f%%") for ticker in daily.columns},
            })
