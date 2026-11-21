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


def get_json(endpoint, token, **params):
    query = urlencode(dict(params, api_token=token, fmt="json"))
    try:
        with urlopen(f"https://eodhd.com/api/{endpoint}?{query}", timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(f"EODHD returned HTTP {error.code} for {endpoint}") from None
    except (URLError, TimeoutError, OSError, ValueError):
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
    levels = [general.get(field) or None for field in ("GicSector","GicGroup","GicIndustry","GicSubIndustry")]
    with db:
        db.execute("""INSERT INTO market_listings VALUES (?,?,?,?,?,?)
                      ON CONFLICT(exchange,ticker) DO UPDATE SET name=excluded.name,currency=excluded.currency""",
                   ("ASX",ticker,f"{ticker}.AU",general["Name"],general["CurrencyCode"],"EODHD"))
        db.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?,?,?,?,?,?,?,?,?,?)", prices)
        db.execute("INSERT OR REPLACE INTO gics_observations VALUES (?,?,?,?,?,?,?,?)",
                   ("ASX",ticker,now.date().isoformat(),*levels,timestamp))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="*", help="ASX codes, e.g. BHP CBA CSL")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "portfolio.db")
    parser.add_argument("--from-date", type=date.fromisoformat,
                        help="Start of price window (default: last 365 days)")
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    tickers = list(dict.fromkeys(t.upper() for t in args.tickers))
    token = os.getenv("EODHD_API_TOKEN")
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
