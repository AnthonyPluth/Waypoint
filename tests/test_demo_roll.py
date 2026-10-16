import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("demo_roll", ROOT / "tools" / "demo_roll.py")
demo_roll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_roll)


class DemoRollTest(unittest.TestCase):
    def test_rolling_to_the_current_date_leaves_the_data_file_byte_for_byte(self):
        raw = demo_roll.DATA.read_text(encoding="utf-8")
        data = json.loads(raw)
        rolled, days, renamed = demo_roll.roll(data, dt.date.fromisoformat(data["asOf"]))
        self.assertEqual((days, renamed), (0, 0))
        self.assertEqual(demo_roll.encode(rolled), raw)

    def test_every_date_moves_by_the_same_days_and_times_stay(self):
        data = {
            "asOf": "2026-10-14",
            "trips": [{"name": "Trip", "start_date": "2026-10-18", "end_date": "2026-10-27"}],
            "flights": [{"departs": "2026-10-18T07:30", "arrives": "2026-10-18T10:05:00"}],
            "count": 3,
            "note": "Booked on 2026-10-18 in the text",
        }
        rolled, days, _ = demo_roll.roll(data, dt.date(2026, 11, 3))
        self.assertEqual(days, 20)
        self.assertEqual(rolled["asOf"], "2026-11-03")
        self.assertEqual(rolled["trips"][0]["start_date"], "2026-11-07")
        self.assertEqual(rolled["trips"][0]["end_date"], "2026-11-16")
        self.assertEqual(rolled["flights"][0], {"departs": "2026-11-07T07:30", "arrives": "2026-11-07T10:05:00"})
        self.assertEqual(rolled["count"], 3)
        self.assertEqual(rolled["note"], "Booked on 2026-10-18 in the text")

    def test_trip_names_follow_their_new_start_month(self):
        data = {
            "asOf": "2024-08-01",
            "trips": [{"name": "Trip to Paris (Aug 2024)", "start_date": "2024-08-05", "end_date": "2024-08-12"}],
        }
        rolled, _, renamed = demo_roll.roll(data, dt.date(2024, 10, 3))
        self.assertEqual(rolled["trips"][0]["name"], "Trip to Paris (Oct 2024)")
        self.assertEqual(renamed, 1)

    def test_names_without_a_month_suffix_are_left_alone(self):
        data = {
            "asOf": "2024-08-01",
            "trips": [{"name": "Home", "start_date": "2024-08-05", "end_date": "2024-08-12"}],
        }
        rolled, _, renamed = demo_roll.roll(data, dt.date(2024, 10, 3))
        self.assertEqual(rolled["trips"][0]["name"], "Home")
        self.assertEqual(renamed, 0)

    def test_refuses_to_move_the_demo_backwards(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            path.write_text(json.dumps({"asOf": "2026-10-14", "trips": []}), encoding="utf-8")
            status = demo_roll.main(["--to", "2026-10-01", "--data", str(path)])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["asOf"], "2026-10-14")


if __name__ == "__main__":
    unittest.main()
