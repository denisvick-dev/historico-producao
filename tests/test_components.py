from __future__ import annotations

import io
import unittest

import pandas as pd

from components.charts import production_chart, ranking_chart
from components.data_import import template_file
from components.layout import csv_download, initials


class ChartComponentTests(unittest.TestCase):
    def test_production_chart_uses_prod_and_gpon(self):
        monthly = pd.DataFrame(
            {
                "period": [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-11-01")],
                "points_prod": [100.0, 120.0],
                "points_gpon": [40.0, 30.0],
                "points_total": [140.0, 150.0],
            }
        )
        figure = production_chart(monthly)
        self.assertEqual([trace.name for trace in figure.data[:2]], ["Prod", "Gpon"])
        self.assertEqual(list(figure.data[0].x), ["out/26", "nov/26"])
        self.assertEqual(figure.layout.barmode, "stack")

    def test_ranking_chart_limits_and_orders_technicians(self):
        ranking = pd.DataFrame(
            {
                "technician": ["André", "Bruno", "Carlos"],
                "points_prod": [100.0, 200.0, 150.0],
                "points_gpon": [50.0, 25.0, 50.0],
                "points_total": [150.0, 225.0, 200.0],
            }
        )
        figure = ranking_chart(ranking, top=2)
        self.assertEqual(list(figure.data[0].y), ["Carlos", "Bruno"])
        self.assertEqual(figure.layout.barmode, "stack")


class LayoutComponentTests(unittest.TestCase):
    def test_initials_and_csv_export(self):
        self.assertEqual(initials("André Santos"), "AS")
        frame = pd.DataFrame({"Técnico": ["João"], "Pontos Totais": [12.5]})
        content = csv_download(frame).decode("utf-8-sig")
        self.assertIn("Técnico;Pontos Totais", content)
        self.assertIn("João;12,5", content)

    def test_template_contains_prod_and_gpon_sheets(self):
        workbook = pd.ExcelFile(io.BytesIO(template_file()))
        self.assertEqual(workbook.sheet_names, ["Prod", "Gpon"])
        for sheet in workbook.sheet_names:
            frame = workbook.parse(sheet)
            self.assertEqual(list(frame.columns), ["Data", "Técnico", "Pontos"])


if __name__ == "__main__":
    unittest.main()
