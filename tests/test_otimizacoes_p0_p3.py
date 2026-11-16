"""Testes das otimizações P0–P3 (SQLite, aliases, materialização, Excel executivo, UX e AppTest)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

import production
from components.componentes import navegar_para_tecnico
from components.pacote_executivo import gerar_pacote_executivo_xlsx
from components.visoes_dashboards import comparar_tecnicos


class OtimizacoesP0P3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._orig_db = production.DB_PATH
        production.DB_PATH = self.tmp_path / "test_p0_p3.db"
        production._INITIALIZED_DBS.clear()
        production.init_database()

    def tearDown(self) -> None:
        production.DB_PATH = self._orig_db
        production._INITIALIZED_DBS.clear()
        self._tmp.cleanup()

    def test_backup_database_wal_safe_and_valid_sqlite(self) -> None:
        production.save_records(
            [
                {
                    "technician": "Carlos Eduardo",
                    "reference_date": "2026-03-10",
                    "source_sheet": production.PROD,
                    "project": "Fibra",
                    "contract": "CT-1001",
                    "wo": "WO-1001",
                    "points": 42.5,
                    "source_file": "lote_mar.xlsx",
                    "source_row": 2,
                }
            ],
            is_demo=False,
        )
        backup_target = self.tmp_path / "backups" / "copia_segura.db"
        result_path = production.backup_database(backup_target)
        self.assertIsNotNone(result_path)
        assert result_path is not None
        self.assertTrue(result_path.exists())
        self.assertGreater(result_path.stat().st_size, 0)

        with sqlite3.connect(result_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(integrity, "ok")
            total = conn.execute("SELECT COUNT(*) FROM production_records").fetchone()[
                0
            ]
            self.assertEqual(total, 1)

    def test_concurrent_sqlite_writes_under_lock(self) -> None:
        def _worker(idx: int) -> bool:
            production.set_setting(f"k_{idx}", str(idx))
            return production.save_technician_alias(
                "login", f"Z99{idx:04d}", f"Tecnico {idx}", notes="stress"
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_worker, range(24)))

        self.assertTrue(all(results))
        aliases = production.load_technician_aliases()
        self.assertEqual(len(aliases), 24)

    def test_technician_aliases_crud_and_enrichment(self) -> None:
        roster = pd.DataFrame(
            [
                {
                    "technician_key": production.normalize_text("Joao Carlos Silva"),
                    "technician": "Joao Carlos Silva",
                    "re_code": "RE100",
                    "login": "Z111111",
                    "monitor": "Monitor Alpha",
                    "un": "UN-SP",
                    "base": "BASE-LESTE",
                    "status": "ATIVO",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                },
                {
                    "technician_key": production.normalize_text("Maria Fernanda"),
                    "technician": "Maria Fernanda",
                    "re_code": "RE200",
                    "login": "Z222222",
                    "monitor": "Monitor Beta",
                    "un": "UN-RJ",
                    "base": "BASE-SUL",
                    "status": "ATIVO",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                },
            ]
        )

        self.assertTrue(
            production.save_technician_alias(
                "name", "J. C. SILVA", "Joao Carlos Silva", notes="abreviação"
            )
        )
        self.assertTrue(
            production.save_technician_alias(
                "login", "Z999888", "Maria Fernanda", notes="login antigo"
            )
        )
        aliases = production.load_technician_aliases()
        self.assertEqual(len(aliases), 2)

        # 1. Enriquecimento de Produção via alias de nome
        prod_raw = pd.DataFrame(
            [
                {
                    "technician": "J. C. SILVA",
                    "reference_date": pd.Timestamp("2026-03-05"),
                    "source_sheet": production.PROD,
                    "project": "Fibra",
                    "points": 50.0,
                }
            ]
        )
        prod_enriched = production.enrich_records_with_roster(prod_raw, roster, aliases)
        self.assertEqual(prod_enriched.iloc[0]["technician"], "Joao Carlos Silva")
        self.assertEqual(prod_enriched.iloc[0]["monitor"], "Monitor Alpha")
        self.assertEqual(prod_enriched.iloc[0]["base"], "BASE-LESTE")

        # 2. Enriquecimento de Consultivo via alias de login
        cons_raw = pd.DataFrame(
            [
                {
                    "reference_date": "2026-03-05",
                    "login_netsales": "Z999888",
                    "seller": "Vendedor Sem Cadastro",
                    "hp": "11999990000",
                    "contact_code": "C-1",
                    "contract": "CT-1",
                    "tabulation_type": "VENDA",
                    "status_netsales": "INSTALADA",
                    "plano_tv": "",
                    "plano_internet": "600 MEGA",
                    "tipo_servico": "600 MEGA",
                    "qtde_consultivo": 1,
                    "qtde_produtos": 2,
                    "qtde_mesh": 1,
                    "qtde_tv": 0,
                    "qtde_virtua": 1,
                    "source_file": "cons.csv",
                    "source_row": 2,
                    "is_demo": 0,
                    "imported_at": "2026-03-06",
                }
            ]
        )
        cons_enriched = production.enrich_consultivo_with_roster(
            cons_raw, roster, aliases
        )
        self.assertEqual(cons_enriched.iloc[0]["VENDEDOR"], "Maria Fernanda")
        self.assertEqual(cons_enriched.iloc[0]["Monitor"], "Monitor Beta")
        self.assertEqual(cons_enriched.iloc[0]["Base"], "BASE-SUL")

        # 3. Exclusão de alias
        first_id = int(aliases.iloc[0]["id"])
        production.delete_technician_alias(first_id)
        self.assertEqual(len(production.load_technician_aliases()), 1)

    def test_materialized_monthly_summaries_refresh_automatically(self) -> None:
        production.save_records(
            [
                {
                    "technician": "Ana Paula",
                    "reference_date": "2026-02-10",
                    "source_sheet": production.PROD,
                    "project": "Fibra",
                    "contract": "CT-10",
                    "wo": "WO-1",
                    "points": 30.0,
                    "source_file": "f1.xlsx",
                    "source_row": 2,
                },
                {
                    "technician": "Ana Paula",
                    "reference_date": "2026-02-12",
                    "source_sheet": production.GPON,
                    "project": "Fibra",
                    "contract": "CT-10",
                    "wo": "WO-2",
                    "points": 15.0,
                    "source_file": "f1.xlsx",
                    "source_row": 3,
                },
            ],
            is_demo=False,
        )
        production.save_consultivo_records(
            [
                {
                    "reference_date": "2026-02-10",
                    "login_netsales": "Z123456",
                    "seller": "Ana Paula",
                    "qtde_consultivo": 3,
                    "qtde_produtos": 4,
                    "qtde_mesh": 2,
                    "qtde_tv": 1,
                    "qtde_virtua": 1,
                    "source_file": "c1.csv",
                    "source_row": 2,
                }
            ],
            is_demo=False,
        )

        prod_sum = production.load_monthly_production_summary()
        self.assertEqual(len(prod_sum), 1)
        self.assertAlmostEqual(float(prod_sum.iloc[0]["points_total"]), 45.0)
        self.assertEqual(int(prod_sum.iloc[0]["os_count"]), 1)
        self.assertEqual(int(prod_sum.iloc[0]["contracts_count"]), 1)

        cons_sum = production.load_monthly_consultivo_summary()
        self.assertEqual(len(cons_sum), 1)
        self.assertEqual(int(cons_sum.iloc[0]["qtde_consultivo"]), 3)
        self.assertEqual(int(cons_sum.iloc[0]["qtde_produtos"]), 4)

        production.clear_database()
        self.assertTrue(production.load_monthly_production_summary().empty)
        self.assertTrue(production.load_monthly_consultivo_summary().empty)

    def test_comparar_tecnicos_vectorized_statuses(self) -> None:
        atual = pd.DataFrame(
            [
                {
                    "technician": "Subiu",
                    "points": 150.0,
                    "source_sheet": production.PROD,
                },
                {"technician": "Caiu", "points": 80.0, "source_sheet": production.PROD},
                {
                    "technician": "Igual",
                    "points": 100.0,
                    "source_sheet": production.PROD,
                },
                {"technician": "Novo", "points": 90.0, "source_sheet": production.PROD},
            ]
        )
        anterior = pd.DataFrame(
            [
                {
                    "technician": "Subiu",
                    "points": 100.0,
                    "source_sheet": production.PROD,
                },
                {
                    "technician": "Caiu",
                    "points": 100.0,
                    "source_sheet": production.PROD,
                },
                {
                    "technician": "Igual",
                    "points": 100.0,
                    "source_sheet": production.PROD,
                },
                {
                    "technician": "Sumiu",
                    "points": 120.0,
                    "source_sheet": production.PROD,
                },
            ]
        )
        comp = comparar_tecnicos(atual, anterior).set_index("Técnico")
        self.assertEqual(comp.loc["Subiu", "Status"], "Alta")
        self.assertAlmostEqual(float(comp["Variação (%)"].loc["Subiu"]), 50.0)
        self.assertEqual(comp.loc["Caiu", "Status"], "Queda")
        self.assertAlmostEqual(float(comp["Variação (%)"].loc["Caiu"]), -20.0)
        self.assertEqual(comp.loc["Igual", "Status"], "Estável")
        self.assertEqual(comp.loc["Novo", "Status"], "Novo na janela")
        self.assertTrue(pd.isna(comp["Variação (%)"].loc["Novo"]))
        self.assertEqual(comp.loc["Sumiu", "Status"], "Sem produção atual")

    def test_gerar_pacote_executivo_xlsx_5_abas(self) -> None:
        production.create_demonstration()
        prod_df, _ = production.load_dashboard_snapshot()
        cons_df, _ = production.load_consultivo_snapshot()
        roster_df = production.load_roster()

        xlsx_bytes = gerar_pacote_executivo_xlsx(
            prod_df,
            cons_df,
            roster_df,
            periodo_label="Base Demo",
        )
        self.assertIsInstance(xlsx_bytes, bytes)
        self.assertGreater(len(xlsx_bytes), 2000)

        wb = load_workbook(BytesIO(xlsx_bytes))
        self.assertEqual(
            wb.sheetnames,
            [
                "Resumo Executivo",
                "Visao 360",
                "Alertas",
                "Supervisao",
                "Mensal",
            ],
        )
        self.assertEqual(wb["Resumo Executivo"]["A4"].value, "Indicador")
        self.assertGreater(wb["Visao 360"].max_row, 5)
        self.assertGreater(wb["Mensal"].max_row, 5)

    def test_navegar_para_tecnico_helper(self) -> None:
        fake_state: dict[str, object] = {}
        with patch.object(st, "session_state", fake_state):
            navegar_para_tecnico("  Ana Paula  ")
        self.assertEqual(fake_state["_pending_navigation"], "Técnicos")
        self.assertEqual(fake_state["_pending_technician"], "Ana Paula")
        self.assertEqual(fake_state["_pending_sidebar_group"], "Todos")

    def test_apptest_sidebar_group_and_governanca_ui(self) -> None:
        app_path = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
        app = AppTest.from_file(app_path, default_timeout=45)
        app.run()
        self.assertFalse(app.exception)

        # Grupo padrão "Todos" expõe os 19 módulos na navegação (inclui Modo Reunião)
        nav_radio = app.radio(key="navigation")
        self.assertEqual(len(nav_radio.options), 19)

        # Filtra grupo Executivo e valida redução limpa das opções
        app.selectbox(key="sidebar_nav_group").set_value("Executivo").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.radio(key="navigation").options), 6)

        # Retorna para Todos e abre Saúde dos dados (com De-Para e Backup)
        app.selectbox(key="sidebar_nav_group").set_value("Todos").run()
        app.radio(key="navigation").set_value("Saúde dos dados").run()
        self.assertFalse(app.exception)
        self.assertTrue(any(b.key == "gov_alias_save_btn" for b in app.button))
        self.assertTrue(any(b.key == "gov_generate_backup_btn" for b in app.button))

        # Verifica Visão 360° com fragment + cache + drill-down
        app.radio(key="navigation").set_value("Visão 360°").run()
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
