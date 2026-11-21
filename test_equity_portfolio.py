import io
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from asx_market import refresh_prices, save_prices
from equity_portfolio import initialise_portfolio, performance, portfolio_csv, save_portfolio, saved_weights
from load_holdings import ROOT


def bar(day, adjusted, close=None):
    close = adjusted if close is None else close
    return dict(date=day, open=close, high=close, low=close, close=close, adjusted_close=adjusted, volume=100)


class EquityPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialise_portfolio(self.db)

    def test_price_refresh_needs_only_eod(self):
        with patch("asx_market.get_json", return_value=[bar("2026-01-02", 10)]) as get:
            self.assertEqual(refresh_prices(self.db, "BHP", "test-token"), 1)
        self.assertEqual(get.call_args.args[0], "eod/BHP.AU")
        self.assertEqual(self.db.execute("SELECT count(*) FROM gics_observations").fetchone(), (0,))

    def test_csv_rejects_invalid_portfolio_without_overwriting(self):
        save_portfolio(self.db, io.StringIO(portfolio_csv()))
        with self.assertRaises(ValueError):
            save_portfolio(self.db, io.StringIO("ticker,exchange,weight_pct\nVAS,ASX,100\n"))
        self.assertEqual(len(saved_weights(self.db)), 10)

    def test_performance_uses_adjusted_close_and_skips_missing_sessions(self):
        now = datetime(2026, 1, 9, tzinfo=timezone.utc)
        save_prices(self.db, "BHP", [bar("2026-01-05", 9), bar("2026-01-06", 10),
                                     bar("2026-01-07", 10), bar("2026-01-08", 11, 5.5)], now)
        save_prices(self.db, "CBA", [bar("2026-01-05", 19), bar("2026-01-07", 20), bar("2026-01-08", 24)], now)
        curve, daily = performance(self.db, [("BHP", "ASX", 60), ("CBA", "ASX", 40)])
        self.assertTrue(daily["CBA"].isna().iloc[2])
        self.assertEqual(curve.index.strftime("%Y-%m-%d").tolist(), ["2026-01-07", "2026-01-08"])
        self.assertAlmostEqual(curve.iloc[-1, 0], 114)

    def test_dashboard_refresh_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.db"
            script = f"from pathlib import Path\nfrom portfolio_dashboard import show_dashboard\nshow_dashboard(Path({str(path)!r}))"
            bars = [bar("2026-01-02", 10), bar("2026-01-05", 11)]
            with patch("equity_dashboard.api_token", return_value="test-token"), patch("asx_market.get_json", return_value=bars) as get:
                app = AppTest.from_string(script).run()
                self.assertFalse(app.exception)
                self.assertEqual(len(app.metric), 0)
                next(b for b in app.button if b.label == "10-share ASX example").click().run()
                next(b for b in app.button if b.label == "Refresh daily prices").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(get.call_count, 10)
                self.assertEqual([m.value for m in app.metric], ["10", "100.0%", "+10.00%"])
                next(b for b in app.button if b.label == "All portfolios").click().run()
                next(b for b in app.button if b.label == "Upload CSV").click().run()
                csv_file = io.BytesIO(b"ticker,exchange,weight_pct\nBHP,ASX,60\nCBA,ASX,40\n")
                with patch("portfolio_builder.st.file_uploader", return_value=csv_file):
                    app.text_input[0].set_value("Uploaded portfolio")
                    app.run()
                    next(b for b in app.button if b.label == "Save and open portfolio").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.metric[0].value, "2")
                self.assertEqual(app.title[0].value, "Uploaded portfolio")
