from __future__ import annotations

import unittest

import pandas as pd

from components.prod_os import _technician_monthly_table


class ProductionOrderTableTests(unittest.TestCase):
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
