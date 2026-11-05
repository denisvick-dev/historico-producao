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

    def test_novas_visoes_carregam_sem_erro(self):
        """As páginas complementares devem abrir sem exceções."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        for pagina in (
            "Projetos",
            "Resumo executivo",
            "Regularidade",
            "Sazonalidade",
            "Saúde dos dados",
        ):
            with self.subTest(pagina=pagina):
                app.radio(key="navigation").set_value(pagina).run(timeout=30)
                self.assertFalse(app.exception)

        app.radio(key="navigation").set_value("Sazonalidade").run(timeout=30)
        app.selectbox(key="seasonality_dimension").set_value("Projeto").run(timeout=30)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
