"""Load one reference snapshot and attribute each portfolio weight to its source."""

import argparse
import csv
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from load_holdings import ROOT


def read_csv(path, columns):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        if next(reader, []) != columns.split(","):
            raise ValueError(f"{path.name}: expected columns {columns}")
        for line, row in enumerate(reader, 2):
            if len(row) != len(columns.split(",")) or any(not field.strip() for field in row):
                raise ValueError(f"{path.name}, line {line}: incomplete or malformed row")
            yield [field.strip().upper() for field in row]


def load_reference(conn, instruments, constituents):
    kinds = {}
    for exchange, ticker, kind in read_csv(instruments, "exchange,ticker,kind"):
        key = exchange, ticker
        if key in kinds or kind not in {"EQUITY", "ETF", "CASH"}:
            raise ValueError(f"Duplicate listing or invalid instrument type: {key}")
        kinds[key] = kind

    edges = []
    seen = set()
    totals = defaultdict(float)
    for fx, ft, cx, ct, raw in read_csv(constituents, "fund_exchange,fund_ticker,exchange,ticker,weight_pct"):
        parent, child = (fx, ft), (cx, ct)
        weight = float(raw)
        if kinds.get(parent) != "ETF" or child not in kinds:
            raise ValueError(f"Unknown constituent or invalid ETF: {parent} -> {child}")
        if (parent, child) in seen or not 0 < weight <= 100:
            raise ValueError(f"Duplicate constituent or invalid weight: {parent} -> {child}")
        seen.add((parent, child))
        totals[parent] += weight
        if totals[parent] > 100 + 1e-9:
            raise ValueError(f"Constituent weights exceed 100% for {parent}")
        edges.append((fx, ft, cx, ct, weight))

    with conn:
        conn.execute("CREATE TABLE IF NOT EXISTS instruments (exchange TEXT, ticker TEXT, kind TEXT, PRIMARY KEY(exchange,ticker))")
        conn.execute("""CREATE TABLE IF NOT EXISTS constituents (
            fund_exchange TEXT, fund_ticker TEXT, exchange TEXT, ticker TEXT, weight_pct REAL,
            PRIMARY KEY(fund_exchange,fund_ticker,exchange,ticker))""")
        conn.execute("DELETE FROM constituents")
        conn.execute("DELETE FROM instruments")
        conn.executemany("INSERT INTO instruments VALUES (?,?,?)", [(x,t,k) for (x,t),k in kinds.items()])
        conn.executemany("INSERT INTO constituents VALUES (?,?,?,?,?)", edges)


def exposure_paths(conn):
    kinds = {(x,t): k for x,t,k in conn.execute("SELECT exchange,ticker,kind FROM instruments")}
    children = defaultdict(list)
    for fx,ft,cx,ct,w in conn.execute("SELECT fund_exchange,fund_ticker,exchange,ticker,weight_pct FROM constituents"):
        children[fx,ft].append(((cx,ct), w))
    rows = []

    def expand(key, allocation, ancestors):
        path = ancestors + (key,)
        listing = ":".join(key)
        def record(name, reason=""):
            rows.append({"Exposure": name, "Source path": " → ".join(":".join(k) for k in path),
                         "Route": "Via ETF" if ancestors or kinds.get(key) == "ETF" else "Direct",
                         "Weight": allocation, "Issue": reason, "Kind": kinds.get(key) if not reason else None})

        if key in ancestors:
            record(f"Unresolved · {listing}", "Circular ETF holding")
        elif key not in kinds:
            record(f"Unresolved · {listing}", "Unknown instrument type")
        elif kinds[key] != "ETF":
            record(listing)
        else:
            members = children[key]
            for child, weight in members:
                expand(child, allocation * weight / 100, path)
            residual = 100 - sum(weight for _, weight in members)
            if residual > 1e-9:
                allocation *= residual / 100
                record(f"Unresolved · {listing}", "Incomplete constituent coverage")

    for x,t,w in conn.execute("SELECT exchange,ticker,weight_pct FROM holdings ORDER BY exchange,ticker"):
        expand((x,t), w, ())
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instruments", type=Path)
    parser.add_argument("constituents", type=Path)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "portfolio.db")
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(args.database)) as db:
        load_reference(db, args.instruments, args.constituents)
    print("ETF reference snapshot imported.")
