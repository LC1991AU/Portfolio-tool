"""Named local portfolios and migration from the original single snapshots."""

import math
import re
from datetime import datetime, timezone

from load_holdings import ROOT, read_holdings


def validate_positions(positions):
    listings = set()
    for ticker, exchange, weight in positions:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,19}", ticker) or not re.fullmatch(r"[A-Z0-9]{1,12}", exchange):
            raise ValueError("Use a valid ticker and exchange for every holding.")
        if (ticker, exchange) in listings or not 0 < weight <= 100:
            raise ValueError("Each listing must appear once with a positive weight.")
        listings.add((ticker, exchange))
    if not math.isclose(math.fsum(row[2] for row in positions), 100, abs_tol=0.01, rel_tol=0):
        raise ValueError("Portfolio weights must add up to 100%.")


def write_portfolio(db, positions, *, name=None, portfolio_id=None):
    validate_positions(positions)
    name = (name or "").strip()
    if portfolio_id is None and not 1 <= len(name) <= 80:
        raise ValueError("Enter a portfolio name of up to 80 characters.")
    now = datetime.now(timezone.utc).isoformat()
    with db:
        if portfolio_id is None:
            inserted = db.execute(
                "INSERT INTO portfolios (name,updated_utc) VALUES (?,?) ON CONFLICT(name) DO NOTHING", (name, now)
            )
            if inserted.rowcount == 0:
                raise ValueError("That name is already in use. Choose a different portfolio name.")
            portfolio_id = inserted.lastrowid
        else:
            changed = db.execute("UPDATE portfolios SET updated_utc=? WHERE id=?", (now, portfolio_id))
            if changed.rowcount != 1:
                raise ValueError("This portfolio could not be found.")
        replace_positions(db, portfolio_id, positions)
    return portfolio_id


def replace_positions(db, portfolio_id, positions):
    db.execute("DELETE FROM portfolio_positions WHERE portfolio_id=?", (portfolio_id,))
    db.executemany(
        "INSERT INTO portfolio_positions (portfolio_id,ticker,exchange,weight_pct) VALUES (?,?,?,?)",
        [(portfolio_id, *position) for position in positions],
    )


def list_portfolios(db):
    return db.execute("""
        SELECT p.id,p.name,COUNT(h.ticker),p.updated_utc
        FROM portfolios p JOIN portfolio_positions h ON h.portfolio_id=p.id
        GROUP BY p.id ORDER BY p.updated_utc DESC,p.id DESC
    """).fetchall()


def load_portfolio(db, portfolio_id):
    header = db.execute("SELECT name FROM portfolios WHERE id=?", (portfolio_id,)).fetchone()
    if header is None:
        return None
    holdings = db.execute("""
        SELECT ticker,exchange,weight_pct
        FROM portfolio_positions WHERE portfolio_id=? ORDER BY exchange,ticker
    """, (portfolio_id,)).fetchall()
    return header[0], holdings


def migrate_legacy_portfolios(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for source, label, query in (
        ("asx_portfolio_holdings", "Previous ASX portfolio", "SELECT ticker,'ASX',weight_pct FROM asx_portfolio_holdings"),
        ("holdings", "Previous CSV portfolio", "SELECT ticker,exchange,weight_pct FROM holdings"),
    ):
        if source not in tables or db.execute("SELECT 1 FROM portfolios WHERE legacy_source=?", (source,)).fetchone():
            continue
        positions = db.execute(query).fetchall()
        if not positions:
            continue
        if source == "holdings" and sorted(positions) == sorted(read_holdings(ROOT / "holdings.csv")):
            has_reference = "constituents" in tables and db.execute("SELECT 1 FROM constituents LIMIT 1").fetchone()
            if not has_reference:
                continue
        with db:
            # Acquire the write lock and recheck so two sessions cannot migrate the same snapshot.
            db.execute("UPDATE portfolios SET updated_utc=updated_utc WHERE legacy_source=?", (source,))
            if db.execute("SELECT 1 FROM portfolios WHERE legacy_source=?", (source,)).fetchone():
                continue
            name = label
            index = 2
            while db.execute("SELECT 1 FROM portfolios WHERE name=?", (name,)).fetchone():
                name = f"{label} ({index})"
                index += 1
            portfolio_id = db.execute(
                "INSERT INTO portfolios (name,updated_utc,legacy_source) VALUES (?,?,?)",
                (name, datetime.now(timezone.utc).isoformat(), source),
            ).lastrowid
            replace_positions(db, portfolio_id, positions)
            if source == "asx_portfolio_holdings":
                db.execute("UPDATE stress_runs SET portfolio_name=? WHERE portfolio_name='Saved portfolio'", (name,))
