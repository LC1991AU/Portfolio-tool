import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from streamlit.testing.v1 import AppTest

from equity_portfolio import initialise_portfolio
from portfolio_store import list_portfolios, load_portfolio, migrate_legacy_portfolios, write_portfolio


class PortfolioStoreTests(unittest.TestCase):
    def test_edit_and_legacy_import_keep_portfolios_separate(self):
        with closing(sqlite3.connect(":memory:")) as db:
            initialise_portfolio(db)
            db.execute("INSERT INTO asx_portfolio_holdings VALUES ('BHP',100)")
            migrate_legacy_portfolios(db)
            migrate_legacy_portfolios(db)
            previous_id, name, _, _ = list_portfolios(db)[0]
            self.assertEqual(name, "Previous ASX portfolio")
            new_id = write_portfolio(db, [("CSL", "ASX", 100)], name="Satellite")
            with self.assertRaises(ValueError):
                write_portfolio(db, [("WOW", "ASX", 100)], name="satellite")
            with self.assertRaises(ValueError):
                write_portfolio(db, [("WOW", "ASX", 80)], portfolio_id=new_id)
            self.assertEqual(load_portfolio(db, new_id)[1], [("CSL", "ASX", 100)])
            write_portfolio(db, [("WOW", "ASX", 100)], portfolio_id=new_id)
            self.assertEqual(load_portfolio(db, previous_id)[1], [("BHP", "ASX", 100)])
            self.assertEqual(len(list_portfolios(db)), 2)

    def test_empty_landing_create_back_and_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.db"
            script = (f"from pathlib import Path\nfrom portfolio_dashboard import show_dashboard\n"
                      f"show_dashboard(Path({str(path)!r}))")
            app = AppTest.from_string(script, default_timeout=30).run()
            self.assertEqual(app.title[0].value, "Your portfolios")
            self.assertFalse(app.metric)
            next(b for b in app.button if b.label == "Enter holdings").click().run()
            self.assertEqual(app.multiselect[0].value, [])
            app.text_input[0].set_value("Core portfolio")
            app.multiselect[0].set_value([("ASX", "BHP"), ("ASX", "CBA")]).run()
            next(b for b in app.button if b.label == "Allocate equally").click().run()
            next(b for b in app.button if b.label == "Save and open portfolio").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "Core portfolio")
            next(b for b in app.button if b.label == "All portfolios").click().run()
            self.assertEqual(app.title[0].value, "Your portfolios")
            self.assertFalse(app.metric)
            app = AppTest.from_string(script, default_timeout=30).run()
            self.assertIsNone(app.selectbox[0].value)
            app.selectbox[0].set_value(1).run()
            next(b for b in app.button if b.label == "Open portfolio").click().run()
            self.assertEqual(app.title[0].value, "Core portfolio")
            next(b for b in app.button if b.label == "Edit holdings").click().run()
            self.assertEqual(set(app.multiselect[0].value), {("ASX", "BHP"), ("ASX", "CBA")})
            app.multiselect[0].set_value([("ASX", "BHP")]).run()
            next(b for b in app.button if b.label == "Allocate equally").click().run()
            next(b for b in app.button if b.label == "Save changes").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "1")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(load_portfolio(db, 1)[1], [("BHP", "ASX", 100)])
