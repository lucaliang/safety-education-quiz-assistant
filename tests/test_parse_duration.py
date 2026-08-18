import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from parse_duration import parse_duration  # noqa: E402


class ParseDurationTests(unittest.TestCase):
    def test_default_is_299_seconds(self):
        self.assertEqual(parse_duration(None), 299)
        self.assertEqual(parse_duration(""), 299)

    def test_accepts_seconds_minutes_and_hours(self):
        self.assertEqual(parse_duration("299"), 299)
        self.assertEqual(parse_duration("299秒"), 299)
        self.assertEqual(parse_duration("5分钟"), 300)
        self.assertEqual(parse_duration("1.5分钟"), 90)
        self.assertEqual(parse_duration("45 min"), 2700)

    def test_rejects_duration_above_45_minutes(self):
        with self.assertRaises(ValueError):
            parse_duration("46分钟")
        with self.assertRaises(ValueError):
            parse_duration("1.5小时")

    def test_rejects_invalid_or_negative_duration(self):
        for value in ("abc", "5天", "-1秒", "-0.5分钟"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_duration(value)


if __name__ == "__main__":
    unittest.main()
