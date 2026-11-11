"""Testes unitários e de integração UI para o Comparativo 2025 x 2026 e Sidebar."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

import pandas as pd
from streamlit.testing.v1 import AppTest

import drive_import
import production
from components.comparativo_anos import calcular_comparativo_anos
from components.componentes import (
    formatar_delta_decimal_br,
    formatar_delta_inteiro_br,
    formatar_variacao_pct_br,
    render_delta_card,
)
from components.sidebar import _CSS_PLACEHOLDERS, _css_tema, render_sidebar_pulse

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class _FakeResponse:
    def __init__(self, *, data: dict | None = None, content: bytes = b"") -> None:
        self.data = data
        self.content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict | None:
        return self.data


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)

    def get(
        self, _url: str, *, params: dict | None = None, timeout: int | None = None
    ) -> _FakeResponse:
        del params, timeout
        return self.responses.pop(0)


class ComparativoAnosCalculoTests(unittest.TestCase):
    """Valida regras oficiais de Contratos, O.S., giro e recortes 2025 x 2026."""

    def _sample_records(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                # Jan/2025 - Ana (ATIVO): 2 O.S. Prod no mesmo contrato CT-01 + 1 Gpon no CT-02 => 2 contratos, 2 O.S.
                {
                    "technician": "Ana",
                    "reference_date": "2025-01-05",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-01",
                    "points": 100.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2025-01-12",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-01",
                    "points": 80.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2025-01-18",
                    "source_sheet": "Gpon",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-02",
                    "points": 50.0,
                },
                # Jan/2025 - Tiago (DESLIGADO): 1 contrato, 1 O.S.
                {
                    "technician": "Tiago",
                    "reference_date": "2025-01-20",
                    "source_sheet": "Prod",
                    "project": "NET-GUARULHOS",
                    "base": "NET-GUARULHOS",
                    "monitor": "Adriano",
                    "roster_status": "DESLIGADO",
                    "contract": "CT-90",
                    "points": 90.0,
                },
                # Dez/2025 - Ana (fora da interseção quando 2026 só tem Jan): 1 contrato, 1 O.S.
                {
                    "technician": "Ana",
                    "reference_date": "2025-12-10",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-12",
                    "points": 110.0,
                },
                # Jan/2026 - Ana (ATIVO): 3 contratos distintos, 4 O.S. Prod
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-03",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-101",
                    "points": 120.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-04",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-101",
                    "points": 60.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-11",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-102",
                    "points": 95.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-19",
                    "source_sheet": "Prod",
                    "project": "NET-ABCDM",
                    "base": "NET-ABCDM",
                    "monitor": "Edson",
                    "roster_status": "ATIVO",
                    "contract": "CT-103",
                    "points": 105.0,
                },
                # Jan/2026 - Bia (ATIVO, nova em 2026): 1 contrato + 1 O.S. sem contrato válido
                {
                    "technician": "Bia",
                    "reference_date": "2026-01-22",
                    "source_sheet": "Prod",
                    "project": "NET-LESTE",
                    "base": "NET-LESTE",
                    "monitor": "Elisangela",
                    "roster_status": "ATIVO",
                    "contract": "CT-201",
                    "points": 130.0,
                },
                {
                    "technician": "Bia",
                    "reference_date": "2026-01-25",
                    "source_sheet": "Prod",
                    "project": "NET-LESTE",
                    "base": "NET-LESTE",
                    "monitor": "Elisangela",
                    "roster_status": "ATIVO",
                    "contract": "Sem contrato",
                    "points": 40.0,
                },
            ]
        )

    def test_modo_equivalente_compara_apenas_meses_comuns_e_respeita_regras(
        self,
    ) -> None:
        resumo = calcular_comparativo_anos(
            self._sample_records(),
            ano_base=2025,
            ano_comp=2026,
            modo_meses="equivalente",
            escopo_equipe="todos",
        )
        # Apenas janeiro (mês 1) existe em ambos os anos; dezembro/2025 fica fora do acumulado equivalente.
        self.assertEqual(resumo.meses_disponiveis_base, [1, 12])
        self.assertEqual(resumo.meses_disponiveis_comp, [1])
        self.assertEqual(resumo.meses_considerados, [1])
        self.assertFalse(resumo.fallback_sem_intersecao)

        # Jan/2025: Ana (2 contratos, 2 O.S.) + Tiago (1 contrato, 1 O.S.) = 3 contratos, 3 O.S.
        self.assertEqual(resumo.contratos_base, 3)
        self.assertEqual(resumo.os_base, 3)
        self.assertAlmostEqual(resumo.os_por_contrato_base, 1.0)

        # Jan/2026: Ana (3 contratos, 4 O.S.) + Bia (1 contrato, 2 O.S.) = 4 contratos, 6 O.S.
        self.assertEqual(resumo.contratos_comp, 4)
        self.assertEqual(resumo.os_comp, 6)
        self.assertEqual(resumo.delta_contratos, 1)
        self.assertEqual(resumo.delta_os, 3)
        self.assertAlmostEqual(resumo.os_por_contrato_comp, 1.5)
        self.assertEqual(resumo.sem_contrato_registros, 1)

        # Pontos de Produção em Jan/2025: Prod = 100+80+90 = 270, Gpon = 50 -> Total = 320.
        # Pontos de Produção em Jan/2026: Prod = 120+60+95+105+130+40 = 550, Gpon = 0 -> Total = 550.
        self.assertAlmostEqual(resumo.pontos_prod_base, 270.0)
        self.assertAlmostEqual(resumo.pontos_gpon_base, 50.0)
        self.assertAlmostEqual(resumo.pontos_totais_base, 320.0)
        self.assertAlmostEqual(resumo.pontos_prod_comp, 550.0)
        self.assertAlmostEqual(resumo.pontos_gpon_comp, 0.0)
        self.assertAlmostEqual(resumo.pontos_totais_comp, 550.0)
        self.assertAlmostEqual(resumo.delta_pontos_totais, 230.0)
        self.assertAlmostEqual(resumo.delta_pontos_prod, 280.0)
        self.assertAlmostEqual(resumo.delta_pontos_gpon, -50.0)
        self.assertAlmostEqual(resumo.pct_pontos_totais or 0.0, 71.875)

    def test_modo_ano_completo_inclui_todos_os_meses_e_calcula_medias_ativas(
        self,
    ) -> None:
        resumo = calcular_comparativo_anos(
            self._sample_records(),
            ano_base=2025,
            ano_comp=2026,
            modo_meses="ano_completo",
            escopo_equipe="todos",
        )
        self.assertEqual(resumo.meses_considerados, list(range(1, 13)))
        # 2025 passa a somar Jan (3) + Dez (1) = 4 contratos em 2 meses ativos -> média 2,0.
        self.assertEqual(resumo.contratos_base, 4)
        self.assertEqual(resumo.os_base, 4)
        self.assertEqual(resumo.meses_ativos_contratos_base, 2)
        self.assertAlmostEqual(resumo.media_mensal_contratos_base, 2.0)
        self.assertAlmostEqual(resumo.media_mensal_contratos_comp, 4.0)

    def test_escopos_ativos_e_mesma_equipe_isolam_efeito_de_turnover(self) -> None:
        ativos = calcular_comparativo_anos(
            self._sample_records(),
            modo_meses="equivalente",
            escopo_equipe="ativos",
        )
        # Tiago (DESLIGADO) sai de 2025; Bia (nova em 2026, ATIVO) permanece em 2026.
        self.assertEqual(ativos.contratos_base, 2)
        self.assertEqual(ativos.contratos_comp, 4)

        mesma_equipe = calcular_comparativo_anos(
            self._sample_records(),
            modo_meses="equivalente",
            escopo_equipe="mesma_equipe",
        )
        # Apenas Ana atuou tanto em Jan/2025 quanto em Jan/2026.
        self.assertEqual(mesma_equipe.tecnicos_comuns, 1)
        self.assertEqual(mesma_equipe.contratos_base, 2)
        self.assertEqual(mesma_equipe.contratos_comp, 3)
        self.assertEqual(mesma_equipe.os_base, 2)
        self.assertEqual(mesma_equipe.os_comp, 4)

    def test_fallback_automatico_quando_anos_nao_tem_meses_sobrepostos(self) -> None:
        # Simula cenário em que 2025 tem apenas Dezembro e 2026 tem Janeiro..Outubro.
        parcial = pd.DataFrame(
            [
                {
                    "technician": "Ana",
                    "reference_date": "2025-12-02",
                    "source_sheet": "Prod",
                    "contract": "CT-25",
                    "points": 50.0,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2026-10-02",
                    "source_sheet": "Prod",
                    "contract": "CT-26",
                    "points": 60.0,
                },
            ]
        )
        resumo = calcular_comparativo_anos(parcial, modo_meses="equivalente")
        self.assertTrue(resumo.fallback_sem_intersecao)
        self.assertEqual(resumo.modo_efetivo, "ano_completo")
        # Garante também que '2026-10-02' foi lido como Outubro (10), nunca Fevereiro (2)!
        self.assertEqual(resumo.meses_disponiveis_base, [12])
        self.assertEqual(resumo.meses_disponiveis_comp, [10])
        self.assertEqual(resumo.contratos_base, 1)
        self.assertEqual(resumo.contratos_comp, 1)


class Ingestao2025SubpastasENomesTests(unittest.TestCase):
    """Garante suporte aos nomes reais 'Produção <Mês> 25.xlsx' e subpastas no Drive."""

    def test_infer_date_from_filename_reconhece_mes_extenso_e_ignora_id_drive(
        self,
    ) -> None:
        casos = {
            "Produção Dezembro 25.xlsx": pd.Timestamp(2025, 12, 1),
            "Produção Janeiro 26 [1gZSKO0e5NMpWhdeMC8gTUUU8X6z8FfZ4].xlsx": pd.Timestamp(
                2026, 1, 1
            ),
            "Produção Março 2025 [25abc99].xlsx": pd.Timestamp(2025, 3, 1),
            "2025-07_relatorio.csv": pd.Timestamp(2025, 7, 1),
        }
        for nome, esperado in casos.items():
            with self.subTest(nome=nome):
                self.assertEqual(production.infer_date_from_filename(nome), esperado)

    def test_list_folder_files_percorre_subpastas_sem_incluir_pastas_como_arquivos(
        self,
    ) -> None:
        session = _FakeSession(
            [
                _FakeResponse(
                    data={
                        "files": [
                            {
                                "id": "sub-2025",
                                "name": "2025",
                                "mimeType": "application/vnd.google-apps.folder",
                            },
                            {
                                "id": "arq-2026",
                                "name": "Produção Janeiro 26.xlsx",
                                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            },
                        ]
                    }
                ),
                _FakeResponse(
                    data={
                        "files": [
                            {
                                "id": "arq-2025",
                                "name": "Produção Dezembro 25.xlsx",
                                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            }
                        ]
                    }
                ),
            ]
        )
        arquivos = drive_import.list_folder_files(session, "pasta-raiz")
        self.assertEqual([f["id"] for f in arquivos], ["arq-2026", "arq-2025"])


class SidebarVisualAndComparativoUiTests(unittest.TestCase):
    """Valida temas da sidebar, telemetria e navegação interativa do Comparativo 2025 x 2026."""

    def test_css_sidebar_substitui_todos_os_placeholders_nos_tres_temas(self) -> None:
        for tema in ("claro", "azul", "laranja"):
            with self.subTest(tema=tema):
                css = _css_tema(tema)
                self.assertNotIn("@@", css)
                for chave in _CSS_PLACEHOLDERS:
                    self.assertNotIn(f"@@{chave}@@", css)
                self.assertIn('[role="radiogroup"]', css)
                self.assertIn(".sidebar-pulse-card", css)

    def test_aba_comparativo_2025_2026_interativa_e_atalho_contratos(self) -> None:
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        self.assertFalse(app.exception)

        # Verifica que o pulso operacional é renderizado na sidebar.
        html_sb = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in app.get("html")
        )
        self.assertIn("sidebar-pulse-card", html_sb)

        # Abre o Comparativo 2025 x 2026 pela navegação da sidebar.
        app.radio(key="navigation").set_value("Comparativo 2025 x 2026").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertGreaterEqual(len(app.get("plotly_chart")), 5)

        html_comp = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in app.get("html")
        )
        self.assertIn("totale-delta-card", html_comp)
        self.assertIn("totale-delta-pct-spotlight", html_comp)
        self.assertIn("totale-delta-subpct", html_comp)
        self.assertIn("VARIAÇÃO %", html_comp)
        self.assertIn("Δ Produção Total (Pontos)", html_comp)
        self.assertIn("Δ Quantidade de O.S. (Prod)", html_comp)
        self.assertIn("Δ Contratos Distintos", html_comp)
        self.assertIn("Δ Pontos em Prod", html_comp)
        self.assertIn("Δ Pontos em Gpon", html_comp)

        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        self.assertTrue(
            any(
                "Contratos 2025" in t.columns and "O.S. 2026" in t.columns
                for t in tabelas
            )
        )
        self.assertTrue(
            any(
                "Baixar comparativo mensal 2025 x 2026" in str(cast("Any", item).label)
                for item in app.get("download_button")
            )
        )

        # Alterna escopo de colaboradores e modo temporal sem exceções.
        app.selectbox(key="comp_escopo_equipe").set_value("mesma_equipe").run(
            timeout=30
        )
        self.assertFalse(app.exception)
        app.selectbox(key="comp_modo_meses").set_value("ano_completo").run(timeout=30)
        self.assertFalse(app.exception)

        # Testa também o botão de atalho rápido na aba Contratos.
        app.radio(key="navigation").set_value("Contratos").run(timeout=30)
        self.assertFalse(app.exception)
        app.button(key="atalho_comp_contratos").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="navigation").value, "Comparativo 2025 x 2026")

    def test_render_sidebar_pulse_em_container_isolado(self) -> None:
        captured: list[str] = []

        class DummyContainer:
            def html(self, markup: str) -> None:
                captured.append(markup)

        render_sidebar_pulse(
            status_label="Drive Conectado",
            tipo="ok",
            escopo="jan/25 – out/26",
            metricas=[("Registros", "12.340"), ("Técnicos", "48")],
            fontes=("Produção", "Consultivo"),
            container=DummyContainer(),
            tema="azul",
        )
        self.assertEqual(len(captured), 1)
        self.assertIn("Drive Conectado", captured[0])
        self.assertIn("12.340", captured[0])
        self.assertIn("Produção", captured[0])

    def test_formatadores_e_render_delta_card_corporativo(self) -> None:
        self.assertEqual(formatar_delta_inteiro_br(1280, "O.S."), "+1.280 O.S.")
        self.assertEqual(formatar_delta_inteiro_br(-312, "ct"), "-312 ct")
        self.assertEqual(formatar_delta_inteiro_br(0, "un."), "0 un.")
        self.assertEqual(formatar_delta_decimal_br(14520.5, 2, "pts"), "+14.520,50 pts")
        self.assertEqual(formatar_delta_decimal_br(-0.14, 2, "x"), "-0,14 x")
        self.assertEqual(formatar_delta_decimal_br(0.0, 2, "pts"), "0,00 pts")
        self.assertEqual(formatar_variacao_pct_br(18.42), "+18,4%")
        self.assertEqual(formatar_variacao_pct_br(-6.25), "-6,2%")
        self.assertEqual(formatar_variacao_pct_br(None, atual=120, base=0), "Novo")
        self.assertEqual(formatar_variacao_pct_br(None, atual=0, base=0), "—")

        captured: list[str] = []

        class DummyContainer:
            def html(self, markup: str) -> None:
                captured.append(markup)

        render_delta_card(
            DummyContainer(),
            "Δ Produção Total <Pontos>",
            "+14.520,50 pts",
            valor_base="78.900,00",
            valor_atual="93.420,50",
            rotulo_base="2025",
            rotulo_atual="2026",
            variacao_pct="+18,4%",
            direcao="up",
            icone="⚡",
            detalhe="Prod: +11.200,00 · Gpon: +3.320,50",
            detalhe_pct="Média/mês: +18,4%",
            detalhe_pct_direcao="up",
            num_base=78900.0,
            num_atual=93420.5,
        )
        self.assertEqual(len(captured), 1)
        self.assertIn("totale-delta-card", captured[0])
        self.assertIn("totale-delta-pct-spotlight", captured[0])
        self.assertIn("totale-delta-subpct", captured[0])
        self.assertIn("VARIAÇÃO %", captured[0])
        self.assertIn("Média/mês: +18,4%", captured[0])
        self.assertIn("&lt;Pontos&gt;", captured[0])
        self.assertIn("+14.520,50 pts", captured[0])
        self.assertIn("+18,4%", captured[0])
        self.assertIn("78.900,00", captured[0])
        self.assertIn("93.420,50", captured[0])


if __name__ == "__main__":
    unittest.main()
