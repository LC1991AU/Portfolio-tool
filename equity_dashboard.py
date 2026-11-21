"""Price refresh and overview for a selected ASX share portfolio."""

import sqlite3

import streamlit as st

from asx_market import FeedUnavailable, api_token, refresh_prices
from equity_portfolio import performance, portfolio_overview


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


def show_asx_overview(db, holdings):
    token = api_token()
    if st.button("Refresh daily prices", disabled=not token):
        refresh_market(db, holdings, token)
    if not token:
        st.caption("Set EODHD_API_TOKEN to enable price refresh.")
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
                "Sector source": st.column_config.LinkColumn(display_text="Reference"),
            },
        )
        st.caption("Closing prices in AUD. Sector sources include the ASX directory and EODHD where available.")

    if not daily.empty:
        with st.expander("Daily stock returns"):
            st.dataframe(daily.sort_index(ascending=False).mul(100), column_config={
                "trade_date": st.column_config.DateColumn("Trading date", format="YYYY-MM-DD"),
                **{ticker: st.column_config.NumberColumn(format="%.2f%%") for ticker in daily.columns},
            })
