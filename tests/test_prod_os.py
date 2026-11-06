from __future__ import annotations

import unittest

import pandas as pd

from components.prod_os import (
    _best_month_style,
    _technician_monthly_table,
    _total_column_style,
)


class ProductionOrderTableTests(unittest.TestCase):
    def test_best_month_for_technician_is_highlighted_green(self):
        row = pd.Series(
            {"Técnico": "Ana", "mar/26": 2, "abr/26": 5, "Total": 7}
        )

        styles = _best_month_style(row)

        self.assertEqual(styles["mar/26"], "")
        self.assertIn("background-color: #DCFCE7", styles["abr/26"])
        self.assertEqual(styles["Total"], "")

    def test_total_general_row_is_not_highlighted(self):
        row = pd.Series(
            {"Técnico": "Total geral", "mar/26": 5, "abr/26": 5, "Total": 10}
        )

        styles = _best_month_style(row)

        self.assertTrue(styles.eq("").all())

    def test_best_month_tie_for_technician_highlights_each_month(self):
        row = pd.Series(
            {"Técnico": "Ana", "mar/26": 5, "abr/26": 5, "Total": 10}
        )

        styles = _best_month_style(row)

        self.assertIn("background-color: #DCFCE7", styles["mar/26"])
        self.assertIn("background-color: #DCFCE7", styles["abr/26"])

    def test_total_column_uses_distinct_color(self):
        style = _total_column_style(10)

        self.assertIn("background-color: #E8EEF8", style)
        self.assertIn("font-weight: 600", style)

    def test_table_has_technicians_months_and_totals(self):
        frame = pd.DataFrame(
            [
                {"technician": "Ana", "period": pd.Timestamp("2026-10-01"), "source_sheet": "Prod"},
                {"technician": "Ana", "period": pd.Timestamp("2026-10-01"), "source_sheet": "Prod"},
                {"technician": "Ana", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Prod"},
                {"technician": "Bia", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Prod"},
                {"technician": "Bia", "period": pd.Timestamp("2026-10-01"), "source_sheet": "Gpon"},
            ]
        )

        result = _technician_monthly_table(frame, ["out/26", "nov/26"])
        rows = result.set_index("Técnico")

        self.assertEqual(list(result.columns), ["Técnico", "out/26", "nov/26", "Total"])
        self.assertEqual(rows.loc["Ana", "out/26"], 2)
        self.assertEqual(rows.loc["Ana", "nov/26"], 1)
        self.assertEqual(rows.loc["Ana", "Total"], 3)
        self.assertEqual(rows.loc["Bia", "out/26"], 0)
        self.assertEqual(rows.loc["Bia", "nov/26"], 1)
        self.assertEqual(rows.loc["Bia", "Total"], 1)
        self.assertEqual(rows.loc["Total geral", "out/26"], 2)
        self.assertEqual(rows.loc["Total geral", "nov/26"], 2)
        self.assertEqual(rows.loc["Total geral", "Total"], 4)
