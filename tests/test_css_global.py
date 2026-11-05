"""Testes para o CSS global e tipografia dos dataframes.

Valida que as funções de estilo retornam CSS não vazio e que as fontes
dos dataframes estão padronizadas na família Inter (--font-texto).
"""

from __future__ import annotations

import unittest

from components.css_global import (
    css_componentes_nativos,
    css_containers,
    css_global_completo,
    injetar_css_global,
    tamanho_css_global,
)


class CssGlobalTests(unittest.TestCase):
    """Verifica que o CSS global é gerado corretamente."""

    def test_css_componentes_nativos_nao_vazio(self):
        css = css_componentes_nativos()
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 1000)

    def test_css_containers_contem_dataframe(self):
        css = css_containers()
        self.assertIn("stDataFrame", css)
        self.assertIn("stTable", css)

    def test_dataframe_body_usa_inter(self):
        """O corpo dos dataframes deve usar --font-texto (Inter)."""
        css = css_containers()
        self.assertIn(
            "var(--font-texto, 'Inter', 'Segoe UI', Arial, sans-serif)",
            css,
        )

    def test_dataframes_usam_tema_visual_corporativo(self):
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

    def test_table_header_usa_inter(self):
        """O cabeçalho de stTable deve usar Inter (--font-texto), não Oscine/Manrope."""
        css = css_containers()
        self.assertIn(
            "var(--font-texto, 'Inter', 'Segoe UI', Arial, sans-serif) !important",
            css,
        )
        # Na linha do thead th, deve usar --font-texto, não --font-titulo
        linhas = css.splitlines()
        for i, linha in enumerate(linhas):
            if "thead th" in linha:
                # Verifica as próximas linhas até encontrar font-family
                bloco = "\n".join(linhas[i : i + 8])
                self.assertIn("var(--font-texto", bloco)
                self.assertNotIn("--font-titulo", bloco)
                self.assertNotIn("Oscine", bloco)
                self.assertNotIn("Manrope", bloco)
                break
        else:
            self.fail("Linha com 'thead th' não encontrada no CSS")

    def test_dataframe_header_usa_inter(self):
        """O cabeçalho de stDataFrame/stDataEditor deve usar Inter."""
        css = css_containers()
        self.assertIn(
            "var(--font-texto, 'Inter', 'Segoe UI', Arial, sans-serif) !important",
            css,
        )

    def test_css_global_completo_nao_vazio(self):
        css = css_global_completo()
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 5000)

    def test_tamanho_css_global(self):
        tamanho = tamanho_css_global()
        self.assertIsInstance(tamanho, int)
        self.assertGreater(tamanho, 1000)

    def test_injetar_css_global_retorna_css_na_primeira_chamada(self):
        # Limpa o estado da sessão para forçar nova injeção
        import streamlit as st

        if "_totale_css_global_versao" in st.session_state:
            del st.session_state["_totale_css_global_versao"]
        if "_totale_css_global_bytes" in st.session_state:
            del st.session_state["_totale_css_global_bytes"]

        css = injetar_css_global()
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 1000)

        # Segunda chamada deve retornar None (idempotente)
        css2 = injetar_css_global()
        self.assertIsNone(css2)


if __name__ == "__main__":
    unittest.main()
