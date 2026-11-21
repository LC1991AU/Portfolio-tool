"""Refresh EODHD prices and observed GICS classifications for selected ASX shares."""

import argparse
import json
import math
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from load_holdings import ROOT


def initialise(db):
    db.executescript((ROOT / "market_schema.sql").read_text(encoding="utf-8"))


class FeedUnavailable(ValueError):
    """An authentication, quota or connection failure affecting the whole feed."""


def api_token():
    token = os.getenv("EODHD_API_TOKEN")
    if token or os.name != "nt":
        return token
    # Running Streamlit processes may predate the user's Windows setting.
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            return winreg.QueryValueEx(key, "EODHD_API_TOKEN")[0]
    except OSError:
        return None


def get_json(endpoint, token, **params):
    query = urlencode(dict(params, api_token=token, fmt="json"))
    try:
        with urlopen(f"https://eodhd.com/api/{endpoint}?{query}", timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        error_type = FeedUnavailable if error.code in {401, 402, 403, 429} else ValueError
        raise error_type(f"EODHD returned HTTP {error.code} for {endpoint}") from None
    except (URLError, TimeoutError, OSError):
        raise FeedUnavailable(f"Could not connect to EODHD for {endpoint}") from None
    except (ValueError, UnicodeError):
        raise ValueError(f"Could not retrieve valid JSON for {endpoint}") from None


def price(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("Expected a positive finite price")
    return number


def save_snapshot(db, ticker, general, bars, now):
    if not isinstance(general, dict) or general.get("Code") != ticker or general.get("Exchange") != "AU":
        raise ValueError("Fundamentals did not identify the requested Australian listing")
    if not general.get("Name") or not general.get("CurrencyCode"):
        raise ValueError("Missing name or quote currency")
    levels = [general.get(field) or None for field in ("GicSector","GicGroup","GicIndustry","GicSubIndustry")]
    save_prices(db, ticker, bars, now, general["Name"], general["CurrencyCode"], levels)


def save_prices(db, ticker, bars, now, name=None, currency="AUD", levels=None):
    if not isinstance(bars, list) or not bars:
        raise ValueError("No price history returned in the requested window")
    timestamp = now.isoformat()
    prices = []
    for bar in bars:
        day = date.fromisoformat(bar["date"]).isoformat()
        op, hi, lo, cl = (price(bar[key]) for key in ("open","high","low","close"))
        if not lo <= min(op, cl) <= max(op, cl) <= hi:
            raise ValueError(f"Inconsistent OHLC prices for {day}")
        adjusted = bar.get("adjusted_close")
        volume = bar.get("volume")
        if volume is not None and (type(volume) is not int or volume < 0):
            raise ValueError(f"Invalid volume for {day}")
        prices.append(("ASX", ticker, day, op, hi, lo, cl, price(adjusted) if adjusted is not None else None,
                       volume, timestamp))
    with db:
        db.execute("""INSERT INTO market_listings VALUES ('ASX',?,?,?,?, 'EODHD')
                      ON CONFLICT(exchange,ticker) DO NOTHING""",
                   (ticker, f"{ticker}.AU", name or ticker, currency))
        db.executemany("""INSERT INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(exchange,ticker,trade_date) DO UPDATE SET
                          open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                          adjusted_close=excluded.adjusted_close, volume=excluded.volume,
                          fetched_utc=excluded.fetched_utc
                          WHERE excluded.fetched_utc >= daily_prices.fetched_utc""", prices)
        if levels is not None:
            db.execute("UPDATE market_listings SET name=?, currency=? WHERE exchange='ASX' AND ticker=?",
                       (name, currency, ticker))
            db.execute("INSERT OR REPLACE INTO gics_observations VALUES (?,?,?,?,?,?,?,?)",
                       ("ASX", ticker, now.date().isoformat(), *levels, timestamp))


def refresh_prices(db, ticker, token, start=None):
    now = datetime.now(timezone.utc)
    start = start or now.date() - timedelta(days=365)
    bars = get_json(f"eod/{ticker}.AU", token, **{"from": start.isoformat(), "period": "d"})
    ref = db.execute("SELECT company FROM asx_builder_securities WHERE ticker=?", (ticker,)).fetchone()
    save_prices(db, ticker, bars, now, name=ref[0] if ref else None)
    return len(bars)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="ASX codes, e.g. BHP CBA CSL")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "portfolio.db")
    parser.add_argument("--from-date", type=date.fromisoformat,
                        help="Start of price window (default: last 365 days)")
    parser.add_argument("--init-only", action="store_true")
    parser.add_argument("--prices-only", action="store_true")
    args = parser.parse_args()
    tickers = list(dict.fromkeys(t.upper() for t in args.tickers))
    token = api_token()
    if not args.init_only and (not tickers or not token):
        parser.error("Supply ASX tickers and set EODHD_API_TOKEN in the environment.")
    if any(not re.fullmatch(r"[A-Z0-9]{1,10}", t) for t in tickers):
        parser.error("Use bare ASX ticker codes, e.g. BHP")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    start = args.from_date or now.date() - timedelta(days=365)
    failures = []
    with closing(sqlite3.connect(args.database)) as db:
        initialise(db)
        if args.init_only:
            print("Market data tables ready.")
            return
        for ticker in tickers:
            symbol = f"{ticker}.AU"
            try:
                if args.prices_only:
                    print(f"{ticker}: {refresh_prices(db, ticker, token, start)} prices")
                    continue
                general = get_json(f"v1.1/fundamentals/{symbol}", token, filter="General")
                general = general.get("General", general) if isinstance(general, dict) else general
                bars = get_json(f"eod/{symbol}", token, **{"from": start.isoformat(), "period": "d"})
                save_snapshot(db, ticker, general, bars, now)
                print(f"{ticker}: {len(bars)} prices; GICS sector: {general.get('GicSector') or 'unclassified'}")
            except (ValueError, KeyError, TypeError, sqlite3.Error) as error:
                failures.append(f"{ticker}: {error}")
    if failures:
        parser.exit(1, "\n".join(failures) + "\n")


if __name__ == "__main__":
    main()
