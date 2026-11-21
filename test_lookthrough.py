import sqlite3
import unittest

from streamlit.testing.v1 import AppTest

from load_holdings import ROOT, read_holdings
from lookthrough import exposure_paths, load_reference


class ExposureTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE holdings (ticker TEXT, exchange TEXT, weight_pct REAL)")
        self.db.executemany("INSERT INTO holdings VALUES (?,?,?)", read_holdings(ROOT / "holdings.csv"))
        load_reference(self.db, ROOT / "examples/instruments.csv", ROOT / "examples/constituents.csv")

    def test_demo(self):
        rows = exposure_paths(self.db)
        bhp = [r for r in rows if r["Exposure"] == "ASX:BHP"]
        self.assertEqual({r["Route"]: r["Weight"] for r in bhp}, {"Direct": 40, "Via ETF": 6})
        self.assertAlmostEqual(sum(r["Weight"] for r in rows if r["Issue"]), 46.2)
        self.assertAlmostEqual(sum(r["Weight"] for r in rows), 100)

    def test_nested_fund_and_cycle(self):
        self.db.execute("INSERT INTO instruments VALUES ('ASX','SUB','ETF')")
        self.db.executemany("INSERT INTO constituents VALUES (?,?,?,?,?)", [
            ("ASX","VAS","ASX","SUB",50), ("ASX","SUB","ASX","BHP",80), ("ASX","SUB","ASX","VAS",20)])
        rows = exposure_paths(self.db)
        self.assertAlmostEqual(sum(r["Weight"] for r in rows if r["Exposure"] == "ASX:BHP"), 70)
        self.assertAlmostEqual(sum(r["Weight"] for r in rows if r["Issue"] == "Circular ETF holding"), 6)
        self.assertAlmostEqual(sum(r["Weight"] for r in rows), 100)

    def test_missing_reference(self):
        self.db.execute("DELETE FROM constituents")
        self.db.execute("DELETE FROM instruments WHERE ticker='BHP'")
        rows = exposure_paths(self.db)
        self.assertAlmostEqual(sum(r["Weight"] for r in rows if r["Issue"]), 100)

    def test_dashboard(self):
        app = AppTest.from_file(str(ROOT / "dashboard.py"), default_timeout=30)
        app.session_state["dashboard_page"] = "ETF look-through"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric], ["53.80%", "46.20%", "100.00%"])
        self.assertEqual(app.dataframe[0].value.loc["ASX:BHP", "Total"], 46)
        app.selectbox[0].select("ASX:CBA").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[-1].value["Source path"].tolist(), ["ASX:VAS → ASX:CBA"])


if __name__ == "__main__":
    unittest.main()
