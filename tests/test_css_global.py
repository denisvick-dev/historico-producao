"""Testes para o CSS global e tipografia dos dataframes.

Valida que as funções de estilo retornam CSS não vazio e que as fontes
dos dataframes estão padronizadas na família Inter (--font-texto).
"""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from components.css_global import (
    css_componentes_nativos,
    css_containers,
    css_global_completo,
    injetar_css_global,
    tamanho_css_global,
)


class CssGlobalTests(unittest.TestCase):
    """Verifica que o CSS global é gerado corretamente."""

    def test_css_componentes_nativos_nao_vazio(self) -> None:
        css = css_componentes_nativos()
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 1000)

    def test_css_containers_contem_dataframe(self) -> None:
        css = css_containers()
        self.assertIn("stDataFrame", css)
        self.assertIn("stTable", css)

    def test_dataframe_body_define_inter_na_fonte_do_canvas(self) -> None:
        """O texto do canvas do DataFrame usa Inter, não só o CSS da página."""
        css = css_containers()
        font_family = "'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
        self.assertIn(f"--gdg-font-family: {font_family}", css)
        self.assertIn(f"--gdg-base-font-style: 12px {font_family}", css)

    def test_tema_nativo_do_streamlit_define_inter(self) -> None:
        """O tema do Streamlit também seleciona Inter para componentes canvas."""
        config_path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
        with config_path.open("rb") as config_file:
            config = tomllib.load(config_file)
        font = config["theme"]["font"]
        self.assertIn("Inter:https://fonts.googleapis.com/css2?family=Inter", font)
        self.assertTrue(font.endswith(", sans-serif"))

    def test_dataframes_usam_tema_visual_corporativo(self) -> None:
        """Todas as grades herdam a paleta, tipografia, bordas e estados do tema."""
        css = css_containers()
        regras = (
            "--gdg-accent-color: var(--totale-laranja)",
            "--gdg-bg-cell: #FFFFFF",
            "--gdg-bg-cell-medium: #F8FAFC",
            "--gdg-bg-header: var(--totale-azul)",
            "--gdg-text-header: #FFFFFF",
            "--gdg-base-font-style: 12px",
            "--gdg-horizontal-border-color: #EDF1F7",
            'stDataFrame"]:hover',
            'stDataEditor"]',
            "tbody tr:nth-child(even)",
            "tbody tr:hover",
        )
        for regra in regras:
            with self.subTest(regra=regra):
                self.assertIn(regra, css)

    def test_table_header_usa_inter(self) -> None:
        """O cabeçalho de stTable deve usar a fonte Inter, não Oscine/Manrope."""
        css = css_containers()
        self.assertIn(
            "font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important",
            css,
        )
        # A regra do cabeçalho deve usar Inter, não a fonte de títulos.
        linhas = css.splitlines()
        for i, linha in enumerate(linhas):
            if "thead th" in linha:
                # Verifica as próximas linhas até encontrar font-family
                bloco = "\n".join(linhas[i : i + 8])
                self.assertIn("font-family: 'Inter'", bloco)
                self.assertNotIn("--font-titulo", bloco)
                self.assertNotIn("Oscine", bloco)
                self.assertNotIn("Manrope", bloco)
                break
        else:
            self.fail("Linha com 'thead th' não encontrada no CSS")

    def test_dataframe_header_usa_inter(self) -> None:
        """O cabeçalho de stDataFrame/stDataEditor deve usar Inter."""
        css = css_containers()
        self.assertIn(
            "font-family: 'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important",
            css,
        )

    def test_css_global_completo_nao_vazio(self) -> None:
        css = css_global_completo()
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 5000)

    def test_tamanho_css_global(self) -> None:
        tamanho = tamanho_css_global()
        self.assertIsInstance(tamanho, int)
        self.assertGreater(tamanho, 1000)

    def test_injetar_css_global_retorna_css_na_primeira_chamada(self) -> None:
        # Limpa o estado da sessão para forçar nova injeção
        import streamlit as st

        if "_totale_css_global_versao" in st.session_state:
            del st.session_state["_totale_css_global_versao"]
        if "_totale_css_global_bytes" in st.session_state:
            del st.session_state["_totale_css_global_bytes"]

        css = injetar_css_global()
        self.assertIsInstance(css, str)
        assert css is not None
        self.assertGreater(len(css), 1000)

        # Segunda chamada deve retornar None (idempotente)
        css2 = injetar_css_global()
        self.assertIsNone(css2)


if __name__ == "__main__":
    unittest.main()
