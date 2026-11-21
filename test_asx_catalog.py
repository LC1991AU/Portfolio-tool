import io
import sqlite3
import unittest

from asx_catalog import ConstituentTable, import_catalog, parse_directory
from equity_portfolio import builder_securities, initialise_portfolio, portfolio_overview, save_portfolio, saved_weights


ASX_HEADER = "ASX listed companies as at Sat Nov 21 19:36:58 AEDT 2026\n\nCompany name,ASX code,GICS industry group\n"


class CatalogTests(unittest.TestCase):
    def test_parse_metadata_and_trading_code(self):
        directory = io.StringIO(ASX_HEADER + "RICEGROWERS LIMITED,SGL,\"Food, Beverage & Tobacco\"\n"
                                "An ASX ETF,VAS,Not Applic\n")
        rows = parse_directory(directory)
        self.assertEqual(set(rows), {"SGLLV"})
        self.assertEqual(rows["SGLLV"][4], "Consumer Staples")
        self.assertEqual(rows["SGLLV"][-1], "2026-11-21")

    def test_membership_and_portfolio_can_use_unpriced_listings(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        initialise_portfolio(db)
        fixture = ASX_HEADER + "TEST COMPANY,NAB,Banks\n" + "".join(
            f"ASX TEST {i},{i:03},Materials\n" for i in range(500)
        )
        import_catalog(db, io.StringIO(fixture), io.StringIO("ticker\nNAB\n"), "2026-11-21", "test")
        with self.assertRaises(ValueError):
            import_catalog(db, io.StringIO(fixture), io.StringIO("ticker\nVAS\n"), "2026-11-22", "test")
        self.assertEqual(builder_securities(db)["NAB"], ("TEST COMPANY", "Financials", True))
        save_portfolio(db, io.StringIO("ticker,exchange,weight_pct\nNAB,ASX,100\n"))
        position = portfolio_overview(db, saved_weights(db)).loc["NAB"]
        self.assertEqual(position["Sector"], "Financials")
        self.assertIsNone(position["close"])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM daily_prices").fetchone(), (0,))

    def test_read_only_tickers_from_supported_constituent_table(self):
        parser = ConstituentTable()
        parser.feed('<table><tr><td>1</td><td>NO</td></tr></table>'
                    '<table id="table_index"><tr><td>1</td><td><a>SGLLV</a></td><td>Ricegrowers</td>'
                    '<td>47.50</td></tr></table>')
        self.assertEqual(parser.tickers, ["SGLLV"])
