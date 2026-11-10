"""Testes unitários para o painel de Produtividade Unitária."""

from __future__ import annotations

import unittest

import pandas as pd
from pandas.io.formats.style import Styler
from streamlit.testing.v1 import AppTest

from components.contratos import resumir_contratos
from components.produtividade_unitaria import (
    _estilizar_tabela,
    classificar_quadrantes,
    resumir_produtividade_unitaria,
)
from production import PROD, summarize_os


class ProdutividadeUnitariaTests(unittest.TestCase):
    def test_calcula_pontos_por_os_apenas_sobre_prod_e_contratos_consistentes(
        self,
    ) -> None:
        frame = pd.DataFrame(
            [
                # Ana: 2 O.S. em Prod (100 + 50 = 150 -> 75 pts/OS) + 60 em Gpon no mesmo contrato CT-1
                # Contrato CT-1 em jan/26 -> 1 contrato atendido com 210 pts totais
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Prod",
                    "contract": "CT-1",
                    "points": 100.0,
                },
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Prod",
                    "contract": "CT-1",
                    "points": 50.0,
                },
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Gpon",
                    "contract": "CT-1",
                    "points": 60.0,
                },
                # Ana: linha sem contrato válido em Prod (90 pts): entra em O.S. mas não em Pontos / Contrato
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "source_sheet": "Prod",
                    "contract": "Sem contrato",
                    "points": 90.0,
                },
                # Bia: apenas Gpon com CT-2 em fev/26 (80 pts) -> 0 O.S., 1 contrato com 80 pts
                {
                    "technician": "Bia",
                    "period": pd.Timestamp("2026-02-01"),
                    "source_sheet": "Gpon",
                    "contract": "CT-2",
                    "points": 80.0,
                },
            ]
        )

        resumo = resumir_produtividade_unitaria(frame)

        # Consistência com summarize_os e resumir_contratos
        os_esperadas = len(frame[frame["source_sheet"].eq(PROD)])
        mensal_ct, _, _, _, _ = resumir_contratos(frame)
        self.assertEqual(resumo.total_os, os_esperadas)
        self.assertEqual(
            int(summarize_os(frame, [])["os_count"].iloc[0]), resumo.total_os
        )
        self.assertEqual(resumo.total_contracts, int(mensal_ct["contratos"].sum()))
        self.assertEqual(resumo.records_without_contract, 1)

        # Ana: 3 O.S. Prod somando 240 -> 80 pts/OS; 1 contrato válido somando 210 -> 210 pts/contrato
        por_tec = resumo.por_tecnico.set_index("technician")
        self.assertEqual(por_tec.loc["Ana", "os_count"], 3)
        self.assertAlmostEqual(por_tec.loc["Ana", "points_prod"], 240.0)
        self.assertAlmostEqual(por_tec.loc["Ana", "points_per_os"], 80.0)
        self.assertEqual(por_tec.loc["Ana", "contracts_count"], 1)
        self.assertAlmostEqual(por_tec.loc["Ana", "points_with_contract"], 210.0)
        self.assertAlmostEqual(por_tec.loc["Ana", "points_per_contract"], 210.0)

        # Bia: 0 O.S. Prod -> 0.0 pts/OS e perfil Sem O.S.; 1 contrato -> 80 pts/contrato
        self.assertEqual(por_tec.loc["Bia", "os_count"], 0)
        self.assertAlmostEqual(por_tec.loc["Bia", "points_per_os"], 0.0)
        self.assertEqual(por_tec.loc["Bia", "profile_os"], "Sem O.S.")
        self.assertEqual(por_tec.loc["Bia", "contracts_count"], 1)
        self.assertAlmostEqual(por_tec.loc["Bia", "points_per_contract"], 80.0)

        # Total geral usa média ponderada da equipe
        total_row = resumo.tabela_exibicao.iloc[-1]
        self.assertEqual(total_row["Técnico"], "Total geral")
        self.assertAlmostEqual(total_row["Pontos / O.S."], 240.0 / 3)
        self.assertAlmostEqual(total_row["Pontos / Contrato"], (210.0 + 80.0) / 2)

    def test_classificacao_dos_quatro_quadrantes(self) -> None:
        volumes = pd.Series([10, 2, 10, 2, 0], index=["T1", "T2", "T3", "T4", "T5"])
        unitarios = pd.Series(
            [100.0, 100.0, 30.0, 30.0, 0.0], index=["T1", "T2", "T3", "T4", "T5"]
        )

        perfis = classificar_quadrantes(volumes, unitarios, rotulo_inativo="Sem O.S.")

        self.assertEqual(perfis["T1"], "Alto volume e pontuação")
        self.assertEqual(perfis["T2"], "Alta pontuação")
        self.assertEqual(perfis["T3"], "Alto giro")
        self.assertEqual(perfis["T4"], "Em desenvolvimento")
        self.assertEqual(perfis["T5"], "Sem O.S.")

    def test_dataframe_vazio_ou_incompleto_retorna_estrutura_segura(self) -> None:
        vazio = resumir_produtividade_unitaria(pd.DataFrame())
        self.assertTrue(vazio.mensal.empty)
        self.assertTrue(vazio.por_tecnico.empty)
        self.assertEqual(vazio.total_os, 0)
        self.assertEqual(vazio.total_contracts, 0)

        incompleto = pd.DataFrame(
            {
                "technician": ["", None],
                "reference_date": ["invalida", "2026-01-01"],
                "points": [10.0, 20.0],
            }
        )
        res_inc = resumir_produtividade_unitaria(incompleto)
        self.assertTrue(res_inc.mensal.empty)
        self.assertEqual(res_inc.excluded_incomplete_rows, 2)

    def test_styler_respeita_limite_de_celulas(self) -> None:
        tabela = pd.DataFrame(
            {
                "Técnico": ["Ana", "Total geral"],
                "Perfil (O.S.)": ["Alta pontuação", "Média da equipe"],
                "Pontos / O.S.": [50.0, 50.0],
                "Pontos / Contrato": [70.0, 70.0],
            }
        )
        self.assertIsInstance(_estilizar_tabela(tabela), Styler)
        with pd.option_context("styler.render.max_elements", 3):
            self.assertIs(_estilizar_tabela(tabela), tabela)

    def test_renderizacao_isolada_sem_os_e_sem_contratos_validos(self) -> None:
        app = AppTest.from_string(
            """
import pandas as pd
from components.produtividade_unitaria import render_produtividade_unitaria
render_produtividade_unitaria(pd.DataFrame({
    "technician": ["Ana"],
    "period": pd.to_datetime(["2026-01-01"]),
    "source_sheet": ["Gpon"],
    "contract": ["Sem contrato"],
    "points": [50.0],
}))
"""
        ).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(
            any("Não há ordens de serviço" in str(item.value) for item in app.info)
        )


if __name__ == "__main__":
    unittest.main()
