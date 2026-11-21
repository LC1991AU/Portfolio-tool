# Portfolio tool

## ASX portfolio

The dashboard opens with ten equal-weight ASX shares. Select **Refresh daily prices** to download up to one year of prices from EODHD. With ten holdings, the button makes ten standard EOD calls. It reads `EODHD_API_TOKEN` from the local environment or the Windows user environment settings. The dashboard uses EODHD adjusted closes to calculate daily returns. Growth of $100 models daily rebalancing to the entered weights over the most recent uninterrupted set of sessions priced for all holdings.

Open **Upload or edit a portfolio** to upload a CSV or enter weights in the browser. Search the ASX catalog by ticker or company name, choose the shares, then enter weights that total 100%. The downloadable CSV uses the ten-share example to show the column format. Saving stores one custom ASX portfolio locally. Shares can be saved and included in sector weights before their prices are available.

### All Ordinaries security catalog

Populate or update the local catalog from the [ASX company directory](https://www.asx.com.au/asx/research/ASXListedCompanies.csv) and [FNArena's published All Ordinaries list](https://fnarena.com/index/ALL-ORDS/):

```powershell
& "$env:USERPROFILE\.venv\Scripts\python.exe" asx_catalog.py --all-ordinaries
```

The security master stores the ASX code, company, GICS industry group, parent sector, source and observation date. Index membership is a separate dated snapshot. In the builder, **Filter to All Ordinaries** narrows the security picker to that list and retains any positions you already hold for editing. ASX directory issuers with classification pending appear as Unclassified. The catalog and index import use no EODHD price calls. The ten-share example is also available on an empty local database.

The sample sector classifications use [Market Index's GICS sector listings](https://www.marketindex.com.au/asx-sectors) before the ASX catalog is loaded. Existing nonempty EODHD GICS values take precedence in the portfolio overview. Price refresh makes no fundamentals calls.

Use **ETF look-through** in the sidebar for the ETF exposure workflow below.

## Benchmark comparison and scenarios

Select **Benchmark & scenarios** in the ASX portfolio view or **Compare benchmark and run scenarios** below the ETF look-through. The built-in ASX benchmark uses illustrative weights. Upload a dated ASX benchmark CSV with the same `ticker,exchange,weight_pct` layout used for portfolios. The active weight is the portfolio percentage minus the benchmark percentage, in percentage points. Both tables include benchmark-only positions. The comparison retains any unresolved portfolio weight.

Apply a one-off security, sector or broad equity shock. The app compares both portfolios at the same starting AUD value and traces each affected position. Cash has zero impact. A sector shock leaves unclassified holdings outside its coverage, and all shocks leave unresolved holdings outside coverage. Save the run to store the weights by ownership path, assumptions, results and coverage in SQLite. This analysis uses holdings percentages without requiring a price refresh.

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
