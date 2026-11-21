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
