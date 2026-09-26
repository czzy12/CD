import unittest
from datetime import datetime
from types import SimpleNamespace

from bankflow_v2.abc_corp import GRID_COLUMNS, _grid_columns, _parse_grid_datetime


class AbcCorpTests(unittest.TestCase):
    def test_parses_day_wrapped_before_time(self):
        parsed, raw = _parse_grid_datetime(["2026-04-", "2616:13:44"])
        self.assertEqual(parsed, datetime(2026, 4, 26, 16, 13, 44))
        self.assertEqual(raw, "2026-04-26 16:13:44")

    def test_reads_eight_and_nine_column_borders(self):
        variants = [
            (15.0, 85.6, 156.2, 226.9, 297.5, 368.1, 438.8, 509.4, 580.0),
            GRID_COLUMNS,
        ]
        for columns in variants:
            page = SimpleNamespace(lines=[
                {"top": 60.0, "bottom": 60.0, "x0": left, "x1": right}
                for left, right in zip(columns, columns[1:])
            ])
            self.assertEqual(_grid_columns(page), columns)

    def test_parses_date_and_time_split_across_grid_lines(self):
        parsed, raw = _parse_grid_datetime(["2026-03-11", "10:14:59"])

        self.assertEqual(parsed, datetime(2026, 3, 11, 10, 14, 59))
        self.assertEqual(raw, "2026-03-11 10:14:59")

    def test_parses_date_and_time_on_one_grid_line(self):
        parsed, raw = _parse_grid_datetime(["2026-03-1110:14:59"])

        self.assertEqual(parsed, datetime(2026, 3, 11, 10, 14, 59))
        self.assertEqual(raw, "2026-03-11 10:14:59")

    def test_uses_all_nine_agricultural_bank_grid_columns(self):
        self.assertEqual(
            GRID_COLUMNS,
            (15.0, 77.8, 140.6, 203.3, 266.1, 328.9, 391.7, 454.4, 517.2, 580.0),
        )


if __name__ == "__main__":
    unittest.main()
