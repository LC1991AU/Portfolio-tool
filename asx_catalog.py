"""Import ASX company metadata and an optional All Ordinaries membership snapshot."""

import argparse
import csv
import io
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from asx_market import initialise
from load_holdings import ROOT


DIRECTORY_URL = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"
XAO_URL = "https://fnarena.com/index/ALL-ORDS/"
SECTOR_REFERENCES = {
    "AXQ": ("Software & Services", "Information Technology",
            "https://fnarena.com/stock-price-analysis/cloud-services/AXQ/"),
    "DGT": ("Equity Real Estate Investment Trusts (REITs)", "Real Estate",
            "https://www.asx.com.au/content/dam/asx/documents/listings/listings-presentation.pdf"),
}
GICS_SECTORS = {
    "Energy": ("Energy",),
    "Materials": ("Materials",),
    "Industrials": ("Capital Goods", "Commercial & Professional Services", "Transportation"),
    "Consumer Discretionary": ("Automobiles & Components", "Consumer Durables & Apparel", "Consumer Services",
                               "Consumer Discretionary Distribution & Retail"),
    "Consumer Staples": ("Consumer Staples Distribution & Retail", "Food, Beverage & Tobacco",
                         "Household & Personal Products"),
    "Health Care": ("Health Care Equipment & Services", "Pharmaceuticals, Biotechnology & Life Sciences"),
    "Financials": ("Banks", "Financial Services", "Insurance"),
    "Information Technology": ("Software & Services", "Technology Hardware & Equipment",
                               "Semiconductors & Semiconductor Equipment"),
    "Communication Services": ("Telecommunication Services", "Media & Entertainment"),
    "Utilities": ("Utilities",),
    "Real Estate": ("Equity Real Estate Investment Trusts (REITs)", "Real Estate Management & Development"),
}
SECTOR_BY_GROUP = {group: sector for sector, groups in GICS_SECTORS.items() for group in groups}


class ConstituentTable(HTMLParser):
    """Read ticker cells from the numbered constituent table."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_cell = False
        self.cells = []
        self.tickers = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "table_index":
            self.in_table = True
        if self.in_table and tag == "tr":
            self.cells = []
        if self.in_table and tag == "td":
            self.cells.append("")
            self.in_cell = True

    def handle_data(self, data):
        if self.in_cell:
            self.cells[-1] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False
        if tag == "table":
            self.in_table = False
        if self.in_table and tag == "tr" and len(self.cells) >= 2 and self.cells[0].strip().isdigit():
            self.tickers.append(self.cells[1].strip().upper())


def download_text(url):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
        return response.read().decode("utf-8-sig")


def parse_directory(stream):
    banner = stream.readline().strip()
    match = re.fullmatch(r"ASX listed companies as at (\w{3} \w{3} \d{1,2}) [\d:]+ \w+ (\d{4})", banner)
    if not match:
        raise ValueError("The ASX directory is missing a recognised observation date.")
    observed = datetime.strptime(" ".join(match.groups()), "%a %b %d %Y").date().isoformat()
    if stream.readline().strip():
        raise ValueError("Unexpected ASX directory format after the observation date.")
    reader = csv.DictReader(stream)
    if reader.fieldnames != ["Company name", "ASX code", "GICS industry group"]:
        raise ValueError("Unexpected ASX company directory headers.")
    rows = {}
    seen = set()
    for record in reader:
        if None in record or any(value is None for value in record.values()):
            raise ValueError(f"Malformed ASX directory listing on row {reader.line_num + 2}.")
        ticker = record["ASX code"].strip().upper()
        name = record["Company name"].strip()
        group = record["GICS industry group"].strip()
        if not re.fullmatch(r"[A-Z0-9]{3}", ticker) or not name or ticker in seen:
            raise ValueError(f"Invalid or duplicate ASX directory listing on row {reader.line_num + 2}.")
        seen.add(ticker)
        sector = SECTOR_BY_GROUP.get(group)
        source = DIRECTORY_URL
        if not sector and ticker in SECTOR_REFERENCES:
            group, sector, source = SECTOR_REFERENCES[ticker]
        if sector or group == "Class Pend":
            # ASX's company directory gives the issuer code SGL. The quoted B shares are SGLLV.
            ticker = "SGLLV" if ticker == "SGL" and name.upper().startswith("RICEGROWERS") else ticker
            rows[ticker] = ("ASX", ticker, name, group if sector else None, sector, source, observed)
    return rows


def import_catalog(db, directory, members=None, membership_date=None, source=None, complete=False):
    rows = parse_directory(directory)
    if len(rows) < 500:
        raise ValueError("ASX directory is incomplete. Expected at least 500 company listings.")
    if members is not None:
        symbols = [row["ticker"].strip().upper() for row in csv.DictReader(members)]
        unknown = sorted(set(symbols) - rows.keys())
        if unknown:
            raise ValueError("Membership file includes listings outside the ASX company directory: " + ", ".join(unknown))
        if len(symbols) != len(set(symbols)) or not 1 <= len(symbols) <= 500:
            raise ValueError("Expected 1–500 unique index members.")
        if complete and len(symbols) < 475:
            raise ValueError("The membership file is too short to mark as a full All Ordinaries list.")
        if not membership_date or not source:
            raise ValueError("Membership needs an observation date and source.")
        membership_date = date.fromisoformat(membership_date).isoformat()

    with db:
        db.executemany("""
            INSERT INTO security_master VALUES (?,?,?,?,?,?,?)
            ON CONFLICT (exchange,ticker) DO UPDATE SET
                company=excluded.company, gics_industry_group=excluded.gics_industry_group,
                gics_sector=excluded.gics_sector, source_url=excluded.source_url,
                observed_date=excluded.observed_date
            WHERE excluded.observed_date >= security_master.observed_date
        """, rows.values())
        if members is not None:
            latest = db.execute("SELECT observed_date FROM index_universe_snapshot WHERE index_code='XAO'").fetchone()
            if latest and membership_date < latest[0]:
                raise ValueError("The membership snapshot predates the current snapshot.")
            db.execute("""INSERT INTO index_universe_snapshot VALUES ('XAO',?,?,?)
                          ON CONFLICT(index_code) DO UPDATE SET observed_date=excluded.observed_date,
                          source_url=excluded.source_url, coverage=excluded.coverage""",
                       (membership_date, source, "complete" if complete else "partial"))
            db.execute("DELETE FROM index_universe_members WHERE index_code='XAO'")
            db.executemany("INSERT INTO index_universe_members VALUES ('XAO','ASX',?)",
                           [(ticker,) for ticker in symbols])
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, help="File from ASX. Default downloads the company directory.")
    membership = parser.add_mutually_exclusive_group()
    membership.add_argument("--members", type=Path, help="Optional All Ordinaries CSV with a ticker column.")
    membership.add_argument("--all-ordinaries", action="store_true", help="Load FNArena's published constituent table.")
    parser.add_argument("--as-of", help="Membership observation date (YYYY-MM-DD).")
    parser.add_argument("--source", help="Membership source URL.")
    parser.add_argument("--complete", action="store_true", help="Mark a full, verified membership file.")
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "portfolio.db")
    args = parser.parse_args()
    try:
        if args.directory:
            content = args.directory.read_text(encoding="utf-8-sig")
        else:
            content = download_text(DIRECTORY_URL)
        args.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.database)) as db:
            initialise(db)
            if args.members:
                with args.members.open(encoding="utf-8-sig", newline="") as members:
                    count = import_catalog(db, io.StringIO(content), members, args.as_of, args.source, args.complete)
            elif args.all_ordinaries:
                table = ConstituentTable()
                table.feed(download_text(XAO_URL))
                members = io.StringIO("ticker\n" + "\n".join(table.tickers))
                count = import_catalog(db, io.StringIO(content), members, date.today().isoformat(), XAO_URL, True)
                print(f"Loaded {len(table.tickers)} All Ordinaries constituents from FNArena.")
            else:
                count = import_catalog(db, io.StringIO(content))
        print(f"Loaded {count} ASX company listings.")
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"ASX catalog import failed: {error}\n")


if __name__ == "__main__":
    main()
