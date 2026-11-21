"""Streamlit benchmark and stress tools shared by both portfolio views."""

import csv
import io
import sqlite3
from datetime import date

import pandas as pd
import streamlit as st

from portfolio_analysis import (
    classify, compare_weights, direct_exposures, import_benchmark, latest_benchmark,
    reference_benchmark, save_stress_run, stress_test,
)


def choose_benchmark(db):
    saved = latest_benchmark(db)
    with st.expander("Upload a benchmark CSV"):
        st.caption("Use ticker, exchange and weight_pct. Include ASX shares that total 100%.")
        with st.form("benchmark_upload"):
            name = st.text_input("Benchmark name", max_chars=100)
            effective = st.date_input("Weights as of", value=date.today())
            uploaded = st.file_uploader("Benchmark CSV", type="csv")
            submitted = st.form_submit_button("Save benchmark")
        if submitted:
            if uploaded is None:
                st.error("Choose a benchmark CSV.")
            else:
                try:
                    content = uploaded.getvalue().decode("utf-8-sig")
                    import_benchmark(db, name, effective.isoformat(), io.StringIO(content))
                    st.session_state["select_saved_benchmark"] = True
                    st.rerun()
                except (ValueError, csv.Error, sqlite3.Error) as error:
                    st.error(str(error))
    sample = reference_benchmark()
    if saved is None:
        st.caption(f"{sample.name} · Synthetic weights · AUD")
        return sample
    if st.session_state.pop("select_saved_benchmark", False):
        st.session_state["benchmark_choice"] = "Uploaded benchmark"
    label = st.radio("Benchmark", ["Uploaded benchmark", "Illustrative benchmark"],
                     horizontal=True, key="benchmark_choice")
    benchmark = saved if label == "Uploaded benchmark" else sample
    if benchmark.effective_date:
        st.caption(f"{benchmark.name} · Weights as of {benchmark.effective_date} · AUD")
    else:
        st.caption(f"{sample.name} · Synthetic weights · AUD")
    return benchmark


def show_benchmark_analysis(db, portfolio_name, exposures):
    benchmark = choose_benchmark(db)
    paths = classify(db, exposures)
    benchmark_paths = classify(db, direct_exposures(benchmark.holdings))
    if paths["Issue"].ne("").any():
        unresolved_weight = paths.loc[paths["Issue"] != "", "Weight"].sum()
        st.caption(f"{unresolved_weight:.2f}% of portfolio weight is unresolved. "
                   "Active weights for individual securities use the identified exposures.")
    sectors = compare_weights(paths, benchmark_paths, "Sector")
    securities = compare_weights(paths, benchmark_paths, "Security")
    percentage_points = st.column_config.NumberColumn(format="%+.2f")
    percent = st.column_config.NumberColumn(format="%.2f%%")
    weights_format = {column: percent for column in securities.columns[:-1]}
    weights_format["Active weight (pp)"] = percentage_points

    st.subheader("Active weights")
    sector_tab, ticker_tab = st.tabs(["GICS sectors", "Securities"])
    with sector_tab:
        st.bar_chart(sectors[["Active weight (pp)"]], horizontal=True, x_label="Percentage points",
                     color="#20776e")
        st.dataframe(sectors, column_config=weights_format)
    with ticker_tab:
        st.dataframe(securities, column_config=weights_format)

    st.subheader("Scenario analysis")
    st.caption("Apply one price shock. Other prices stay fixed and the benchmark starts at the same AUD value.")
    scope = st.selectbox("Shock scope", ["Sector", "Security", "All equities"])
    target = "All equities"
    if scope != "All equities":
        dimension = "Sector" if scope == "Sector" else "Security"
        known_equities = pd.concat([paths, benchmark_paths])
        options = sorted(set(known_equities.loc[known_equities["Kind"] == "EQUITY", dimension])
                         - {"Unclassified", "Unresolved"})
        if not options:
            st.info(f"No identified {dimension.lower()} exposures are available for this scenario.")
            return
        target = st.selectbox(f"{dimension} to shock", options)
    shock_col, value_col = st.columns(2)
    shock = shock_col.number_input("Price shock (%)", min_value=-100.0, max_value=100.0, value=-20.0, step=1.0)
    value = value_col.number_input("Starting value (AUD)", min_value=1.0, max_value=1_000_000_000_000.0,
                                   value=100_000.0, step=1_000.0, format="%.2f")
    portfolio = stress_test(paths, scope, target, shock)
    reference = stress_test(benchmark_paths, scope, target, shock)
    details, portfolio_return, portfolio_coverage = portfolio
    reference_details, reference_return, reference_coverage = reference
    port_col, bench_col, relative_col = st.columns(3)
    port_col.metric("Portfolio impact", f"{portfolio_return:+.2f}%", f"AUD {value * portfolio_return / 100:+,.0f}",
                    delta_color="off")
    bench_col.metric("Benchmark impact", f"{reference_return:+.2f}%", f"AUD {value * reference_return / 100:+,.0f}",
                     delta_color="off")
    difference = portfolio_return - reference_return
    relative_col.metric("Relative impact", f"{difference:+.2f} pp", f"AUD {value * difference / 100:+,.0f}",
                         delta_color="off")
    st.caption(f"Coverage for this shock: {portfolio_coverage:.2f}% of portfolio weight and "
               f"{reference_coverage:.2f}% of benchmark weight.")
    scoped = pd.concat([details.assign(Book="Portfolio"), reference_details.assign(Book="Benchmark")])
    scoped = scoped.loc[scoped["In scope"]].drop(columns="In scope").rename(columns={"Weight": "Weight (%)"})
    if not scoped.empty:
        st.dataframe(scoped[["Book", "Security", "Source path", "Weight (%)", "Contribution (pp)"]],
                     hide_index=True, column_config={"Weight (%)": percent, "Contribution (pp)": percentage_points})
    if st.button("Save scenario"):
        try:
            save_stress_run(db, portfolio_name, benchmark, scope, target, shock, value, portfolio, reference)
            st.success("Scenario saved.")
        except sqlite3.Error as error:
            st.error(f"Could not save the scenario. {error}")
    with st.expander("Recent saved scenarios"):
        recent = pd.read_sql_query("""
            SELECT created_utc AS "Saved (UTC)", benchmark_name AS Benchmark, shock_target AS Target,
                   shock_pct AS "Shock (%)", portfolio_return_pct AS "Portfolio (%)",
                   benchmark_return_pct AS "Benchmark (%)"
            FROM stress_runs WHERE portfolio_name=? ORDER BY id DESC LIMIT 10
        """, db, params=(portfolio_name,))
        st.dataframe(recent, hide_index=True)
