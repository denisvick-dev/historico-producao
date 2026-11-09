import unittest

import pandas as pd
from pandas.io.formats.style import Styler

from components.eficiencia import (
    _estilo_faixa,
    _estilo_resumo_linha,
    _styled_faixa_table,
    calcular_eficiencia,
    resumir_eficiencia_contrato,
)


class EficienciaTests(unittest.TestCase):
    """Faixas de eficiência por técnico e por contrato (funções puras)."""

    def test_limites_e_soma_mensal(self) -> None:
        frame = pd.DataFrame(
            {
                "technician": ["A"] * 7,
                "reference_date": pd.to_datetime(
                    [
                        "2024-01-01",
                        "2024-02-01",
                        "2024-03-01",
                        "2024-04-01",
                        "2024-05-01",
                        "2024-05-01",
                        "2024-06-01",
                    ]
                ),
                "points": [299.99, 300, 350, 375, 200, 200, 349.99],
            }
        )
        detalhes, resumo = calcular_eficiencia(frame)
        self.assertEqual(
            detalhes["Faixa"].tolist(),
            ["Faixa 1", "Faixa 2", "Faixa 3", "Faixa 4", "Faixa 5", "Faixa 2"],
        )
        self.assertEqual(detalhes.iloc[4]["Pontos"], 400)
        self.assertEqual(resumo.iloc[0]["Faixa mais frequente"], "Faixa 2")
        self.assertEqual(resumo.iloc[0]["Meses com registros"], 6)

    def test_empate_e_meses_sem_registro(self) -> None:
        frame = pd.DataFrame(
            {
                "technician": ["A", "A", "B"],
                "period": pd.to_datetime(["2024-01-01", "2024-03-01", "2024-03-01"]),
                "points": [0, 400, 374.99],
            }
        )
        _, resumo = calcular_eficiencia(frame)
        self.assertEqual(resumo.iloc[0]["Faixa mais frequente"], "Faixa 1 / Faixa 5")
        self.assertEqual(resumo.iloc[0]["Meses com registros"], 2)
        self.assertEqual(resumo.iloc[1]["Faixa mais frequente"], "Faixa 3")

    def test_sem_dados_validos(self) -> None:
        detalhes, resumo = calcular_eficiencia(pd.DataFrame())
        self.assertTrue(detalhes.empty and resumo.empty)

    def test_cores_destacam_faixas_com_registros_e_a_mais_frequente(self) -> None:
        linha = pd.Series(
            {
                "Técnico": "A",
                "Meses com registros": 3,
                "Faixa 1": 1,
                "Faixa 2": 0,
                "Faixa 3": 0,
                "Faixa 4": 0,
                "Faixa 5": 2,
                "Faixa mais frequente": "Faixa 5",
            }
        )

        estilos = _estilo_resumo_linha(linha)

        self.assertEqual(estilos["Faixa 1"], _estilo_faixa("Faixa 1"))
        self.assertEqual(estilos["Faixa 2"], "")
        self.assertEqual(estilos["Faixa 5"], _estilo_faixa("Faixa 5"))
        self.assertEqual(estilos["Faixa mais frequente"], _estilo_faixa("Faixa 5"))
        self.assertIn("background-color", estilos["Meses com registros"])

    def test_empate_na_faixa_mais_frequente_recebe_destaque(self) -> None:
        linha = pd.Series(
            {
                "Técnico": "A",
                "Meses com registros": 2,
                "Faixa 1": 1,
                "Faixa 2": 0,
                "Faixa 3": 0,
                "Faixa 4": 0,
                "Faixa 5": 1,
                "Faixa mais frequente": "Faixa 1 / Faixa 5",
            }
        )

        estilos = _estilo_resumo_linha(linha)

        self.assertEqual(
            estilos["Faixa mais frequente"],
            "background-color: #E0F2FE; color: #075985; font-weight: 600",
        )

    def test_resumo_eficiencia_contrato_ignora_sem_contrato_e_soma_pontos(self) -> None:
        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Ana", "Ana", "Bia"],
                "contract": ["C1", "C1", "C2", "Sem contrato"],
                "period": pd.to_datetime(
                    ["2026-01-01", "2026-02-01", "2026-01-01", "2026-01-01"]
                ),
                "points": [310, 320, 450, 999],
            }
        )

        detalhes, resumo, faixas = resumir_eficiencia_contrato(frame)

        self.assertEqual(
            detalhes.to_dict("records"),
            [
                {
                    "Contrato": "C1",
                    "Competência": pd.Timestamp("2026-01-01"),
                    "Pontos": 310,
                    "Faixa": "Faixa 2",
                },
                {
                    "Contrato": "C1",
                    "Competência": pd.Timestamp("2026-02-01"),
                    "Pontos": 320,
                    "Faixa": "Faixa 2",
                },
                {
                    "Contrato": "C2",
                    "Competência": pd.Timestamp("2026-01-01"),
                    "Pontos": 450,
                    "Faixa": "Faixa 5",
                },
            ],
        )
        self.assertEqual(
            resumo.to_dict("records"),
            [
                {
                    "Contrato": "C1",
                    "Meses com registros": 2,
                    "Pontos totais": 630,
                    "Faixa mais frequente": "Faixa 2",
                },
                {
                    "Contrato": "C2",
                    "Meses com registros": 1,
                    "Pontos totais": 450,
                    "Faixa mais frequente": "Faixa 5",
                },
            ],
        )
        self.assertEqual(
            faixas.to_dict(),
            {
                "Faixa 1": 0,
                "Faixa 2": 2,
                "Faixa 3": 0,
                "Faixa 4": 0,
                "Faixa 5": 1,
            },
        )

    def test_resumo_eficiencia_contrato_frame_vazio(self) -> None:
        detalhes, resumo, faixas = resumir_eficiencia_contrato(pd.DataFrame())
        self.assertTrue(detalhes.empty and resumo.empty)
        self.assertEqual(int(faixas.sum()), 0)

    def test_tabela_de_faixas_nao_aplica_styler_acima_do_limite(self) -> None:
        frame = pd.DataFrame(
            {
                "Contrato": ["C1"],
                "Competência": ["2026-01"],
                "Pontos": [320],
                "Faixa": ["Faixa 2"],
            }
        )

        with pd.option_context("styler.render.max_elements", 3):
            resultado = _styled_faixa_table(frame)

        self.assertIs(resultado, frame)

    def test_tabela_de_faixas_mantem_styler_abaixo_do_limite(self) -> None:
        frame = pd.DataFrame({"Faixa": ["Faixa 2"]})

        resultado = _styled_faixa_table(frame)

        self.assertIsInstance(resultado, Styler)


if __name__ == "__main__":
    unittest.main()
