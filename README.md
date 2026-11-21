# Portfolio tool

A local Streamlit dashboard for tracing a portfolio through ETF constituents. It combines direct and indirect holdings by exchange and ticker. All bundled weights are illustrative. The example deliberately contains only part of the VAS portfolio.

## Run the dashboard

From the project folder on Windows, with Python installed:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m streamlit run dashboard.py
```

The default **Illustrative example** opens immediately. The example holds 40% BHP and 60% VAS. A synthetic 10% BHP weight in VAS adds 6 percentage points to the portfolio's BHP exposure. The other two disclosed constituents add 7.8 points, leaving 46.2% of the portfolio unresolved.

## Load a local portfolio

Keep private inputs under the ignored `data/` folder. Use the column headers in `holdings.csv`, `examples/instruments.csv` and `examples/constituents.csv` as templates. Weights are percentages. Each reference import replaces both reference tables as a single snapshot. Acceptable instrument kinds are equity, ETF and cash. Register nested ETFs as ETFs. A fund can have zero disclosed constituents. Put its known constituents in the file at their actual portfolio weights.

```powershell
.\.venv\Scripts\python load_holdings.py data/holdings.csv
.\.venv\Scripts\python lookthrough.py data/instruments.csv data/constituents.csv
```

Choose **Local portfolio** in the sidebar. Select a holding to trace its direct and ETF ownership paths. Unmapped positions, circular ETF paths and undisclosed fund weights appear under unresolved holdings. This version handles long-only snapshots and aggregates at the listing level. Prices, hedge overlays, issuer mapping across share classes, historical snapshots and live constituent feeds are future work.

## Verify

```powershell
.\.venv\Scripts\python -m unittest -v test_lookthrough
```
