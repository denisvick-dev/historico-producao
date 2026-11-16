from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import html
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from collections.abc import Mapping
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import structlog
from streamlit.errors import StreamlitSecretNotFoundError

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

from components.componentes import (
    LOGO_PADRAO_TOTALE,
    Cores,
    Fontes,
    aplicar_estilo_corp,
    formatar_numero_br,
    render_hero_totale_1,
    formatar_delta_decimal_br,
    formatar_variacao_pct_br,
    injetar_css_delta_cards,
    render_delta_card,
    render_drilldown_tecnico,
    render_sidebar_brand,
    render_sidebar_divider,
    render_sidebar_footer_info,
    render_sidebar_section,
    render_sidebar_theme_selector,
    render_ticker,
)
from components.sidebar import render_sidebar_pulse
from components.comparativo_anos import render_comparativo_anos
from components.comparativo_consultivo import render_comparativo_consultivo
from components.consultivo import render_consultivo
from components.contratos import render_contratos
from components.eficiencia import render_eficiencia
from components.pacote_executivo import gerar_pacote_executivo_xlsx
from components.prod_os import render_prod_orders
from components.produtividade_unitaria import render_produtividade_unitaria
from components.quadro_tecnicos import render_quadro_tecnicos
from components.qualidade_ritmo import render_qualidade_ritmo
from components.radar_alertas import render_radar_alertas
from components.scorecard_supervisao import render_scorecard_supervisao
from components.turnover_rampup import render_turnover_rampup
from components.visao_360 import render_visao_360, resumo_consultivo_tecnico
from components.visoes_dashboards import (
    render_projetos,
    render_regularidade_producao,
    render_saude_dados,
    render_sazonalidade,
    selecionar_periodo_anterior,
)
from drive_import import (
    CONSULTIVO_PARSER_VERSION,
    IMPORT_PARSER_VERSION,
    ROSTER_PARSER_VERSION,
    DriveImportError,
    import_consultivo_folder_snapshot,
    import_drive_folder_snapshot,
    import_roster_spreadsheet,
)
import production as production_mod
from production import (
    DEFAULT_CONSULTIVO_FOLDER_ID,
    DEFAULT_ROSTER_SHEET_ID,
    ROSTER_STATUS_ORDER,
    backup_database,
    best_month_by_technician as _production_best_month_by_technician,
    consultivo_import_batches,
    count_active_months_by_technician,
    create_demonstration,
    database_stats,
    delete_technician_alias,
    extract_drive_folder_id,
    extract_spreadsheet_id,
    format_points,
    get_consultivo_file_fingerprints,
    get_drive_file_fingerprints,
    get_roster_fingerprint,
    import_batches,
    init_database,
    load_consultivo_snapshot,
    load_dashboard_snapshot,
    load_roster,
    load_technician_aliases,
    month_label,
    save_roster_records,
    save_technician_alias,
    summarize,
    sync_consultivo_drive_records,
    sync_drive_records,
)

try:
    _drive_folder_secret = st.secrets.get("drive_folder_id")
except (KeyError, StreamlitSecretNotFoundError, AttributeError):
    _drive_folder_secret = None

try:
    _roster_sheet_secret = st.secrets.get("roster_sheet_id")
except (KeyError, StreamlitSecretNotFoundError, AttributeError):
    _roster_sheet_secret = None

try:
    _consultivo_folder_secret = st.secrets.get("consultivo_folder_id")
except (KeyError, StreamlitSecretNotFoundError, AttributeError):
    _consultivo_folder_secret = None

DRIVE_FOLDER_ID = (
    _drive_folder_secret
    or os.getenv("DRIVE_FOLDER_ID")
    or "1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq"
)
ROSTER_SHEET_ID = (
    extract_spreadsheet_id(
        str(_roster_sheet_secret or os.getenv("ROSTER_SHEET_ID") or "")
    )
    or DEFAULT_ROSTER_SHEET_ID
)
CONSULTIVO_FOLDER_ID = (
    extract_drive_folder_id(
        str(_consultivo_folder_secret or os.getenv("CONSULTIVO_FOLDER_ID") or "")
    )
    or DEFAULT_CONSULTIVO_FOLDER_ID
)

COLORS = {
    "ink": Cores.PRIMARIA,
    "green": Cores.PRIMARIA,
    "mint": Cores.SECUNDARIA,
    "pale": Cores.AZUL_SUAVE,
    "text": Cores.TEXTO,
    "muted": Cores.TEXTO_3,
    "grid": Cores.BORDA,
    "background": Cores.FUNDO,
}

ICONE_PAGINA_TOTALE = LOGO_PADRAO_TOTALE.parent / "totale.ico"

st.set_page_config(
    page_title="Inteligência & Gestão Operacional | Totale",
    page_icon=(
        str(ICONE_PAGINA_TOTALE)
        if ICONE_PAGINA_TOTALE.is_file()
        else str(LOGO_PADRAO_TOTALE)
        if LOGO_PADRAO_TOTALE.is_file()
        else "📈"
    ),
    layout="wide",
    initial_sidebar_state="expanded",
)

# Preserva o tema escolhido durante a sessão; azul segue como padrão inicial.
st.session_state.setdefault("_totale_sidebar_theme", "azul")
aplicar_estilo_corp()

st.markdown(
    """
    <style>
    :root {
        --ink: #012869;
        --green: #012869;
        --mint: #F37C04;
        --muted: #64748b;
        --text: #122033;
        --line: #e6edf5;
        --surface: #ffffff;
        --background: #f3f6fb;
    }
    html, body, [class*="css"], .stApp { font-family: 'Inter', 'Segoe UI', Arial, sans-serif; }
    h1, h2, h3 { font-family: 'Manrope', 'Inter', 'Segoe UI', sans-serif; }
    .stApp { background: var(--background); color: var(--text); }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stHeader"] { background: rgba(243,246,251,.88); }
    [data-testid="stMainBlockContainer"] { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }

    h1, h2, h3 { color:#012869; letter-spacing:-.035em; }
    h1 { font-size:2rem !important; font-weight:800 !important; margin-bottom:.1rem !important; }
    h2 { font-size:1.15rem !important; font-weight:650 !important; }
    h3 { font-size:1rem !important; font-weight:650 !important; }
    p { color:var(--muted); }
    .page-subtitle { color:var(--muted); font-size:14px; margin-top:.15rem; }
    .header-meta { text-align:right; color:var(--muted); font-size:12px; padding-top:12px; line-height:1.55; }
    .header-meta strong { color:#012869; font-weight:600; }
    .demo-banner {
        background:#E8EEF8; border:1px solid #cbd8eb; color:#012869; padding:.78rem 1rem;
        border-radius:10px; font-size:13px; margin:1.1rem 0 1rem;
    }
    .demo-banner strong { color:#012869; }
    .filter-label { color:#4f6560; font-size:12px; font-weight:600; margin-bottom:-5px; }
    .kpi-card {
        position:relative; isolation:isolate; overflow:hidden; min-height:144px;
        display:flex; flex-direction:column; justify-content:space-between;
        padding:1.15rem 1.25rem 1.05rem; background:#fff;
        border:1px solid #e2eaf4; border-radius:15px;
        box-shadow:0 5px 18px rgba(1,40,105,.055);
        transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .kpi-card::before {
        content:""; position:absolute; z-index:1; inset:0 0 auto; height:4px; pointer-events:none;
        background:linear-gradient(90deg, #012869 0%, #0A48AA 72%, #F37C04 100%);
    }
    .kpi-card:hover { transform:translateY(-3px); border-color:#c8d7eb; box-shadow:0 12px 26px rgba(1,40,105,.11); }

    /* KPI cards coloridos por métrica */
    .kpi-card--azul { border-color:#012869; box-shadow:0 5px 18px rgba(1,40,105,.08); }
    .kpi-card--azul::before { background:linear-gradient(90deg, #012869 0%, #1E40AF 100%); }
    .kpi-card--azul .kpi-value { color:#012869 !important; }
    .kpi-card--azul .kpi-label { color:#1E40AF !important; }

    .kpi-card--laranja { border-color:#F37C04; box-shadow:0 5px 18px rgba(243,124,4,.08); }
    .kpi-card--laranja::before { background:linear-gradient(90deg, #F37C04 0%, #FB923C 100%); }
    .kpi-card--laranja .kpi-value { color:#F37C04 !important; }
    .kpi-card--laranja .kpi-label { color:#C2410C !important; }

    .kpi-card--verde { border-color:#047857; box-shadow:0 5px 18px rgba(4,120,87,.08); }
    .kpi-card--verde::before { background:linear-gradient(90deg, #047857 0%, #10B981 100%); }
    .kpi-card--verde .kpi-value { color:#047857 !important; }
    .kpi-card--verde .kpi-label { color:#0F766E !important; }

    .kpi-card--roxo { border-color:#7C3AED; box-shadow:0 5px 18px rgba(124,58,237,.08); }
    .kpi-card--roxo::before { background:linear-gradient(90deg, #7C3AED 0%, #A855F7 100%); }
    .kpi-card--roxo .kpi-value { color:#7C3AED !important; }
    .kpi-card--roxo .kpi-label { color:#6D28D9 !important; }

    .kpi-card--vermelho { border-color:#DC2626; box-shadow:0 5px 18px rgba(220,38,38,.08); }
    .kpi-card--vermelho::before { background:linear-gradient(90deg, #DC2626 0%, #EF4444 100%); }
    .kpi-card--vermelho .kpi-value { color:#DC2626 !important; }
    .kpi-card--vermelho .kpi-label { color:#B91C1C !important; }

    /* Badges coloridos */
    .badge {
        display:inline-flex; align-items:center; gap:.4rem;
        padding:.25rem .7rem; border-radius:999px; font-size:11px;
        font-weight:750; letter-spacing:.05em; text-transform:uppercase;
    }
    .badge--azul { background:#EFF6FF; color:#1E40AF; border:1px solid #BFDBFE; }
    .badge--laranja { background:#FFF7ED; color:#C2410C; border:1px solid #FCD34D; }
    .badge--verde { background:#ECFDF5; color:#0F766E; border:1px solid #A7F3D0; }
    .badge--roxo { background:#FAF5FF; color:#6D28D9; border:1px solid #E9D5FF; }
    .badge--vermelho { background:#FEF2F2; color:#B91C1C; border:1px solid #FECACA; }

    /* Barra de progresso colorida */
    .progress-track {
        width:100%; height:8px; background:#E2E8F0; border-radius:999px;
        overflow:hidden; margin-top:.5rem;
    }
    .progress-fill {
        height:100%; border-radius:999px; transition:width .6s ease;
    }
    .progress-fill--azul { background:linear-gradient(90deg, #012869, #1E40AF); }
    .progress-fill--laranja { background:linear-gradient(90deg, #F37C04, #FB923C); }
    .progress-fill--verde { background:linear-gradient(90deg, #047857, #10B981); }
    .kpi-top { display:flex; align-items:center; justify-content:space-between; gap:.65rem; }
    .kpi-label { font-size:11px; font-weight:700; color:#52657d; letter-spacing:.075em; line-height:1.35; }
    .kpi-dot {
        flex:0 0 34px; width:34px; height:34px; border-radius:10px;
        background:linear-gradient(145deg,#fff7ed,#ffedd5); border:1px solid #fed7aa;
        display:flex; align-items:center; justify-content:center; font-size:12px;
        color:#9a4d00; font-weight:800;
    }
    .kpi-value {
        font-family:'Manrope','Inter',sans-serif; font-size:30px; line-height:1.1;
        letter-spacing:-.045em; font-weight:800; color:#012869; margin:.45rem 0 .15rem;
        font-variant-numeric:tabular-nums;
    }
    .kpi-note { font-size:11.5px; line-height:1.4; color:#64748B; font-variant-numeric:tabular-nums; }
    .kpi-note.positive,
    .kpi-note.negative,
    .kpi-note.share-orange,
    .kpi-note.share-green {
        display:inline-flex; align-items:center; width:fit-content;
        padding:3px 9px; border-radius:999px; font-size:12px; font-weight:800;
        letter-spacing:-0.01em; margin-top:2px;
    }
    .kpi-note.positive { background:#ECFDF5; color:#047857; border:1px solid #A7F3D0; }
    .kpi-note.negative { background:#FEF2F2; color:#B91C1C; border:1px solid #FECACA; }
    .kpi-note.share-orange { background:#FFF7ED; color:#C2410C; border:1px solid #FED7AA; }
    .kpi-note.share-green { background:#ECFDF5; color:#047857; border:1px solid #A7F3D0; }
    .section-heading { margin:1.45rem 0 .75rem; display:flex; justify-content:space-between; align-items:end; }
    .section-heading h2 { margin:0 !important; font-family:"Manrope", "Inter", sans-serif; font-weight:750 !important; }
    .section-heading p { margin:.15rem 0 0; font-size:12px; }
    [data-testid="stVerticalBlockBorderWrapper"] { background:#fff; border-color:var(--line) !important; border-radius:13px !important; box-shadow:0 4px 16px rgba(1,40,105,.035); }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { gap:.8rem; }
    [data-testid="stPlotlyChart"] { border-radius:8px; }
    .stButton > button, .stDownloadButton > button { border-radius:8px; font-weight:600; min-height:2.55rem; }
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background:#012869; border-color:#012869; }
    .stButton > button[kind="primary"]:hover { background:#011838; border-color:#F37C04; box-shadow:0 0 0 3px rgba(243,124,4,.12); }
    .stTextInput input, .stSelectbox > div > div, .stMultiSelect > div > div, .stDateInput > div > div { border-radius:8px; }
    [data-testid="stFileUploader"] { background:#f8faff; border:1px dashed #b9cae3; border-radius:12px; padding:.4rem; }
    .small-muted { color:var(--muted); font-size:12px; line-height:1.5; }
    .formula { background:#E8EEF8; border-radius:9px; padding:.8rem 1rem; color:#012869; font-size:13px; border:1px solid #e0ece5; }
    .technician-hero { display:flex; align-items:center; gap:1rem; padding:.25rem 0 .8rem; }
    .avatar { width:50px; height:50px; border-radius:50%; background:#E8EEF8; color:#012869; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:17px; }
    .tech-name { color:#012869; font-size:20px; font-weight:700; line-height:1.2; }
    .rank-pill { display:inline-block; background:#FFF3E6; color:#9A4D00; padding:4px 9px; border-radius:20px; font-size:11px; font-weight:600; margin-top:5px; }
    .empty-state { text-align:center; background:white; border:1px solid var(--line); border-radius:14px; padding:3rem 1.5rem; margin-top:1.2rem; }
    .empty-icon { width:54px; height:54px; margin:0 auto 1rem; border-radius:15px; background:#E8EEF8; color:#012869; display:flex; align-items:center; justify-content:center; font-size:25px; }
    .empty-state h2 { margin-bottom:.4rem !important; }
    .empty-state p { max-width:540px; margin:0 auto 1.2rem; font-size:14px; }
    .filter-chips-bar {
        display:flex; flex-wrap:wrap; align-items:center; gap:.42rem;
        margin:.35rem 0 .85rem;
    }
    .filter-chip {
        display:inline-flex; align-items:center; gap:.32rem;
        padding:.22rem .68rem; border-radius:999px; font-size:11.5px;
        font-weight:600; background:#EFF4FF; color:#012869; border:1px solid #BFDBFE;
    }
    .filter-chip strong { font-weight:750; color:#012869; }
    .filter-chip--accent { background:#FFF7ED; color:#9A4D00; border-color:#FED7AA; }
    .footer { text-align:center; color:#8a9995; font-size:11px; margin-top:2rem; padding-top:1rem; border-top:1px solid #e6edf5; }
    .stTabs [data-baseweb="tab-list"] { gap:1.5rem; }
    .stTabs [data-baseweb="tab"] { font-weight:600; }

    /* Faixa de indicadores no estilo de um ticker de mercado */
    .ticker-viewport {
        overflow: hidden;
        margin: 1rem 0 1.5rem;
        border: 1px solid #183b62;
        border-radius: 8px;
        background: #071a33;
        box-shadow: 0 4px 14px rgba(1, 20, 45, 0.14);
    }
    .ticker-track {
        display: flex;
        width: max-content;
        animation: ticker-scroll 30s linear infinite;
    }
    .ticker-viewport:hover .ticker-track {
        animation-play-state: paused;
    }
    .ticker-group {
        display: flex;
        align-items: center;
        flex: 0 0 max-content;
        min-width: 100vw;
        justify-content: space-around;
    }
    .ticker-item {
        display: inline-flex;
        align-items: center;
        gap: 0.55rem;
        flex: 0 0 auto;
        padding: 0.78rem 1.25rem;
        border-right: 1px solid rgba(148, 173, 204, 0.22);
        color: #f8fafc;
        font-size: 12px;
        white-space: nowrap;
    }
    .ticker-item::before {
        content: "";
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: #22c55e;
        box-shadow: 0 0 7px rgba(34, 197, 94, 0.55);
    }
    .ticker-label {
        color: #9fb3cc;
        font-size: 10px;
        font-weight: 750;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }
    .ticker-item strong {
        font-weight: 750;
        font-variant-numeric: tabular-nums;
    }
    @keyframes ticker-scroll {
        to { transform: translateX(-50%); }
    }
    @media (prefers-reduced-motion: reduce) {
        .ticker-viewport .ticker-track {
            animation-duration: 30s !important;
            animation-iteration-count: infinite !important;
        }
    }
    @media (max-width: 700px) {
        [data-testid="stMainBlockContainer"] { padding:1rem; }
        .header-meta { display:none; }
        .kpi-card { padding:1rem; min-height:120px; }
        .kpi-value { font-size:23px; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def best_month_by_technician(records: pd.DataFrame) -> dict[str, str]:
    """Retorna a competência de maior produção total para cada técnico."""
    series = _production_best_month_by_technician(records)
    return {str(k): str(v) for k, v in series.items()}


def chart_layout(fig: go.Figure, height: int = 340) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=12, t=15, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=COLORS["muted"], size=11),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor="white", font_color=COLORS["text"]),
        bargap=0.35,
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        tickfont=dict(size=10),
        fixedrange=True,
    )
    fig.update_yaxes(
        gridcolor=COLORS["grid"],
        zeroline=False,
        showline=False,
        tickfont=dict(size=10),
        fixedrange=True,
        separatethousands=True,
    )
    return fig


def production_chart(monthly: pd.DataFrame) -> go.Figure:
    monthly = monthly.sort_values("period").copy()
    monthly["label"] = monthly["period"].map(month_label)
    fig = go.Figure()
    fig.add_bar(
        x=monthly["label"],
        y=monthly["points_prod"],
        name="Prod",
        marker_color=COLORS["ink"],
        hovertemplate="<b>%{x}</b><br>Prod: %{y:,.2f} pontos<extra></extra>",
    )
    fig.add_bar(
        x=monthly["label"],
        y=monthly["points_gpon"],
        name="Gpon",
        marker_color=COLORS["mint"],
        hovertemplate="<b>%{x}</b><br>Gpon: %{y:,.2f} pontos<extra></extra>",
    )
    fig.add_scatter(
        x=monthly["label"],
        y=monthly["points_total"],
        mode="text",
        text=[format_points(value) for value in monthly["points_total"]],
        textposition="top center",
        textfont=dict(size=10, color="#012869"),
        showlegend=False,
        hoverinfo="skip",
        cliponaxis=False,
    )
    fig.update_layout(barmode="stack")
    maximum = monthly["points_total"].max() if not monthly.empty else 1
    fig.update_yaxes(range=[0, maximum * 1.22 if maximum else 1])
    return chart_layout(fig)


def ranking_chart(ranking: pd.DataFrame, top: int = 8) -> go.Figure:
    data = ranking.nlargest(top, "points_total").sort_values("points_total")
    fig = go.Figure()
    fig.add_bar(
        y=data["technician"],
        x=data["points_prod"],
        name="Prod",
        orientation="h",
        marker_color=COLORS["ink"],
        hovertemplate="%{y}<br>Prod: %{x:,.2f}<extra></extra>",
    )
    fig.add_bar(
        y=data["technician"],
        x=data["points_gpon"],
        name="Gpon",
        orientation="h",
        marker_color=COLORS["mint"],
        hovertemplate="%{y}<br>Gpon: %{x:,.2f}<extra></extra>",
    )
    fig.add_scatter(
        y=data["technician"],
        x=data["points_total"],
        mode="text",
        text=[format_points(value) for value in data["points_total"]],
        textposition="middle right",
        textfont=dict(size=10, color="#012869"),
        showlegend=False,
        hoverinfo="skip",
        cliponaxis=False,
    )
    fig.update_layout(barmode="stack")
    fig.update_xaxes(showgrid=False, showticklabels=False)
    fig.update_yaxes(showgrid=False, tickfont=dict(size=10, color="#415c53"))
    chart_layout(fig, height=max(290, len(data) * 38 + 70))
    fig.update_layout(margin=dict(l=8, r=65, t=15, b=8))
    return fig


def initials(name: str) -> str:
    parts = name.split()
    return "".join(part[0] for part in (parts[0], parts[-1])).upper()


def metric_card(
    label: str,
    value: str,
    note: str,
    symbol: str,
    note_class: str = "",
    card_class: str = "",
) -> None:
    st.markdown(
        f"""
        <div class="kpi-card {card_class}">
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


def _limpar_filtros_globais() -> None:
    """Restaura os filtros operacionais globais e limpa os parâmetros de URL."""
    for chave in (
        "monitor_filter",
        "base_filter",
        "un_filter",
        "project_filter",
        "technician_filter",
    ):
        if chave in st.session_state:
            st.session_state[chave] = []
    if "period_filter" in st.session_state:
        st.session_state["period_filter"] = "Últimos 12 meses"
    for qp_key in ("monitor", "base", "un", "projeto", "periodo"):
        try:
            if qp_key in st.query_params:
                del st.query_params[qp_key]
        except Exception:
            break


def _sync_query_params_from_filters(
    *,
    pagina: str | None = None,
    period_choice: str | None = None,
    monitors: list[str] | None = None,
    bases: list[str] | None = None,
    uns: list[str] | None = None,
    projects: list[str] | None = None,
) -> None:
    """Reflete filtros ativos na URL via ``st.query_params`` para compartilhamento."""
    try:
        if pagina:
            if st.query_params.get("page") != pagina:
                st.query_params["page"] = pagina
        mapping: list[tuple[str, str]] = []
        if period_choice and period_choice != "Últimos 12 meses":
            mapping.append(("periodo", period_choice))
        else:
            mapping.append(("periodo", ""))
        mapping.append(("monitor", "|".join(monitors or [])))
        mapping.append(("base", "|".join(bases or [])))
        mapping.append(("un", "|".join(uns or [])))
        mapping.append(("projeto", "|".join(projects or [])))
        for key, val in mapping:
            if val:
                if st.query_params.get(key) != val:
                    st.query_params[key] = val
            elif key in st.query_params:
                del st.query_params[key]
    except Exception:
        logger.debug("falha_atualizar_query_params", exc_info=True)


def _hydrate_filters_from_query_params(
    *,
    monitor_options: list[str],
    base_options: list[str],
    un_options: list[str],
    project_options: list[str],
) -> None:
    """Hidrata filtros globais a partir de ``st.query_params`` uma vez por sessão."""
    if st.session_state.get("_totale_qp_filters_hydrated"):
        return
    st.session_state["_totale_qp_filters_hydrated"] = True
    try:
        qp = st.query_params
    except Exception:
        return
    valid_periods = {
        "Todo o período",
        "Últimos 3 meses",
        "Últimos 6 meses",
        "Últimos 12 meses",
        "Personalizado",
    }
    periodo_qp = str(qp.get("periodo", "") or "").strip()
    if periodo_qp in valid_periods and "period_filter" not in st.session_state:
        st.session_state["period_filter"] = periodo_qp

    for qp_key, state_key, valid_opts in (
        ("monitor", "monitor_filter", monitor_options),
        ("base", "base_filter", base_options),
        ("un", "un_filter", un_options),
        ("projeto", "project_filter", project_options),
    ):
        raw_val = str(qp.get(qp_key, "") or "").strip()
        if raw_val and state_key not in st.session_state:
            valid_set = set(valid_opts)
            parsed = [v for v in raw_val.split("|") if v in valid_set]
            if parsed:
                st.session_state[state_key] = parsed


def _render_active_filter_chips(
    *,
    period_choice: str,
    selected_statuses: list[str],
    selected_monitors: list[str],
    selected_bases: list[str],
    selected_uns: list[str],
    selected_projects: list[str],
    selected_technicians: list[str],
    total_filtered: int,
) -> None:
    """Exibe chips compactos resumindo os filtros ativos do recorte atual."""
    chips: list[tuple[str, str, bool]] = [
        ("Período", period_choice, False),
    ]
    if selected_statuses:
        chips.append(("Situação", ", ".join(selected_statuses), False))
    if selected_monitors:
        chips.append(
            (
                "Monitor",
                ", ".join(selected_monitors[:3])
                + ("…" if len(selected_monitors) > 3 else ""),
                True,
            )
        )
    if selected_bases:
        chips.append(
            (
                "Base",
                ", ".join(selected_bases[:3])
                + ("…" if len(selected_bases) > 3 else ""),
                True,
            )
        )
    if selected_uns:
        chips.append(
            (
                "U.N.",
                ", ".join(selected_uns[:3]) + ("…" if len(selected_uns) > 3 else ""),
                True,
            )
        )
    if selected_projects:
        chips.append(
            (
                "Projeto",
                ", ".join(selected_projects[:3])
                + ("…" if len(selected_projects) > 3 else ""),
                True,
            )
        )
    if selected_technicians:
        chips.append(("Técnicos", f"{len(selected_technicians)} selecionado(s)", True))
    chips.append(("Linhas", formatar_numero_br(total_filtered), False))

    html_chips = "".join(
        f'<span class="filter-chip{" filter-chip--accent" if accent else ""}">'
        f"<strong>{html.escape(lbl)}:</strong> {html.escape(val)}</span>"
        for lbl, val, accent in chips
    )
    st.markdown(
        f'<div class="filter-chips-bar" aria-label="Filtros ativos">{html_chips}</div>',
        unsafe_allow_html=True,
    )


def apply_filters(
    records: pd.DataFrame,
    *,
    show_technicians: bool = True,
    apply_roster_filters: bool = True,
    roster: pd.DataFrame | None = None,
) -> tuple[
    pd.DataFrame,
    list[str],
    int | None,
    list[str],
    pd.Timestamp,
    pd.Timestamp,
]:
    """Renderiza filtros e devolve o recorte, dimensões e limites temporais."""
    has_roster = bool(
        apply_roster_filters
        and "roster_status" in records.columns
        and records["roster_status"].ne("Sem cadastro").any()
    )
    all_projects = sorted(records["project"].dropna().unique())

    selected_statuses: list[str] = []
    selected_monitors: list[str] = []
    selected_bases: list[str] = []
    selected_uns: list[str] = []

    monitor_options = (
        sorted(m for m in records["monitor"].dropna().unique() if str(m).strip())
        if has_roster and "monitor" in records.columns
        else []
    )
    base_options = (
        sorted(b for b in records["base"].dropna().unique() if str(b).strip())
        if has_roster and "base" in records.columns
        else []
    )
    un_options = (
        sorted(u for u in records["un"].dropna().unique() if str(u).strip())
        if has_roster and "un" in records.columns
        else []
    )
    _hydrate_filters_from_query_params(
        monitor_options=monitor_options,
        base_options=base_options,
        un_options=un_options,
        project_options=all_projects,
    )

    with st.container(border=True):
        if has_roster:
            present_statuses = set(records["roster_status"].dropna().unique())
            if roster is not None and not roster.empty and "status" in roster.columns:
                present_statuses.update(roster["status"].dropna().unique())
            status_options = [s for s in ROSTER_STATUS_ORDER if s in present_statuses]
            for extra in sorted(present_statuses):
                if extra not in status_options:
                    status_options.append(extra)
            default_status = ["ATIVO"] if "ATIVO" in status_options else []

            roster_cols = st.columns([1.25, 1.3, 1.15, 1.1])
            with roster_cols[0]:
                selected_statuses = st.multiselect(
                    "Situação cadastral (lista_ativos)",
                    status_options,
                    default=default_status,
                    placeholder="Todas as situações",
                    key="roster_status_filter",
                )
            with roster_cols[1]:
                selected_monitors = st.multiselect(
                    "Monitor",
                    monitor_options,
                    default=[],
                    placeholder="Todos os monitores",
                    key="monitor_filter",
                )
            with roster_cols[2]:
                selected_bases = st.multiselect(
                    "Base",
                    base_options,
                    default=[],
                    placeholder="Todas as bases",
                    key="base_filter",
                )
            with roster_cols[3]:
                selected_uns = st.multiselect(
                    "U.N.",
                    un_options,
                    default=[],
                    placeholder="Todas as U.N.",
                    key="un_filter",
                )

        # Máscara booleana única para o recorte cadastral (evita múltiplas cópias sequenciais).
        mask = pd.Series(True, index=records.index)
        if has_roster:
            if selected_statuses:
                mask &= records["roster_status"].isin(selected_statuses)
            if selected_monitors:
                mask &= records["monitor"].isin(selected_monitors)
            if selected_bases:
                mask &= records["base"].isin(selected_bases)
            if selected_uns and "un" in records.columns:
                mask &= records["un"].isin(selected_uns)

        all_technicians = sorted(records.loc[mask, "technician"].unique())
        filter_columns = st.columns(
            [1.15, 1.45, 1.6, 0.72] if show_technicians else [1.15, 1.75, 0.72]
        )
        period_col, project_col = filter_columns[:2]
        with period_col:
            period_choice = st.selectbox(
                "Período de análise",
                [
                    "Todo o período",
                    "Últimos 3 meses",
                    "Últimos 6 meses",
                    "Últimos 12 meses",
                    "Personalizado",
                ],
                index=3,
                key="period_filter",
            )
        with project_col:
            selected_projects = st.multiselect(
                "Projetos",
                all_projects,
                default=[],
                placeholder="Todos os projetos",
                key="project_filter",
            )
        selected_technicians = []
        if show_technicians:
            prior_tech = st.session_state.get("technician_filter")
            if isinstance(prior_tech, list):
                valid_prior = [t for t in prior_tech if t in all_technicians]
                if valid_prior != prior_tech:
                    st.session_state["technician_filter"] = valid_prior
            with filter_columns[2]:
                selected_technicians = st.multiselect(
                    "Técnicos",
                    all_technicians,
                    default=[],
                    placeholder="Todos os técnicos",
                    key="technician_filter",
                )
        with filter_columns[-1]:
            st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
            st.button(
                "Limpar",
                key="clear_global_filters_button",
                icon=":material/filter_alt_off:",
                on_click=_limpar_filtros_globais,
                width="stretch",
                help="Limpa os filtros de Monitor, Base, U.N., Projeto e Técnico.",
            )

    months: int | None = None
    last_date = records["reference_date"].max()
    first_date = records["reference_date"].min()
    window_start = pd.Timestamp(first_date)
    window_end = pd.Timestamp(last_date)
    if period_choice.startswith("Últimos"):
        months = int(period_choice.split()[1])
        cutoff = (last_date.to_period("M") - (months - 1)).to_timestamp()
        window_start = pd.Timestamp(cutoff)
        mask &= records["reference_date"] >= cutoff
    elif period_choice == "Personalizado":
        start_col, end_col, _ = st.columns([1, 1, 3])
        with start_col:
            start = st.date_input(
                "Data inicial",
                value=first_date.date(),
                min_value=first_date.date(),
                max_value=last_date.date(),
                format="DD/MM/YYYY",
                key="custom_start",
            )
        with end_col:
            end = st.date_input(
                "Data final",
                value=last_date.date(),
                min_value=first_date.date(),
                max_value=last_date.date(),
                format="DD/MM/YYYY",
                key="custom_end",
            )
        if start > end:
            st.warning("A data inicial deve ser anterior à data final.")
            start, end = end, start
        window_start = pd.Timestamp(start)
        window_end = pd.Timestamp(end)
        mask &= records["reference_date"].between(window_start, window_end)
    if selected_projects:
        mask &= records["project"].isin(selected_projects)
    if selected_technicians:
        mask &= records["technician"].isin(selected_technicians)
    filtered = records.loc[mask].copy()
    _sync_query_params_from_filters(
        period_choice=period_choice,
        monitors=selected_monitors,
        bases=selected_bases,
        uns=selected_uns,
        projects=selected_projects,
    )
    _render_active_filter_chips(
        period_choice=period_choice,
        selected_statuses=selected_statuses,
        selected_monitors=selected_monitors,
        selected_bases=selected_bases,
        selected_uns=selected_uns,
        selected_projects=selected_projects,
        selected_technicians=selected_technicians,
        total_filtered=len(filtered),
    )
    return (
        filtered,
        selected_technicians or all_technicians,
        months,
        selected_projects or all_projects,
        window_start,
        window_end,
    )


def render_metrics(
    filtered: pd.DataFrame,
    records: pd.DataFrame,
    technicians: list[str],
    months: int | None,
    projects: list[str],
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> None:
    totals = summarize(filtered, [])
    if totals.empty:
        current_prod = current_gpon = current_total = 0.0
    else:
        current_prod = totals.iloc[0]["points_prod"]
        current_gpon = totals.iloc[0]["points_gpon"]
        current_total = totals.iloc[0]["points_total"]
    active = filtered["technician"].nunique()
    average = current_total / active if active else 0

    previous = selecionar_periodo_anterior(
        records, filtered, technicians, months, projects, period_start, period_end
    )
    previous_total = previous["points"].sum()
    if previous_total > 0:
        variation = (current_total / previous_total - 1) * 100
        arrow = "↑" if variation >= 0 else "↓"
        variation_label = f"{abs(variation):.2f}%".replace(".", ",")
        note = f"{arrow} {variation_label} vs. período anterior"
        note_class = "positive" if variation >= 0 else "negative"
    else:
        note = "Sem base histórica comparável"
        note_class = ""

    columns = st.columns(4)
    with columns[0]:
        metric_card(
            "PONTOS TOTAIS",
            format_points(current_total),
            note,
            "Σ",
            note_class,
            "kpi-card--azul",
        )
    with columns[1]:
        share_prod = current_prod / current_total * 100 if current_total else 0
        metric_card(
            "PONTOS EM PROD",
            format_points(current_prod),
            f"{share_prod:.1f}% do total".replace(".", ","),
            "P",
            "share-orange",
            "kpi-card--laranja",
        )
    with columns[2]:
        share_gpon = current_gpon / current_total * 100 if current_total else 0
        metric_card(
            "PONTOS EM GPON",
            format_points(current_gpon),
            f"{share_gpon:.1f}% do total".replace(".", ","),
            "G",
            "share-green",
            "kpi-card--verde",
        )
    with columns[3]:
        metric_card(
            "MÉDIA POR TÉCNICO",
            format_points(average),
            f"{active} {'técnicos ativos' if active != 1 else 'técnico ativo'} no recorte",
            "Ø",
            "",
            "kpi-card--roxo",
        )

    if not previous.empty:
        prev_totals = summarize(previous, [])
        prev_prod = (
            float(prev_totals.iloc[0]["points_prod"]) if not prev_totals.empty else 0.0
        )
        prev_gpon = (
            float(prev_totals.iloc[0]["points_gpon"]) if not prev_totals.empty else 0.0
        )
        prev_tot = float(previous_total)
        delta_tot = float(current_total) - prev_tot
        delta_prod_pts = float(current_prod) - prev_prod
        delta_gpon_pts = float(current_gpon) - prev_gpon
        pct_tot = (
            ((float(current_total) / prev_tot - 1.0) * 100.0) if prev_tot > 0 else None
        )
        pct_prod = (
            ((float(current_prod) / prev_prod - 1.0) * 100.0) if prev_prod > 0 else None
        )
        pct_gpon = (
            ((float(current_gpon) / prev_gpon - 1.0) * 100.0) if prev_gpon > 0 else None
        )

        injetar_css_delta_cards()
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        d_cols = st.columns(3)
        render_delta_card(
            d_cols[0],
            "Δ Produção Total vs Período Anterior",
            formatar_delta_decimal_br(delta_tot, 2, "pts"),
            valor_base=format_points(prev_tot),
            valor_atual=format_points(current_total),
            rotulo_base="Anterior",
            rotulo_atual="Atual",
            variacao_pct=formatar_variacao_pct_br(
                pct_tot, atual=current_total, base=prev_tot
            ),
            direcao="up" if delta_tot > 0 else ("down" if delta_tot < 0 else "neutral"),
            icone="⚡",
            detalhe="Comparativo contra a janela equivalente imediatamente anterior",
            num_base=prev_tot,
            num_atual=float(current_total),
        )
        render_delta_card(
            d_cols[1],
            "Δ Pontos em Prod vs Período Anterior",
            formatar_delta_decimal_br(delta_prod_pts, 2, "pts"),
            valor_base=format_points(prev_prod),
            valor_atual=format_points(current_prod),
            rotulo_base="Anterior",
            rotulo_atual="Atual",
            variacao_pct=formatar_variacao_pct_br(
                pct_prod, atual=current_prod, base=prev_prod
            ),
            direcao=(
                "up"
                if delta_prod_pts > 0
                else ("down" if delta_prod_pts < 0 else "neutral")
            ),
            icone="🔧",
            detalhe="Saldo líquido de pontos na aba Prod",
            detalhe_pct=f"Mix atual: {share_prod:.1f}%".replace(".", ","),
            detalhe_pct_direcao="neutral",
            num_base=prev_prod,
            num_atual=float(current_prod),
        )
        render_delta_card(
            d_cols[2],
            "Δ Pontos em Gpon vs Período Anterior",
            formatar_delta_decimal_br(delta_gpon_pts, 2, "pts"),
            valor_base=format_points(prev_gpon),
            valor_atual=format_points(current_gpon),
            rotulo_base="Anterior",
            rotulo_atual="Atual",
            variacao_pct=formatar_variacao_pct_br(
                pct_gpon, atual=current_gpon, base=prev_gpon
            ),
            direcao=(
                "up"
                if delta_gpon_pts > 0
                else ("down" if delta_gpon_pts < 0 else "neutral")
            ),
            icone="🌐",
            detalhe="Saldo líquido de pontos na aba Gpon",
            detalhe_pct=f"Mix atual: {share_gpon:.1f}%".replace(".", ","),
            detalhe_pct_direcao="neutral",
            num_base=prev_gpon,
            num_atual=float(current_gpon),
        )


def render_overview(
    filtered: pd.DataFrame,
    records: pd.DataFrame,
    technicians: list[str],
    months: int | None,
    projects: list[str],
    period_start: pd.Timestamp,
    period_end: pd.Timestamp,
) -> None:
    render_metrics(
        filtered,
        records,
        technicians,
        months,
        projects,
        period_start,
        period_end,
    )

    # Ticker animado com destaques da visão geral
    totals = summarize(filtered, [])
    if not totals.empty:
        current_total = totals.iloc[0]["points_total"]
        current_prod = totals.iloc[0]["points_prod"]
        current_gpon = totals.iloc[0]["points_gpon"]

        ranking = summarize(filtered, "technician").sort_values(
            "points_total", ascending=False
        )
        top_tech = ""
        if not ranking.empty:
            top_tech = f"{ranking.iloc[0]['technician']} · {format_points(ranking.iloc[0]['points_total'])} pontos"

        latest_period = filtered["period"].max()
        latest = summarize(
            filtered[filtered["period"].eq(latest_period)], "technician"
        ).set_index("technician")
        best_competence = ""
        if not latest.empty:
            best_tech = str(latest["points_total"].idxmax())
            best_points = latest["points_total"].loc[best_tech]
            best_competence = f"{best_tech} · {format_points(best_points)} pontos em {month_label(latest_period)}"

        ticker_items = [
            ("Pontos totais", format_points(current_total)),
            ("Prod", f"{format_points(current_prod)} pontos"),
            ("Gpon", f"{format_points(current_gpon)} pontos"),
        ]
        if top_tech:
            ticker_items.append(("Destaque da equipe", top_tech))
        if best_competence:
            ticker_items.append(("Melhor competência", best_competence))

        render_ticker(ticker_items, label="Indicadores da visão geral")

    section_heading(
        "Produção da equipe", "Pontos consolidados por competência e por técnico"
    )
    chart_col, ranking_col = st.columns([1.65, 1])
    monthly = summarize(filtered, "period").sort_values("period")
    ranking = summarize(filtered, "technician").sort_values(
        "points_total", ascending=False
    )
    with chart_col, st.container(border=True):
        st.markdown("**Evolução mensal**")
        st.plotly_chart(production_chart(monthly), width="stretch", config=CHART_CONFIG)
    with ranking_col, st.container(border=True):
        st.markdown("**Ranking de técnicos**")
        st.plotly_chart(ranking_chart(ranking), width="stretch", config=CHART_CONFIG)

    section_heading(
        "Desempenho por técnico", "O total é sempre a soma dos pontos de Prod e Gpon"
    )
    active_months = count_active_months_by_technician(filtered)
    best_months = best_month_by_technician(filtered)
    latest_period = filtered["period"].max()
    latest = summarize(
        filtered[filtered["period"].eq(latest_period)], "technician"
    ).set_index("technician")
    previous_month = latest_period - pd.DateOffset(months=1)
    previous = summarize(
        filtered[filtered["period"].eq(previous_month)], "technician"
    ).set_index("technician")

    table = ranking.copy()
    table["Meses com produção"] = (
        table["technician"].map(active_months).fillna(0).astype(int)
    )
    table["Melhor mês"] = table["technician"].map(best_months)
    table["Média mensal"] = table["points_total"].div(
        table["Meses com produção"].where(table["Meses com produção"].gt(0), 1)
    )
    variations = []
    for technician in table["technician"]:
        current_value = latest["points_total"].get(technician, 0)
        previous_value = previous["points_total"].get(technician, 0)
        var = (current_value / previous_value - 1) * 100 if previous_value else None
        variations.append(_status_value(var))
    table["Variação no último mês"] = variations
    table.insert(0, "Posição", range(1, len(table) + 1))
    table = table.rename(
        columns={
            "technician": "Técnico",
            "points_prod": "Prod",
            "points_gpon": "Gpon",
            "points_total": "Pontos Totais",
        }
    )
    display_table = table[
        [
            "Posição",
            "Técnico",
            "Prod",
            "Gpon",
            "Pontos Totais",
            "Meses com produção",
            "Melhor mês",
            "Média mensal",
            "Variação no último mês",
        ]
    ]
    st.dataframe(
        display_table.style.map(_total_points_style, subset=["Pontos Totais"])
        .map(_monthly_average_style, subset=["Média mensal"])
        .map(_status_badge_style, subset=["Variação no último mês"]),
        width="stretch",
        hide_index=True,
        alt="Ranking mensal de produção, GPON e pontos por técnico",
        column_config={
            "Posição": st.column_config.NumberColumn(format="%dº", width="small"),
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
            "Meses com produção": st.column_config.NumberColumn(format="%d"),
            "Melhor mês": st.column_config.TextColumn(width="small"),
            "Média mensal": st.column_config.NumberColumn(format="%.2f"),
            "Variação no último mês": st.column_config.TextColumn(width="small"),
        },
    )
    st.caption(
        "Média mensal = Pontos Totais ÷ meses com produção. "
        "Melhor mês considera os maiores Pontos Totais (Prod + Gpon). "
        "Critérios: 275–299,99 amarelo · 300–399,99 verde · 400 ou mais azul."
    )
    if not display_table.empty:
        render_drilldown_tecnico(
            display_table["Técnico"].tolist(),
            key_prefix="overview",
        )
    exp_col, _ = st.columns([1.4, 2.6])
    with exp_col:
        db_key_exp = str(production_mod.DB_PATH)
        st.download_button(
            "📊 Baixar Pacote Executivo (.xlsx)",
            data=_gerar_pacote_geral_xlsx_cached(filtered, db_key_exp),
            file_name="totale_pacote_executivo.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="overview_download_xlsx",
            use_container_width=True,
        )


def _total_points_style(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return "background-color: #F1F5F9; color: #475569; font-weight: 600"


def _monthly_average_style(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    if 275 <= value < 300:
        return "background-color: #FEF3C7; color: #92400E; font-weight: 600"
    if 300 <= value < 400:
        return "background-color: #DCFCE7; color: #166534; font-weight: 600"
    if value >= 400:
        return "background-color: #DBEAFE; color: #1E40AF; font-weight: 600"
    return ""


def _status_value(var: float | None) -> str:
    if var is None:
        return "Sem dado"
    if var >= 10:
        return f"↑ {var:.2f}%"
    if var >= 0:
        return f"→ {var:.2f}%"
    if var >= -10:
        return f"↓ {abs(var):.2f}%"
    return f"↓ {abs(var):.2f}%"


def _status_badge_style(value: object) -> str:
    if not isinstance(value, str):
        return ""
    if value == "Sem dado":
        return (
            "background-color: #FAF5FF; color: #6D28D9; border: 1px solid #E9D5FF; "
            "border-radius: 999px; padding: 0.16rem 0.5rem; font-size: 10px; "
            "font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; "
            "display: inline-flex; align-items: center; justify-content: center; "
            "min-width: 74px; line-height: 1.4;"
        )
    if value.startswith("↑"):
        return (
            "background-color: #ECFDF5; color: #0F766E; border: 1px solid #A7F3D0; "
            "border-radius: 999px; padding: 0.16rem 0.5rem; font-size: 10px; "
            "font-weight: 700; display: inline-flex; align-items: center; justify-content: center; "
            "min-width: 74px; line-height: 1.4;"
        )
    if value.startswith("→"):
        return (
            "background-color: #EFF6FF; color: #1E40AF; border: 1px solid #BFDBFE; "
            "border-radius: 999px; padding: 0.16rem 0.5rem; font-size: 10px; "
            "font-weight: 700; display: inline-flex; align-items: center; justify-content: center; "
            "min-width: 74px; line-height: 1.4;"
        )
    if value.startswith("↓"):
        try:
            magnitude = float(value[2:-1])
        except ValueError:
            magnitude = 0.0
        if magnitude > 10:
            return (
                "background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; "
                "border-radius: 999px; padding: 0.16rem 0.5rem; font-size: 10px; "
                "font-weight: 700; display: inline-flex; align-items: center; justify-content: center; "
                "min-width: 74px; line-height: 1.4;"
            )
        return (
            "background-color: #FFF7ED; color: #C2410C; border: 1px solid #FCD34D; "
            "border-radius: 999px; padding: 0.16rem 0.5rem; font-size: 10px; "
            "font-weight: 700; display: inline-flex; align-items: center; justify-content: center; "
            "min-width: 74px; line-height: 1.4;"
        )
    return ""


def render_technicians(
    filtered: pd.DataFrame,
    *,
    consultivo_frame: pd.DataFrame | None = None,
    period_start: pd.Timestamp | None = None,
    period_end: pd.Timestamp | None = None,
) -> None:
    section_heading(
        "Perfil do técnico",
        "Filtre por projeto e selecione o técnico para ver seu desempenho técnico e comercial.",
    )
    ranking = summarize(filtered, "technician").sort_values(
        "points_total", ascending=False
    )
    names = ranking["technician"].tolist()
    if not names:
        st.info("Nenhum técnico disponível no recorte atual.")
        return
    pending_tech = st.session_state.pop("_pending_technician", None)
    if isinstance(pending_tech, str) and pending_tech in names:
        st.session_state["technician_profile"] = pending_tech
    selected = st.selectbox("Técnico", names, key="technician_profile")
    if selected is None:
        return
    position = names.index(selected) + 1
    technician_data = filtered[filtered["technician"].eq(selected)]
    totals = ranking[ranking["technician"].eq(selected)].iloc[0]

    meta_parts: list[str] = []
    first_row = technician_data.iloc[0]
    login_val = str(first_row.get("login", "")).strip()
    if str(first_row.get("re_code", "")).strip():
        meta_parts.append(f"RE {first_row['re_code']}")
    if login_val:
        meta_parts.append(f"Login {login_val}")
    status_val = str(first_row.get("roster_status", "")).strip()
    if status_val and status_val != "Sem cadastro":
        meta_parts.append(status_val)
    monitor_val = str(first_row.get("monitor", "")).strip()
    if monitor_val and monitor_val != "Sem monitor":
        meta_parts.append(f"Monitor: {monitor_val}")
    base_val = str(first_row.get("base", "")).strip()
    if base_val and base_val != "Sem base":
        meta_parts.append(f"Base: {base_val}")
    meta_html = (
        f'<div style="color:#64748B;font-size:12px;margin-top:4px;">'
        f"{' &nbsp;·&nbsp; '.join(meta_parts)}</div>"
        if meta_parts
        else ""
    )

    st.markdown(
        f"""
        <div class="technician-hero">
            <div class="avatar">{initials(selected)}</div>
            <div><div class="tech-name">{selected}</div><div class="rank-pill">{position}º lugar no ranking do período</div>{meta_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    monthly = summarize(technician_data, "period").sort_values("period")
    best = monthly.sort_values("points_total").iloc[-1]
    average = monthly["points_total"].mean()
    columns = st.columns(4)
    with columns[0]:
        metric_card(
            "PONTOS TOTAIS",
            format_points(totals["points_total"]),
            "Prod + Gpon no período",
            "Σ",
        )
    with columns[1]:
        metric_card(
            "PROD", format_points(totals["points_prod"]), "Pontos acumulados", "P"
        )
    with columns[2]:
        metric_card(
            "GPON", format_points(totals["points_gpon"]), "Pontos acumulados", "G"
        )
    with columns[3]:
        metric_card(
            "MELHOR COMPETÊNCIA",
            month_label(best["period"]),
            f"{format_points(best['points_total'])} pontos · média {format_points(average)}",
            "↑",
        )

    # Dossiê 360° — Performance Consultiva do técnico no mesmo recorte temporal
    if consultivo_frame is not None and not consultivo_frame.empty:
        cons_res = resumo_consultivo_tecnico(
            consultivo_frame,
            selected,
            login=login_val,
            period_start=period_start,
            period_end=period_end,
        )
        section_heading(
            "Performance Consultiva (Visão 360° Individual)",
            "Resultados comerciais do técnico no NetSales dentro da mesma janela",
        )
        c360 = st.columns(4)
        with c360[0]:
            metric_card(
                "CONSULTIVOS",
                formatar_numero_br(cons_res["consultivos"]),
                "Atendimentos consultivos no período",
                "🎯",
                "",
                "kpi-card--laranja",
            )
        with c360[1]:
            metric_card(
                "PRODUTOS VENDIDOS",
                formatar_numero_br(cons_res["produtos"]),
                f"Conversão: {cons_res['conversao_pct']:.1f}%".replace(".", ","),
                "📦",
                "",
                "kpi-card--verde",
            )
        with c360[2]:
            metric_card(
                "MIX · MESH / TV / VIRTUA",
                f"{cons_res['mesh']} / {cons_res['tv']} / {cons_res['virtua']}",
                "Distribuição por produto comercializado",
                "🧩",
                "",
                "kpi-card--azul",
            )
        with c360[3]:
            contratos_tec = (
                int(
                    technician_data.loc[
                        technician_data["contract"].ne("Sem contrato"), "contract"
                    ].nunique()
                )
                if "contract" in technician_data.columns
                else 0
            )
            pen_tec = (
                cons_res["consultivos"] / contratos_tec * 100.0
                if contratos_tec > 0
                else 0.0
            )
            metric_card(
                "PENETRAÇÃO CONSULTIVA",
                f"{pen_tec:.1f}%".replace(".", ","),
                f"{cons_res['consultivos']} cons. ÷ {contratos_tec} contratos",
                "🔗",
                "",
                "kpi-card--roxo",
            )

    team_monthly = summarize(filtered, "period").sort_values("period")
    active_by_month = filtered.groupby("period")["technician"].nunique()
    team_monthly["team_average"] = team_monthly["points_total"].div(
        team_monthly["period"].map(active_by_month).fillna(1).replace(0, 1)
    )
    monthly["label"] = monthly["period"].map(month_label)
    team_monthly["label"] = team_monthly["period"].map(month_label)
    fig = go.Figure()
    fig.add_bar(
        x=monthly["label"],
        y=monthly["points_total"],
        name=selected,
        marker_color=COLORS["green"],
        text=[format_points(value) for value in monthly["points_total"]],
        textposition="outside",
        textfont=dict(size=10, color="#012869"),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y:,.2f} pontos<extra></extra>",
    )
    fig.add_scatter(
        x=team_monthly["label"],
        y=team_monthly["team_average"],
        name="Média da equipe",
        mode="lines+markers",
        line=dict(color="#F37C04", width=2, dash="dot"),
        marker=dict(size=6),
        hovertemplate="<b>%{x}</b><br>Média: %{y:,.2f}<extra></extra>",
    )
    maximum = max(monthly["points_total"].max(), team_monthly["team_average"].max())
    fig.update_yaxes(range=[0, maximum * 1.25 if maximum else 1])
    chart_layout(fig)
    with st.container(border=True):
        st.markdown("**Evolução individual**")
        st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)

    detail = monthly.sort_values("period", ascending=False).copy()
    detail["Competência"] = detail["period"].map(month_label)
    detail = detail.rename(
        columns={
            "points_prod": "Prod",
            "points_gpon": "Gpon",
            "points_total": "Pontos Totais",
        }
    )
    st.caption("Pontos Totais = Prod + Gpon; os valores são exibidos em cinza.")
    st.dataframe(
        detail[["Competência", "Prod", "Gpon", "Pontos Totais"]].style.map(
            _total_points_style, subset=["Pontos Totais"]
        ),
        width="stretch",
        hide_index=True,
        alt="Produção e pontos GPON por competência no período selecionado",
        column_config={
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    # Comparação direta (Lado a Lado) com outro técnico do recorte
    outros = [n for n in names if n != selected]
    if outros:
        section_heading(
            "Comparação Direta (Lado a Lado)",
            "Compare a curva mensal e o acumulado do técnico selecionado frente a outro colaborador",
        )
        comparado = st.selectbox(
            "Comparar com",
            options=["Nenhum", *outros],
            index=0,
            key="technician_compare_peer",
        )
        if comparado and comparado != "Nenhum":
            peer_data = filtered[filtered["technician"].eq(comparado)]
            peer_monthly = summarize(peer_data, "period").sort_values("period")
            peer_totals = ranking[ranking["technician"].eq(comparado)].iloc[0]
            comp_df = (
                monthly[["period", "points_total"]]
                .rename(columns={"points_total": selected})
                .merge(
                    peer_monthly[["period", "points_total"]].rename(
                        columns={"points_total": comparado}
                    ),
                    on="period",
                    how="outer",
                )
                .fillna(0.0)
                .sort_values("period")
            )
            comp_df["Competência"] = comp_df["period"].map(month_label)

            fig_h2h = go.Figure()
            fig_h2h.add_bar(
                x=comp_df["Competência"],
                y=comp_df[selected],
                name=selected,
                marker_color=COLORS["green"],
            )
            fig_h2h.add_bar(
                x=comp_df["Competência"],
                y=comp_df[comparado],
                name=comparado,
                marker_color="#F37C04",
            )
            fig_h2h.update_layout(barmode="group")
            chart_layout(fig_h2h, height=330)
            with st.container(border=True):
                st.plotly_chart(
                    fig_h2h,
                    width="stretch",
                    config=CHART_CONFIG,
                    key="technician_h2h_chart",
                )
            diff_pts = float(totals["points_total"]) - float(
                peer_totals["points_total"]
            )
            st.caption(
                f"Diferença acumulada no período: **{selected}** "
                f"({format_points(totals['points_total'])} pts) vs **{comparado}** "
                f"({format_points(peer_totals['points_total'])} pts) · "
                f"Δ {formatar_delta_decimal_br(diff_pts, 2, 'pts')}."
            )


@st.cache_resource(show_spinner=False)
def _initialize_demo_once(db_path_key: str) -> None:
    """Cria a base de demonstração uma vez por banco configurado."""
    del db_path_key
    create_demonstration()


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _load_sidebar_stats(db_path_key: str) -> dict[str, Any]:
    """Lê apenas metadados agregados no SQLite para a sidebar (sem carregar DataFrames)."""
    del db_path_key
    return database_stats()


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _load_dashboard_snapshot(db_path_key: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Mantém a leitura da base em cache até uma atualização explícita."""
    del db_path_key
    return load_dashboard_snapshot()


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _load_roster_cached(db_path_key: str) -> pd.DataFrame:
    """Mantém o quadro cadastral em cache até uma atualização explícita."""
    del db_path_key
    return load_roster()


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _load_consultivo_cached(db_path_key: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Mantém o histórico consultivo em cache até uma atualização explícita."""
    del db_path_key
    return load_consultivo_snapshot()


@st.cache_data(ttl=1800, max_entries=8, show_spinner=False)
def _gerar_pacote_geral_xlsx_cached(
    filtered_prod: pd.DataFrame,
    db_path_key: str,
) -> bytes:
    """Gera o Pacote Executivo multi-aba (.xlsx) a partir do recorte filtrado."""
    cons_df, _ = _load_consultivo_cached(db_path_key)
    roster_df = _load_roster_cached(db_path_key)
    return gerar_pacote_executivo_xlsx(
        filtered_prod,
        cons_df,
        roster_df,
        periodo_label=str(st.session_state.get("period_filter", "Recorte ativo")),
    )


def _trim_for_test_runtime(
    frame: pd.DataFrame, stats: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reduz a massa de dados em testes de UI sem alterar o comportamento em produção."""
    if os.getenv("PYTEST_CURRENT_TEST") is None or frame.empty:
        return frame, stats
    if len(frame) <= 2500:
        return frame, stats
    recent = frame.sort_values("reference_date", ascending=False).head(2500).copy()
    recent["reference_date"] = pd.to_datetime(recent["reference_date"])
    recent["period"] = recent["reference_date"].dt.to_period("M").dt.to_timestamp()
    trimmed_stats = dict(stats)
    trimmed_stats["records"] = len(recent)
    trimmed_stats["technicians"] = int(recent["technician"].nunique())
    return recent, trimmed_stats


def _drive_service_account() -> Mapping[str, Any] | None:
    try:
        return cast(Mapping[str, Any], st.secrets["gcp_service_account"])
    except (KeyError, StreamlitSecretNotFoundError):
        raw_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if raw_env:
            try:
                parsed = json.loads(raw_env)
                if isinstance(parsed, Mapping):
                    return parsed
            except ValueError:
                return None
        return None


def _sync_roster_sheet_worker(
    service_account: Mapping[str, Any] | None, *, force: bool = False
) -> tuple[bool, str, bool]:
    """Sincroniza lista_ativos sem tocar em APIs de UI do Streamlit (thread-safe)."""
    known_fp = None if force else get_roster_fingerprint(ROSTER_SHEET_ID)
    try:
        roster_result = import_roster_spreadsheet(
            service_account,
            ROSTER_SHEET_ID,
            known_fingerprint=known_fp,
            allow_public_fallback=True,
        )
    except DriveImportError as error:
        logger.warning("falha_sincronizacao_cadastro", erro=str(error))
        return False, f"Falha ao sincronizar lista_ativos: {error}", False

    if roster_result.refreshed:
        saved = save_roster_records(
            roster_result.records,
            is_demo=False,
            sheet_id=ROSTER_SHEET_ID,
            fingerprint=roster_result.fingerprint,
        )
        return (
            True,
            f"Cadastro '{roster_result.sheet_name}' atualizado ({saved} colaboradores).",
            True,
        )
    return True, f"Cadastro '{roster_result.sheet_name}' já está atualizado.", False


def _sync_roster_sheet(*, force: bool = False) -> tuple[bool, str]:
    """Sincroniza a planilha lista_ativos sob demanda ou ao abrir a sessão."""
    ok, msg, refreshed = _sync_roster_sheet_worker(
        _drive_service_account(), force=force
    )
    if refreshed:
        _load_sidebar_stats.clear()
        _load_dashboard_snapshot.clear()
        _load_roster_cached.clear()
        _load_consultivo_cached.clear()
    return ok, msg


def _sync_consultivo_folder_worker(
    service_account: Mapping[str, Any] | None, *, force: bool = False
) -> tuple[bool, str, list[str], list[str]]:
    """Sincroniza pasta Histórico Consultivo sem tocar em st.session_state (thread-safe)."""
    if service_account is None:
        return (
            False,
            "Conta de serviço do Google Drive não configurada para Histórico Consultivo.",
            [],
            [],
        )
    known_fps = {} if force else get_consultivo_file_fingerprints(CONSULTIVO_FOLDER_ID)
    try:
        cons_result = import_consultivo_folder_snapshot(
            service_account,
            CONSULTIVO_FOLDER_ID,
            known_file_fingerprints=known_fps,
        )
    except DriveImportError as error:
        logger.warning("falha_sincronizacao_consultivo", erro=str(error))
        err_msg = f"Falha ao sincronizar Histórico Consultivo: {error}"
        return False, err_msg, [err_msg], [err_msg]

    saved = sync_consultivo_drive_records(
        cons_result.records,
        cons_result.file_ids,
        cons_result.refreshed_file_ids,
        folder_id=CONSULTIVO_FOLDER_ID,
        file_fingerprints=cons_result.file_fingerprints,
    )
    issues_top = list(cons_result.issues[:20])
    msg = (
        f"Consultivo sincronizado: {saved} registros atualizados "
        f"({cons_result.successful_files}/{len(cons_result.file_ids)} arquivo(s))."
    )
    return True, msg, list(cons_result.issues[:10]), issues_top


def _sync_consultivo_folder(*, force: bool = False) -> tuple[bool, str, list[str]]:
    """Sincroniza a pasta Histórico Consultivo do Google Drive."""
    ok, msg, issues_short, issues_top = _sync_consultivo_folder_worker(
        _drive_service_account(), force=force
    )
    if ok:
        _load_consultivo_cached.clear()
    if ok or issues_top:
        st.session_state["consultivo_sync_issues"] = issues_top
        st.session_state["_last_consultivo_sync_ts"] = time.time()
    return ok, msg, issues_short


def _sync_drive_production_worker(
    service_account: Mapping[str, Any], *, force: bool = False
) -> tuple[bool, int, int, int, list[str], str]:
    """Sincroniza a pasta de Produção no Google Drive (thread-safe)."""
    try:
        known_file_fingerprints = (
            {} if force else get_drive_file_fingerprints(DRIVE_FOLDER_ID)
        )
        drive_result = import_drive_folder_snapshot(
            service_account,
            DRIVE_FOLDER_ID,
            known_file_fingerprints=known_file_fingerprints,
        )
    except DriveImportError as error:
        logger.error("falha_sincronizacao_drive", erro=str(error))
        return False, 0, 0, 0, [], str(error)

    count = sync_drive_records(
        drive_result.records,
        drive_result.file_ids,
        drive_result.refreshed_file_ids,
        folder_id=DRIVE_FOLDER_ID,
        file_fingerprints=drive_result.file_fingerprints,
    )
    return (
        True,
        count,
        drive_result.successful_files,
        len(drive_result.file_ids),
        list(drive_result.issues[:10]),
        "",
    )


def _sync_external_data(*, force: bool = False) -> dict[str, Any]:
    """Sincroniza Drive (produção e consultivo) e cadastro em paralelo."""
    drive_service_account = _drive_service_account()
    if drive_service_account is None:
        if os.getenv("ROSTER_PUBLIC_SYNC", "0") == "1":
            roster_ok, roster_msg = _sync_roster_sheet(force=force)
            return {
                "type": "success" if roster_ok else "warning",
                "message": roster_msg,
                "issues": [],
            }
        return {
            "type": "info",
            "message": (
                "Atualização automática do Drive não configurada. "
                "Configure a conta de serviço para habilitá-la."
            ),
            "issues": [],
        }

    # Executa as 3 sincronizações de rede/I/O em paralelo para reduzir o tempo de abertura.
    with ThreadPoolExecutor(max_workers=3) as executor:
        fut_roster = executor.submit(
            _sync_roster_sheet_worker, drive_service_account, force=force
        )
        fut_cons = executor.submit(
            _sync_consultivo_folder_worker, drive_service_account, force=force
        )
        fut_prod = executor.submit(
            _sync_drive_production_worker, drive_service_account, force=force
        )
        roster_ok, roster_msg, roster_refreshed = fut_roster.result()
        cons_ok, cons_msg, cons_issues, cons_issues_top = fut_cons.result()
        prod_ok, count, ok_files, total_files, prod_issues, prod_err = fut_prod.result()

    st.session_state["consultivo_sync_issues"] = cons_issues_top
    st.session_state["_last_consultivo_sync_ts"] = time.time()

    if roster_refreshed or cons_ok or prod_ok:
        _load_sidebar_stats.clear()
        _load_dashboard_snapshot.clear()
        _load_roster_cached.clear()
        _load_consultivo_cached.clear()

    if not prod_ok:
        return {
            "type": "warning",
            "message": (
                f"Falha ao atualizar os dados do Drive: {prod_err} · "
                f"{cons_msg} · {roster_msg}"
            ),
            "issues": cons_issues,
        }

    all_issues = prod_issues + cons_issues
    if not roster_ok:
        all_issues.insert(0, roster_msg)
    if not cons_ok:
        all_issues.insert(0, cons_msg)
    status = {
        "type": "warning" if all_issues else "success",
        "message": (
            f"Drive sincronizado: {count} registros atualizados; "
            f"{ok_files} arquivo(s) processado(s) "
            f"de {total_files}. {cons_msg} {roster_msg}"
        ),
        "issues": all_issues,
    }
    logger.info(
        "sincronizacao_drive_sucesso",
        registros_sincronizados=count,
        arquivos_processados=ok_files,
        total_issues=len(all_issues),
    )
    return status


_BG_SYNC_LOCK = threading.Lock()
_BG_SYNC_STATE: dict[str, Any] = {
    "running": False,
    "status": None,
    "finished_at": 0.0,
}


def _run_background_sync_thread(
    service_account: Mapping[str, Any],
) -> None:
    """Executa a sincronização paralela do Drive fora do caminho crítico de render."""
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_roster = executor.submit(
                _sync_roster_sheet_worker, service_account, force=False
            )
            fut_cons = executor.submit(
                _sync_consultivo_folder_worker, service_account, force=False
            )
            fut_prod = executor.submit(
                _sync_drive_production_worker, service_account, force=False
            )
            roster_ok, roster_msg, roster_refreshed = fut_roster.result()
            cons_ok, cons_msg, cons_issues, _ = fut_cons.result()
            prod_ok, count, ok_files, total_files, prod_issues, prod_err = (
                fut_prod.result()
            )

        if roster_refreshed or cons_ok or prod_ok:
            _load_sidebar_stats.clear()
            _load_dashboard_snapshot.clear()
            _load_roster_cached.clear()
            _load_consultivo_cached.clear()

        if not prod_ok:
            status: dict[str, Any] = {
                "type": "warning",
                "message": (
                    f"Falha ao atualizar os dados do Drive: {prod_err} · "
                    f"{cons_msg} · {roster_msg}"
                ),
                "issues": cons_issues,
            }
        else:
            all_issues = prod_issues + cons_issues
            if not roster_ok:
                all_issues.insert(0, roster_msg)
            if not cons_ok:
                all_issues.insert(0, cons_msg)
            status = {
                "type": "warning" if all_issues else "success",
                "message": (
                    f"Drive sincronizado em segundo plano: {count} registros; "
                    f"{ok_files}/{total_files} arquivo(s). {cons_msg} {roster_msg}"
                ),
                "issues": all_issues,
            }
    except Exception as exc:
        logger.warning("falha_sync_background", erro=str(exc))
        status = {
            "type": "warning",
            "message": f"Falha na sincronização em segundo plano: {exc}",
            "issues": [],
        }
    finally:
        with _BG_SYNC_LOCK:
            _BG_SYNC_STATE["running"] = False
            _BG_SYNC_STATE["status"] = status
            _BG_SYNC_STATE["finished_at"] = time.time()


def _trigger_cache_first_auto_sync() -> dict[str, Any]:
    """Usa base SQLite local imediatamente quando já populada; dispara Drive em background."""
    drive_sa = _drive_service_account()
    in_pytest = os.getenv("PYTEST_CURRENT_TEST") is not None
    if drive_sa is not None and not in_pytest:
        pre_stats = database_stats()
        has_real_local_data = bool(
            pre_stats.get("records", 0) > 0
            and pre_stats.get("demo_rows", 0) < pre_stats.get("records", 0)
        )
        if has_real_local_data:
            with _BG_SYNC_LOCK:
                if not _BG_SYNC_STATE["running"]:
                    _BG_SYNC_STATE["running"] = True
                    worker = threading.Thread(
                        target=_run_background_sync_thread,
                        args=(dict(drive_sa),),
                        daemon=True,
                        name="totale-drive-bg-sync",
                    )
                    worker.start()
            return {
                "type": "info",
                "message": (
                    "Base local carregada instantaneamente (cache-first). "
                    "Sincronização incremental com o Google Drive em andamento em segundo plano."
                ),
                "issues": [],
            }
    return _sync_external_data(force=False)


logger.info(
    "aplicacao_iniciando",
    pasta_drive=DRIVE_FOLDER_ID,
    pasta_consultivo=CONSULTIVO_FOLDER_ID,
    planilha_cadastro=ROSTER_SHEET_ID,
)

# Preserva a sincronização automática da pasta do Drive e da planilha lista_ativos:
# com dados locais já presentes, abre instantaneamente (cache-first) e atualiza em segundo plano.
init_database()
logger.info("banco_dados_inicializado")
_AUTO_SYNC_VERSION_TAG = (
    f"{IMPORT_PARSER_VERSION}|{ROSTER_PARSER_VERSION}|{CONSULTIVO_PARSER_VERSION}"
)
if (
    "drive_auto_sync_attempted" not in st.session_state
    or st.session_state.get("drive_auto_sync_version") != _AUTO_SYNC_VERSION_TAG
):
    st.session_state["drive_auto_sync_attempted"] = True
    st.session_state["drive_auto_sync_version"] = _AUTO_SYNC_VERSION_TAG
    st.session_state["drive_auto_sync_status"] = _trigger_cache_first_auto_sync()
else:
    with _BG_SYNC_LOCK:
        if _BG_SYNC_STATE["status"] is not None:
            st.session_state["drive_auto_sync_status"] = _BG_SYNC_STATE["status"]

_active_db_key = str(production_mod.DB_PATH)
_initialize_demo_once(_active_db_key)
stats = _load_sidebar_stats(_active_db_key)
logger.info(
    "dashboard_carregado",
    total_registros=stats.get("records", 0),
    total_tecnicos=stats.get("technicians", 0),
    dados_demonstracao=stats.get("demo_rows", 0),
)


def _abrir_comparativo_anos() -> None:
    st.session_state["navigation"] = "Comparativo 2025 x 2026"


def _abrir_comparativo_consultivo() -> None:
    st.session_state["navigation"] = "Consultivo 2025 x 2026"


def _abrir_painel_consultivo() -> None:
    st.session_state["navigation"] = "Consultivo"


def _resumo_janela_sidebar_stats(db_stats: Mapping[str, Any]) -> tuple[str, int]:
    first_dt = db_stats.get("first_date")
    last_dt = db_stats.get("last_date")
    qtd = int(db_stats.get("months_count") or 0)
    if not first_dt or not last_dt:
        return "Sem dados", 0
    inicio = month_label(pd.Timestamp(str(first_dt)))
    fim = month_label(pd.Timestamp(str(last_dt)))
    janela = inicio if inicio == fim else f"{inicio} – {fim}"
    return janela, qtd


with st.sidebar:
    render_sidebar_brand(
        nome="TOTALE",
        subtitulo="Inteligência & Gestão Operacional",
        versao="2025 · 2026",
        logo=LOGO_PADRAO_TOTALE,
        logo_banner=True,
    )
    _sb_is_demo = bool(
        stats.get("records") and stats.get("demo_rows") == stats.get("records")
    )
    _sb_janela, _sb_competencias = _resumo_janela_sidebar_stats(stats)
    render_sidebar_pulse(
        status_label="Modo Demonstração"
        if _sb_is_demo
        else (
            "Drive Conectado" if _drive_service_account() is not None else "Base Local"
        ),
        tipo="alerta" if _sb_is_demo else "ok",
        escopo=_sb_janela,
        metricas=[
            ("Registros", formatar_numero_br(stats.get("records", 0))),
            ("Técnicos", formatar_numero_br(stats.get("technicians", 0))),
            ("Competências", f"{_sb_competencias} meses"),
            ("Arquivos", formatar_numero_br(stats.get("files", 0))),
        ],
        fontes=("Produção", "lista_ativos", "Consultivo"),
    )
    render_sidebar_section("Módulos Executivos", icone="🧭")
    nav_labels = {
        "Visão geral": ":material/dashboard:  Visão Executiva · Produção",
        "Visão 360°": ":material/hub:  Visão 360° · Prod × Consultivo",
        "Radar de Alertas": ":material/notifications_active:  Radar de Alertas",
        "Scorecard Supervisão": ":material/leaderboard:  Scorecard · Monitor & Base",
        "Comparativo 2025 x 2026": ":material/compare_arrows:  Produção 2025 × 2026",
        "Consultivo 2025 x 2026": ":material/trending_up:  Consultivo 2025 × 2026",
        "Consultivo": ":material/support_agent:  Performance Consultiva",
        "Projetos": ":material/account_tree:  Gestão por Projeto",
        "Quantidade de O.S.": ":material/assignment:  Ordens de Serviço (O.S.)",
        "Contratos": ":material/description:  Gestão de Contratos",
        "Produtividade unitária": ":material/speed:  Produtividade Unitária",
        "Qualidade & Ritmo": ":material/verified:  Qualidade, Reincidência & Ritmo",
        "Regularidade": ":material/calendar_month:  Regularidade & Sazonalidade",
        "Eficiência": ":material/bolt:  Matriz de Eficiência",
        "Técnicos": ":material/person:  Desempenho Individual",
        "Turnover & Ramp-up": ":material/group_remove:  Turnover & Curva de Ramp-up",
        "Quadro de técnicos": ":material/groups:  Quadro Cadastral (Ativos)",
        "Saúde dos dados": ":material/monitor_heart:  Governança & Dados",
    }
    nav_groups: dict[str, list[str]] = {
        "Todos": list(nav_labels),
        "Executivo": [
            "Visão geral",
            "Visão 360°",
            "Radar de Alertas",
            "Scorecard Supervisão",
            "Comparativo 2025 x 2026",
        ],
        "Operação": [
            "Projetos",
            "Quantidade de O.S.",
            "Contratos",
            "Produtividade unitária",
            "Qualidade & Ritmo",
            "Regularidade",
            "Eficiência",
        ],
        "Comercial": [
            "Consultivo",
            "Consultivo 2025 x 2026",
            "Visão 360°",
        ],
        "Pessoas & Dados": [
            "Técnicos",
            "Turnover & Ramp-up",
            "Quadro de técnicos",
            "Saúde dos dados",
        ],
    }

    # Aplica navegação pendente (drill-down 1-clique ou query param ?page=).
    pending_group = st.session_state.pop("_pending_sidebar_group", None)
    if isinstance(pending_group, str) and pending_group in nav_groups:
        st.session_state["sidebar_nav_group"] = pending_group
    pending_nav = st.session_state.pop("_pending_navigation", None)
    if isinstance(pending_nav, str) and pending_nav in nav_labels:
        st.session_state["navigation"] = pending_nav
    elif not st.session_state.get("_totale_qp_page_hydrated"):
        st.session_state["_totale_qp_page_hydrated"] = True
        try:
            qp_page = str(st.query_params.get("page", "") or "").strip()
        except Exception:
            qp_page = ""
        if qp_page in nav_labels and "navigation" not in st.session_state:
            st.session_state["navigation"] = qp_page

    selected_group = st.selectbox(
        "Categoria de módulos",
        options=list(nav_groups),
        index=0,
        key="sidebar_nav_group",
        label_visibility="collapsed",
        help="Filtre os módulos por área ou mantenha 'Todos' para exibir os 18 painéis.",
    )
    visible_nav_options = nav_groups.get(str(selected_group), list(nav_labels))
    # Evita seleções de navegação fora das opções visíveis.
    if st.session_state.get("navigation") not in (None, *visible_nav_options):
        st.session_state["navigation"] = visible_nav_options[0]
    navigation = st.radio(
        "Navegação",
        visible_nav_options,
        format_func=nav_labels.get,
        label_visibility="collapsed",
        key="navigation",
    )
    render_sidebar_divider(label="Sincronização", estilo="gradiente")
    if st.button(
        "Atualizar dados",
        key="refresh_data_button",
        type="primary",
        icon=":material/refresh:",
        width="stretch",
    ):
        with st.spinner("Atualizando os dados da base..."):
            sync_status = _sync_external_data(force=True)
            _load_sidebar_stats.clear()
            _load_dashboard_snapshot.clear()
            _load_roster_cached.clear()
            _load_consultivo_cached.clear()
            st.session_state["drive_auto_sync_status"] = sync_status
            stats = _load_sidebar_stats(_active_db_key)
        status_renderer = {
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "info": st.info,
        }.get(str(sync_status["type"]), st.info)
        status_renderer(str(sync_status["message"]))
    render_sidebar_section("Aparência", icone="🎨")
    render_sidebar_theme_selector(
        label="Tema da barra lateral",
        help="Escolha entre os temas claro corporativo, navy executivo e terracota.",
        mostrar_icone=True,
    )
    render_sidebar_footer_info(
        itens={
            "Registros": formatar_numero_br(stats["records"]),
            "Técnicos": formatar_numero_br(stats["technicians"]),
        },
        unidade="Sincronização sob demanda e na abertura",
        ambiente="Demo" if _sb_is_demo else "Produção",
        copyright="Totale · Inteligência & Gestão Operacional",
    )


def _render_governanca_avancada(
    records: pd.DataFrame,
    roster: pd.DataFrame,
) -> None:
    """Renderiza ferramentas de governança: De-Para de técnicos/logins e Backup SQLite."""
    section_heading(
        "De-Para de Técnicos & Logins NetSales",
        "Corrija nomes divergentes ou logins antigos sem alterar as planilhas de origem.",
    )
    with st.container(border=True):
        aliases_df = load_technician_aliases()
        nomes_canonicos: set[str] = set()
        if not roster.empty and "technician" in roster.columns:
            nomes_canonicos.update(
                str(n).strip()
                for n in roster["technician"].dropna().unique()
                if str(n).strip()
            )
        if not records.empty and "technician" in records.columns:
            nomes_canonicos.update(
                str(n).strip()
                for n in records["technician"].dropna().unique()
                if str(n).strip()
            )
        opcoes_canonicas = sorted(nomes_canonicos)

        c1, c2, c3, c4 = st.columns([0.9, 1.3, 1.5, 1.1])
        with c1:
            alias_tipo = st.selectbox(
                "Tipo de de-para",
                options=["name", "login"],
                format_func=lambda v: (
                    "Nome divergente" if v == "name" else "Login NetSales"
                ),
                key="gov_alias_type",
            )
        with c2:
            alias_origem = st.text_input(
                "Valor na planilha (origem)",
                placeholder="Ex.: JOAO SILVA ou Z649999",
                key="gov_alias_source",
            )
        with c3:
            if opcoes_canonicas:
                alias_destino = st.selectbox(
                    "Técnico canônico (destino)",
                    options=opcoes_canonicas,
                    key="gov_alias_target_sel",
                )
            else:
                alias_destino = st.text_input(
                    "Técnico canônico (destino)",
                    placeholder="Nome oficial no cadastro",
                    key="gov_alias_target_txt",
                )
        with c4:
            alias_nota = st.text_input(
                "Observação",
                placeholder="Opcional",
                key="gov_alias_notes",
            )

        if st.button(
            "Salvar regra De-Para",
            key="gov_alias_save_btn",
            type="primary",
            icon=":material/link:",
        ):
            if alias_origem.strip() and str(alias_destino or "").strip():
                saved_ok = save_technician_alias(
                    cast(Any, alias_tipo),
                    alias_origem.strip(),
                    str(alias_destino).strip(),
                    notes=alias_nota.strip(),
                )
                if saved_ok:
                    _load_dashboard_snapshot.clear()
                    _load_consultivo_cached.clear()
                    st.success("Regra De-Para salva e caches recarregados.")
                    st.rerun()
            else:
                st.warning("Informe o valor de origem e o técnico canônico de destino.")

        if aliases_df.empty:
            st.caption("Nenhuma regra De-Para cadastrada até o momento.")
        else:
            st.dataframe(aliases_df, width="stretch", hide_index=True)
            rem_c1, rem_c2 = st.columns([2.5, 1.0], vertical_alignment="bottom")
            with rem_c1:
                id_opcoes = aliases_df["id"].astype(int).tolist()
                rotulos_id = {
                    int(r_id): f"#{int(r_id)} · [{r_tipo}] {r_src} → {r_dst}"
                    for r_id, r_tipo, r_src, r_dst in zip(
                        aliases_df["id"].tolist(),
                        aliases_df["alias_type"].tolist(),
                        aliases_df["source_value"].tolist(),
                        aliases_df["canonical_technician"].tolist(),
                        strict=False,
                    )
                }
                alias_rem = st.selectbox(
                    "Remover regra existente",
                    options=id_opcoes,
                    format_func=lambda i: rotulos_id.get(int(i), str(i)),
                    key="gov_alias_delete_select",
                )
            with rem_c2:
                if st.button(
                    "Remover regra",
                    key="gov_alias_delete_btn",
                    use_container_width=True,
                ):
                    delete_technician_alias(int(alias_rem))
                    _load_dashboard_snapshot.clear()
                    _load_consultivo_cached.clear()
                    st.success("Regra removida com sucesso.")
                    st.rerun()

    section_heading(
        "Backup Seguro do Banco SQLite (WAL-Safe)",
        "Gera uma cópia consistente via API nativa sqlite3.backup() com PRAGMA optimize.",
    )
    with st.container(border=True):
        b_col1, b_col2 = st.columns([1.4, 2.6], vertical_alignment="center")
        with b_col1:
            if st.button(
                "Gerar snapshot de backup (.db)",
                key="gov_generate_backup_btn",
                icon=":material/backup:",
                use_container_width=True,
            ):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    snap_path = backup_database(Path(tmp_dir) / "totale_backup.db")
                    if snap_path and snap_path.exists():
                        st.session_state["_gov_backup_bytes"] = snap_path.read_bytes()
                        st.session_state["_gov_backup_name"] = (
                            f"totale_producao_backup_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.db"
                        )
        with b_col2:
            if st.session_state.get("_gov_backup_bytes"):
                st.download_button(
                    "⬇️ Baixar backup SQLite (.db)",
                    data=st.session_state["_gov_backup_bytes"],
                    file_name=str(
                        st.session_state.get("_gov_backup_name", "totale_backup.db")
                    ),
                    mime="application/x-sqlite3",
                    key="gov_download_backup_btn",
                )
            else:
                st.caption(
                    "Clique em 'Gerar snapshot de backup (.db)' para criar uma cópia íntegra pronta para download."
                )


def render_dashboard() -> None:
    """Renderiza o painel com lazy loading por módulo (carrega apenas o necessário)."""
    render_t0 = time.perf_counter()
    db_key = str(production_mod.DB_PATH)
    _paginas_somente_consultivo = ("Consultivo", "Consultivo 2025 x 2026")
    _paginas_com_consultivo = (
        "Visão 360°",
        "Radar de Alertas",
        "Scorecard Supervisão",
        "Consultivo",
        "Consultivo 2025 x 2026",
        "Comparativo 2025 x 2026",
        "Técnicos",
        "Saúde dos dados",
    )
    _paginas_com_roster = (
        "Visão 360°",
        "Radar de Alertas",
        "Scorecard Supervisão",
        "Consultivo",
        "Consultivo 2025 x 2026",
        "Comparativo 2025 x 2026",
        "Turnover & Ramp-up",
        "Quadro de técnicos",
        "Saúde dos dados",
    )

    try:
        if navigation and st.query_params.get("page") != navigation:
            st.query_params["page"] = str(navigation)
    except Exception:
        logger.debug("falha_sync_query_param_page", exc_info=True)

    if navigation in _paginas_somente_consultivo:
        current_records = pd.DataFrame()
        current_stats = _load_sidebar_stats(db_key)
    else:
        current_records, current_stats = _load_dashboard_snapshot(db_key)
        current_records, current_stats = _trim_for_test_runtime(
            current_records, current_stats
        )

    is_demo = bool(
        current_stats["records"]
        and current_stats["demo_rows"] == current_stats["records"]
    )
    page_titles = {
        "Visão geral": (
            "Visão Executiva · Produção Operacional",
            "Monitoramento consolidado de pontuação técnica (Prod + Gpon), produtividade e evolução das equipes.",
        ),
        "Visão 360°": (
            "Visão 360° Operacional × Comercial",
            "Cruzamento integrado entre Produção Técnica (Prod + Gpon, O.S. e Contratos) e Performance Consultiva (NetSales) por Técnico, Monitor, Base e U.N.",
        ),
        "Radar de Alertas": (
            "Radar de Alertas & Gestão à Vista",
            "Sinalizações priorizadas de oportunidades de virada de faixa, quedas MoM, ativos sem apontamento, lacunas consultivas e governança.",
        ),
        "Scorecard Supervisão": (
            "Scorecard de Supervisão · Monitor, Base e U.N.",
            "Avaliação consolidada de span of control, cobertura produtiva, dispersão interna, participação em Faixas 4–5 e conversão comercial.",
        ),
        "Comparativo 2025 x 2026": (
            "Comparativo Interanual 2025 × 2026 · Produção, Contratos e O.S.",
            "Análise interanual de pontuação, contratos distintos, ordens de serviço (Prod), giro O.S./contrato e evolução por equipe.",
        ),
        "Consultivo 2025 x 2026": (
            "Comparativo Interanual 2025 × 2026 · Performance Consultiva",
            "Análise interanual de consultivos realizados, mix comercial (Mesh, TV Box, Virtua), conversão e metas por equipe.",
        ),
        "Projetos": (
            "Gestão Operacional por Projeto",
            "Comparativo executivo de pontuação, ordens de serviço e participação percentual por frente de projeto.",
        ),
        "Quantidade de O.S.": (
            "Gestão de Ordens de Serviço (O.S.)",
            "Acompanhamento de ordens de serviço produtivas (aba Prod) por competência, projeto e técnico.",
        ),
        "Contratos": (
            "Gestão & Eficiência de Contratos",
            "Monitoramento de contratos distintos atendidos por competência, técnico e faixa de eficiência operacional.",
        ),
        "Produtividade unitária": (
            "Produtividade Unitária & Densidade Técnica",
            "Relação entre pontos por O.S., pontos por contrato e posicionamento volume × complexidade da equipe.",
        ),
        "Qualidade & Ritmo": (
            "Qualidade, Reincidência & Ritmo Diário",
            "Auditoria de reincidência por contrato/O.S., cadência por dia da semana (Seg–Sáb) e projeção de fechamento mensal.",
        ),
        "Consultivo": (
            "Performance Consultiva & Mix Comercial",
            "Indicadores consolidados de consultivos realizados, funil NetSales, mix de planos e vínculo com o quadro ativo.",
        ),
        "Regularidade": (
            "Regularidade Operacional & Sazonalidade",
            "Análise estatística de médias, medianas, coeficiente de variação, lacunas e mapa de calor mensal por técnico ou projeto.",
        ),
        "Eficiência": (
            "Matriz de Eficiência Mensal por Técnico",
            "Classificação mensal de faixas de entrega e predominância histórica de performance da equipe.",
        ),
        "Técnicos": (
            "Desempenho Individual de Técnicos",
            "Dossiê individual técnico + consultivo, melhor competência e comparação direta lado a lado.",
        ),
        "Turnover & Ramp-up": (
            "Turnover, Capacidade Perdida & Curva de Ramp-up",
            "Análise de desligamentos, motivos, perda de capacidade produtiva mensal e curva de maturação de novos técnicos.",
        ),
        "Quadro de técnicos": (
            "Quadro Cadastral & Conciliação de Ativos",
            "Conciliação executiva entre o cadastro oficial (lista_ativos / desligados) e entregas por Monitor, U.N. e Base.",
        ),
        "Saúde dos dados": (
            "Governança de Dados & Auditoria de Importações",
            "Rastreabilidade de cobertura, lotes sincronizados no Google Drive, auditoria de contratos por arquivo e exportação CSV.",
        ),
    }
    page_badges = {
        "Visão 360°": "TOTALE · VISÃO 360°",
        "Radar de Alertas": "TOTALE · GESTÃO À VISTA",
        "Scorecard Supervisão": "TOTALE · SCORECARD DE SUPERVISÃO",
        "Projetos": "TOTALE · GESTÃO POR PROJETO",
        "Quantidade de O.S.": "TOTALE · ORDENS DE SERVIÇO",
        "Contratos": "TOTALE · GESTÃO DE CONTRATOS",
        "Produtividade unitária": "TOTALE · PERFORMANCE & PRODUTIVIDADE",
        "Qualidade & Ritmo": "TOTALE · QUALIDADE & RITMO DIÁRIO",
        "Regularidade": "TOTALE · REGULARIDADE & SAZONALIDADE",
        "Eficiência": "TOTALE · MATRIZ DE EFICIÊNCIA",
        "Técnicos": "TOTALE · DESEMPENHO INDIVIDUAL",
        "Turnover & Ramp-up": "TOTALE · RETENÇÃO & MATURAÇÃO",
        "Quadro de técnicos": "TOTALE · GOVERNANÇA CADASTRAL",
        "Saúde dos dados": "TOTALE · GOVERNANÇA DE DADOS",
    }
    title, subtitle = page_titles[navigation]
    hero_badge = page_badges.get(navigation, "TOTALE · GESTÃO OPERACIONAL")
    updated = "Aguardando dados da operação"
    if current_stats["last_import"]:
        updated = pd.Timestamp(current_stats["last_import"]).strftime(
            "Atualizado em %d/%m/%Y às %H:%M"
        )
    if navigation not in (
        "Consultivo",
        "Comparativo 2025 x 2026",
        "Consultivo 2025 x 2026",
    ):
        render_hero_totale_1(
            titulo=title,
            subtitulo=subtitle,
            badge=hero_badge,
            icone="monitoring",
            meta_info=updated,
        )

    if navigation in _paginas_com_roster:
        current_roster = _load_roster_cached(db_key)
    else:
        current_roster = pd.DataFrame()
    if navigation in _paginas_com_consultivo:
        current_consultivo, current_consultivo_stats = _load_consultivo_cached(db_key)
    else:
        current_consultivo = pd.DataFrame()
        current_consultivo_stats = {}

    _drive_consultivo_disponivel = _drive_service_account() is not None

    if navigation in _paginas_somente_consultivo and _drive_consultivo_disponivel:
        _first_cons_dt = str(current_consultivo_stats.get("first_date") or "")
        _sem_base_2025 = not _first_cons_dt or _first_cons_dt > "2025-12-31"
        _decorrido_cons = time.time() - float(
            st.session_state.get("_last_consultivo_sync_ts", 0.0)
        )
        _cooldown_cons = 15.0 if _sem_base_2025 else 90.0
        if _decorrido_cons >= _cooldown_cons:
            _ok_auto_cons, _, _ = _sync_consultivo_folder(force=False)
            if _ok_auto_cons:
                current_consultivo, current_consultivo_stats = _load_consultivo_cached(
                    db_key
                )

    def _acao_sincronizar_consultivo_manual() -> None:
        with st.spinner("Sincronizando pasta Histórico Consultivo no Google Drive..."):
            ok_sync, msg_sync, issues_sync = _sync_consultivo_folder(force=True)
        st.session_state["consultivo_manual_sync_feedback"] = (
            "warning" if (not ok_sync or issues_sync) else "success",
            msg_sync,
        )
        st.rerun()

    is_demo_consultivo = bool(
        current_consultivo_stats.get("records")
        and current_consultivo_stats.get("demo_rows")
        == current_consultivo_stats.get("records")
    )

    if (
        (navigation not in _paginas_somente_consultivo and is_demo)
        or (navigation in _paginas_somente_consultivo and is_demo_consultivo)
    ) and navigation != "Saúde dos dados":
        st.markdown(
            """
            <div class="demo-banner">
                <strong>Dados de demonstração.</strong>
                Explore os indicadores. Esta amostra será substituída quando os dados de produção estiverem sincronizados na base.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if navigation in _paginas_somente_consultivo:
        _feedback_cons = st.session_state.pop("consultivo_manual_sync_feedback", None)
        if isinstance(_feedback_cons, tuple) and len(_feedback_cons) == 2:
            _tipo_fb, _msg_fb = _feedback_cons
            if _tipo_fb == "success":
                st.success(_msg_fb)
            else:
                st.warning(_msg_fb)

    if navigation == "Consultivo":
        st.button(
            "Abrir Comparativo 2025 x 2026 de Consultivos",
            key="atalho_comp_consultivo",
            icon=":material/trending_up:",
            on_click=_abrir_comparativo_consultivo,
        )
        render_consultivo(
            current_consultivo,
            current_roster,
            consultivo_stats=current_consultivo_stats,
            consultivo_folder_id=CONSULTIVO_FOLDER_ID,
            drive_configured=_drive_consultivo_disponivel,
            on_sync_consultivo=_acao_sincronizar_consultivo_manual,
            sync_issues=st.session_state.get("consultivo_sync_issues"),
        )
    elif navigation == "Consultivo 2025 x 2026":
        render_comparativo_consultivo(
            current_consultivo,
            roster=current_roster,
            consultivo_folder_id=CONSULTIVO_FOLDER_ID,
            drive_configured=_drive_consultivo_disponivel,
            on_sync_consultivo=_acao_sincronizar_consultivo_manual,
            sync_issues=st.session_state.get("consultivo_sync_issues"),
            on_abrir_painel_consultivo=_abrir_painel_consultivo,
            on_abrir_comparativo_contratos=_abrir_comparativo_anos,
            on_dados_importados=_load_consultivo_cached.clear,
        )
    elif navigation == "Visão 360°":
        render_visao_360(
            current_records,
            current_consultivo,
            roster_frame=current_roster,
        )
    elif navigation == "Turnover & Ramp-up":
        render_turnover_rampup(
            current_records,
            roster_frame=current_roster,
        )
    elif navigation == "Comparativo 2025 x 2026":
        st.button(
            "Ver Comparativo 2025 x 2026 de Consultivos",
            key="atalho_ir_comp_consultivo",
            icon=":material/trending_up:",
            on_click=_abrir_comparativo_consultivo,
        )
        render_comparativo_anos(
            current_records,
            roster=current_roster,
            consultivo_frame=current_consultivo,
        )
    elif navigation == "Saúde dos dados":
        render_saude_dados(
            current_records,
            current_stats,
            import_batches(),
            st.session_state.get("drive_auto_sync_status"),
            consultivo_stats=current_consultivo_stats,
            lotes_consultivo=consultivo_import_batches(),
        )
        _render_governanca_avancada(current_records, current_roster)
    elif navigation == "Quadro de técnicos":
        if current_records.empty:
            render_quadro_tecnicos(
                current_records,
                current_roster,
                sheet_id=ROSTER_SHEET_ID,
            )
        else:
            filtered_quadro, *_ = apply_filters(
                current_records,
                show_technicians=False,
                apply_roster_filters=False,
            )
            render_quadro_tecnicos(
                filtered_quadro,
                current_roster,
                sheet_id=ROSTER_SHEET_ID,
            )
    elif current_records.empty:
        st.markdown(
            """
            <div class="empty-state">
                <div class="empty-icon">↻</div>
                <h2>Nenhum registro disponível</h2>
                <p>A base é carregada ao abrir o painel. Use “Atualizar dados” na barra lateral para buscar os dados novamente.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        (
            filtered,
            technicians,
            months,
            projects,
            period_start,
            period_end,
        ) = apply_filters(
            current_records,
            show_technicians=navigation != "Técnicos",
            roster=current_roster,
        )
        if filtered.empty:
            st.info(
                "Não há produção para os filtros selecionados. "
                "Ajuste o período, projeto ou técnico."
            )
        elif navigation == "Visão geral":
            render_overview(
                filtered,
                current_records,
                technicians,
                months,
                projects,
                period_start,
                period_end,
            )
        elif navigation == "Radar de Alertas":
            render_radar_alertas(
                filtered,
                consultivo_frame=current_consultivo,
                roster_frame=current_roster,
            )
        elif navigation == "Scorecard Supervisão":
            render_scorecard_supervisao(
                filtered,
                consultivo_frame=current_consultivo,
                roster_frame=current_roster,
            )
        elif navigation == "Projetos":
            render_projetos(filtered)
        elif navigation == "Quantidade de O.S.":
            st.button(
                "Abrir Comparativo 2025 x 2026 de Contratos e O.S.",
                key="atalho_comp_os",
                icon=":material/compare_arrows:",
                on_click=_abrir_comparativo_anos,
            )
            render_prod_orders(
                filtered,
                records=current_records,
                technicians=technicians,
                months=months,
                projects=projects,
                period_start=period_start,
                period_end=period_end,
            )
        elif navigation == "Contratos":
            st.button(
                "Abrir Comparativo 2025 x 2026 de Contratos e O.S.",
                key="atalho_comp_contratos",
                icon=":material/compare_arrows:",
                on_click=_abrir_comparativo_anos,
            )
            render_contratos(filtered)
        elif navigation == "Produtividade unitária":
            render_produtividade_unitaria(filtered)
        elif navigation == "Qualidade & Ritmo":
            render_qualidade_ritmo(filtered)
        elif navigation == "Regularidade":
            render_regularidade_producao(filtered, period_start, period_end)
            st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
            render_sazonalidade(filtered, period_start, period_end)
        elif navigation == "Eficiência":
            render_eficiencia(filtered)
        elif navigation == "Técnicos":
            render_technicians(
                filtered,
                consultivo_frame=current_consultivo,
                period_start=period_start,
                period_end=period_end,
            )

    st.markdown(
        '<div class="footer">Totale · Inteligência &amp; Gestão Operacional &nbsp;•&nbsp; '
        "Produção (Prod + Gpon), Contratos, O.S. &amp; Performance Consultiva · Atualize os dados pela barra lateral</div>",
        unsafe_allow_html=True,
    )
    logger.info(
        "pagina_renderizada",
        pagina=navigation,
        duracao_ms=round((time.perf_counter() - render_t0) * 1000.0, 2),
        registros_base=int(len(current_records)),
    )


render_dashboard()
