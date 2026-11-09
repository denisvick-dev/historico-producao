from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import production


class ParsingTests(unittest.TestCase):
    def test_parse_brazilian_and_international_points(self) -> None:
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

    def test_parse_complete_and_monthly_dates(self) -> None:
        self.assertEqual(
            production.parse_reference_date("03/11/2026"), pd.Timestamp("2026-11-03")
        )
        self.assertEqual(
            production.parse_reference_date("11/2026"), pd.Timestamp("2026-11-01")
        )
        self.assertEqual(
            production.parse_reference_date("2026-11"), pd.Timestamp("2026-11-01")
        )
        self.assertEqual(
            production.parse_reference_date("nov/26"), pd.Timestamp("2026-11-01")
        )
        self.assertEqual(
            production.infer_date_from_filename("producao_2026-10.xlsx"),
            pd.Timestamp("2026-10-01"),
        )

    def test_format_points_always_displays_two_decimal_places(self) -> None:
        self.assertEqual(production.format_points(1234), "1.234,00")
        self.assertEqual(production.format_points(1234.5), "1.234,50")
        self.assertEqual(production.format_points(0), "0,00")

    def test_clean_technician_standardizes_case_and_spaces(self) -> None:
        self.assertEqual(
            production.clean_technician("  joão   DA silva "), "João da Silva"
        )
        self.assertEqual(production.clean_technician("nan"), "")


class MonthlyProductionTests(unittest.TestCase):
    def test_best_month_by_technician_uses_total_points_and_latest_month_for_ties(
        self,
    ) -> None:
        frame = pd.DataFrame(
            [
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Prod",
                    "points": 100,
                },
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Gpon",
                    "points": 20,
                },
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-03-01"),
                    "source_sheet": "Prod",
                    "points": 80,
                },
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-03-01"),
                    "source_sheet": "Gpon",
                    "points": 40,
                },
                {
                    "technician": "Bia",
                    "period": pd.Timestamp("2026-02-01"),
                    "source_sheet": "Prod",
                    "points": 90,
                },
            ]
        )

        best_months = production.best_month_by_technician(frame)

        self.assertEqual(best_months.to_dict(), {"Ana": "mar/26", "Bia": "fev/26"})

    def test_best_month_by_technician_accepts_empty_frame(self) -> None:
        best_months = production.best_month_by_technician(pd.DataFrame())

        self.assertTrue(best_months.empty)
        self.assertEqual(best_months.name, "best_month")

    def test_count_active_months_by_technician(self) -> None:
        frame = pd.DataFrame(
            [
                {"technician": "Ana", "period": pd.Timestamp("2026-01-01")},
                {"technician": "Ana", "period": pd.Timestamp("2026-01-01")},
                {"technician": "Ana", "period": pd.Timestamp("2026-03-01")},
                {"technician": "Bia", "period": pd.Timestamp("2026-02-01")},
            ]
        )

        counts = production.count_active_months_by_technician(frame)

        self.assertEqual(counts.to_dict(), {"Ana": 2, "Bia": 1})

    def test_count_active_months_by_technician_accepts_empty_frame(self) -> None:
        counts = production.count_active_months_by_technician(pd.DataFrame())

        self.assertTrue(counts.empty)
        self.assertEqual(counts.name, "active_months")


class WorkbookTests(unittest.TestCase):
    def test_process_dataframe_accepts_aliases_and_reports_bad_rows(self) -> None:
        frame = pd.DataFrame(
            {
                "Colaborador": [
                    "ANDRÉ SANTOS",
                    "Bruno Oliveira",
                    "Carlos Ferreira",
                    "",
                ],
                "Pontuação": ["100,5", "80", "inválido", "999"],
                "Competência": ["11/2026", "11/2026", "11/2026", "11/2026"],
            }
        )
        records, issues = production.process_dataframe(
            frame, production.PROD, "teste.xlsx"
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["technician"], "André Santos")
        self.assertEqual(records[0]["points"], 100.5)
        self.assertEqual(records[0]["reference_date"], "2026-11-01")
        self.assertEqual(records[0]["project"], "Sem projeto")
        self.assertEqual(len(issues), 1)
        self.assertIn("Linha 4", issues[0])

    def test_summarize_os_counts_only_prod_rows(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "technician": "André Santos",
                    "period": pd.Timestamp("2026-11-01"),
                    "source_sheet": "Prod",
                },
                {
                    "technician": "André Santos",
                    "period": pd.Timestamp("2026-11-01"),
                    "source_sheet": "Prod",
                },
                {
                    "technician": "Bruno Oliveira",
                    "period": pd.Timestamp("2026-11-01"),
                    "source_sheet": "Prod",
                },
                {
                    "technician": "André Santos",
                    "period": pd.Timestamp("2026-11-01"),
                    "source_sheet": "Gpon",
                },
            ]
        )

        total = production.summarize_os(frame, []).iloc[0]["os_count"]
        by_technician = production.summarize_os(frame, "technician").set_index(
            "technician"
        )
        self.assertEqual(total, 3)
        self.assertEqual(by_technician.loc["André Santos", "os_count"], 2)
        self.assertEqual(by_technician.loc["Bruno Oliveira", "os_count"], 1)

    def test_process_dataframe_reads_project_column(self) -> None:
        frame = pd.DataFrame(
            {
                "Data": ["03/11/2026", "04/11/2026", "05/11/2026"],
                "Técnico": ["Ana", "Bruno", "Carla"],
                "Projeto": ["  Fibra Norte  ", "Projeto Alfa", None],
                "Pontos": [10, 20, 30],
            }
        )
        records, issues = production.process_dataframe(
            frame, production.PROD, "projetos.xlsx"
        )
        self.assertEqual(issues, [])
        self.assertEqual(
            [record["project"] for record in records],
            ["Fibra Norte", "Projeto Alfa", "Sem projeto"],
        )

    def test_process_excel_combines_prod_and_gpon(self) -> None:
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

    def test_process_excel_finds_offset_headers_and_nome_equipe(self) -> None:
        content = io.BytesIO()
        with pd.ExcelWriter(content, engine="openpyxl") as writer:
            pd.DataFrame(
                [
                    ["Relatório de produção", None, None, None, None],
                    ["Competência: novembro/2026", None, None, None, None],
                    [
                        "Data Agendamento",
                        "Data Atendimento",
                        "Período",
                        "Nome Equipe",
                        "Pontos",
                    ],
                    ["02/11/2026", None, "08:00 - 12:00", "Equipe A", 25],
                    ["03/11/2026", "03/11/2026", "12:00 - 15:00", "Equipe A", 15],
                ]
            ).to_excel(writer, sheet_name="Prod", index=False, header=False)
        records, issues = production.process_upload("producao.xlsx", content.getvalue())

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

    def test_csv_semicolon_and_filename_fallback(self) -> None:
        content = "Técnico;Pontos\nAndré Santos;125,5\n".encode("latin-1")
        records, issues = production.process_upload(
            "producao_2026-10.csv", content, csv_origin=production.GPON
        )
        self.assertEqual(issues, [])
        self.assertEqual(records[0]["reference_date"], "2026-10-01")
        self.assertEqual(records[0]["source_sheet"], "Gpon")

    def test_missing_required_column_has_useful_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Técnico"):
            production.process_dataframe(
                pd.DataFrame({"Pontos": [1]}), "Prod", "erro.xlsx"
            )


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = production.DB_PATH
        production.DB_PATH = Path(self.temp_dir.name) / "test.db"
        production.init_database()

    def tearDown(self) -> None:
        production.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    @staticmethod
    def record(
        points: float | int = 100,
        technician: str = "André Santos",
        origin: str = "Prod",
        row: int = 2,
        project: str = "Sem projeto",
    ) -> dict:
        return {
            "technician": technician,
            "reference_date": "2026-11-03",
            "source_sheet": origin,
            "project": project,
            "points": points,
            "source_file": "producao.xlsx",
            "source_row": row,
        }

    def test_reimport_replaces_file_without_duplicates(self) -> None:
        production.save_records([self.record(), self.record(points=40, origin="Gpon")])
        production.save_records([self.record(points=120)])
        loaded = production.load_records()
        self.assertEqual(len(loaded), 2)
        total = production.summarize(loaded, []).iloc[0]
        self.assertEqual(total["points_prod"], 120)
        self.assertEqual(total["points_gpon"], 40)
        self.assertEqual(total["points_total"], 160)

    def test_save_and_load_preserves_project(self) -> None:
        production.save_records([self.record(project="Rede Metropolitana")])
        loaded = production.load_records()
        self.assertEqual(loaded.iloc[0]["project"], "Rede Metropolitana")

    def test_dashboard_snapshot_returns_records_and_stats(self) -> None:
        production.save_records([self.record(project="Rede Metropolitana")])
        loaded, stats = production.load_dashboard_snapshot()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.iloc[0]["project"], "Rede Metropolitana")
        self.assertEqual(stats["records"], 1)
        self.assertEqual(stats["technicians"], 1)

    def test_existing_database_migrates_project_column(self) -> None:
        current_path = production.DB_PATH
        production.DB_PATH = Path(self.temp_dir.name) / "legacy.db"
        try:
            with sqlite3.connect(production.DB_PATH) as connection:
                connection.executescript(
                    """
                    CREATE TABLE production_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        technician TEXT NOT NULL,
                        reference_date TEXT NOT NULL,
                        source_sheet TEXT NOT NULL,
                        points REAL NOT NULL,
                        source_file TEXT NOT NULL,
                        source_row INTEGER NOT NULL,
                        is_demo INTEGER NOT NULL DEFAULT 0,
                        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT INTO production_records
                        (technician, reference_date, source_sheet, points, source_file, source_row)
                    VALUES ('Ana', '2026-11-03', 'Prod', 10, 'legacy.xlsx', 2);
                    """
                )
            connection.close()
            production.init_database()
            loaded = production.load_records()
            self.assertEqual(loaded.iloc[0]["project"], "Sem projeto")
        finally:
            production.DB_PATH = current_path

    def test_import_batches_conta_contratos_distintos_por_arquivo(self) -> None:
        principal = self.record(row=2)
        principal["contract"] = "001"
        repetido = self.record(row=3)
        repetido["contract"] = "001"
        outro = self.record(row=4)
        outro["contract"] = "002"
        ausente = self.record(row=5)
        ausente["contract"] = "Sem contrato"
        outro_arquivo = self.record(row=6)
        outro_arquivo["source_file"] = "outro.xlsx"
        outro_arquivo["contract"] = "009"
        production.save_records([principal, repetido, outro, ausente, outro_arquivo])

        lotes = production.import_batches().set_index("source_file")
        self.assertEqual(int(lotes.loc["producao.xlsx", "contracts_count"]), 2)
        self.assertEqual(int(lotes.loc["outro.xlsx", "contracts_count"]), 1)

    def test_import_batches_sem_contratos(self) -> None:
        production.save_records([self.record()])
        lotes = production.import_batches()
        self.assertEqual(int(lotes.iloc[0]["contracts_count"]), 0)

    def test_load_records_inclui_qtde_contrato_por_arquivo(self) -> None:
        primeiro = self.record(row=2)
        primeiro["contract"] = "001"
        segundo = self.record(row=3)
        segundo["contract"] = "002"
        repetido = self.record(row=4)
        repetido["contract"] = "001"
        sem_contrato = self.record(row=5)
        sem_contrato["contract"] = "Sem contrato"
        outro_arquivo = self.record(row=6)
        outro_arquivo["source_file"] = "outro.xlsx"
        outro_arquivo["contract"] = "009"
        production.save_records(
            [primeiro, segundo, repetido, sem_contrato, outro_arquivo]
        )

        for frame in (
            production.load_records(),
            production.load_dashboard_snapshot()[0],
        ):
            por_arquivo = frame.groupby("source_file")["contracts_qty"].unique()
            self.assertEqual(list(por_arquivo["producao.xlsx"]), [2])
            self.assertEqual(list(por_arquivo["outro.xlsx"]), [1])

    def test_add_contracts_qty_ignora_sem_contrato_e_arquivo_vazio(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx", "b.xlsx"],
                "contract": ["001", "Sem contrato", "NULL"],
            }
        )
        resultado = production.add_contracts_qty(frame)
        self.assertEqual(resultado["contracts_qty"].tolist(), [1, 1, 0])
        vazio = production.add_contracts_qty(pd.DataFrame())
        self.assertTrue(vazio.empty)
        self.assertIn("contracts_qty", vazio.columns)

    def test_first_real_import_removes_demonstration(self) -> None:
        demo = self.record(points=999)
        demo["source_file"] = production.DEMO_SOURCE
        production.save_records([demo], is_demo=True)
        production.save_records([self.record(points=100)])
        loaded = production.load_records()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.iloc[0]["is_demo"], 0)
        self.assertEqual(production.get_setting("demo_disabled"), "1")

    def test_drive_sync_replaces_processed_files_and_removes_deleted_files(
        self,
    ) -> None:
        old_prod = self.record(points=10, row=2)
        old_prod["source_file"] = "producao [live-id].xlsx"
        old_gpon = self.record(points=20, origin="Gpon", row=2)
        old_gpon["source_file"] = "producao [live-id].xlsx"
        removed = self.record(points=30)
        removed["source_file"] = "producao [removed-id].xlsx"
        manual = self.record(points=40)
        production.save_records([old_prod, old_gpon, removed, manual])

        refreshed = self.record(points=50, row=3)
        refreshed["source_file"] = "producao [live-id].xlsx"
        count = production.sync_drive_records(
            [refreshed],
            live_file_ids={"live-id"},
            refreshed_file_ids={"live-id"},
        )

        loaded = production.load_records()
        self.assertEqual(count, 1)
        self.assertEqual(
            set(loaded["source_file"]),
            {"producao [live-id].xlsx", "producao.xlsx"},
        )
        live_rows = loaded[loaded["source_file"] == "producao [live-id].xlsx"]
        self.assertEqual(len(live_rows), 1)
        self.assertEqual(live_rows.iloc[0]["points"], 50)

    def test_drive_sync_preserves_records_for_live_but_unreadable_files(self) -> None:
        current = self.record(points=70)
        current["source_file"] = "producao [live-id].xlsx"
        production.save_records([current])

        production.sync_drive_records(
            [],
            live_file_ids={"live-id"},
            refreshed_file_ids=set(),
        )

        loaded = production.load_records()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.iloc[0]["points"], 70)

    def test_drive_sync_persists_fingerprints_and_removes_deleted_files(self) -> None:
        production.sync_drive_records(
            [],
            live_file_ids={"live-id"},
            refreshed_file_ids={"live-id"},
            folder_id="folder-id",
            file_fingerprints={"live-id": "fingerprint-v1"},
        )

        self.assertEqual(
            production.get_drive_file_fingerprints("folder-id"),
            {"live-id": "fingerprint-v1"},
        )

        production.sync_drive_records(
            [],
            live_file_ids=set(),
            refreshed_file_ids=set(),
            folder_id="folder-id",
        )

        self.assertEqual(production.get_drive_file_fingerprints("folder-id"), {})

    def test_drive_sync_removes_stale_fingerprint_when_metadata_missing(self) -> None:
        production.sync_drive_records(
            [],
            {"live-id"},
            {"live-id"},
            folder_id="folder-id",
            file_fingerprints={"live-id": "old"},
        )
        production.sync_drive_records(
            [],
            {"live-id"},
            {"live-id"},
            folder_id="folder-id",
        )
        self.assertEqual(production.get_drive_file_fingerprints("folder-id"), {})

    def test_clear_database_invalidates_drive_file_fingerprints(self) -> None:
        production.sync_drive_records(
            [],
            live_file_ids={"live-id"},
            refreshed_file_ids={"live-id"},
            folder_id="folder-id",
            file_fingerprints={"live-id": "fingerprint-v1"},
        )

        production.clear_database()

        self.assertEqual(production.get_drive_file_fingerprints("folder-id"), {})


if __name__ == "__main__":
    unittest.main()
