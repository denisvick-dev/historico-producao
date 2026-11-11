"""
sidebar.py
==========
Sidebar independente do Design System TOTALE para aplicações Streamlit.

Inclui os três temas (claro, azul e laranja), persistência de tema entre páginas,
seletor compatível com os controles BaseWeb/React Aria do Streamlit, marca,
seções, divisores, cartões de usuário e de status.

Uso básico:
    import streamlit as st
    from sidebar import aplicar_sidebar_corp, render_sidebar_brand
    from sidebar import render_sidebar_theme_selector, render_sidebar_section

    aplicar_sidebar_corp()  # preserva o tema salvo na sessão
    render_sidebar_brand(nome="TOTALE", subtitulo="Inteligência & Gestão Operacional")
    render_sidebar_theme_selector()
    render_sidebar_section("NAVEGAÇÃO")

Dependência: streamlit.
"""

from __future__ import annotations

import base64
import html as html_lib
import logging
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import streamlit as st

logger = logging.getLogger(__name__)

TemaSidebarType = Literal["claro", "azul", "laranja", "padrao"]
_FUSO_BR = ZoneInfo("America/Sao_Paulo")
_TEMAS_VALIDOS: tuple[str, ...] = ("claro", "azul", "laranja")
LOGO_PADRAO_TOTALE: Path = (
    Path(__file__).resolve().parent.parent / "assets" / "novo-logo-totale.png"
)
_MIMES_IMAGEM: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
_REGEX_DATA_URI_IMAGEM = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp|gif|svg\+xml);base64,[A-Za-z0-9+/=\s]+$"
)

# Tokens centralizados do sidebar. Os valores são deliberadamente opacos onde
# possível, para manter previsível a leitura dos controles e do menu.
_TEMAS: dict[str, dict[str, str]] = {
    "claro": {
        "fundo": "linear-gradient(180deg, #FFFFFF 0%, #F7FAFE 52%, #EDF3FA 100%)",
        "fundo_base": "#EDF3FA",
        "borda": "#D5DFEC",
        "texto_primario": "#0C2340",
        "texto_secundario": "#364B63",
        "texto_muted": "#52657D",
        "texto_acento": "#B45309",
        "icone": "#4B6079",
        "secao": "#475B73",
        "card_fundo": "rgba(255, 255, 255, 0.92)",
        "card_borda": "#D8E2EE",
        "rail_fundo": "rgba(241, 245, 251, 0.85)",
        "rail_borda": "#DCE5F0",
        "nav_ativo_fundo": "linear-gradient(135deg, #012869 0%, #0A439C 100%)",
        "nav_ativo_texto": "#FFFFFF",
        "nav_ativo_borda": "#012869",
        "nav_ativo_acento": "#F37C04",
        "nav_passivo_texto": "#253951",
        "nav_hover_texto": "#012869",
        "nav_hover_fundo": "#E4EEFA",
        "nav_hover_borda": "#C5D7EE",
        "botao_fundo": "#FFFFFF",
        "botao_texto": "#0C2340",
        "botao_hover_fundo": "#012869",
        "botao_hover_texto": "#FFFFFF",
        "cta_fundo": "linear-gradient(135deg, #012869 0%, #0A48AA 78%, #C2410C 155%)",
        "cta_texto": "#FFFFFF",
        "cta_borda": "#012869",
        "cta_hover_fundo": "linear-gradient(135deg, #011D4E 0%, #012869 65%, #EA580C 145%)",
        "input_fundo": "#FFFFFF",
        "input_texto": "#0C2340",
        "input_borda": "#8A9BB0",
        "numero_fundo": "#F1F5F9",
        "numero_borda": "#52657D",
        "input_focus": "#EA580C",
        "input_focus_ring": "rgba(234, 88, 12, 0.22)",
        "accent_topo": "linear-gradient(90deg, #012869 0%, #0A48AA 58%, #F37C04 100%)",
        "scrollbar": "#C4D1E0",
    },
    "azul": {
        "fundo": "linear-gradient(180deg, #051122 0%, #091D36 46%, #0E294B 100%)",
        "fundo_base": "#0E294B",
        "borda": "rgba(148, 184, 226, 0.16)",
        "texto_primario": "#F8FAFC",
        "texto_secundario": "#D5E1EE",
        "texto_muted": "#9EB4CC",
        "texto_acento": "#FDBA74",
        "icone": "#AFC5DC",
        "secao": "#9FB6CE",
        "card_fundo": "rgba(255, 255, 255, 0.055)",
        "card_borda": "rgba(191, 219, 254, 0.15)",
        "rail_fundo": "rgba(3, 12, 26, 0.34)",
        "rail_borda": "rgba(191, 219, 254, 0.11)",
        "nav_ativo_fundo": "linear-gradient(90deg, rgba(243, 124, 4, 0.22) 0%, rgba(10, 72, 170, 0.46) 48%, rgba(10, 72, 170, 0.18) 100%)",
        "nav_ativo_texto": "#FFFFFF",
        "nav_ativo_borda": "rgba(253, 186, 116, 0.32)",
        "nav_ativo_acento": "#FB923C",
        "nav_passivo_texto": "#D8E4F2",
        "nav_hover_texto": "#FFFFFF",
        "nav_hover_fundo": "rgba(255, 255, 255, 0.085)",
        "nav_hover_borda": "rgba(191, 219, 254, 0.18)",
        "botao_fundo": "rgba(255, 255, 255, 0.08)",
        "botao_texto": "#FFFFFF",
        "botao_hover_fundo": "#EA580C",
        "botao_hover_texto": "#FFFFFF",
        "cta_fundo": "linear-gradient(135deg, #F37C04 0%, #EA580C 62%, #C2410C 100%)",
        "cta_texto": "#FFFFFF",
        "cta_borda": "rgba(253, 186, 116, 0.42)",
        "cta_hover_fundo": "linear-gradient(135deg, #FB923C 0%, #F37C04 58%, #EA580C 100%)",
        "input_fundo": "rgba(255, 255, 255, 0.07)",
        "input_texto": "#FFFFFF",
        "input_borda": "rgba(203, 224, 248, 0.38)",
        "numero_fundo": "#112B4A",
        "numero_borda": "#AFC5DC",
        "input_focus": "#FDBA74",
        "input_focus_ring": "rgba(253, 186, 116, 0.28)",
        "accent_topo": "linear-gradient(90deg, #F37C04 0%, #FDBA74 52%, #38BDF8 100%)",
        "scrollbar": "rgba(255, 255, 255, 0.22)",
    },
    "laranja": {
        "fundo": "linear-gradient(180deg, #190904 0%, #2C1107 42%, #431B0B 76%, #56230F 100%)",
        "fundo_base": "#56230F",
        "borda": "rgba(255, 196, 150, 0.24)",
        "texto_primario": "#FFF9F3",
        "texto_secundario": "#FFE6CC",
        "texto_muted": "#F1C79F",
        "texto_acento": "#FFD09A",
        "icone": "#FFD1A3",
        "secao": "#FFD3A6",
        "card_fundo": "rgba(0, 0, 0, 0.22)",
        "card_borda": "rgba(255, 220, 185, 0.18)",
        "rail_fundo": "rgba(0, 0, 0, 0.20)",
        "rail_borda": "rgba(255, 220, 185, 0.14)",
        "nav_ativo_fundo": "linear-gradient(90deg, rgba(243, 124, 4, 0.42) 0%, rgba(243, 124, 4, 0.14) 100%)",
        "nav_ativo_texto": "#FFFFFF",
        "nav_ativo_borda": "rgba(255, 205, 157, 0.36)",
        "nav_ativo_acento": "#FFB067",
        "nav_passivo_texto": "#FFE4C7",
        "nav_hover_texto": "#FFFFFF",
        "nav_hover_fundo": "rgba(255, 255, 255, 0.09)",
        "nav_hover_borda": "rgba(255, 214, 175, 0.22)",
        "botao_fundo": "rgba(255, 255, 255, 0.10)",
        "botao_texto": "#FFFFFF",
        "botao_hover_fundo": "#012869",
        "botao_hover_texto": "#FFFFFF",
        "cta_fundo": "linear-gradient(135deg, #F37C04 0%, #D97706 100%)",
        "cta_texto": "#FFFFFF",
        "cta_borda": "rgba(255, 220, 185, 0.40)",
        "cta_hover_fundo": "linear-gradient(135deg, #FB923C 0%, #F37C04 100%)",
        "input_fundo": "rgba(0, 0, 0, 0.24)",
        "input_texto": "#FFFFFF",
        "input_borda": "rgba(255, 225, 196, 0.44)",
        "numero_fundo": "#56230F",
        "numero_borda": "#FFD09A",
        "input_focus": "#FFD09A",
        "input_focus_ring": "rgba(255, 208, 154, 0.28)",
        "accent_topo": "linear-gradient(90deg, #F37C04 0%, #FFD09A 60%, #FFF9F3 100%)",
        "scrollbar": "rgba(255, 255, 255, 0.24)",
    },
}

_CSS_SIDEBAR = r"""
<style>
[data-testid="stSidebar"] {
    --totale-sb-primary: @@TEXTO_PRIMARIO@@;
    --totale-sb-secondary: @@TEXTO_SECUNDARIO@@;
    --totale-sb-muted: @@TEXTO_MUTED@@;
    --totale-sb-accent-text: @@TEXTO_ACENTO@@;
    --totale-sb-icon: @@ICONE@@;
    --totale-sb-section: @@SECAO@@;
    --totale-sb-card: @@CARD_FUNDO@@;
    --totale-sb-card-border: @@CARD_BORDA@@;
    --totale-sb-rail-bg: @@RAIL_FUNDO@@;
    --totale-sb-rail-border: @@RAIL_BORDA@@;
    --totale-sb-nav-active-bg: @@NAV_ATIVO_FUNDO@@;
    --totale-sb-nav-active-text: @@NAV_ATIVO_TEXTO@@;
    --totale-sb-nav-active-border: @@NAV_ATIVO_BORDA@@;
    --totale-sb-nav-active-accent: @@NAV_ATIVO_ACENTO@@;
    --totale-sb-nav: @@NAV_PASSIVO_TEXTO@@;
    --totale-sb-nav-hover: @@NAV_HOVER_TEXTO@@;
    --totale-sb-nav-hover-bg: @@NAV_HOVER_FUNDO@@;
    --totale-sb-nav-hover-border: @@NAV_HOVER_BORDA@@;
    --totale-sb-button-bg: @@BOTAO_FUNDO@@;
    --totale-sb-button-text: @@BOTAO_TEXTO@@;
    --totale-sb-button-hover-bg: @@BOTAO_HOVER_FUNDO@@;
    --totale-sb-button-hover-text: @@BOTAO_HOVER_TEXTO@@;
    --totale-sb-cta-bg: @@CTA_FUNDO@@;
    --totale-sb-cta-text: @@CTA_TEXTO@@;
    --totale-sb-cta-border: @@CTA_BORDA@@;
    --totale-sb-cta-hover-bg: @@CTA_HOVER_FUNDO@@;
    --totale-sb-input-bg: @@INPUT_FUNDO@@;
    --totale-sb-input-text: @@INPUT_TEXTO@@;
    --totale-sb-input-border: @@INPUT_BORDA@@;
    --totale-sb-number-bg: @@NUMERO_FUNDO@@;
    --totale-sb-number-border: @@NUMERO_BORDA@@;
    --totale-sb-input-focus: @@INPUT_FOCUS@@;
    --totale-sb-input-focus-ring: @@INPUT_FOCUS_RING@@;
    position: relative;
    isolation: isolate;
    background: @@FUNDO@@ !important;
    border-right: 1px solid @@BORDA@@ !important;
    color: var(--totale-sb-secondary) !important;
    font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif !important;
    box-shadow: 10px 0 32px rgba(2, 12, 27, .12);
}
@media (min-width: 992px) {
    [data-testid="stSidebar"][aria-expanded="true"] {
        min-width: 276px !important;
        max-width: 304px !important;
    }
}
[data-testid="stSidebar"]::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0;
    height: 3.5px; z-index: 100; background: @@ACCENT_TOPO@@;
}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    padding-top: 12px;
    padding-bottom: 18px;
}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding-top: 0.35rem !important;
    padding-inline: 0.95rem !important;
}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
    gap: 0.45rem;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: var(--totale-sb-muted) !important;
    font-size: 10px !important;
    font-weight: 800 !important;
    letter-spacing: .09em !important;
    text-transform: uppercase !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] li,
[data-testid="stSidebar"] .stMarkdown { color: var(--totale-sb-secondary) !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 { color: var(--totale-sb-primary) !important; }
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {
    color: var(--totale-sb-muted) !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button:hover {
    background: var(--totale-sb-nav-hover-bg) !important;
    color: var(--totale-sb-primary) !important;
}

/* Navegação Streamlit: links passivos e item ativo, com acento estável de 3px. */
[data-testid="stSidebarNav"] { padding: 4px 2px 12px; }
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] {
    color: var(--totale-sb-section) !important; font-size: 10px !important;
    font-weight: 800 !important; letter-spacing: .11em !important;
    text-transform: uppercase !important; padding: 10px 12px 6px 14px !important;
}
[data-testid="stSidebarNav"] a {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    min-height: 40px !important;
    padding: 9px 11px !important;
    margin: 3px 0 !important;
    box-sizing: border-box !important;
    color: var(--totale-sb-nav) !important;
    font-size: 12.5px !important;
    line-height: 1.35 !important;
    font-weight: 560 !important;
    border-radius: 10px !important;
    border: 1px solid transparent !important;
    border-left: 3px solid transparent !important;
    text-decoration: none !important;
    transition: background .18s ease, color .18s ease, transform .18s ease, box-shadow .18s ease !important;
}
[data-testid="stSidebarNav"] a:not([aria-current="page"]):hover {
    background: var(--totale-sb-nav-hover-bg) !important;
    color: var(--totale-sb-nav-hover) !important;
    transform: translateX(2px);
}
[data-testid="stSidebarNav"] a:not([aria-current="page"]) span {
    color: var(--totale-sb-nav) !important;
    -webkit-text-fill-color: var(--totale-sb-nav) !important;
}
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: var(--totale-sb-nav-active-bg) !important;
    color: var(--totale-sb-nav-active-text) !important; font-weight: 700 !important;
    border: 1px solid var(--totale-sb-nav-active-border) !important;
    border-left: 3px solid var(--totale-sb-nav-active-accent) !important;
    box-shadow: 0 5px 14px rgba(0, 0, 0, .16), inset 0 1px 0 rgba(255, 255, 255, .08) !important;
    transform: translateX(1px);
}
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebarNav"] a[aria-current="page"] * {
    color: var(--totale-sb-nav-active-text) !important;
    -webkit-text-fill-color: var(--totale-sb-nav-active-text) !important;
}

/* Links do menu customizado (st.page_link): mesma hierarquia do menu nativo. */
[data-testid="stSidebar"] [data-testid="stPageLink"] > a {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    min-height: 38px !important;
    padding: 8px 10px !important;
    margin: 2px 0 !important;
    box-sizing: border-box !important;
    color: var(--totale-sb-nav) !important;
    font-size: 12.5px !important;
    line-height: 1.35 !important;
    font-weight: 560 !important;
    border-radius: 9px !important;
    border: 1px solid transparent !important;
    border-left: 3px solid transparent !important;
    text-decoration: none !important;
    transition: background .18s ease, color .18s ease, transform .18s ease, box-shadow .18s ease !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] > a:not([aria-current="page"]):hover {
    background: var(--totale-sb-nav-hover-bg) !important;
    color: var(--totale-sb-nav-hover) !important;
    transform: translateX(2px);
}
[data-testid="stSidebar"] [data-testid="stPageLink"] > a[aria-current="page"] {
    background: var(--totale-sb-nav-active-bg) !important;
    color: var(--totale-sb-nav-active-text) !important;
    font-weight: 700 !important;
    border: 1px solid var(--totale-sb-nav-active-border) !important;
    border-left: 3px solid var(--totale-sb-nav-active-accent) !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, .13) !important;
}
[data-testid="stSidebar"] [data-testid="stPageLink"] > a[aria-current="page"],
[data-testid="stSidebar"] [data-testid="stPageLink"] > a[aria-current="page"] * {
    color: var(--totale-sb-nav-active-text) !important;
    -webkit-text-fill-color: var(--totale-sb-nav-active-text) !important;
}

/* Compatibilidade BaseWeb e React Aria nas versões recentes do Streamlit. */
[data-testid="stSidebar"] div[data-baseweb="select"] > div,
[data-testid="stSidebar"] input:not([type="checkbox"]):not([type="radio"]),
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"] {
    background: var(--totale-sb-input-bg) !important;
    border: 1px solid var(--totale-sb-input-border) !important;
    color: var(--totale-sb-input-text) !important; border-radius: 10px !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, .06) !important;
    transition: border-color .15s ease, box-shadow .15s ease, background .15s ease !important;
}
/* Number input: os controles de incremento também acompanham a paleta ativa. */
[data-testid="stSidebar"] [data-testid="stNumberInput"] div[data-baseweb="input"],
[data-testid="stSidebar"] [data-testid="stNumberInput"] div[data-baseweb="input"] > div {
    background-color: var(--totale-sb-number-bg) !important;
    border: 1px solid var(--totale-sb-number-border) !important;
    border-radius: 9px !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] > div,
[data-testid="stSidebar"] [data-testid="stNumberInput"] [data-baseweb="input"] > div {
    background-color: var(--totale-sb-number-bg) !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] input[type="number"] {
    background-color: var(--totale-sb-number-bg) !important;
    color: var(--totale-sb-input-text) !important;
    -webkit-text-fill-color: var(--totale-sb-input-text) !important;
    caret-color: var(--totale-sb-input-focus) !important;
    font-weight: 700 !important;
    opacity: 1 !important;
    border: 0 !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button,
[data-testid="stSidebar"] [data-testid="stNumberInput"] [role="button"] {
    width: 1.5rem !important;
    min-width: 1.5rem !important;
    flex: 0 0 1.5rem !important;
    padding-inline: 0 !important;
    color: var(--totale-sb-input-text) !important;
    -webkit-text-fill-color: var(--totale-sb-input-text) !important;
    background-color: var(--totale-sb-number-bg) !important;
    border-color: var(--totale-sb-number-border) !important;
    opacity: 1 !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button *,
[data-testid="stSidebar"] [data-testid="stNumberInput"] [role="button"] * {
    color: var(--totale-sb-input-text) !important;
    fill: var(--totale-sb-input-text) !important;
    stroke: var(--totale-sb-input-text) !important;
}
[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover,
[data-testid="stSidebar"] [data-testid="stNumberInput"] [role="button"]:hover {
    background: var(--totale-sb-button-hover-bg) !important;
    color: var(--totale-sb-button-hover-text) !important;
}
/* Selectbox mantém texto/ícone legíveis nos markups BaseWeb e React Aria. */
[data-testid="stSidebar"] [data-testid="stSelectbox"] div[data-baseweb="select"] > div {
    background: var(--totale-sb-input-bg) !important;
    border-color: var(--totale-sb-input-border) !important;
}
[data-testid="stSidebar"] div[data-baseweb="select"] span,
[data-testid="stSidebar"] [data-testid="stSelectbox"] input[role="combobox"],
[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"] input[role="combobox"] {
    color: var(--totale-sb-input-text) !important;
    -webkit-text-fill-color: var(--totale-sb-input-text) !important;
}
[data-testid="stSidebar"] div[data-baseweb="select"] svg,
[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"] svg {
    fill: var(--totale-sb-icon) !important; color: var(--totale-sb-icon) !important;
}
[data-testid="stSidebar"] div[data-baseweb="select"] > div:focus-within,
[data-testid="stSidebar"] input:not([type="checkbox"]):not([type="radio"]):focus,
[data-testid="stSidebar"] textarea:focus,
[data-testid="stSidebar"] [data-testid="stSelectbox"] [role="group"]:focus-within {
    border-color: var(--totale-sb-input-focus) !important;
    box-shadow: 0 0 0 2px var(--totale-sb-input-focus-ring) !important;
    outline: none !important;
}
[data-testid="stSidebar"] label[data-baseweb="checkbox"] span,
[data-testid="stSidebar"] label[data-baseweb="radio"] span { color: var(--totale-sb-secondary) !important; }
[data-testid="stSidebar"] label[data-baseweb="checkbox"] [data-baseweb="checkbox--checkmark"],
[data-testid="stSidebar"] label[data-baseweb="radio"] [data-baseweb="radio--circle"] {
    border-color: var(--totale-sb-icon) !important;
}

/* Menu por st.radio (shell raiz): trilha unificada, ícones alinhados e estado ativo nítido em todos os temas. */
[data-testid="stSidebar"] [role="radiogroup"] {
    display: flex !important;
    flex-direction: column !important;
    gap: 3px !important;
    padding: 5px !important;
    border-radius: 13px !important;
    background: var(--totale-sb-rail-bg) !important;
    border: 1px solid var(--totale-sb-rail-border) !important;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .04) !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label {
    position: relative !important;
    display: flex !important;
    align-items: center !important;
    justify-content: flex-start !important;
    width: 100% !important;
    min-height: 37px !important;
    margin: 0 !important;
    padding: 0.48rem 1.55rem 0.48rem 0.72rem !important;
    box-sizing: border-box !important;
    border-radius: 9px !important;
    background: transparent !important;
    border: 1px solid transparent !important;
    border-left: 3px solid transparent !important;
    cursor: pointer !important;
    transition: background .16s ease, border-color .16s ease, transform .16s ease, box-shadow .16s ease !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
    display: none !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label p,
[data-testid="stSidebar"] [role="radiogroup"] label span {
    margin: 0 !important;
    font-size: 12.5px !important;
    font-weight: 600 !important;
    letter-spacing: .005em !important;
    line-height: 1.28 !important;
    color: var(--totale-sb-nav) !important;
    -webkit-text-fill-color: var(--totale-sb-nav) !important;
    transition: color .16s ease !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:not(:has(input:checked)):hover {
    background: var(--totale-sb-nav-hover-bg) !important;
    border-color: var(--totale-sb-nav-hover-border) !important;
    border-left-color: var(--totale-sb-nav-active-accent) !important;
    transform: translateX(2px);
}
[data-testid="stSidebar"] [role="radiogroup"] label:not(:has(input:checked)):hover p,
[data-testid="stSidebar"] [role="radiogroup"] label:not(:has(input:checked)):hover span {
    color: var(--totale-sb-nav-hover) !important;
    -webkit-text-fill-color: var(--totale-sb-nav-hover) !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: var(--totale-sb-nav-active-bg) !important;
    border: 1px solid var(--totale-sb-nav-active-border) !important;
    border-left: 3.5px solid var(--totale-sb-nav-active-accent) !important;
    box-shadow: 0 6px 16px rgba(0, 0, 0, .18), inset 0 1px 0 rgba(255, 255, 255, .10) !important;
    transform: translateX(1px);
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p,
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) span {
    color: var(--totale-sb-nav-active-text) !important;
    -webkit-text-fill-color: var(--totale-sb-nav-active-text) !important;
    font-weight: 740 !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked)::after {
    content: "";
    position: absolute;
    right: 10px;
    top: 50%;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    transform: translateY(-50%);
    background: var(--totale-sb-nav-active-accent);
    box-shadow: 0 0 8px var(--totale-sb-nav-active-accent);
}

[data-testid="stSidebar"] [data-testid="stButton"] > button,
[data-testid="stSidebar"] [data-testid="stDownloadButton"] > button {
    background: var(--totale-sb-button-bg) !important;
    color: var(--totale-sb-button-text) !important;
    border: 1px solid var(--totale-sb-card-border) !important;
    border-radius: 10px !important; min-height: 2.4rem !important;
    font-size: 12.5px !important; letter-spacing: .01em !important;
    font-weight: 680 !important; box-shadow: 0 2px 6px rgba(2, 12, 27, .08) !important;
    transition: background .16s ease, color .16s ease, border-color .16s ease, transform .16s ease, box-shadow .16s ease !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:hover,
[data-testid="stSidebar"] [data-testid="stDownloadButton"] > button:hover {
    background: var(--totale-sb-button-hover-bg) !important;
    color: var(--totale-sb-button-hover-text) !important;
    border-color: var(--totale-sb-button-hover-bg) !important;
    transform: translateY(-1px);
    box-shadow: 0 6px 14px rgba(2, 12, 27, .16) !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] {
    background: var(--totale-sb-cta-bg) !important;
    color: var(--totale-sb-cta-text) !important;
    -webkit-text-fill-color: var(--totale-sb-cta-text) !important;
    border: 1px solid var(--totale-sb-cta-border) !important;
    box-shadow: 0 6px 16px rgba(243, 124, 4, .22), inset 0 1px 0 rgba(255, 255, 255, .18) !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] p,
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] span {
    color: var(--totale-sb-cta-text) !important;
    -webkit-text-fill-color: var(--totale-sb-cta-text) !important;
    font-weight: 740 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"]:hover {
    background: var(--totale-sb-cta-hover-bg) !important;
    border-color: var(--totale-sb-nav-active-accent) !important;
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(243, 124, 4, .30) !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] > button:disabled {
    opacity: .58 !important; cursor: not-allowed !important; box-shadow: none !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] details {
    background: var(--totale-sb-card) !important;
    border: 1px solid var(--totale-sb-card-border) !important;
    border-radius: 10px !important;
    overflow: hidden;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {
    color: var(--totale-sb-primary) !important;
    background: var(--totale-sb-card) !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
    background: var(--totale-sb-nav-hover-bg) !important;
}
[data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    background: var(--totale-sb-input-focus) !important;
    border-color: var(--totale-sb-input-focus) !important;
    box-shadow: 0 1px 5px var(--totale-sb-input-focus-ring) !important;
}
[data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] div[style*="width"] {
    background: var(--totale-sb-input-focus) !important;
}
[data-testid="stSidebar"] [data-testid="stSlider"] [data-baseweb="slider"] div[role="presentation"] {
    background: var(--totale-sb-input-border);
}
/* O dropzone e o botão de upload usam os mesmos tokens de input/ação. */
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
    background: var(--totale-sb-input-bg) !important;
    border: 1.5px dashed var(--totale-sb-input-border) !important;
    border-radius: 10px !important;
    color: var(--totale-sb-input-text) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--totale-sb-input-focus) !important;
    background: var(--totale-sb-nav-hover-bg) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
    color: var(--totale-sb-button-text) !important;
    background: var(--totale-sb-button-bg) !important;
    border: 1px solid var(--totale-sb-input-border) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
    color: var(--totale-sb-button-hover-text) !important;
    background: var(--totale-sb-button-hover-bg) !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] {
    background: var(--totale-sb-card) !important;
    border-color: var(--totale-sb-card-border) !important;
    color: var(--totale-sb-secondary) !important;
}
[data-testid="stSidebar"] hr { border-color: var(--totale-sb-card-border) !important; }
[data-testid="stSidebar"] *::-webkit-scrollbar { width: 8px; height: 8px; }
[data-testid="stSidebar"] *::-webkit-scrollbar-track { background: transparent; }
[data-testid="stSidebar"] *::-webkit-scrollbar-thumb {
    background: @@SCROLLBAR@@; border-radius: 99px;
}
[data-testid="stSidebar"] *::-webkit-scrollbar-thumb:hover { background: var(--totale-sb-nav-active-accent); }
[data-testid="stSidebar"]:focus-within *:focus-visible {
    outline: 2px solid var(--totale-sb-input-focus) !important; outline-offset: 2px;
}
.sidebar-brand {
    position: relative; isolation: isolate; overflow: hidden;
    padding: 13px 13px 11px; margin: 2px 0 10px;
    border: 1px solid var(--totale-sb-card-border);
    border-radius: 15px; background: var(--totale-sb-card);
    box-shadow: 0 8px 22px rgba(2, 12, 27, .12);
    backdrop-filter: blur(8px);
}
.sidebar-brand::before {
    content: ""; position: absolute; inset: 0 0 auto; height: 3px;
    background: @@ACCENT_TOPO@@;
}
.sidebar-brand::after {
    content: ""; position: absolute; z-index: 0; width: 128px; height: 128px;
    right: -52px; top: -64px; border-radius: 50%;
    background: radial-gradient(circle, rgba(243, 124, 4, .18), transparent 68%);
}
.sidebar-brand > * { position: relative; z-index: 1; }
.sidebar-brand-row { display: flex; align-items: center; gap: 11px; min-width: 0; }
.sidebar-brand-copy { min-width: 0; }
.sidebar-brand-mark, .sidebar-brand-logo {
    display: inline-flex; align-items: center; justify-content: center;
    flex: 0 0 40px; width: 40px; height: 40px;
    border-radius: 12px; object-fit: cover;
}
.sidebar-brand-mark {
    color: #FFFFFF; font-size: 19px; line-height: 1;
    background: linear-gradient(145deg, #012869 5%, #0A48AA 72%, #C2410C 145%);
    border: 1px solid rgba(255, 255, 255, .22);
    box-shadow: 0 5px 12px rgba(1, 40, 105, .22);
}
.sidebar-brand-logo { border: 1px solid var(--totale-sb-card-border); }
.sidebar-brand-name {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font-size: 17px; font-weight: 820; letter-spacing: -.035em;
    margin: 0; line-height: 1.12; color: var(--totale-sb-primary);
}
.sidebar-brand-sub {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: var(--totale-sb-secondary); font-size: 10.5px;
    line-height: 1.4; margin-top: 4px;
}
.sidebar-brand-banner {
    display: flex; align-items: center; justify-content: center;
    width: 100%; border-radius: 11px; padding: 8px 12px;
    box-sizing: border-box;
}
.sidebar-brand-banner--plate {
    background: linear-gradient(180deg, #FFFFFF 0%, #F4F7FC 100%);
    border: 1px solid rgba(255, 255, 255, .65);
    box-shadow: 0 4px 14px rgba(2, 12, 27, .22);
}
.sidebar-brand-banner--clean {
    background: #FFFFFF;
    border: 1px solid #E6EDF5;
    padding: 7px 10px;
}
.sidebar-brand-wordmark {
    display: block; width: 100%; max-width: 172px;
    height: auto; max-height: 52px; object-fit: contain;
}
.sidebar-brand-banner-meta {
    display: flex; align-items: center; justify-content: center;
    gap: 6px; margin-top: 9px; text-align: center;
}
.sidebar-brand-banner-meta .sidebar-brand-sub {
    margin-top: 0;
}
.sidebar-brand-banner-dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--totale-sb-nav-active-accent);
    box-shadow: 0 0 8px var(--totale-sb-nav-active-accent);
    flex: 0 0 6px;
}
.sidebar-section-header {
    margin: 13px 0 5px; padding: 2px 0 4px 11px; position: relative;
}
.sidebar-section-header::before {
    content: ""; position: absolute; left: 0; top: 3px; width: 3px; height: 13px;
    border-radius: 99px; background: var(--totale-sb-nav-active-accent);
    box-shadow: 0 0 10px color-mix(in srgb, var(--totale-sb-nav-active-accent) 36%, transparent);
}
.sidebar-pulse-card {
    position: relative; overflow: hidden;
    margin: 0 0 10px; padding: 10px 11px 9px;
    border-radius: 13px;
    background: var(--totale-sb-card);
    border: 1px solid var(--totale-sb-card-border);
    box-shadow: 0 6px 16px rgba(2, 12, 27, .09);
}
.sidebar-pulse-top {
    display: flex; align-items: center; justify-content: space-between;
    gap: 6px; margin-bottom: 8px;
}
.sidebar-pulse-grid {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
}
.sidebar-pulse-cell {
    padding: 6px 8px; border-radius: 9px;
    background: var(--totale-sb-rail-bg);
    border: 1px solid var(--totale-sb-rail-border);
    min-width: 0;
}
.sidebar-pulse-k {
    font-size: 9px; font-weight: 750; letter-spacing: .07em;
    text-transform: uppercase; color: var(--totale-sb-muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sidebar-pulse-v {
    margin-top: 2px; font-size: 12px; font-weight: 800;
    color: var(--totale-sb-primary);
    font-variant-numeric: tabular-nums;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sidebar-pulse-chips {
    display: flex; flex-wrap: wrap; gap: 4px;
    margin-top: 8px; padding-top: 7px;
    border-top: 1px solid var(--totale-sb-card-border);
}
.sidebar-pulse-chip {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 7px; border-radius: 999px;
    background: var(--totale-sb-rail-bg);
    border: 1px solid var(--totale-sb-rail-border);
    font-size: 9.5px; font-weight: 680;
    color: var(--totale-sb-secondary);
}
.sidebar-profile-card, .sidebar-status-card {
    position: relative; overflow: hidden;
    border: 1px solid var(--totale-sb-card-border);
    border-radius: 14px; background: var(--totale-sb-card);
    box-shadow: 0 6px 18px rgba(15, 23, 42, .07);
    transition: transform .18s ease, box-shadow .18s ease;
}
.sidebar-profile-card:hover, .sidebar-status-card:hover {
    transform: translateY(-1px);
    box-shadow: 0 9px 22px rgba(15, 23, 42, .11);
}
.sidebar-footer {
    margin-top: 14px; padding: 12px 12px 9px;
    border: 1px solid var(--totale-sb-card-border);
    border-radius: 14px; background: var(--totale-sb-card);
    box-shadow: 0 5px 16px rgba(15, 23, 42, .05);
}
@media (prefers-reduced-motion: reduce) {
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] *::before,
    [data-testid="stSidebar"] *::after { transition: none !important; animation: none !important; }
}
</style>
"""

_CSS_PLACEHOLDERS: dict[str, str] = {
    "FUNDO": "fundo",
    "BORDA": "borda",
    "TEXTO_PRIMARIO": "texto_primario",
    "TEXTO_SECUNDARIO": "texto_secundario",
    "TEXTO_MUTED": "texto_muted",
    "TEXTO_ACENTO": "texto_acento",
    "ICONE": "icone",
    "SECAO": "secao",
    "CARD_FUNDO": "card_fundo",
    "CARD_BORDA": "card_borda",
    "RAIL_FUNDO": "rail_fundo",
    "RAIL_BORDA": "rail_borda",
    "NAV_ATIVO_FUNDO": "nav_ativo_fundo",
    "NAV_ATIVO_TEXTO": "nav_ativo_texto",
    "NAV_ATIVO_BORDA": "nav_ativo_borda",
    "NAV_ATIVO_ACENTO": "nav_ativo_acento",
    "NAV_PASSIVO_TEXTO": "nav_passivo_texto",
    "NAV_HOVER_TEXTO": "nav_hover_texto",
    "NAV_HOVER_FUNDO": "nav_hover_fundo",
    "NAV_HOVER_BORDA": "nav_hover_borda",
    "BOTAO_FUNDO": "botao_fundo",
    "BOTAO_TEXTO": "botao_texto",
    "BOTAO_HOVER_FUNDO": "botao_hover_fundo",
    "BOTAO_HOVER_TEXTO": "botao_hover_texto",
    "CTA_FUNDO": "cta_fundo",
    "CTA_TEXTO": "cta_texto",
    "CTA_BORDA": "cta_borda",
    "CTA_HOVER_FUNDO": "cta_hover_fundo",
    "INPUT_FUNDO": "input_fundo",
    "INPUT_TEXTO": "input_texto",
    "INPUT_BORDA": "input_borda",
    "NUMERO_FUNDO": "numero_fundo",
    "NUMERO_BORDA": "numero_borda",
    "INPUT_FOCUS": "input_focus",
    "INPUT_FOCUS_RING": "input_focus_ring",
    "ACCENT_TOPO": "accent_topo",
    "SCROLLBAR": "scrollbar",
}


def _escapar(valor: Any) -> str:
    """Escapa valores antes de inseri-los em HTML."""
    if valor is None:
        return ""
    return html_lib.escape(str(valor), quote=True)


def _agora_br() -> datetime:
    return datetime.now(_FUSO_BR)


def normalizar_tema_sidebar(tema: Any) -> TemaSidebarType:
    """Normaliza o nome do tema. O alias legado ``padrao`` equivale a ``claro``."""
    valor = str(getattr(tema, "value", tema) or "").strip().lower()
    if valor == "padrao":
        valor = "claro"
    return valor if valor in _TEMAS_VALIDOS else "claro"  # type: ignore[return-value]


def _obter_tema_sidebar(tema_param: Any = None) -> TemaSidebarType:
    if tema_param is not None:
        return normalizar_tema_sidebar(tema_param)
    # O estado canônico é escrito pelo callback do selectbox, evitando que a
    # chamada de estilo no começo de uma página reverta a escolha do usuário.
    for chave in (
        "_totale_sidebar_theme",
        "_totale_sidebar_theme_select",
        "seletor_cor_sidebar",
        "tema_sidebar",
    ):
        valor = st.session_state.get(chave)
        if valor:
            return normalizar_tema_sidebar(valor)
    return "claro"


def definir_tema_sidebar(tema: TemaSidebarType | str) -> None:
    """Persiste o tema ativo e tenta sincronizar a chave padrão do seletor."""
    tema_norm = normalizar_tema_sidebar(tema)
    st.session_state["_totale_sidebar_theme"] = tema_norm
    chave_widget = "_totale_sidebar_theme_select"
    if st.session_state.get(chave_widget) != tema_norm:
        try:
            st.session_state[chave_widget] = tema_norm
        except Exception:
            # O Streamlit proíbe alterar uma chave de widget depois que o widget
            # foi instanciado na execução atual; a próxima execução sincroniza.
            logger.debug("Seletor de tema sincronizado na próxima execução.")


def _render_html(markup: str, container: Any = None) -> None:
    """Renderiza HTML usando st.html quando disponível e markdown como fallback."""
    if not markup:
        return
    destino = container if container is not None else st
    limpo = markup.strip()
    html_fn = getattr(destino, "html", None)
    if callable(html_fn):
        try:
            html_fn(limpo)
            return
        except Exception:
            logger.debug(
                "st.html falhou; usando markdown com HTML permitido.", exc_info=True
            )
    try:
        destino.markdown(limpo, unsafe_allow_html=True)
    except Exception:
        logger.exception("Não foi possível renderizar o componente HTML da sidebar.")


def _css_tema(tema: TemaSidebarType | str) -> str:
    tokens = _TEMAS[normalizar_tema_sidebar(tema)]
    css = _CSS_SIDEBAR
    for placeholder, chave in _CSS_PLACEHOLDERS.items():
        css = css.replace(f"@@{placeholder}@@", tokens[chave])
    return css


def aplicar_estilo(tema_sidebar: TemaSidebarType | str | None = None) -> None:
    """Aplica apenas o CSS do sidebar, mantendo o tema da sessão se omitido."""
    tema = _obter_tema_sidebar(tema_sidebar)
    definir_tema_sidebar(tema)
    _render_html(_css_tema(tema), st)
    st.session_state["_totale_sidebar_css_tema"] = tema


def aplicar_estilo_corp(tema_sidebar: TemaSidebarType | str | None = None) -> None:
    """Alias compatível com o Design System corporativo."""
    aplicar_estilo(tema_sidebar=tema_sidebar)


def aplicar_sidebar_corp(tema: TemaSidebarType | str | None = None) -> None:
    """Aplica um tema explícito ou reaplica o tema atual da sessão."""
    aplicar_estilo(tema_sidebar=tema)


def _callback_tema_sidebar(chave: str) -> None:
    escolha = st.session_state.get(chave)
    if escolha:
        st.session_state["_totale_sidebar_theme"] = normalizar_tema_sidebar(escolha)


def render_sidebar_theme_selector(
    label: str = "TEMA DA SIDEBAR",
    help: str = "",
    container: Any = None,
    key: str = "_totale_sidebar_theme_select",
    mostrar_icone: bool = True,
    aplicar_automaticamente: bool = True,
) -> TemaSidebarType:
    """Renderiza o seletor de tema e persiste a escolha na sessão Streamlit."""
    alvo = container if container is not None else st.sidebar
    opcoes: list[TemaSidebarType] = ["claro", "azul", "laranja"]
    nomes = {
        "claro": "☀️ Claro Corporativo" if mostrar_icone else "Claro Corporativo",
        "azul": "🔷 Deep Executive Navy" if mostrar_icone else "Deep Executive Navy",
        "laranja": "🔶 Terracotta & Amber" if mostrar_icone else "Terracotta & Amber",
    }
    tema_atual = _obter_tema_sidebar()
    kwargs: dict[str, Any] = {
        "format_func": lambda valor: nomes.get(valor, str(valor).title()),
        "key": key,
        "on_change": _callback_tema_sidebar,
        "args": (key,),
    }
    if help:
        kwargs["help"] = help
    if key not in st.session_state:
        kwargs["index"] = opcoes.index(tema_atual)
    elif normalizar_tema_sidebar(st.session_state.get(key)) not in opcoes:
        # Corrige valores antigos/inválidos antes da criação do widget.
        st.session_state[key] = tema_atual

    escolha = alvo.selectbox(label, options=opcoes, **kwargs)
    tema_escolhido = normalizar_tema_sidebar(escolha)
    definir_tema_sidebar(tema_escolhido)
    if aplicar_automaticamente:
        aplicar_estilo(tema_sidebar=tema_escolhido)
    return tema_escolhido


def render_page_sidebar_theme_selector() -> TemaSidebarType:
    """Renderiza o seletor somente quando a página não usa o shell raiz."""
    if st.session_state.get("_totale_root_navigation_shell", False):
        return _obter_tema_sidebar()
    return render_sidebar_theme_selector()


def carregar_layout_corporativo(
    tema_sidebar: TemaSidebarType | str | None = None,
    renderizar_sidebar: bool = False,
    nome: str = "TOTALE",
    subtitulo: str = "Portal de Produção & Performance",
    versao: str = "",
) -> None:
    """Atalho para aplicar o tema e, opcionalmente, desenhar marca e seletor."""
    tema_ativo = _obter_tema_sidebar(tema_sidebar)
    aplicar_estilo(tema_sidebar=tema_ativo)
    if renderizar_sidebar:
        logo_padrao = LOGO_PADRAO_TOTALE if LOGO_PADRAO_TOTALE.is_file() else None
        render_sidebar_brand(
            nome=nome,
            subtitulo=subtitulo,
            versao=versao,
            logo=logo_padrao,
            logo_banner=logo_padrao is not None,
        )
        render_sidebar_theme_selector()


def _url_valida(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(str(url))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=16)
def _carregar_data_uri_arquivo(caminho_str: str, mtime_ns: int) -> str | None:
    del mtime_ns
    caminho = Path(caminho_str)
    mime = _MIMES_IMAGEM.get(caminho.suffix.lower())
    if not mime:
        return None
    try:
        conteudo = caminho.read_bytes()
    except OSError:
        logger.warning("Não foi possível ler o logotipo em %s.", caminho_str)
        return None
    codificado = base64.b64encode(conteudo).decode("ascii")
    return f"data:{mime};base64,{codificado}"


def _resolver_src_imagem(origem: str | Path | None) -> str | None:
    """Resolve URL HTTP(S), data URI segura ou arquivo de imagem local."""
    if origem is None:
        return None
    texto = str(origem).strip()
    if not texto:
        return None
    if _url_valida(texto):
        return texto
    if texto.startswith("data:image/") and _REGEX_DATA_URI_IMAGEM.fullmatch(texto):
        return texto
    try:
        caminho = Path(origem)
        if caminho.is_file() and caminho.suffix.lower() in _MIMES_IMAGEM:
            resolvido = caminho.resolve()
            return _carregar_data_uri_arquivo(
                str(resolvido), resolvido.stat().st_mtime_ns
            )
    except OSError:
        return None
    return None


def render_sidebar_brand(
    nome: str = "TOTALE",
    subtitulo: str = "Analytics & Intelligence",
    versao: str = "",
    logo_url: str | Path | None = None,
    icone: str = "⚡",
    titulo: str = "",
    logo: str | Path | None = None,
    logo_banner: bool = False,
    tema: TemaSidebarType | str | None = None,
    **kwargs: Any,
) -> None:
    """Mostra marca, subtítulo, ícone/logotipo e badge de versão no sidebar."""
    nome_final = str(titulo or nome or "").strip()
    subtitulo_final = str(kwargs.get("segmento", subtitulo) or "").strip()
    versao_final = str(versao or "").strip()
    logo_final = logo if logo is not None else logo_url
    tema_ativo = _obter_tema_sidebar(tema)
    if not nome_final and not subtitulo_final and not logo_final:
        return

    logo_src = _resolver_src_imagem(logo_final)

    if tema_ativo == "azul":
        cor_nome, fundo_badge, cor_badge, borda_badge = (
            "#FFFFFF",
            "rgba(255,255,255,.12)",
            "#FDBA74",
            "rgba(255,255,255,.20)",
        )
        estilo_nome = "background:linear-gradient(100deg,#FFFFFF 20%,#FDBA74 100%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;"
    elif tema_ativo == "laranja":
        cor_nome, fundo_badge, cor_badge, borda_badge = (
            "#FFFFFF",
            "rgba(255,255,255,.16)",
            "#FFFFFF",
            "rgba(255,255,255,.28)",
        )
        estilo_nome = ""
    else:
        cor_nome, fundo_badge, cor_badge, borda_badge = (
            "#011E52",
            "#E8EEF8",
            "#011E52",
            "#D6E0F0",
        )
        estilo_nome = "background:linear-gradient(100deg,#012869 10%,#0A48AA 62%,#F37C04 140%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;"

    badge = ""
    if versao_final:
        badge_txt = (
            versao_final if versao_final.lower().startswith("v") else f"v{versao_final}"
        )
        badge = (
            f'<span style="display:inline-flex;margin-top:8px;padding:4px 9px;border-radius:999px;'
            f"background:{fundo_badge};color:{cor_badge};border:1px solid {borda_badge};"
            f'font-size:10px;font-weight:750;letter-spacing:.04em;">{_escapar(badge_txt)}</span>'
        )

    if logo_src and logo_banner:
        classe_banner = (
            "sidebar-brand-banner--clean"
            if tema_ativo == "claro"
            else "sidebar-brand-banner--plate"
        )
        subtitulo_banner = (
            '<div class="sidebar-brand-banner-meta">'
            '<span class="sidebar-brand-banner-dot" aria-hidden="true"></span>'
            f'<span class="sidebar-brand-sub">{_escapar(subtitulo_final)}</span>'
            "</div>"
            if subtitulo_final
            else ""
        )
        badge_wrap = f'<div style="text-align:center;">{badge}</div>' if badge else ""
        markup = (
            f'<div class="sidebar-brand"><div class="sidebar-brand-banner {classe_banner}">'
            f'<img class="sidebar-brand-wordmark" src="{_escapar(logo_src)}" '
            f'alt="{_escapar(nome_final or "Logotipo")}" loading="eager">'
            f"</div>{subtitulo_banner}{badge_wrap}</div>"
        )
        _render_html(markup, st.sidebar)
        return

    if logo_src:
        marca_visual = (
            f'<img class="sidebar-brand-logo" src="{_escapar(logo_src)}" '
            f'alt="{_escapar(nome_final or "Logotipo")}" loading="lazy">'
        )
    else:
        marca_visual = f'<span class="sidebar-brand-mark" aria-hidden="true">{_escapar(icone or "⚡")}</span>'
    nome_html = (
        f'<h2 class="sidebar-brand-name" style="color:{cor_nome};{estilo_nome}">'
        f"{_escapar(nome_final)}</h2>"
        if nome_final
        else ""
    )
    subtitulo_html = (
        f'<div class="sidebar-brand-sub">{_escapar(subtitulo_final)}</div>'
        if subtitulo_final
        else ""
    )
    markup = (
        '<div class="sidebar-brand"><div class="sidebar-brand-row">'
        f'{marca_visual}<div class="sidebar-brand-copy">{nome_html}{subtitulo_html}</div>'
        f"</div>{badge}</div>"
    )
    _render_html(markup, st.sidebar)


def render_sidebar_section(
    titulo: str,
    icone: str = "",
    collapsible: bool = False,
    tema: TemaSidebarType | str | None = None,
) -> None:
    """Renderiza o título de uma seção da sidebar."""
    if not str(titulo or "").strip():
        return
    if collapsible:
        with st.sidebar.expander(f"{icone} {titulo}".strip(), expanded=True):
            pass
        return

    tema_ativo = _obter_tema_sidebar(tema)
    tokens = _TEMAS[tema_ativo]
    icone_html = (
        f'<span aria-hidden="true" style="font-size:14px;color:{tokens["texto_acento"]};">'
        f"{_escapar(icone)}</span>"
        if icone
        else ""
    )
    markup = (
        '<div class="sidebar-section-header">'
        '<div style="display:flex;align-items:center;gap:7px;min-width:0;'
        f"font-size:11px;font-weight:750;color:{tokens['secao']};"
        f'text-transform:uppercase;letter-spacing:.08em;">{icone_html}'
        f"<span>{_escapar(titulo)}</span></div></div>"
    )
    _render_html(markup, st.sidebar)


def _cor_css_segura(cor: str, padrao: str) -> str:
    valor = str(cor or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", valor):
        return valor
    if re.fullmatch(r"rgba?\([\d\s.,%+-]+\)", valor):
        return valor
    nomes = {"white", "black", "transparent", "currentColor"}
    if valor in nomes:
        return valor
    return padrao


def render_sidebar_divider(
    estilo: Literal["linha", "gradiente", "pontilhado", "espaco"] = "gradiente",
    espacamento: Literal["pequeno", "medio", "grande"] = "medio",
    cor: str = "",
    label: str = "",
    tema: TemaSidebarType | str | None = None,
) -> None:
    """Renderiza divisor, linha rotulada ou espaço vertical."""
    margens = {"pequeno": "6px 0", "medio": "14px 0", "grande": "24px 0"}
    margem = margens.get(espacamento, margens["medio"])
    tema_ativo = _obter_tema_sidebar(tema)
    if tema_ativo == "claro":
        cor_default = "#CBD5E1"
        gradiente = "border:none;height:1px;background:linear-gradient(90deg,transparent 0%,#01286955 40%,#F37C04 70%,transparent 100%);"
        label_color = "#011E52"
    elif tema_ativo == "azul":
        cor_default = "rgba(255,255,255,.16)"
        gradiente = "border:none;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.32),transparent);"
        label_color = "#FDBA74"
    else:
        cor_default = "rgba(255,255,255,.22)"
        gradiente = "border:none;height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.42),transparent);"
        label_color = "#FFFFFF"
    cor_final = _cor_css_segura(cor, cor_default)

    if estilo == "espaco":
        alturas = {"pequeno": "8px", "medio": "16px", "grande": "28px"}
        _render_html(
            f'<div aria-hidden="true" style="height:{alturas.get(espacamento, "16px")};"></div>',
            st.sidebar,
        )
        return
    if estilo == "pontilhado":
        linha = f"border:none;border-top:1.5px dashed {cor_final};"
    elif estilo == "gradiente":
        linha = gradiente
    else:
        linha = f"border:none;border-top:1px solid {cor_final};"

    if label:
        markup = (
            f'<div style="display:flex;align-items:center;gap:10px;margin:{margem};">'
            f'<div style="flex:1;{linha}"></div>'
            f'<span style="font-size:9px;font-weight:750;color:{label_color};'
            f'text-transform:uppercase;letter-spacing:.12em;">{_escapar(label)}</span>'
            f'<div style="flex:1;{linha}"></div></div>'
        )
    else:
        markup = f'<div style="margin:{margem};{linha}"></div>'
    _render_html(markup, st.sidebar)


def render_sidebar_footer_info(
    itens: dict[str, Any] | list[tuple[str, Any]] | None = None,
    copyright: str = "",
    empresa: str = "TOTALE",
    ano: int | None = None,
    versao: str = "",
    ambiente: str = "",
    unidade: str = "",
    mostrar_relógio: bool = False,
    tema: TemaSidebarType | str | None = None,
    **kwargs: Any,
) -> None:
    """Renderiza versão, ambiente, metadados, relógio opcional e copyright."""
    mostrar_relogio = mostrar_relógio or bool(kwargs.get("mostrar_relogio", False))
    try:
        itens_dict = dict(itens) if itens is not None else {}
    except (TypeError, ValueError):
        itens_dict = {}
    agora = _agora_br()
    ano_final = ano if ano is not None else agora.year
    tema_ativo = _obter_tema_sidebar(tema)
    tokens = _TEMAS[tema_ativo]

    badges: list[str] = []
    if versao:
        versao_txt = str(versao)
        if not versao_txt.lower().startswith("v"):
            versao_txt = f"v{versao_txt}"
        badges.append(
            f'<span style="padding:3px 8px;border-radius:999px;background:{tokens["card_fundo"]};'
            f'color:{tokens["texto_acento"]};font-size:10px;font-weight:750;">{_escapar(versao_txt)}</span>'
        )
    if ambiente:
        amb_key = str(ambiente).strip().lower()
        amb_cfg = {
            "produção": ("#ECFDF5", "#065F46", "#059669"),
            "producao": ("#ECFDF5", "#065F46", "#059669"),
            "prod": ("#ECFDF5", "#065F46", "#059669"),
            "homologação": ("#FFFBEB", "#92400E", "#D97706"),
            "homologacao": ("#FFFBEB", "#92400E", "#D97706"),
            "hml": ("#FFFBEB", "#92400E", "#D97706"),
            "desenvolvimento": ("#EFF6FF", "#1E40AF", "#3B82F6"),
            "dev": ("#EFF6FF", "#1E40AF", "#3B82F6"),
            "local": ("#F3F4F6", "#374151", "#9CA3AF"),
        }
        bg, fg, dot = amb_cfg.get(
            amb_key, (tokens["card_fundo"], tokens["texto_secundario"], tokens["icone"])
        )
        badges.append(
            f'<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;'
            f'border-radius:999px;background:{bg};color:{fg};font-size:10px;font-weight:750;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{dot};"></span>'
            f"{_escapar(ambiente)}</span>"
        )

    badges_html = (
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">{"".join(badges)}</div>'
        if badges
        else ""
    )
    unidade_html = (
        f'<div style="font-size:11px;font-weight:650;color:{tokens["texto_secundario"]};'
        f'margin-bottom:8px;border-left:3px solid #F37C04;padding-left:8px;">'
        f"{_escapar(unidade)}</div>"
        if unidade
        else ""
    )
    linhas = "".join(
        '<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0;">'
        f'<span style="font-size:11px;color:{tokens["texto_muted"]};">{_escapar(chave)}</span>'
        f'<span style="font-size:11px;color:{tokens["texto_primario"]};font-weight:750;">{_escapar(valor)}</span></div>'
        for chave, valor in itens_dict.items()
    )
    itens_html = (
        f'<div style="border-top:1px solid {tokens["card_borda"]};padding-top:8px;">{linhas}</div>'
        if linhas
        else ""
    )
    relogio_html = (
        f'<div style="font-size:10px;color:{tokens["texto_muted"]};text-align:center;margin-top:8px;">'
        f"{agora.strftime('%d/%m/%Y %H:%M')}</div>"
        if mostrar_relogio
        else ""
    )
    copy_final = copyright or f"© {ano_final} {empresa}"
    markup = (
        f'<div class="sidebar-footer">{badges_html}{unidade_html}{itens_html}{relogio_html}'
        f'<div style="margin-top:10px;padding-top:8px;border-top:1px solid {tokens["card_borda"]};'
        f'font-size:10px;color:{tokens["texto_muted"]};text-align:center;">{_escapar(copy_final)}</div></div>'
    )
    _render_html(markup, st.sidebar)


def render_sidebar_info(
    user_name: str = "",
    role: str = "",
    email: str = "",
    avatar: str = "",
    itens: dict[str, Any] | list[tuple[str, Any]] | None = None,
    icone: str = "ℹ️",
    rodape: str = "",
    status: Literal["online", "offline", "ausente", "ocupado", ""] = "online",
    titulo: str = "",
    tema: TemaSidebarType | str | None = None,
) -> None:
    """Renderiza cartão opcional de usuário, dados complementares e presença."""
    try:
        itens_dict = dict(itens) if itens is not None else {}
    except (TypeError, ValueError):
        itens_dict = {}
    tema_ativo = _obter_tema_sidebar(tema)
    tokens = _TEMAS[tema_ativo]

    status_cfg = {
        "online": ("#059669", "Online"),
        "offline": ("#94A3B8", "Offline"),
        "ausente": ("#D97706", "Ausente"),
        "ocupado": ("#DC2626", "Ocupado"),
    }
    if avatar and _url_valida(avatar):
        avatar_html = (
            f'<img src="{_escapar(avatar)}" alt="" '
            'style="width:40px;height:40px;border-radius:12px;object-fit:cover;flex:none;">'
        )
    else:
        if avatar:
            iniciais = str(avatar).strip()[:2].upper()
        elif user_name.strip():
            partes = user_name.strip().split()
            iniciais = (
                (partes[0][0] + partes[-1][0]).upper()
                if len(partes) > 1
                else partes[0][0].upper()
            )
        else:
            iniciais = "U"
        avatar_html = (
            f'<div aria-hidden="true" style="width:40px;height:40px;border-radius:12px;display:flex;'
            f'align-items:center;justify-content:center;background:#012869;color:#fff;font-weight:800;flex:none;">'
            f"{_escapar(iniciais)}</div>"
        )

    status_html = ""
    if status and status in status_cfg:
        cor_status, label_status = status_cfg[status]
        status_html = (
            f'<span style="display:inline-flex;align-items:center;gap:5px;margin-top:3px;'
            f'font-size:10px;font-weight:750;color:{cor_status};">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{cor_status};"></span>'
            f"{label_status}</span>"
        )
    user_html = ""
    if user_name or role or email or avatar:
        user_html = (
            '<div style="display:flex;align-items:center;gap:12px;">'
            f'{avatar_html}<div style="min-width:0;">'
            f'<p class="sidebar-user-name" style="margin:0;font-size:13px;font-weight:750;color:{tokens["texto_primario"]};">{_escapar(user_name)}</p>'
            f'<p class="sidebar-user-role" style="margin:2px 0 0;font-size:11px;color:{tokens["texto_acento"]};font-weight:650;">{_escapar(role)}</p>'
            f'<p class="sidebar-user-email" style="margin:2px 0 0;font-size:11px;color:{tokens["texto_muted"]};overflow-wrap:anywhere;">{_escapar(email)}</p>'
            f"{status_html}</div></div>"
        )
    linhas = "".join(
        '<div style="display:flex;justify-content:space-between;gap:8px;padding:4px 0;">'
        f'<span style="font-size:11px;color:{tokens["texto_muted"]};">{_escapar(chave)}</span>'
        f'<span style="font-size:11px;color:{tokens["texto_primario"]};font-weight:750;">{_escapar(valor)}</span></div>'
        for chave, valor in itens_dict.items()
    )
    itens_html = f'<div style="margin-top:8px;">{linhas}</div>' if linhas else ""
    rodape_html = (
        f'<div style="margin-top:8px;font-size:10px;color:{tokens["texto_muted"]};">{_escapar(rodape)}</div>'
        if rodape
        else ""
    )
    titulo_html = (
        f'<div class="sidebar-section-header"><span style="font-size:11px;font-weight:750;'
        f'color:{tokens["secao"]};text-transform:uppercase;letter-spacing:.08em;">'
        f"{_escapar(titulo)}</span></div>"
        if titulo
        else ""
    )
    if not any((user_html, itens_html, rodape_html, titulo_html)):
        return
    markup = (
        f'{titulo_html}<div class="sidebar-profile-card" role="region" '
        f'aria-label="{_escapar(titulo or user_name or "Informações do usuário")}" '
        f'style="background:{tokens["card_fundo"]};border:1px solid {tokens["card_borda"]};'
        f'border-radius:14px;padding:14px;margin:8px 0 12px;">'
        f"{user_html}{itens_html}{rodape_html}</div>"
    )
    _render_html(markup, st.sidebar)


def formatar_datetime_exibicao(valor: Any, com_segundos: bool = False) -> str:
    """Formata datas para exibição, aceitando datetime, Timestamp e texto."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        formato = "%d/%m/%Y %H:%M:%S" if com_segundos else "%d/%m/%Y %H:%M"
        return valor.strftime(formato)
    try:
        import pandas as pd

        ts = pd.Timestamp(valor)
        if pd.isna(ts):
            return str(valor)
        formato = "%d/%m/%Y %H:%M:%S" if com_segundos else "%d/%m/%Y %H:%M"
        return ts.strftime(formato)
    except (TypeError, ValueError, OverflowError, ImportError):
        return str(valor)


def render_sidebar_status(
    status: str = "Ativo",
    label: str = "STATUS DO SISTEMA",
    ultima_atualizacao: Any = "",
    total_registros: int | str | None = None,
    detalhes: dict[str, Any] | None = None,
    tipo: Literal["ok", "info", "alerta", "critico"] = "ok",
    compacto: bool = False,
    container: Any = None,
    tema: TemaSidebarType | str | None = None,
    nav_contrast: str | None = None,
    **kwargs: Any,
) -> None:
    """Renderiza badge compacto ou cartão detalhado de status do sistema."""
    if nav_contrast is None and "cor_nav_contrast" in kwargs:
        nav_contrast = kwargs.get("cor_nav_contrast")
    if nav_contrast:
        cor_nav = _cor_css_segura(nav_contrast, "#FFFFFF")
        _render_html(
            '<style>[data-testid="stSidebarNav"] a[aria-current="page"],'
            '[data-testid="stSidebarNav"] a[aria-current="page"] * {'
            f"color:{cor_nav} !important;-webkit-text-fill-color:{cor_nav} !important;}}</style>",
            st,
        )

    tema_ativo = _obter_tema_sidebar(tema)
    tokens = _TEMAS[tema_ativo]
    cfg = {
        "ok": ("#047857", "#ECFDF5", "#A7F3D0", "#065F46"),
        "info": ("#1D4ED8", "#EFF6FF", "#BFDBFE", "#1E3A8A"),
        "alerta": ("#D97706", "#FFFBEB", "#FDE68A", "#92400E"),
        "critico": ("#DC2626", "#FEF2F2", "#FECACA", "#991B1B"),
    }
    cor, bg, borda, texto = cfg.get(tipo, cfg["ok"])
    pill = (
        f'<span style="display:inline-flex;align-items:center;gap:5px;padding:3px 8px;'
        f"border-radius:999px;background:{bg};color:{texto};border:1px solid {borda};"
        f'font-size:10px;font-weight:750;white-space:nowrap;">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{cor};"></span>'
        f"{_escapar(status)}</span>"
    )
    destino = container if container is not None else st.sidebar
    if compacto or kwargs.get("badge_only", False):
        _render_html(f'<div style="margin:6px 0;">{pill}</div>', destino)
        return

    detalhes_html = "".join(
        '<div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0;">'
        f'<span style="font-size:11px;color:{tokens["texto_muted"]};">{_escapar(chave)}</span>'
        f'<span style="font-size:11px;color:{tokens["texto_primario"]};font-weight:750;">{_escapar(valor)}</span></div>'
        for chave, valor in (detalhes or {}).items()
    )
    ultima_fmt = (
        formatar_datetime_exibicao(ultima_atualizacao) if ultima_atualizacao else ""
    )
    data_html = (
        f'<div style="font-size:10px;color:{tokens["texto_muted"]};margin-top:6px;">'
        f"Atualizado {_escapar(ultima_fmt)}</div>"
        if ultima_fmt
        else ""
    )
    total_html = (
        f'<div style="font-size:12px;color:{tokens["texto_secundario"]};margin-top:5px;">'
        f'Registros <strong style="color:{tokens["texto_primario"]};">{_escapar(total_registros)}</strong></div>'
        if total_registros is not None
        else ""
    )
    markup = (
        f'<div class="sidebar-status-card" role="status" aria-label="{_escapar(label)}" '
        f'style="background:{tokens["card_fundo"]};border:1px solid {tokens["card_borda"]};'
        f'border-radius:14px;padding:13px 14px;margin:10px 0 14px;box-shadow:inset 3px 0 0 {cor};">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">'
        f'<span style="font-size:10px;font-weight:800;letter-spacing:.08em;color:{tokens["texto_muted"]};">'
        f"{_escapar(label.strip().upper())}</span>{pill}</div>{total_html}{detalhes_html}{data_html}</div>"
    )
    _render_html(markup, destino)


def render_sidebar_pulse(
    status_label: str = "Operacional",
    tipo: Literal["ok", "info", "alerta", "critico"] = "ok",
    escopo: str = "",
    metricas: list[tuple[str, Any]] | dict[str, Any] | None = None,
    fontes: list[str] | tuple[str, ...] | None = None,
    container: Any = None,
    tema: TemaSidebarType | str | None = None,
) -> None:
    """Renderiza painel compacto de telemetria operacional no topo da sidebar."""
    tema_ativo = _obter_tema_sidebar(tema)
    tokens = _TEMAS[tema_ativo]
    cfg = {
        "ok": (
            "#10B981",
            "rgba(16, 185, 129, 0.16)",
            "rgba(16, 185, 129, 0.34)",
            "#34D399",
        ),
        "info": (
            "#3B82F6",
            "rgba(59, 130, 246, 0.16)",
            "rgba(59, 130, 246, 0.34)",
            "#93C5FD",
        ),
        "alerta": (
            "#F59E0B",
            "rgba(245, 158, 11, 0.16)",
            "rgba(245, 158, 11, 0.36)",
            "#FCD34D",
        ),
        "critico": (
            "#EF4444",
            "rgba(239, 68, 68, 0.16)",
            "rgba(239, 68, 68, 0.36)",
            "#FCA5A5",
        ),
    }
    if tema_ativo == "claro":
        cfg = {
            "ok": ("#059669", "#ECFDF5", "#A7F3D0", "#065F46"),
            "info": ("#1D4ED8", "#EFF6FF", "#BFDBFE", "#1E3A8A"),
            "alerta": ("#D97706", "#FFFBEB", "#FDE68A", "#92400E"),
            "critico": ("#DC2626", "#FEF2F2", "#FECACA", "#991B1B"),
        }
    dot_cor, pill_bg, pill_borda, pill_txt = cfg.get(tipo, cfg["ok"])
    pill_html = (
        f'<span style="display:inline-flex;align-items:center;gap:5px;padding:2px 8px;'
        f"border-radius:999px;background:{pill_bg};color:{pill_txt};border:1px solid {pill_borda};"
        f'font-size:9.5px;font-weight:750;letter-spacing:.03em;white-space:nowrap;">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{dot_cor};'
        f'box-shadow:0 0 6px {dot_cor};"></span>{_escapar(status_label)}</span>'
    )
    escopo_html = (
        f'<span style="font-size:9.5px;font-weight:750;letter-spacing:.05em;'
        f'color:{tokens["texto_acento"]};white-space:nowrap;">{_escapar(escopo)}</span>'
        if escopo
        else ""
    )

    pares = (
        list(metricas.items()) if isinstance(metricas, dict) else list(metricas or [])
    )
    celulas_html = "".join(
        f'<div class="sidebar-pulse-cell">'
        f'<div class="sidebar-pulse-k">{_escapar(chave)}</div>'
        f'<div class="sidebar-pulse-v">{_escapar(valor)}</div>'
        f"</div>"
        for chave, valor in pares[:4]
    )
    grid_html = (
        f'<div class="sidebar-pulse-grid">{celulas_html}</div>' if celulas_html else ""
    )

    chips_html = ""
    if fontes:
        itens_chip = "".join(
            f'<span class="sidebar-pulse-chip">{_escapar(fonte)}</span>'
            for fonte in fontes
            if str(fonte).strip()
        )
        if itens_chip:
            chips_html = f'<div class="sidebar-pulse-chips">{itens_chip}</div>'

    markup = (
        f'<div class="sidebar-pulse-card" role="region" aria-label="Resumo operacional">'
        f'<div class="sidebar-pulse-top">{pill_html}{escopo_html}</div>'
        f"{grid_html}{chips_html}</div>"
    )
    destino = container if container is not None else st.sidebar
    _render_html(markup, destino)


def render_sidebar_spacer(
    altura: Literal["pequeno", "medio", "grande", "xgrande"] | int | str = "medio",
) -> None:
    """Adiciona espaço vertical controlado na sidebar."""
    presets = {"pequeno": "8px", "medio": "16px", "grande": "28px", "xgrande": "48px"}
    if isinstance(altura, int):
        altura_css = f"{max(0, min(altura, 1200))}px"
    else:
        valor = str(altura).strip().lower()
        if re.fullmatch(r"\d+(?:\.\d+)?(?:px|rem|em|vh|vw|%)", valor):
            altura_css = valor
        else:
            altura_css = presets.get(valor, "16px")
    _render_html(
        f'<div aria-hidden="true" style="height:{altura_css};"></div>', st.sidebar
    )


__all__ = [
    "LOGO_PADRAO_TOTALE",
    "TemaSidebarType",
    "aplicar_estilo",
    "aplicar_estilo_corp",
    "aplicar_sidebar_corp",
    "carregar_layout_corporativo",
    "definir_tema_sidebar",
    "formatar_datetime_exibicao",
    "normalizar_tema_sidebar",
    "render_page_sidebar_theme_selector",
    "render_sidebar_brand",
    "render_sidebar_divider",
    "render_sidebar_footer_info",
    "render_sidebar_info",
    "render_sidebar_pulse",
    "render_sidebar_section",
    "render_sidebar_spacer",
    "render_sidebar_status",
    "render_sidebar_theme_selector",
]
