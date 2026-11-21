"""Benchmark weights and deterministic shocks for direct and looked-through holdings."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd

from equity_portfolio import sample_weights, validate_portfolio


SAMPLE_NAME = "Illustrative ASX benchmark"
WEIGHT_COLUMNS = ["Portfolio weight (%)", "Benchmark weight (%)"]


@dataclass(frozen=True)
class Benchmark:
    name: str
    effective_date: str | None
    holdings: list


def reference_benchmark():
    # Use the same priced names as the demo, but with different allocations.
    weights = {"BHP": 7, "BXB": 5, "CBA": 20, "CSL": 14, "GMG": 13,
               "TCL": 9, "TLS": 8, "WDS": 8, "WES": 9, "WOW": 7}
    return Benchmark(SAMPLE_NAME, None,
                     [(ticker, exchange, weights[ticker]) for ticker, exchange, _ in sample_weights()])


def import_benchmark(db, name, effective_date, source):
    name = name.strip()
    if not name or len(name) > 100:
        raise ValueError("Enter a benchmark name of up to 100 characters.")
    effective = date.fromisoformat(effective_date).isoformat()
    weights = validate_portfolio(db, source)
    with db:
        snapshot = db.execute(
            "INSERT INTO benchmark_snapshots (name,effective_date,imported_utc) VALUES (?,?,?)",
            (name, effective, datetime.now(timezone.utc).isoformat()),
        ).lastrowid
        db.executemany("INSERT INTO benchmark_weights VALUES (?,?,?,?)",
                       [(snapshot, exchange, ticker, weight) for ticker, exchange, weight in weights])


def latest_benchmark(db):
    snapshot = db.execute("SELECT id,name,effective_date FROM benchmark_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if snapshot is None:
        return None
    snapshot_id, name, effective = snapshot
    weights = db.execute(
        "SELECT ticker,exchange,weight_pct FROM benchmark_weights WHERE snapshot_id=? ORDER BY exchange,ticker",
        (snapshot_id,),
    ).fetchall()
    return Benchmark(name, effective, weights)


def direct_exposures(holdings):
    return [dict(Exposure=f"{exchange}:{ticker}", Weight=weight, Kind="EQUITY",
                 Issue="", **{"Source path": f"{exchange}:{ticker}"})
            for ticker, exchange, weight in holdings]


def classify(db, exposures):
    sector_lookup = dict(db.execute("""
        SELECT 'ASX:' || s.ticker, COALESCE(m.sector,s.sector)
        FROM asx_builder_securities s
        LEFT JOIN latest_asx_market_data m ON m.ticker=s.ticker
    """))
    paths = pd.DataFrame(exposures)
    paths["Security"] = paths["Exposure"].where(paths["Issue"] == "", "Unresolved")
    paths["Sector"] = paths["Security"].map(sector_lookup).fillna("Unclassified")
    paths.loc[paths["Kind"] == "CASH", "Sector"] = "Cash"
    paths.loc[paths["Issue"] != "", "Sector"] = "Unresolved"
    return paths


def compare_weights(portfolio, benchmark, dimension):
    comparison = pd.concat([portfolio.groupby(dimension)["Weight"].sum(),
                            benchmark.groupby(dimension)["Weight"].sum()], axis=1).fillna(0.0)
    comparison.columns = WEIGHT_COLUMNS
    comparison["Active weight (pp)"] = comparison.iloc[:, 0] - comparison.iloc[:, 1]
    return comparison.sort_values("Active weight (pp)", ascending=False)


def stress_test(paths, scope, target, shock):
    """Apply a single isolated shock to equities. Keep uncovered exposures visible."""
    if not math.isfinite(shock) or not -100 <= shock <= 100:
        raise ValueError("Shock must be between -100% and +100%.")
    equities = paths["Kind"] == "EQUITY"
    if scope == "Sector":
        matched = equities & (paths["Sector"] == target) & (paths["Sector"] != "Unclassified")
        coverage = (equities & (paths["Sector"] != "Unclassified")) | (paths["Kind"] == "CASH")
    elif scope == "Security":
        matched = equities & (paths["Security"] == target)
        coverage = paths["Issue"] == ""
    elif scope == "All equities":
        matched = equities
        coverage = paths["Issue"] == ""
    else:
        raise ValueError("Choose a valid shock scope.")
    result = paths[["Security", "Sector", "Source path", "Weight"]].copy()
    result["Contribution (pp)"] = paths["Weight"].where(matched, 0) * shock / 100
    result["In scope"] = matched
    return result, float(result["Contribution (pp)"].sum()), float(paths.loc[coverage, "Weight"].sum())


def save_stress_run(db, portfolio_name, benchmark, scope, target, shock, value, portfolio, reference):
    portfolio_paths, portfolio_return, portfolio_coverage = portfolio
    reference_paths, reference_return, reference_coverage = reference
    payload = json.dumps({"portfolio": portfolio_paths.to_dict("records"),
                          "benchmark": reference_paths.to_dict("records")}, allow_nan=False)
    with db:
        db.execute("""INSERT INTO stress_runs (
            created_utc,portfolio_name,benchmark_name,benchmark_date,shock_scope,shock_target,shock_pct,
            portfolio_value_aud,portfolio_return_pct,benchmark_return_pct,portfolio_coverage_pct,
            benchmark_coverage_pct,result_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (datetime.now(timezone.utc).isoformat(), portfolio_name, benchmark.name, benchmark.effective_date,
                    scope, target, shock, value, portfolio_return, reference_return, portfolio_coverage,
                    reference_coverage, payload))
