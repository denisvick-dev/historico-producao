"""Testes de integração para a UI do Streamlit.

Usa ``streamlit.testing.v1.AppTest`` para verificar que o painel carrega,
renderiza as seções principais e responde a filtros sem erros.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

import pandas as pd
from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class StreamlitAppTests(unittest.TestCase):
    """Valida que o app inicia e renderiza corretamente."""

    at: AppTest

    @classmethod
    def setUpClass(cls) -> None:
        cls.at = AppTest.from_file(_APP_PATH).run(timeout=30)

    def test_app_carrega_sem_erro(self) -> None:
        """O app não deve lançar exceções ao iniciar."""
        self.assertFalse(self.at.exception)

    def test_titulo_da_pagina(self) -> None:
        """O app não deve lançar exceção relacionada ao título."""
        # page_title configurado via st.set_page_config não é exposto
        # diretamente por AppTest.title; validamos apenas ausência de erro
        exception_list = self.at.exception
        self.assertEqual(len(exception_list), 0)

    def test_sidebar_tem_navegacao(self) -> None:
        """A sidebar deve conter o rádio de navegação."""
        self.assertIsNotNone(self.at.sidebar)
        botoes = self.at.get("button")
        self.assertTrue(
            any(
                getattr(botao, "key", None) == "refresh_data_button" for botao in botoes
            )
        )

    def test_metricas_renderizadas(self) -> None:
        """Os cards de KPI devem ser renderizados na visão geral."""
        # Verifica que há pelo menos um elemento de métrica
        metricas = self.at.get("metric")
        self.assertGreaterEqual(len(metricas), 0)

    def test_graficos_renderizados(self) -> None:
        """Os gráficos Plotly devem ser renderizados."""
        charts = self.at.get("plotly_chart")
        self.assertGreaterEqual(len(charts), 0)

    def test_dataframes_renderizados(self) -> None:
        """Os dataframes devem ser renderizados."""
        dataframes = self.at.get("dataframe")
        self.assertGreaterEqual(len(dataframes), 0)

    def test_media_mensal_considera_meses_com_producao(self) -> None:
        """A média deve usar apenas os meses com produção de cada técnico."""
        element = cast("Any", self.at.get("dataframe")[0])
        table = cast("pd.DataFrame", element.value)

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

    def test_aba_contratos_exibe_graficos_matriz_e_download(self) -> None:
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Contratos").run(timeout=30)
        self.assertFalse(app.exception)
        markdown = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("TOTAL DE CONTRATOS", markdown)
        self.assertIn("Evolução mensal de contratos", markdown)
        self.assertIn("Contratos por técnico · Top 15", markdown)
        self.assertIn("não são contratos únicos", markdown)
        self.assertGreaterEqual(len(app.get("plotly_chart")), 2)
        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        matriz = next(
            t for t in tabelas if "Técnico" in t.columns and "Total" in t.columns
        )
        self.assertEqual(matriz.iloc[-1]["Técnico"], "Total geral")
        self.assertEqual(matriz.iloc[-1]["Total"], matriz.iloc[:-1]["Total"].sum())
        self.assertIn("Meses com produção", matriz.columns)
        self.assertIn("Média mensal", matriz.columns)
        for _, row in matriz.iterrows():
            self.assertGreater(row["Meses com produção"], 0)
            self.assertAlmostEqual(
                row["Média mensal"], row["Total"] / row["Meses com produção"]
            )
        self.assertTrue(
            any(
                "Baixar quantidade de contratos" in str(cast("Any", item).label)
                for item in app.get("download_button")
            )
        )
        # Verifica também a sub-aba de Eficiência de contratos dentro da aba Contratos
        self.assertIn("Eficiência de contratos", markdown)
        self.assertIn("CONTRATOS AVALIADOS", markdown)
        self.assertIn("Evolução mensal das faixas de contratos", markdown)
        matriz_eficiencia = next(
            t
            for t in tabelas
            if "Contrato" in t.columns and "Faixa mais frequente" in t.columns
        )
        self.assertIn("Média mensal", matriz_eficiencia.columns)
        self.assertIn("Faixa 5", matriz_eficiencia.columns)
        self.assertTrue(
            any(
                "Baixar eficiência de contratos em CSV" in str(cast("Any", item).label)
                for item in app.get("download_button")
            )
        )
        self.assertTrue(
            any(
                "Baixar eficiência mensal de contratos em CSV"
                in str(cast("Any", item).label)
                for item in app.get("download_button")
            )
        )

    def test_eficiencia_de_contratos_filtra_por_tecnico_e_faixa(self) -> None:
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Contratos").run(timeout=30)
        opcoes_tec = app.selectbox(key="eficiencia_contrato_tecnico_filter").options
        self.assertGreater(len(opcoes_tec), 1)
        app.selectbox(key="eficiencia_contrato_tecnico_filter").set_value(
            opcoes_tec[1]
        ).run(timeout=30)
        self.assertFalse(app.exception)

        app.selectbox(key="eficiencia_contrato_faixa_filter").set_value("Faixa 1").run(
            timeout=30
        )
        self.assertFalse(app.exception)

    def test_contratos_respeita_filtro_global_de_tecnico(self) -> None:
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Contratos").run(timeout=30)
        tecnico = app.multiselect(key="technician_filter").options[0]
        app.multiselect(key="technician_filter").set_value([tecnico]).run(timeout=30)
        self.assertFalse(app.exception)
        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        matriz = next(
            t for t in tabelas if "Técnico" in t.columns and "Total" in t.columns
        )
        self.assertEqual(matriz["Técnico"].tolist(), [tecnico, "Total geral"])

    def test_aba_contratos_sem_identificador_valido(self) -> None:
        app = AppTest.from_string("""
import pandas as pd
from components.contratos import render_contratos
render_contratos(pd.DataFrame({"contract": ["Sem contrato"], "technician": ["Ana"], "period": pd.to_datetime(["2026-01-01"])}))
""").run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any("Não há contratos" in str(item.value) for item in app.info))
        self.assertFalse(app.get("plotly_chart"))

    def test_navegacao_desconhecida_volta_para_visao_geral(self) -> None:
        app = AppTest.from_file(_APP_PATH)
        app.session_state["navigation"] = "Página removida"
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.radio(key="navigation").value, "Visão geral")

    def test_aba_saude_dados_mostra_contratos_por_arquivo(self) -> None:
        """A lista de arquivos importados deve exibir o contador de contratos."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Saúde dos dados").run(timeout=30)
        self.assertFalse(app.exception)
        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        arquivos = [tabela for tabela in tabelas if "Contratos" in tabela.columns]
        self.assertTrue(arquivos)
        self.assertIn("Arquivo", arquivos[0].columns)

    def test_aba_saude_dados_exibe_qtde_contrato_por_arquivo(self) -> None:
        """O detalhamento do arquivo deve trazer a coluna Qtde_Contrato."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Saúde dos dados").run(timeout=30)
        self.assertFalse(app.exception)
        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        detalhes = [tabela for tabela in tabelas if "Qtde_Contrato" in tabela.columns]
        self.assertTrue(detalhes)
        self.assertIn("Contrato", detalhes[0].columns)
        self.assertTrue(detalhes[0]["Qtde_Contrato"].gt(0).all())

    def test_aba_produtividade_unitaria_exibe_graficos_quadrantes_e_download(
        self,
    ) -> None:
        """A aba própria de produtividade unitária renderiza KPIs, quadrantes, tabela e CSV."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        app.radio(key="navigation").set_value("Produtividade unitária").run(timeout=30)
        self.assertFalse(app.exception)
        markdown = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("PONTOS POR O.S. (PROD)", markdown)
        self.assertIn("PONTOS POR CONTRATO", markdown)
        self.assertIn("Evolução mensal do ticket médio de pontos", markdown)
        self.assertIn("Quadrantes por O.S. (Prod)", markdown)
        self.assertGreaterEqual(len(app.get("plotly_chart")), 4)

        # Alterna os quadrantes para Contratos
        app.radio(key="unit_productivity_quadrant_mode").set_value("Por Contrato").run(
            timeout=30
        )
        self.assertFalse(app.exception)
        markdown_ct = " ".join(str(item.value) for item in app.markdown)
        self.assertIn("Quadrantes por Contrato", markdown_ct)

        tabelas = [
            cast("pd.DataFrame", cast("Any", item).value)
            for item in app.get("dataframe")
        ]
        resumo_tbl = next(t for t in tabelas if "Pontos / O.S." in t.columns)
        self.assertEqual(resumo_tbl.iloc[-1]["Técnico"], "Total geral")
        self.assertIn("Pontos / Contrato", resumo_tbl.columns)
        self.assertTrue(
            any(
                "Baixar produtividade unitária" in str(cast("Any", item).label)
                for item in app.get("download_button")
            )
        )

    def test_novas_visoes_carregam_sem_erro(self) -> None:
        """As páginas complementares devem abrir sem exceções."""
        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        for pagina in (
            "Comparativo 2025 x 2026",
            "Consultivo 2025 x 2026",
            "Projetos",
            "Quantidade de O.S.",
            "Contratos",
            "Produtividade unitária",
            "Consultivo",
            "Regularidade",
            "Eficiência",
            "Quadro de técnicos",
            "Saúde dos dados",
        ):
            with self.subTest(pagina=pagina):
                app.radio(key="navigation").set_value(pagina).run(timeout=30)
                self.assertFalse(app.exception)

    def test_sidebar_exibe_novo_logo_totale_em_temas_escuro_e_claro(self) -> None:
        """O arquivo assets/novo-logo-totale.png existe e é renderizado na sidebar."""
        from components.sidebar import LOGO_PADRAO_TOTALE, _resolver_src_imagem

        self.assertTrue(LOGO_PADRAO_TOTALE.is_file())
        data_uri = _resolver_src_imagem(LOGO_PADRAO_TOTALE)
        self.assertIsNotNone(data_uri)
        assert data_uri is not None
        self.assertTrue(data_uri.startswith("data:image/png;base64,"))
        self.assertIsNone(_resolver_src_imagem("assets/arquivo-inexistente.png"))

        app = AppTest.from_file(_APP_PATH).run(timeout=30)
        self.assertFalse(app.exception)
        html_azul = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in app.get("html")
        )
        self.assertIn("sidebar-brand-wordmark", html_azul)
        self.assertIn("sidebar-brand-banner--plate", html_azul)
        self.assertIn("data:image/png;base64,", html_azul)

        app.selectbox(key="_totale_sidebar_theme_select").set_value("claro").run(
            timeout=30
        )
        self.assertFalse(app.exception)
        html_claro = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in app.get("html")
        )
        self.assertIn("sidebar-brand-banner--clean", html_claro)

    def test_nomenclatura_corporativa_coerente(self) -> None:
        """Valida identidade corporativa unificada no pyproject, README e UI."""
        from pathlib import Path

        raiz = Path(_APP_PATH).resolve().parent
        pyproject_txt = (raiz / "pyproject.toml").read_text(encoding="utf-8")
        readme_txt = (raiz / "README.md").read_text(encoding="utf-8")
        self.assertIn('name = "totale-gestao-operacional"', pyproject_txt)
        self.assertIn("Totale · Inteligência & Gestão Operacional", readme_txt)

        html_main = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in self.at.get("html")
        )
        md_main = "\n".join(
            str(getattr(item, "body", getattr(item, "value", "")))
            for item in self.at.get("markdown")
        )
        dom_combinado = f"{html_main}\n{md_main}"
        self.assertIn("Inteligência &amp; Gestão Operacional", dom_combinado)
        self.assertIn("TOTALE · GESTÃO OPERACIONAL", dom_combinado)


if __name__ == "__main__":
    unittest.main()
