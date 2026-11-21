"""Storage and calculations for a long-only ASX portfolio snapshot."""

import csv
import io

import pandas as pd

from asx_market import initialise
from load_holdings import ROOT, parse_holdings


def sample_reference():
    with (ROOT / "examples/asx_sample.csv").open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def initialise_portfolio(db):
    initialise(db)
    with db:
        db.executemany(
            "INSERT OR IGNORE INTO asx_sector_reference VALUES (?,?,?,?)",
            [(row["ticker"], row["company"], row["sector"],
              "https://www.marketindex.com.au/asx/sectors/" + row["sector_slug"])
             for row in sample_reference()],
        )


def sample_weights():
    reference = sample_reference()
    return [(row["ticker"], "ASX", 100 / len(reference)) for row in reference]


def validate_portfolio(db, stream):
    rows = parse_holdings(stream)
    supported = {row[0] for row in db.execute("SELECT ticker FROM asx_builder_securities")}
    invalid = [f"{exchange}:{ticker}" for ticker, exchange, _ in rows
               if exchange != "ASX" or ticker not in supported]
    if invalid:
        raise ValueError(f"These listings are outside the ASX company catalog: {', '.join(invalid)}.")
    return rows


def portfolio_csv():
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["ticker", "exchange", "weight_pct"])
    writer.writerows(sample_weights())
    return stream.getvalue()


def save_portfolio(db, stream):
    rows = validate_portfolio(db, stream)
    with db:
        db.execute("DELETE FROM asx_portfolio_holdings")
        db.executemany("INSERT INTO asx_portfolio_holdings VALUES (?,?)",
                       [(ticker, weight) for ticker, _, weight in rows])


def saved_weights(db):
    return db.execute("SELECT ticker, 'ASX', weight_pct FROM asx_portfolio_holdings ORDER BY ticker").fetchall()


def builder_securities(db):
    return {ticker: (company, sector, bool(reported)) for ticker, company, sector, reported in db.execute(
        "SELECT ticker,company,sector,reported_xao FROM asx_builder_securities ORDER BY ticker"
    )}


def portfolio_overview(db, holdings):
    reference = pd.read_sql_query("""
        SELECT r.ticker AS Ticker, r.company AS Company, COALESCE(m.sector,r.sector,'Unclassified') AS Sector,
               CASE WHEN m.sector IS NULL AND r.sector IS NOT NULL THEN r.source_url END AS sector_url,
               m.trade_date AS price_date, m.close AS close, d.daily_return AS daily_return,
               m.currency AS currency, m.source AS price_source
        FROM asx_builder_securities r
        LEFT JOIN latest_asx_market_data m ON r.ticker=m.ticker
        LEFT JOIN asx_daily_returns d ON (m.ticker,m.trade_date)=(d.ticker,d.trade_date)
    """, db)
    weights = pd.Series({ticker: weight for ticker, _, weight in holdings}, name="Weight (%)")
    positions = reference.set_index("Ticker").loc[weights.index].join(weights)
    positions.index.name = "Ticker"
    return positions.sort_values("Weight (%)", ascending=False)


def performance(db, holdings):
    """Compound a fixed-weight, daily rebalanced portfolio on complete ASX sessions."""
    weights = pd.Series({ticker: weight for ticker, _, weight in holdings}, dtype=float)
    placeholders = ",".join("?" for _ in weights)
    observations = pd.read_sql_query(
        f"""SELECT ticker, trade_date, adjusted_close, daily_return
        FROM asx_daily_returns WHERE ticker IN ({placeholders}) ORDER BY trade_date""",
        db, params=tuple(weights.index), parse_dates=["trade_date"],
    )
    prices = observations.pivot(index="trade_date", columns="ticker", values="adjusted_close").reindex(columns=weights.index)
    daily = observations.pivot(index="trade_date", columns="ticker", values="daily_return").reindex(columns=weights.index)
    complete = prices.notna().all(axis=1)
    if not complete.any():
        return pd.DataFrame(), daily
    # Start after the last gap before the most recent jointly priced session.
    complete = complete.loc[:complete[complete].index[-1]]
    first = max((i + 1 for i, ok in enumerate(complete) if not ok), default=0)
    valid_dates = complete.index[first:]
    if len(valid_dates) < 2:
        return pd.DataFrame(), daily
    comparable = daily.loc[valid_dates[1:]].dropna()
    if comparable.empty or len(comparable) != len(valid_dates) - 1:
        return pd.DataFrame(), daily
    portfolio_returns = comparable.dot(weights / weights.sum())
    growth = (1 + portfolio_returns).cumprod() * 100
    growth.loc[valid_dates[0]] = 100
    return growth.sort_index().to_frame("Portfolio"), daily
