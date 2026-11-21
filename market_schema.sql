PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS market_listings (
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    provider_symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    currency TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (exchange, ticker)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL CHECK (close > 0),
    adjusted_close REAL CHECK (adjusted_close > 0),
    volume INTEGER CHECK (volume >= 0),
    fetched_utc TEXT NOT NULL,
    PRIMARY KEY (exchange, ticker, trade_date),
    FOREIGN KEY (exchange, ticker) REFERENCES market_listings
);

CREATE TABLE IF NOT EXISTS gics_observations (
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    observed_date TEXT NOT NULL,
    sector TEXT,
    industry_group TEXT,
    industry TEXT,
    sub_industry TEXT,
    fetched_utc TEXT NOT NULL,
    PRIMARY KEY (exchange, ticker, observed_date),
    FOREIGN KEY (exchange, ticker) REFERENCES market_listings
);

CREATE VIEW IF NOT EXISTS latest_asx_market_data AS
SELECT l.exchange, l.ticker, l.name, l.currency, l.source,
       p.trade_date, p.close, p.adjusted_close, g.sector, g.observed_date
FROM market_listings l
LEFT JOIN daily_prices p ON (p.exchange,p.ticker) = (l.exchange,l.ticker)
    AND p.trade_date = (SELECT MAX(trade_date) FROM daily_prices
                        WHERE exchange=l.exchange AND ticker=l.ticker)
LEFT JOIN gics_observations g ON (g.exchange,g.ticker) = (l.exchange,l.ticker)
    AND g.observed_date = (SELECT MAX(observed_date) FROM gics_observations
                           WHERE exchange=l.exchange AND ticker=l.ticker)
WHERE l.exchange='ASX';

CREATE VIEW IF NOT EXISTS asx_daily_returns AS
WITH sessions AS (
    SELECT trade_date, LAG(trade_date) OVER (ORDER BY trade_date) AS previous_date
    FROM (SELECT DISTINCT trade_date FROM daily_prices WHERE exchange='ASX')
)
SELECT p.ticker, p.trade_date, s.previous_date, p.adjusted_close,
       p.adjusted_close / prior.adjusted_close - 1.0 AS daily_return
FROM daily_prices p
JOIN sessions s ON p.trade_date = s.trade_date
LEFT JOIN daily_prices prior ON (prior.exchange, prior.ticker, prior.trade_date) =
                                (p.exchange, p.ticker, s.previous_date)
WHERE p.exchange='ASX';

CREATE TABLE IF NOT EXISTS asx_sector_reference (
    ticker TEXT PRIMARY KEY NOT NULL,
    company TEXT NOT NULL,
    sector TEXT NOT NULL,
    source_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asx_portfolio_holdings (
    ticker TEXT PRIMARY KEY NOT NULL,
    weight_pct REAL NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100)
);

CREATE TABLE IF NOT EXISTS security_master (
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company TEXT NOT NULL,
    gics_industry_group TEXT,
    gics_sector TEXT,
    source_url TEXT NOT NULL,
    observed_date TEXT NOT NULL,
    PRIMARY KEY (exchange, ticker)
);

CREATE TABLE IF NOT EXISTS index_universe_snapshot (
    index_code TEXT PRIMARY KEY NOT NULL,
    observed_date TEXT NOT NULL,
    source_url TEXT NOT NULL,
    coverage TEXT NOT NULL CHECK (coverage IN ('partial', 'complete'))
);

CREATE TABLE IF NOT EXISTS index_universe_members (
    index_code TEXT NOT NULL REFERENCES index_universe_snapshot,
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    PRIMARY KEY (index_code, exchange, ticker),
    FOREIGN KEY (exchange, ticker) REFERENCES security_master (exchange, ticker)
);

CREATE VIEW IF NOT EXISTS asx_builder_securities AS
SELECT s.ticker, s.company, s.gics_sector AS sector, s.source_url,
       x.ticker IS NOT NULL AS reported_xao
FROM security_master s
LEFT JOIN index_universe_members x ON (x.exchange,x.ticker)=(s.exchange,s.ticker) AND x.index_code='XAO'
WHERE s.exchange='ASX'
UNION ALL
SELECT t.ticker, t.company, t.sector, t.source_url, 0
FROM asx_sector_reference t
WHERE NOT EXISTS (SELECT 1 FROM security_master s WHERE s.exchange='ASX' AND s.ticker=t.ticker);

CREATE TABLE IF NOT EXISTS benchmark_snapshots (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    imported_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_weights (
    snapshot_id INTEGER NOT NULL REFERENCES benchmark_snapshots,
    exchange TEXT NOT NULL,
    ticker TEXT NOT NULL,
    weight_pct REAL NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
    PRIMARY KEY (snapshot_id, exchange, ticker)
);

CREATE TABLE IF NOT EXISTS stress_runs (
    id INTEGER PRIMARY KEY,
    created_utc TEXT NOT NULL,
    portfolio_name TEXT NOT NULL,
    benchmark_name TEXT NOT NULL,
    benchmark_date TEXT,
    shock_scope TEXT NOT NULL,
    shock_target TEXT NOT NULL,
    shock_pct REAL NOT NULL,
    portfolio_value_aud REAL NOT NULL CHECK (portfolio_value_aud > 0),
    portfolio_return_pct REAL NOT NULL,
    benchmark_return_pct REAL NOT NULL,
    portfolio_coverage_pct REAL NOT NULL,
    benchmark_coverage_pct REAL NOT NULL,
    result_json TEXT NOT NULL
);
