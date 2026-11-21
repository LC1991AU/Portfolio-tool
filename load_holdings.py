"""Import a single portfolio snapshot into a local SQLite database."""

import argparse
import csv
import math
import sqlite3
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def read_holdings(path):
    positions = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["ticker", "exchange", "weight_pct"]:
            raise ValueError("Expected CSV header: ticker,exchange,weight_pct")
        for row in reader:
            if None in row or any(not value or not value.strip() for value in row.values()):
                raise ValueError(f"Line {reader.line_num}: expected three populated fields")
            key = (row["ticker"].strip().upper(), row["exchange"].strip().upper())
            if key in positions:
                raise ValueError(f"Line {reader.line_num}: duplicate listing {key}")
            try:
                weight = float(row["weight_pct"])
            except ValueError:
                raise ValueError(f"Line {reader.line_num}: invalid weight") from None
            if not 0 < weight <= 100:
                raise ValueError(f"Line {reader.line_num}: weight must be above 0 and at most 100")
            positions[key] = weight
    total = math.fsum(positions.values())
    if not math.isclose(total, 100, abs_tol=0.01):
        raise ValueError(f"Weights total {total:.4f}%, expected 100% within 0.01 percentage points")
    return [(ticker, exchange, weight) for (ticker, exchange), weight in positions.items()]


def import_snapshot(source, database):
    rows = read_holdings(source)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS holdings (
                    ticker TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    weight_pct REAL NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
                    PRIMARY KEY (ticker, exchange)
                )
            """)
            connection.execute("DELETE FROM holdings")
            connection.executemany("INSERT INTO holdings (ticker, exchange, weight_pct) VALUES (?, ?, ?)", rows)
        return connection.execute("SELECT ticker, exchange, weight_pct FROM holdings ORDER BY ticker, exchange").fetchall()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", type=Path, default=ROOT / "holdings.csv")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "portfolio.db")
    args = parser.parse_args()
    try:
        holdings = import_snapshot(args.csv, args.database)
    except (ValueError, OSError, csv.Error, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")
    for ticker, exchange, weight in holdings:
        print(f"{exchange}:{ticker}  {weight:.2f}%")
    print(f"{len(holdings)} holdings, total weight {sum(row[2] for row in holdings):.2f}%.")
