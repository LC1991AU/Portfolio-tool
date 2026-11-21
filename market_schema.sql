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
