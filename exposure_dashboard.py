import streamlit as st


def show_etf_paths(paths):
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

