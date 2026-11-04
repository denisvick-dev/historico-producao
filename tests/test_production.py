from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import production


class ParsingTests(unittest.TestCase):
    def test_parse_brazilian_and_international_points(self):
        cases = {
            "1.234,56": 1234.56,
            "1,234.56": 1234.56,
            "125,5": 125.5,
            "1.234": 1234.0,
            "85 pontos": 85.0,
            42: 42.0,
            42.75: 42.75,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(production.parse_points(raw), expected)
        self.assertIsNone(production.parse_points("sem pontos"))
        self.assertIsNone(production.parse_points(""))

    def test_parse_complete_and_monthly_dates(self):
        self.assertEqual(production.parse_reference_date("03/11/2026"), pd.Timestamp("2026-11-03"))
        self.assertEqual(production.parse_reference_date("11/2026"), pd.Timestamp("2026-11-01"))
        self.assertEqual(production.parse_reference_date("2026-11"), pd.Timestamp("2026-11-01"))
        self.assertEqual(production.parse_reference_date("nov/26"), pd.Timestamp("2026-11-01"))
        self.assertEqual(production.infer_date_from_filename("producao_2026-10.xlsx"), pd.Timestamp("2026-10-01"))

    def test_clean_technician_standardizes_case_and_spaces(self):
        self.assertEqual(production.clean_technician("  joão   DA silva "), "João da Silva")
        self.assertEqual(production.clean_technician("nan"), "")


class WorkbookTests(unittest.TestCase):
    def test_process_dataframe_accepts_aliases_and_reports_bad_rows(self):
        frame = pd.DataFrame(
            {
                "Colaborador": ["ANDRÉ SANTOS", "Bruno Oliveira", "Carlos Ferreira", ""],
                "Pontuação": ["100,5", "80", "inválido", "999"],
                "Competência": ["11/2026", "11/2026", "11/2026", "11/2026"],
            }
        )
        records, issues = production.process_dataframe(frame, production.PROD, "teste.xlsx")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["technician"], "André Santos")
        self.assertEqual(records[0]["points"], 100.5)
        self.assertEqual(records[0]["reference_date"], "2026-11-01")
        self.assertEqual(len(issues), 1)
        self.assertIn("Linha 4", issues[0])

    def test_summarize_os_counts_only_prod_rows(self):
        frame = pd.DataFrame(
            [
                {"technician": "André Santos", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Prod"},
                {"technician": "André Santos", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Prod"},
                {"technician": "Bruno Oliveira", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Prod"},
                {"technician": "André Santos", "period": pd.Timestamp("2026-11-01"), "source_sheet": "Gpon"},
            ]
        )

        total = production.summarize_os(frame, []).iloc[0]["os_count"]
        by_technician = production.summarize_os(frame, "technician").set_index("technician")
        self.assertEqual(total, 3)
        self.assertEqual(by_technician.loc["André Santos", "os_count"], 2)
        self.assertEqual(by_technician.loc["Bruno Oliveira", "os_count"], 1)

    def test_process_excel_combines_prod_and_gpon(self):
        content = io.BytesIO()
        with pd.ExcelWriter(content, engine="openpyxl") as writer:
            pd.DataFrame(
                {"Data": ["03/11/2026"], "Técnico": ["André Santos"], "Pontos": [100]}
            ).to_excel(writer, sheet_name="Prod", index=False)
            pd.DataFrame(
                {"Data": ["03/11/2026"], "Técnico": ["André Santos"], "Pontos": [35.5]}
            ).to_excel(writer, sheet_name="Gpon", index=False)
        records, issues = production.process_upload("novembro.xlsx", content.getvalue())
        self.assertEqual(issues, [])
        self.assertEqual(len(records), 2)
        self.assertEqual({row["source_sheet"] for row in records}, {"Prod", "Gpon"})

        frame = pd.DataFrame(records)
        total = production.summarize(frame, ["technician"]).iloc[0]
        self.assertEqual(total["points_prod"], 100)
        self.assertEqual(total["points_gpon"], 35.5)
        self.assertEqual(total["points_total"], 135.5)

    def test_process_excel_finds_offset_headers_and_nome_equipe(self):
        content = io.BytesIO()
        with pd.ExcelWriter(content, engine="openpyxl") as writer:
            pd.DataFrame(
                [
                    ["Relatório de produção", None, None, None, None],
                    ["Competência: novembro/2026", None, None, None, None],
                    ["Data Agendamento", "Data Atendimento", "Período", "Nome Equipe", "Pontos"],
                    ["02/11/2026", None, "08:00 - 12:00", "Equipe A", 25],
                    ["03/11/2026", "03/11/2026", "12:00 - 15:00", "Equipe A", 15],
                ]
            ).to_excel(writer, sheet_name="Prod", index=False, header=False)
        records, issues = production.process_upload(
            "producao.xlsx", content.getvalue()
        )

        self.assertEqual(issues, [])
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["technician"], "Equipe A")
        self.assertEqual(records[0]["reference_date"], "2026-11-02")
        self.assertEqual(
            production.summarize(
                pd.DataFrame(records), ["technician", "reference_date"]
            )["points_total"].sum(),
            40,
        )

    def test_csv_semicolon_and_filename_fallback(self):
        content = "Técnico;Pontos\nAndré Santos;125,5\n".encode("latin-1")
        records, issues = production.process_upload(
            "producao_2026-10.csv", content, csv_origin=production.GPON
        )
        self.assertEqual(issues, [])
        self.assertEqual(records[0]["reference_date"], "2026-10-01")
        self.assertEqual(records[0]["source_sheet"], "Gpon")

    def test_missing_required_column_has_useful_error(self):
        with self.assertRaisesRegex(ValueError, "Técnico"):
            production.process_dataframe(pd.DataFrame({"Pontos": [1]}), "Prod", "erro.xlsx")


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = production.DB_PATH
        production.DB_PATH = Path(self.temp_dir.name) / "test.db"
        production.init_database()

    def tearDown(self):
        production.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    @staticmethod
    def record(points=100, technician="André Santos", origin="Prod", row=2):
        return {
            "technician": technician,
            "reference_date": "2026-11-03",
            "source_sheet": origin,
            "points": points,
            "source_file": "producao.xlsx",
            "source_row": row,
        }

    def test_reimport_replaces_file_without_duplicates(self):
        production.save_records([self.record(), self.record(points=40, origin="Gpon")])
        production.save_records([self.record(points=120)])
        loaded = production.load_records()
        self.assertEqual(len(loaded), 2)
        total = production.summarize(loaded, []).iloc[0]
        self.assertEqual(total["points_prod"], 120)
        self.assertEqual(total["points_gpon"], 40)
        self.assertEqual(total["points_total"], 160)

    def test_first_real_import_removes_demonstration(self):
        demo = self.record(points=999)
        demo["source_file"] = production.DEMO_SOURCE
        production.save_records([demo], is_demo=True)
        production.save_records([self.record(points=100)])
        loaded = production.load_records()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.iloc[0]["is_demo"], 0)
        self.assertEqual(production.get_setting("demo_disabled"), "1")


if __name__ == "__main__":
    unittest.main()
