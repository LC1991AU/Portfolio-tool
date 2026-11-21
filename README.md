# Portfolio tool

## ASX portfolio

The dashboard opens with ten equal-weight ASX shares. Select **Refresh daily prices** to download up to one year of prices from EODHD. With ten holdings, the button makes ten standard EOD calls. It reads `EODHD_API_TOKEN` from the local environment or the Windows user environment settings. The dashboard uses EODHD adjusted closes to calculate daily returns. Growth of $100 models daily rebalancing to the entered weights over the most recent uninterrupted set of sessions priced for all holdings.

Open **Upload or edit a portfolio** to upload a CSV or enter weights in the browser. The downloadable CSV gives the exact column format and ten supported listings. Enter positive weights that total 100%. The manual editor accepts zero for unused positions. Saving stores one custom ASX portfolio locally and leaves the example available for comparison.

The ten sector classifications are sourced from [Market Index's GICS sector listings](https://www.marketindex.com.au/asx-sectors). Existing nonempty EODHD GICS values take precedence. The sample sectors are reference data and price refresh makes no fundamentals calls. The database stores the sector reference, the saved ASX snapshot and a daily returns view alongside the existing market data.

Use **ETF look-through** in the sidebar for the ETF exposure workflow below.

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

## ASX end-of-day market data

The EODHD adapter loads daily OHLC, adjusted close, volume and observed GICS levels for explicitly selected ASX shares. It uses the Australian exchange suffix `.AU` and the dedicated `GicSector` field. Generic sector names never fill missing GICS classifications. See the [Australian coverage](https://eodhd.com/asx-data), [fundamentals](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds) and [price documentation](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes).

Set the environment variable `EODHD_API_TOKEN` privately to a token entitled to Australian EOD and fundamentals. From the VS Code PowerShell terminal, refresh the starter universe with:

```powershell
& "$env:USERPROFILE\.venv\Scripts\python.exe" asx_market.py BHP CBA CSL
```

Use **Show ASX market data** in the dashboard sidebar. Each run reloads the trailing 365 calendar days and replaces revised prices by trading date; use `--from-date YYYY-MM-DD` for older history or historical adjustment revisions. Each ticker commits independently. A failed ticker leaves its prior data intact and returns a nonzero exit code. The sector date is the UTC observation date; historical classifications begin when you start collecting them. Portfolio look-through can join these records on exchange and ticker. The share feed does not supply ETF weights. Keep tokens and licensed data local and confirm client display and derived-data rights before hosting.

## Run tests

```powershell
.\.venv\Scripts\python -m unittest discover -v
```
