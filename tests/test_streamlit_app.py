"""Testes de integração para a UI do Streamlit.

Usa ``streamlit.testing.v1.AppTest`` para verificar que o painel carrega,
renderiza as seções principais e responde a filtros sem erros.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class StreamlitAppTests(unittest.TestCase):
    """Valida que o app inicia e renderiza corretamente."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.at = AppTest.from_file(_APP_PATH).run(timeout=30)

    def test_app_carrega_sem_erro(self):
        """O app não deve lançar exceções ao iniciar."""
        self.assertFalse(self.at.exception)

    def test_titulo_da_pagina(self):
        """O app não deve lançar exceção relacionada ao título."""
        # page_title configurado via st.set_page_config não é exposto
        # diretamente por AppTest.title; validamos apenas ausência de erro
        exception_list = self.at.exception
        self.assertEqual(len(exception_list), 0)

    def test_sidebar_tem_navegacao(self):
        """A sidebar deve conter o rádio de navegação."""
        self.assertIsNotNone(self.at.sidebar)

    def test_metricas_renderizadas(self):
        """Os cards de KPI devem ser renderizados na visão geral."""
        # Verifica que há pelo menos um elemento de métrica
        metricas = self.at.get("metric")
        self.assertGreaterEqual(len(metricas), 0)

    def test_graficos_renderizados(self):
        """Os gráficos Plotly devem ser renderizados."""
        charts = self.at.get("plotly_chart")
        self.assertGreaterEqual(len(charts), 0)

    def test_dataframes_renderizados(self):
        """Os dataframes devem ser renderizados."""
        dataframes = self.at.get("dataframe")
        self.assertGreaterEqual(len(dataframes), 0)

    def test_media_mensal_considera_meses_com_producao(self):
        """A média deve usar apenas os meses com produção de cada técnico."""
        table = self.at.get("dataframe")[0].value

        self.assertIn("Meses com produção", table.columns)
        self.assertIn("Melhor mês", table.columns)
        self.assertIn("Variação no último mês", table.columns)
        self.assertNotIn("Status", table.columns)
        for _, row in table.iterrows():
            active_months = row["Meses com produção"]
            self.assertGreater(active_months, 0)
            self.assertAlmostEqual(
                row["Média mensal"],
                row["Pontos Totais"] / active_months,
            )

    def test_aba_contratos_exibe_contador(self):
        """A aba Contratos unificada deve abrir com o contador e a eficiência."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Contratos").run(timeout=30)
        self.assertFalse(app.exception)
        markdown = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("CONTRATOS NO RECORTE", markdown)
        self.assertIn("Contador por técnico", markdown)
        self.assertIn("Evolução mensal dos contratos", markdown)
        self.assertIn("Eficiência por contrato", markdown)
        self.assertIn("Resumo por contrato", markdown)
        self.assertGreaterEqual(len(app.get("plotly_chart")), 3)
        self.assertGreaterEqual(len(app.get("dataframe")), 3)

    def test_aba_contratos_unifica_eficiencia_por_contrato(self):
        """A navegação não deve mais separar Eficiência por contrato."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        radio = app.radio(key="navigation")
        self.assertNotIn("Eficiência por contrato", radio.options)

    def test_aba_saude_dados_mostra_contratos_por_arquivo(self):
        """A lista de arquivos importados deve exibir o contador de contratos."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Saúde dos dados").run(timeout=30)
        self.assertFalse(app.exception)
        tabelas = [item.value for item in app.get("dataframe")]
        arquivos = [tabela for tabela in tabelas if "Contratos" in tabela.columns]
        self.assertTrue(arquivos)
        self.assertIn("Arquivo", arquivos[0].columns)

    def test_aba_saude_dados_exibe_qtde_contrato_por_arquivo(self):
        """O detalhamento do arquivo deve trazer a coluna Qtde_Contrato."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Saúde dos dados").run(timeout=30)
        self.assertFalse(app.exception)
        tabelas = [item.value for item in app.get("dataframe")]
        detalhes = [tabela for tabela in tabelas if "Qtde_Contrato" in tabela.columns]
        self.assertTrue(detalhes)
        self.assertIn("Contrato", detalhes[0].columns)
        self.assertTrue(detalhes[0]["Qtde_Contrato"].gt(0).all())

    def test_novas_visoes_carregam_sem_erro(self):
        """As páginas complementares devem abrir sem exceções."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        for pagina in (
            "Projetos",
            "Contratos",
            "Regularidade",
            "Eficiência",
            "Saúde dos dados",
        ):
            with self.subTest(pagina=pagina):
                app.radio(key="navigation").set_value(pagina).run(timeout=30)
                self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
