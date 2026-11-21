import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from equity_portfolio import initialise_portfolio
from lookthrough import exposure_paths
from portfolio_analysis import (
    classify, compare_weights, direct_exposures, import_benchmark, latest_benchmark,
    reference_benchmark, save_stress_run, stress_test,
)


class PortfolioAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialise_portfolio(self.db)

    def test_benchmark_upload_is_dated_and_keeps_prior_on_error(self):
        valid = "ticker,exchange,weight_pct\nBHP,ASX,7\nCBA,ASX,93\n"
        import_benchmark(self.db, "Reference", "2026-11-20", io.StringIO(valid))
        with self.assertRaises(ValueError):
            import_benchmark(self.db, "Invalid", "2026-11-21", io.StringIO(valid.replace("93", "3")))
        benchmark = latest_benchmark(self.db)
        self.assertEqual((benchmark.name, benchmark.effective_date), ("Reference", "2026-11-20"))
        self.assertEqual(benchmark.holdings, [("BHP", "ASX", 7), ("CBA", "ASX", 93)])

    def test_mixed_portfolio_stress_attributes_both_paths(self):
        self.db.executescript("""
            CREATE TABLE holdings (ticker, exchange, weight_pct);
            INSERT INTO holdings VALUES ('BHP','ASX',8),('DEMO','ASX',40),('AUD','CASH',52);
            CREATE TABLE instruments (exchange,ticker,kind);
            INSERT INTO instruments VALUES ('ASX','BHP','EQUITY'),('ASX','DEMO','ETF'),('CASH','AUD','CASH');
            CREATE TABLE constituents (fund_exchange,fund_ticker,exchange,ticker,weight_pct);
            INSERT INTO constituents VALUES ('ASX','DEMO','ASX','BHP',10);
        """)
        portfolio = classify(self.db, exposure_paths(self.db))
        benchmark = reference_benchmark()
        reference = classify(self.db, direct_exposures(benchmark.holdings))
        active = compare_weights(portfolio, reference, "Security")
        self.assertEqual(active.loc["ASX:BHP", "Active weight (pp)"], 5)
        self.assertEqual(active.loc["ASX:CBA", "Active weight (pp)"], -20)
        self.assertEqual(active.loc["Unresolved", "Portfolio weight (%)"], 36)
        result = stress_test(portfolio, "Security", "ASX:BHP", -20)
        reference_result = stress_test(reference, "Security", "ASX:BHP", -20)
        self.assertAlmostEqual(result[1], -2.4)
        self.assertEqual(result[2], 64)
        self.assertAlmostEqual(reference_result[1], -1.4)
        scoped = result[0].loc[result[0]["In scope"], "Contribution (pp)"]
        self.assertEqual(scoped.tolist(), [-1.6, -0.8])
        save_stress_run(self.db, "Mixed example", benchmark, "Security", "ASX:BHP", -20,
                        100_000, result, reference_result)
        payload, relative = self.db.execute(
            "SELECT result_json, portfolio_return_pct - benchmark_return_pct FROM stress_runs"
        ).fetchone()
        self.assertAlmostEqual(relative * 1000, -1000)
        self.assertEqual(len(json.loads(payload)["portfolio"]), 4)

    def test_scenario_page_upload_select_and_save(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.db"
            script = (f"from pathlib import Path\nfrom portfolio_dashboard import show_dashboard\n"
                      f"show_dashboard(Path({str(path)!r}))")
            app = AppTest.from_string(script).run()
            next(b for b in app.button if b.label == "10-share ASX example").click().run()
            app.radio[0].set_value("Benchmark & scenarios").run()
            self.assertFalse(app.exception)
            weights = next(table.value for table in app.dataframe if table.value.index.name == "Security")
            self.assertEqual(weights.loc["ASX:BHP", "Active weight (pp)"], 3)
            with patch("analysis_dashboard.st.file_uploader", return_value=io.BytesIO(
                b"ticker,exchange,weight_pct\nBHP,ASX,7\nCBA,ASX,93\n"
            )):
                app.text_input[0].set_value("Test reference")
                next(b for b in app.button if b.label == "Save benchmark").click().run()
            self.assertFalse(app.exception)
            app.selectbox[0].set_value("Security").run()
            app.selectbox[1].set_value("ASX:BHP").run()
            self.assertEqual([m.value for m in app.metric], ["-2.00%", "-1.40%", "-0.60 pp"])
            next(b for b in app.button if b.label == "Save scenario").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.dataframe[-1].value.iloc[0]["Benchmark"], "Test reference")
