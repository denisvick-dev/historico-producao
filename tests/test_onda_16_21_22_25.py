"""Testes dos itens 1.6 (Modo Reunião), 2.1 (Materialização/Pushdown SQL), 2.2 (Modularização/st.navigation) e 2.5 (Presets & Comparação 1:1)."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from streamlit.testing.v1 import AppTest

from components.modo_reuniao import gerar_briefing_html, montar_briefing_reuniao
from components.tecnicos_comparacao import calcular_comparacao_tecnicos
from core.page_registry import (
    PAGE_SPECS,
    build_nav_groups,
    build_nav_labels,
    load_page_callable,
    resolve_page_key,
)
from core.presets import normalize_preset_payload
import production


class Onda16212225Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._orig_db = production.DB_PATH
        production.DB_PATH = self.tmp_path / "test_onda.db"
        production._INITIALIZED_DBS.clear()
        production.init_database()

    def tearDown(self) -> None:
        production.DB_PATH = self._orig_db
        production._INITIALIZED_DBS.clear()
        self._tmp.cleanup()

    def test_composite_indexes_and_sql_window_pushdown(self) -> None:
        with sqlite3.connect(production.DB_PATH) as conn:
            prod_indexes = {
                row[1]
                for row in conn.execute(
                    "PRAGMA index_list(production_records)"
                ).fetchall()
            }
            cons_indexes = {
                row[1]
                for row in conn.execute(
                    "PRAGMA index_list(consultivo_records)"
                ).fetchall()
            }
        self.assertIn("idx_production_date_sheet", prod_indexes)
        self.assertIn("idx_production_date_tech", prod_indexes)
        self.assertIn("idx_consultivo_date_login", cons_indexes)

        production.save_records(
            [
                {
                    "technician": "Alice Souza",
                    "reference_date": "2026-01-10",
                    "source_sheet": production.PROD,
                    "project": "Fibra",
                    "contract": "CT-1",
                    "wo": "WO-1",
                    "points": 100.0,
                    "source_file": "jan.xlsx",
                    "source_row": 2,
                },
                {
                    "technician": "Alice Souza",
                    "reference_date": "2026-03-15",
                    "source_sheet": production.GPON,
                    "project": "Fibra",
                    "contract": "CT-2",
                    "wo": "WO-2",
                    "points": 55.0,
                    "source_file": "mar.xlsx",
                    "source_row": 2,
                },
                {
                    "technician": "Bruno Lima",
                    "reference_date": "2026-03-20",
                    "source_sheet": production.PROD,
                    "project": "HFC",
                    "contract": "CT-3",
                    "wo": "WO-3",
                    "points": 80.0,
                    "source_file": "mar.xlsx",
                    "source_row": 3,
                },
            ],
            is_demo=False,
        )
        production.save_consultivo_records(
            [
                {
                    "reference_date": "2026-01-12",
                    "login_netsales": "Z100001",
                    "seller": "Alice Souza",
                    "qtde_consultivo": 2,
                    "qtde_produtos": 3,
                    "qtde_mesh": 1,
                    "qtde_tv": 1,
                    "qtde_virtua": 1,
                    "source_file": "c_jan.csv",
                    "source_row": 2,
                },
                {
                    "reference_date": "2026-03-18",
                    "login_netsales": "Z200002",
                    "seller": "Bruno Lima",
                    "qtde_consultivo": 4,
                    "qtde_produtos": 6,
                    "qtde_mesh": 2,
                    "qtde_tv": 2,
                    "qtde_virtua": 2,
                    "source_file": "c_mar.csv",
                    "source_row": 2,
                },
            ],
            is_demo=False,
        )

        # Pushdown SQL por data e origem
        mar_prod = production.load_records_window(
            date_start="2026-03-01",
            date_end="2026-03-31",
            source_sheet=production.PROD,
        )
        self.assertEqual(len(mar_prod), 1)
        self.assertEqual(mar_prod.iloc[0]["technician"], "Bruno Lima")

        mar_cons = production.load_consultivo_window(
            date_start="2026-03-01",
            date_end="2026-03-31",
            login_netsales="z200002",
        )
        self.assertEqual(len(mar_cons), 1)
        self.assertEqual(int(mar_cons.iloc[0]["QTDE_CONSULTIVO"]), 4)

        # Pushdown nas tabelas materializadas mensais
        mat_prod_mar = production.load_monthly_production_summary(
            date_start="2026-03-01", date_end="2026-03-31"
        )
        self.assertEqual(len(mat_prod_mar), 2)
        self.assertAlmostEqual(float(mat_prod_mar["points_total"].sum()), 135.0)

        mat_cons_jan = production.load_monthly_consultivo_summary(
            date_start="2026-01-01", date_end="2026-01-31"
        )
        self.assertEqual(len(mat_cons_jan), 1)
        self.assertEqual(int(mat_cons_jan.iloc[0]["qtde_consultivo"]), 2)

        # Sidebar pulse consumindo resumo materializado
        pulse = production.load_sidebar_pulse_summary()
        self.assertTrue(pulse["materialized"])
        self.assertEqual(pulse["records"], 3)
        self.assertEqual(pulse["technicians"], 2)
        self.assertEqual(pulse["months_count"], 2)
        self.assertEqual(pulse["consultivos_total"], 6)
        self.assertAlmostEqual(pulse["points_total"], 235.0)

    def test_filter_presets_crud_and_payload_sanitization(self) -> None:
        sanitized = normalize_preset_payload(
            {
                "period_filter": "Últimos 3 meses",
                "base_filter": ["BASE-LESTE", "  "],
                "monitor_filter": ("Monitor A",),
                "chave_invalida": "nao_entra",
            }
        )
        self.assertEqual(sanitized["period_filter"], "Últimos 3 meses")
        self.assertEqual(sanitized["base_filter"], ["BASE-LESTE"])
        self.assertEqual(sanitized["monitor_filter"], ["Monitor A"])
        self.assertNotIn("chave_invalida", sanitized)

        self.assertTrue(
            production.save_filter_preset(
                "Base Leste · 90d",
                {
                    "period_filter": "Últimos 3 meses",
                    "base_filter": ["BASE-LESTE"],
                    "navigation": "Modo Reunião",
                },
                page="Modo Reunião",
            )
        )
        # Upsert pelo mesmo nome sobrescreve sem duplicar
        self.assertTrue(
            production.save_filter_preset(
                "Base Leste · 90d",
                {
                    "period_filter": "Últimos 6 meses",
                    "base_filter": ["BASE-LESTE", "BASE-SUL"],
                },
                page="Visão geral",
            )
        )
        df = production.load_filter_presets()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["page"], "Visão geral")
        self.assertEqual(df.iloc[0]["payload"]["period_filter"], "Últimos 6 meses")
        self.assertEqual(len(df.iloc[0]["payload"]["base_filter"]), 2)

        production.delete_filter_preset("Base Leste · 90d")
        self.assertTrue(production.load_filter_presets().empty)

    def test_modo_reuniao_briefing_and_html_export(self) -> None:
        production.create_demonstration()
        rec, _ = production.load_dashboard_snapshot()
        cons, _ = production.load_consultivo_snapshot()
        roster = production.load_roster()
        mat_prod = production.load_monthly_production_summary()
        mat_cons = production.load_monthly_consultivo_summary()

        briefing = montar_briefing_reuniao(
            rec,
            cons,
            roster,
            periodo_label="Demo <2026>",
            monthly_prod_summary=mat_prod,
            monthly_cons_summary=mat_cons,
        )
        self.assertGreater(briefing.pontos_totais, 0.0)
        self.assertGreater(briefing.os_totais, 0)
        self.assertGreaterEqual(len(briefing.narrativa_bullets), 3)
        self.assertEqual(len(briefing.top_destaques), 3)
        self.assertFalse(briefing.comparativo_mom_bases.empty)
        self.assertFalse(briefing.serie_mensal.empty)
        self.assertGreaterEqual(len(briefing.pendencias_governanca), 2)

        html_bytes = gerar_briefing_html(briefing)
        html_text = html_bytes.decode("utf-8")
        self.assertIn("<!DOCTYPE html>", html_text)
        self.assertIn("@media print", html_text)
        self.assertIn("Demo &lt;2026&gt;", html_text)
        self.assertNotIn("Demo <2026>", html_text)

    def test_comparacao_lado_a_lado_tres_modos(self) -> None:
        production.create_demonstration()
        rec, _ = production.load_dashboard_snapshot()
        cons, _ = production.load_consultivo_snapshot()
        names = sorted(rec["technician"].unique().tolist())
        self.assertGreaterEqual(len(names), 2)

        # Modo 1: Técnico A vs Técnico B
        res_h2h = calcular_comparacao_tecnicos(
            rec,
            names[0],
            modo="tecnico",
            tecnico_b=names[1],
            consultivo_frame=cons,
        )
        self.assertEqual(res_h2h.referencia_label, names[1])
        self.assertFalse(res_h2h.tabela_metricas.empty)
        self.assertFalse(res_h2h.serie_mensal.empty)
        self.assertEqual(len(res_h2h.radar_normalizado), 6)

        # Modo 2: Técnico A vs Média da Base
        res_base = calcular_comparacao_tecnicos(
            rec, names[0], modo="media_base", consultivo_frame=cons
        )
        self.assertIn("Média", res_base.referencia_label)
        self.assertIn("Delta (%)", res_base.tabela_metricas.columns)

        # Modo 3: Técnico A vs Top Quartil (P75)
        res_p75 = calcular_comparacao_tecnicos(
            rec, names[0], modo="top_quartil", consultivo_frame=cons
        )
        self.assertEqual(res_p75.referencia_label, "Top Quartil (P75)")
        self.assertTrue((res_p75.radar_normalizado[names[0]] >= 0).all())
        self.assertTrue((res_p75.radar_normalizado[names[0]] <= 100).all())

    def test_page_registry_19_pages_unique_slugs_and_lazy_loader(self) -> None:
        self.assertEqual(len(PAGE_SPECS), 19)
        slugs = [s.slug for s in PAGE_SPECS]
        self.assertEqual(len(slugs), len(set(slugs)))
        labels = build_nav_labels()
        groups = build_nav_groups()
        self.assertIn("Modo Reunião", labels)
        self.assertIn("Modo Reunião", groups["Executivo"])
        self.assertEqual(resolve_page_key("modo-reuniao"), "Modo Reunião")
        self.assertEqual(resolve_page_key("visao-360"), "Visão 360°")
        self.assertEqual(resolve_page_key("inexistente"), "Visão geral")

        fn_reuniao = load_page_callable("Modo Reunião")
        self.assertTrue(callable(fn_reuniao))
        fn_360 = load_page_callable("Visão 360°")
        self.assertTrue(callable(fn_360))

    def test_apptest_modo_reuniao_presets_e_comparacao_1on1(self) -> None:
        app_path = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
        app = AppTest.from_file(app_path, default_timeout=45)
        app.run()
        self.assertFalse(app.exception)

        # 1. Navega para Modo Reunião via st.navigation + sidebar radio
        app.radio(key="navigation").set_value("Modo Reunião").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="navigation").value, "Modo Reunião")

        # 2. Salva um Preset de Filtro na sidebar e verifica persistência no SQLite
        app.text_input(key="sidebar_preset_name_input").set_value(
            "Reunião Semanal"
        ).run()
        app.button(key="sidebar_preset_save_btn").click().run()
        self.assertFalse(app.exception)
        presets_df = production.load_filter_presets()
        self.assertIn("Reunião Semanal", presets_df["name"].tolist())

        # 3. Abre Técnicos e valida presença da aba Comparação Lado a Lado (1:1)
        app.radio(key="navigation").set_value("Técnicos").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="navigation").value, "Técnicos")
        tab_labels = [t.label for t in app.tabs]
        self.assertIn("Dossiê Individual", tab_labels)
        self.assertIn("Comparação Lado a Lado (1:1)", tab_labels)

        # 4. Aplica o preset salvo (deve retornar para Modo Reunião)
        app.button(key="sidebar_preset_apply_btn").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="navigation").value, "Modo Reunião")


if __name__ == "__main__":
    unittest.main()
