import sqlite3
import unittest
from datetime import datetime, timezone

from asx_market import initialise, save_snapshot


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialise(self.db)
        self.general = dict(Code="XYZ", Exchange="AU", CurrencyCode="AUD", Name="Example",
                            Sector="Generic field", GicSector="Materials")
        self.bar = dict(date="2026-01-02", open=10, close=11, low=9, high=12, adjusted_close=10.5, volume=20)
        self.now = datetime(2026, 1, 3, tzinfo=timezone.utc)

    def save(self, general, bars, now=None):
        save_snapshot(self.db, "XYZ", general, bars, now or self.now)

    def test_repeat_and_revise(self):
        self.save(self.general, [self.bar])
        self.save(self.general, [dict(self.bar, close=12)])
        self.assertEqual(self.db.execute("SELECT count(*),close FROM daily_prices").fetchone(), (1,12))
        self.save(dict(self.general,GicSector=None), [self.bar], self.now.replace(day=4))
        self.assertEqual(self.db.execute("SELECT count(*) FROM gics_observations").fetchone(), (2,))
        self.assertEqual(self.db.execute("SELECT sector,trade_date FROM latest_asx_market_data").fetchone(),
                         (None, "2026-01-02"))

    def test_invalid_response_preserves_snapshot(self):
        self.save(self.general, [self.bar])
        for general, bars in [(dict(self.general, Exchange="US"), [self.bar]), (self.general, []),
                              (self.general, [self.bar, dict(self.bar, close=float("inf"))])]:
            with self.assertRaises(ValueError):
                self.save(general, bars)
        self.assertEqual(self.db.execute("SELECT close,sector FROM latest_asx_market_data").fetchone(),
                         (11, "Materials"))
