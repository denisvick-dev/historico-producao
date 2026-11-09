from __future__ import annotations

import unittest

import pandas as pd

from components.visoes_dashboards import (
    comparar_tecnicos,
    matriz_sazonalidade,
    resumir_projetos,
    resumir_regularidade,
    resumir_saude_dados,
    rotulo_janelas_comparacao,
    selecionar_periodo_anterior,
)


class ProjectDashboardTests(unittest.TestCase):
    def test_project_summary_combines_points_but_counts_os_only_from_prod(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "project": "Projeto A",
                    "technician": "Ana",
                    "source_sheet": "Prod",
                    "points": 100,
                },
                {
                    "project": "Projeto A",
                    "technician": "Ana",
                    "source_sheet": "Gpon",
                    "points": 20,
                },
                {
                    "project": "Projeto B",
                    "technician": "Ana",
                    "source_sheet": "Prod",
                    "points": 40,
                },
                {
                    "project": "Projeto B",
                    "technician": "Bia",
                    "source_sheet": "Gpon",
                    "points": 80,
                },
                {
                    "project": "Sem projeto",
                    "technician": "Caio",
                    "source_sheet": "Gpon",
                    "points": 50,
                },
            ]
        )

        resumo = resumir_projetos(frame).set_index("project")

        self.assertEqual(resumo.loc["Projeto A", "points_total"], 120)
        self.assertEqual(resumo.loc["Projeto A", "os_count"], 1)
        self.assertEqual(resumo.loc["Projeto A", "technicians"], 1)
        self.assertEqual(resumo.loc["Projeto B", "points_total"], 120)
        self.assertEqual(resumo.loc["Projeto B", "os_count"], 1)
        self.assertEqual(resumo.loc["Projeto B", "technicians"], 2)
        self.assertEqual(resumo.loc["Sem projeto", "os_count"], 0)
        self.assertAlmostEqual(resumo["share_pct"].sum(), 100)

    def test_empty_project_summary_has_stable_columns(self) -> None:
        result = resumir_projetos(pd.DataFrame())
        self.assertEqual(
            list(result.columns),
            [
                "project",
                "points_prod",
                "points_gpon",
                "points_total",
                "os_count",
                "technicians",
                "share_pct",
            ],
        )


class ProductionRegularityTests(unittest.TestCase):
    def test_regularidade_conta_lacunas_e_destaca_um_pico(self) -> None:
        frame = pd.DataFrame(
            [
                {"technician": "Ana", "period": "2026-01-01", "points": 100},
                {"technician": "Ana", "period": "2026-02-01", "points": 100},
                {"technician": "Ana", "period": "2026-04-01", "points": 300},
                {"technician": "Bia", "period": "2026-01-01", "points": 50},
            ]
        )

        resumo = resumir_regularidade(
            frame, pd.Timestamp("2026-01-01"), pd.Timestamp("2026-04-30")
        ).set_index("technician")

        ana = resumo.loc["Ana"]
        self.assertEqual(ana["active_months"], 3)
        self.assertEqual(ana["months_without_records"], 1)
        self.assertEqual(ana["missing_periods"], "mar/26")
        self.assertAlmostEqual(ana["mean_active_monthly_points"], 500 / 3)
        self.assertEqual(ana["median_active_monthly_points"], 100)
        self.assertEqual(ana["peak_month"], "abr/26")
        self.assertAlmostEqual(ana["peak_vs_median_pct"], 200)
        self.assertEqual(ana["regularity"], "Alta oscilação")

        bia = resumo.loc["Bia"]
        self.assertEqual(bia["months_without_records"], 3)
        self.assertEqual(bia["regularity"], "Base curta")

    def test_regularidade_vazia_mantem_colunas(self) -> None:
        resumo = resumir_regularidade(pd.DataFrame())
        self.assertIn("missing_periods", resumo.columns)
        self.assertIn("coefficient_variation_pct", resumo.columns)
        self.assertTrue(resumo.empty)


class SeasonalityDashboardTests(unittest.TestCase):
    def test_heatmap_preenche_competencias_e_ordena_entidades(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "technician": "Ana",
                    "project": "Projeto A",
                    "period": "2026-01-01",
                    "points": 10,
                },
                {
                    "technician": "Ana",
                    "project": "Projeto A",
                    "period": "2026-03-01",
                    "points": 30,
                },
                {
                    "technician": "Bia",
                    "project": "Projeto B",
                    "period": "2026-01-01",
                    "points": 40,
                },
                {
                    "technician": "Bia",
                    "project": "Projeto B",
                    "period": "2026-02-01",
                    "points": 20,
                },
            ]
        )

        matrix = matriz_sazonalidade(
            frame,
            "technician",
            pd.Timestamp("2026-01-01"),
            pd.Timestamp("2026-04-30"),
            top_n=1,
        )

        self.assertEqual(matrix.index.tolist(), ["Bia"])
        self.assertEqual(
            matrix.columns.tolist(),
            list(pd.date_range("2026-01-01", "2026-04-01", freq="MS")),
        )
        self.assertEqual(matrix.loc["Bia"].tolist(), [40, 20, 0, 0])

    def test_heatmap_aceita_projeto_e_valida_dimensao(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "technician": "Ana",
                    "project": "Projeto A",
                    "period": "2026-01-01",
                    "points": 10,
                },
                {
                    "technician": "Bia",
                    "project": "Projeto B",
                    "period": "2026-01-01",
                    "points": 20,
                },
            ]
        )

        matrix = matriz_sazonalidade(frame, "project")
        self.assertEqual(matrix.index.name, "project")
        self.assertEqual(matrix.index.tolist(), ["Projeto B", "Projeto A"])
        with self.assertRaises(ValueError):
            matriz_sazonalidade(frame, "period")


class ExecutiveDashboardTests(unittest.TestCase):
    def test_technician_comparison_marks_new_and_inactive_people(self) -> None:
        atual = pd.DataFrame(
            [
                {"technician": "Ana", "source_sheet": "Prod", "points": 150},
                {"technician": "Bia", "source_sheet": "Gpon", "points": 60},
            ]
        )
        anterior = pd.DataFrame(
            [
                {"technician": "Ana", "source_sheet": "Prod", "points": 100},
                {"technician": "Caio", "source_sheet": "Gpon", "points": 80},
            ]
        )

        resultado = comparar_tecnicos(atual, anterior).set_index("Técnico")

        self.assertEqual(resultado.loc["Ana", "Status"], "Alta")
        self.assertEqual(resultado.loc["Ana", "Variação (%)"], 50)
        self.assertEqual(resultado.loc["Bia", "Status"], "Novo na janela")
        self.assertTrue(pd.isna(resultado.loc["Bia", "Variação (%)"]))
        self.assertEqual(resultado.loc["Caio", "Status"], "Sem produção atual")
        self.assertEqual(resultado.loc["Caio", "Variação (%)"], -100)

    def test_empty_previous_window_is_not_misreported_as_new_hires(self) -> None:
        atual = pd.DataFrame(
            [{"technician": "Ana", "source_sheet": "Prod", "points": 100}]
        )

        resultado = comparar_tecnicos(atual, pd.DataFrame())

        self.assertEqual(resultado.loc[0, "Status"], "Sem base anterior")
        self.assertTrue(pd.isna(resultado.loc[0, "Variação (%)"]))

    def test_comparison_label_uses_equal_length_month_windows(self) -> None:
        atual = pd.DataFrame(
            {"period": [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-11-01")]}
        )
        label = rotulo_janelas_comparacao(atual, meses=2)
        self.assertIn("out/26–nov/26", label)
        self.assertIn("ago/26–set/26", label)

    def test_comparison_label_shows_exact_custom_window_dates(self) -> None:
        atual = pd.DataFrame({"period": [pd.Timestamp("2026-10-01")]})

        label = rotulo_janelas_comparacao(
            atual,
            meses=2,
            inicio=pd.Timestamp("2026-10-15"),
            fim=pd.Timestamp("2026-11-05"),
        )

        self.assertIn("15/10/2026 a 05/11/2026", label)
        self.assertIn("15/08/2026 a 14/10/2026", label)

    def test_previous_period_matches_window_and_selected_dimensions(self) -> None:
        records = pd.DataFrame(
            [
                {
                    "source_file": "prior-a.xlsx",
                    "reference_date": "2025-12-01",
                    "period": "2025-12-01",
                    "technician": "Ana",
                    "project": "Projeto A",
                    "source_sheet": "Prod",
                    "points": 100,
                },
                {
                    "source_file": "prior-a2.xlsx",
                    "reference_date": "2026-05-31",
                    "period": "2026-05-01",
                    "technician": "Ana",
                    "project": "Projeto A",
                    "source_sheet": "Gpon",
                    "points": 30,
                },
                {
                    "source_file": "too-old.xlsx",
                    "reference_date": "2025-11-30",
                    "period": "2025-11-01",
                    "technician": "Ana",
                    "project": "Projeto A",
                    "source_sheet": "Prod",
                    "points": 10,
                },
                {
                    "source_file": "current.xlsx",
                    "reference_date": "2026-06-01",
                    "period": "2026-06-01",
                    "technician": "Ana",
                    "project": "Projeto A",
                    "source_sheet": "Prod",
                    "points": 150,
                },
                {
                    "source_file": "other-tech.xlsx",
                    "reference_date": "2026-01-01",
                    "period": "2026-01-01",
                    "technician": "Bia",
                    "project": "Projeto A",
                    "source_sheet": "Prod",
                    "points": 80,
                },
                {
                    "source_file": "other-project.xlsx",
                    "reference_date": "2026-01-01",
                    "period": "2026-01-01",
                    "technician": "Ana",
                    "project": "Projeto B",
                    "source_sheet": "Prod",
                    "points": 90,
                },
            ]
        )
        records["reference_date"] = pd.to_datetime(records["reference_date"])
        records["period"] = pd.to_datetime(records["period"])
        atual = records.loc[records["source_file"].eq("current.xlsx")]

        anterior = selecionar_periodo_anterior(
            records,
            atual,
            ["Ana"],
            6,
            ["Projeto A"],
            pd.Timestamp("2026-06-01"),
            pd.Timestamp("2026-11-01"),
        )

        self.assertEqual(
            set(anterior["source_file"]), {"prior-a.xlsx", "prior-a2.xlsx"}
        )


class DataHealthDashboardTests(unittest.TestCase):
    def test_data_coverage_counts_unassigned_projects_and_demo_rows(self) -> None:
        frame = pd.DataFrame(
            [
                {"technician": "Ana", "project": "Projeto A", "is_demo": 0},
                {"technician": "Bia", "project": "Sem projeto", "is_demo": 1},
                {"technician": "Caio", "project": " ", "is_demo": 1},
            ]
        )

        resumo = resumir_saude_dados(frame)

        self.assertEqual(resumo["registros"], 3)
        self.assertEqual(resumo["tecnicos"], 3)
        self.assertEqual(resumo["projetos_identificados"], 1)
        self.assertEqual(resumo["sem_projeto"], 2)
        self.assertAlmostEqual(resumo["percentual_sem_projeto"], 200 / 3)
        self.assertEqual(resumo["registros_demo"], 2)
        self.assertEqual(resumo["registros_producao"], 1)

    def test_tecnicos_vazios_ou_ausentes_nao_sao_contados(self) -> None:
        frame = pd.DataFrame({"technician": [" Ana ", "Ana", " ", None, pd.NA]})
        self.assertEqual(resumir_saude_dados(frame)["tecnicos"], 1)

    def test_empty_data_has_zeroed_health_indicators(self) -> None:
        resumo = resumir_saude_dados(pd.DataFrame())
        self.assertEqual(resumo["registros"], 0)
        self.assertEqual(resumo["sem_projeto"], 0)
        self.assertEqual(resumo["percentual_sem_projeto"], 0)


if __name__ == "__main__":
    unittest.main()
