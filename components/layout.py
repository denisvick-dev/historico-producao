"""Componentes visuais e utilitários de apresentação."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from .styles import GLOBAL_CSS


def initials(name: str) -> str:
    parts = name.split()
    return "".join(part[0] for part in (parts[0], parts[-1])).upper()


def metric_card(label: str, value: str, note: str, symbol: str, note_class: str = "") -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-top"><span class="kpi-label">{label}</span><span class="kpi-dot">{symbol}</span></div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-note {note_class}">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_heading(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>',
        unsafe_allow_html=True,
    )


def csv_download(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def apply_styles() -> None:
    """Aplica uma única vez a identidade visual compartilhada."""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_sidebar() -> str:
    """Desenha a navegação e devolve a página escolhida."""
    with st.sidebar:
        st.markdown(
            """
            <div class="brand">
                <div class="brand-mark">T</div>
                <div><div class="brand-name">totale</div><div class="brand-sub">Gestão de produção</div></div>
            </div>
            <div class="nav-caption">ACOMPANHAMENTO</div>
            """,
            unsafe_allow_html=True,
        )
        navigation = st.radio(
            "Navegação",
            ["Visão geral", "Histórico", "Técnicos", "Importar dados"],
            label_visibility="collapsed",
            key="navigation",
        )
        st.divider()
        st.markdown(
            """
            <div class="sidebar-foot">
                <strong>Regra de consolidação</strong><br>
                Pontos Totais = Prod + Gpon<br><br>
                Os dados permanecem separados por origem e são consolidados nos relatórios.
            </div>
            """,
            unsafe_allow_html=True,
        )
    return navigation


def render_page_header(title: str, subtitle: str, stats: dict) -> None:
    title_col, meta_col = st.columns([3.4, 1])
    with title_col:
        st.markdown(
            f"<h1>{title}</h1><div class='page-subtitle'>{subtitle}</div>",
            unsafe_allow_html=True,
        )
    with meta_col:
        updated = "Sem importações"
        if stats["last_import"]:
            updated = pd.Timestamp(stats["last_import"]).strftime(
                "Atualizado em %d/%m/%Y<br>%H:%M"
            )
        st.markdown(
            f"<div class='header-meta'><strong>Base de produção</strong><br>{updated}</div>",
            unsafe_allow_html=True,
        )


def render_demo_banner() -> None:
    st.markdown(
        """
        <div class="demo-banner">
            <strong>Dados de demonstração.</strong> Explore o painel à vontade. Ao importar a primeira planilha real, esta base será substituída automaticamente.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state() -> None:
    st.markdown(
        """
        <div class="empty-state">
            <div class="empty-icon">↥</div>
            <h2>Comece importando sua produção</h2>
            <p>Envie os arquivos Excel com as abas Prod e Gpon. O sistema calculará os Pontos Totais e montará o histórico automaticamente.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    st.markdown(
        '<div class="footer">Totale · Histórico de produção &nbsp;•&nbsp; Pontos Totais = Prod + Gpon</div>',
        unsafe_allow_html=True,
    )
