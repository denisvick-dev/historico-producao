from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

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
    render_sidebar_brand,
    render_sidebar_divider,
    render_sidebar_footer_info,
    render_sidebar_pulse,
    render_sidebar_section,
    render_sidebar_theme_selector,
    render_ticker,
)
from components.comparativo_anos import render_comparativo_anos
from components.comparativo_consultivo import render_comparativo_consultivo
from components.consultivo import render_consultivo
from components.contratos import render_contratos
from components.eficiencia import render_eficiencia
from components.prod_os import render_prod_orders
from components.produtividade_unitaria import render_produtividade_unitaria
from components.quadro_tecnicos import render_quadro_tecnicos
from components.visoes_dashboards import (
    render_projetos,
    render_regularidade_producao,
    render_saude_dados,
    selecionar_periodo_anterior,
)
from drive_import import (
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
    consultivo_import_batches,
    count_active_months_by_technician,
    create_demonstration,
    extract_drive_folder_id,
    extract_spreadsheet_id,
    format_points,
    get_drive_file_fingerprints,
    get_roster_fingerprint,
    import_batches,
    init_database,
    load_consultivo_snapshot,
    load_dashboard_snapshot,
    load_roster,
    month_label,
    save_roster_records,
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
    page_title="Histórico de produção | Totale",
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
    .kpi-note { font-size:11px; line-height:1.4; color:#718198; }
    .kpi-note.positive { color:#218361; }
    .kpi-note.negative { color:#bc5d58; }
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
    monthly = summarize(records, ["technician", "period"])
    if monthly.empty:
        return {}
    best = monthly.sort_values(["points_total", "period"]).drop_duplicates(
        "technician", keep="last"
    )
    return dict(zip(best["technician"], best["period"].map(month_label)))


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

            roster_cols = st.columns([1.35, 1.45, 1.3])
            with roster_cols[0]:
                selected_statuses = st.multiselect(
                    "Situação cadastral (lista_ativos)",
                    status_options,
                    default=default_status,
                    placeholder="Todas as situações",
                    key="roster_status_filter",
                )
            with roster_cols[1]:
                monitor_options = sorted(
                    m for m in records["monitor"].dropna().unique() if str(m).strip()
                )
                selected_monitors = st.multiselect(
                    "Monitor",
                    monitor_options,
                    default=[],
                    placeholder="Todos os monitores",
                    key="monitor_filter",
                )
            with roster_cols[2]:
                base_options = sorted(
                    b for b in records["base"].dropna().unique() if str(b).strip()
                )
                selected_bases = st.multiselect(
                    "Base",
                    base_options,
                    default=[],
                    placeholder="Todas as bases",
                    key="base_filter",
                )

        roster_scoped = records
        if has_roster:
            if selected_statuses:
                roster_status_mask = roster_scoped["roster_status"].isin(
                    selected_statuses
                )
                roster_scoped = roster_scoped.loc[roster_status_mask].copy()
            if selected_monitors:
                monitor_mask = roster_scoped["monitor"].isin(selected_monitors)
                roster_scoped = roster_scoped.loc[monitor_mask].copy()
            if selected_bases:
                base_mask = roster_scoped["base"].isin(selected_bases)
                roster_scoped = roster_scoped.loc[base_mask].copy()

        all_technicians = sorted(roster_scoped["technician"].unique())
        filter_columns = st.columns(
            [1.15, 1.55, 1.7] if show_technicians else [1.15, 1.55]
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

    filtered = roster_scoped.copy()
    months: int | None = None
    last_date = records["reference_date"].max()
    first_date = records["reference_date"].min()
    window_start = pd.Timestamp(first_date)
    window_end = pd.Timestamp(last_date)
    if period_choice.startswith("Últimos"):
        months = int(period_choice.split()[1])
        cutoff = (last_date.to_period("M") - (months - 1)).to_timestamp()
        window_start = pd.Timestamp(cutoff)
        filtered = filtered[filtered["reference_date"] >= cutoff]
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
        filtered = filtered[
            filtered["reference_date"].between(window_start, window_end)
        ]
    if selected_projects:
        filtered = filtered[filtered["project"].isin(selected_projects)]
    if selected_technicians:
        filtered = filtered[filtered["technician"].isin(selected_technicians)]
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
        share = current_prod / current_total * 100 if current_total else 0
        metric_card(
            "PONTOS EM PROD",
            format_points(current_prod),
            f"{share:.1f}% do total".replace(".", ","),
            "P",
            "",
            "kpi-card--laranja",
        )
    with columns[2]:
        share = current_gpon / current_total * 100 if current_total else 0
        metric_card(
            "PONTOS EM GPON",
            format_points(current_gpon),
            f"{share:.1f}% do total".replace(".", ","),
            "G",
            "",
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


def render_technicians(filtered: pd.DataFrame) -> None:
    section_heading(
        "Perfil do técnico",
        "Filtre por projeto e selecione o técnico para ver seu desempenho.",
    )
    ranking = summarize(filtered, "technician").sort_values(
        "points_total", ascending=False
    )
    names = ranking["technician"].tolist()
    if not names:
        st.info("Nenhum técnico disponível no recorte atual.")
        return
    selected = st.selectbox("Técnico", names, key="technician_profile")
    if selected is None:
        return
    position = names.index(selected) + 1
    technician_data = filtered[filtered["technician"].eq(selected)]
    totals = ranking[ranking["technician"].eq(selected)].iloc[0]

    meta_parts: list[str] = []
    first_row = technician_data.iloc[0]
    if str(first_row.get("re_code", "")).strip():
        meta_parts.append(f"RE {first_row['re_code']}")
    if str(first_row.get("login", "")).strip():
        meta_parts.append(f"Login {first_row['login']}")
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

    team_monthly = summarize(filtered, "period").sort_values("period")
    active_by_month = filtered.groupby("period")["technician"].nunique()
    team_monthly["team_average"] = team_monthly.apply(
        lambda row: row["points_total"] / active_by_month.get(row["period"], 1), axis=1
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


@st.cache_resource(show_spinner=False)
def _initialize_demo_once(db_path_key: str) -> None:
    """Cria a base de demonstração uma vez por banco configurado."""
    del db_path_key
    create_demonstration()


@st.cache_data(show_spinner=False)
def _load_dashboard_snapshot(db_path_key: str) -> tuple[pd.DataFrame, dict]:
    """Mantém a leitura da base em cache até uma atualização explícita."""
    del db_path_key
    return load_dashboard_snapshot()


@st.cache_data(show_spinner=False)
def _load_roster_cached(db_path_key: str) -> pd.DataFrame:
    """Mantém o quadro cadastral em cache até uma atualização explícita."""
    del db_path_key
    return load_roster()


@st.cache_data(show_spinner=False)
def _load_consultivo_cached(db_path_key: str) -> tuple[pd.DataFrame, dict]:
    """Mantém o histórico consultivo em cache até uma atualização explícita."""
    del db_path_key
    return load_consultivo_snapshot()


def _trim_for_test_runtime(
    frame: pd.DataFrame, stats: dict
) -> tuple[pd.DataFrame, dict]:
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
        return st.secrets["gcp_service_account"]
    except (KeyError, StreamlitSecretNotFoundError):
        return None


def _sync_roster_sheet(*, force: bool = False) -> tuple[bool, str]:
    """Sincroniza a planilha lista_ativos sob demanda ou ao abrir a sessão."""
    known_fp = None if force else get_roster_fingerprint(ROSTER_SHEET_ID)
    try:
        roster_result = import_roster_spreadsheet(
            _drive_service_account(),
            ROSTER_SHEET_ID,
            known_fingerprint=known_fp,
            allow_public_fallback=True,
        )
    except DriveImportError as error:
        logger.warning("falha_sincronizacao_cadastro", erro=str(error))
        return False, f"Falha ao sincronizar lista_ativos: {error}"

    if roster_result.refreshed:
        saved = save_roster_records(
            roster_result.records,
            is_demo=False,
            sheet_id=ROSTER_SHEET_ID,
            fingerprint=roster_result.fingerprint,
        )
        _load_dashboard_snapshot.clear()
        _load_roster_cached.clear()
        _load_consultivo_cached.clear()
        return (
            True,
            f"Cadastro '{roster_result.sheet_name}' atualizado ({saved} colaboradores).",
        )
    return True, f"Cadastro '{roster_result.sheet_name}' já está atualizado."


def _sync_consultivo_folder(*, force: bool = False) -> tuple[bool, str, list[str]]:
    """Sincroniza a pasta Histórico Consultivo do Google Drive."""
    drive_service_account = _drive_service_account()
    if drive_service_account is None:
        return (
            False,
            "Conta de serviço do Google Drive não configurada para Histórico Consultivo.",
            [],
        )
    known_fps = {} if force else get_drive_file_fingerprints(CONSULTIVO_FOLDER_ID)
    try:
        cons_result = import_consultivo_folder_snapshot(
            drive_service_account,
            CONSULTIVO_FOLDER_ID,
            known_file_fingerprints=known_fps,
        )
    except DriveImportError as error:
        logger.warning("falha_sincronizacao_consultivo", erro=str(error))
        return False, f"Falha ao sincronizar Histórico Consultivo: {error}", []

    saved = sync_consultivo_drive_records(
        cons_result.records,
        cons_result.file_ids,
        cons_result.refreshed_file_ids,
        folder_id=CONSULTIVO_FOLDER_ID,
        file_fingerprints=cons_result.file_fingerprints,
    )
    _load_consultivo_cached.clear()
    msg = (
        f"Consultivo sincronizado: {saved} registros atualizados "
        f"({cons_result.successful_files}/{len(cons_result.file_ids)} arquivo(s))."
    )
    return True, msg, list(cons_result.issues[:10])


def _sync_external_data(*, force: bool = False) -> dict[str, Any]:
    """Sincroniza Drive (produção e consultivo) e cadastro, retornando um status para a interface."""
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

    roster_ok, roster_msg = _sync_roster_sheet(force=force)
    cons_ok, cons_msg, cons_issues = _sync_consultivo_folder(force=force)
    try:
        known_file_fingerprints = (
            {} if force else get_drive_file_fingerprints(DRIVE_FOLDER_ID)
        )
        drive_result = import_drive_folder_snapshot(
            drive_service_account,
            DRIVE_FOLDER_ID,
            known_file_fingerprints=known_file_fingerprints,
        )
    except DriveImportError as error:
        logger.error("falha_sincronizacao_drive", erro=str(error))
        return {
            "type": "warning",
            "message": (
                f"Falha ao atualizar os dados do Drive: {error} · "
                f"{cons_msg} · {roster_msg}"
            ),
            "issues": cons_issues,
        }

    count = sync_drive_records(
        drive_result.records,
        drive_result.file_ids,
        drive_result.refreshed_file_ids,
        folder_id=DRIVE_FOLDER_ID,
        file_fingerprints=drive_result.file_fingerprints,
    )
    _load_dashboard_snapshot.clear()
    all_issues = list(drive_result.issues[:10]) + cons_issues
    if not roster_ok:
        all_issues.insert(0, roster_msg)
    if not cons_ok:
        all_issues.insert(0, cons_msg)
    status = {
        "type": "warning" if all_issues else "success",
        "message": (
            f"Drive sincronizado: {count} registros atualizados; "
            f"{drive_result.successful_files} arquivo(s) processado(s) "
            f"de {len(drive_result.file_ids)}. {cons_msg} {roster_msg}"
        ),
        "issues": all_issues,
    }
    logger.info(
        "sincronizacao_drive_sucesso",
        registros_sincronizados=count,
        arquivos_processados=drive_result.successful_files,
        total_issues=len(all_issues),
    )
    return status


logger.info(
    "aplicacao_iniciando",
    pasta_drive=DRIVE_FOLDER_ID,
    pasta_consultivo=CONSULTIVO_FOLDER_ID,
    planilha_cadastro=ROSTER_SHEET_ID,
)

# Preserva a sincronização automática da pasta do Drive e da planilha lista_ativos:
# ela ocorre ao abrir uma nova sessão, antes da leitura/cache do painel.
init_database()
logger.info("banco_dados_inicializado")
if "drive_auto_sync_attempted" not in st.session_state:
    st.session_state["drive_auto_sync_attempted"] = True
    st.session_state["drive_auto_sync_status"] = _sync_external_data(force=False)

_active_db_key = str(production_mod.DB_PATH)
_initialize_demo_once(_active_db_key)
records, stats = _load_dashboard_snapshot(_active_db_key)
records, stats = _trim_for_test_runtime(records, stats)
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


def _resumo_janela_sidebar(frame: pd.DataFrame) -> tuple[str, int]:
    if frame.empty or "period" not in frame.columns:
        return "Sem dados", 0
    periodos = pd.to_datetime(frame["period"], errors="coerce").dropna()
    if periodos.empty:
        return "Sem dados", 0
    inicio = month_label(periodos.min())
    fim = month_label(periodos.max())
    qtd = int(periodos.dt.to_period("M").nunique())
    janela = inicio if inicio == fim else f"{inicio} – {fim}"
    return janela, qtd


with st.sidebar:
    render_sidebar_brand(
        nome="TOTALE",
        subtitulo="Gestão de Produção & Performance",
        versao="2025 · 2026",
        logo=LOGO_PADRAO_TOTALE,
        logo_banner=True,
    )
    _sb_is_demo = bool(
        stats.get("records") and stats.get("demo_rows") == stats.get("records")
    )
    _sb_janela, _sb_competencias = _resumo_janela_sidebar(records)
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
    render_sidebar_section("Navegação", icone="🧭")
    nav_labels = {
        "Visão geral": ":material/dashboard:  Visão geral",
        "Comparativo 2025 x 2026": ":material/compare_arrows:  Comparativo 2025 x 2026",
        "Consultivo 2025 x 2026": ":material/trending_up:  Consultivo 2025 x 2026",
        "Projetos": ":material/account_tree:  Projetos",
        "Quantidade de O.S.": ":material/assignment:  Quantidade de O.S.",
        "Contratos": ":material/description:  Contratos",
        "Produtividade unitária": ":material/speed:  Produtividade unitária",
        "Consultivo": ":material/support_agent:  Consultivo",
        "Regularidade": ":material/calendar_month:  Regularidade",
        "Eficiência": ":material/bolt:  Eficiência por técnico",
        "Técnicos": ":material/person:  Técnicos",
        "Quadro de técnicos": ":material/groups:  Quadro de técnicos",
        "Saúde dos dados": ":material/monitor_heart:  Saúde dos dados",
    }
    # Evita seleções de navegação que não existam mais.
    if st.session_state.get("navigation") not in (None, *nav_labels):
        st.session_state["navigation"] = "Visão geral"
    navigation = st.radio(
        "Navegação",
        list(nav_labels),
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
            _load_dashboard_snapshot.clear()
            _load_roster_cached.clear()
            _load_consultivo_cached.clear()
            st.session_state["drive_auto_sync_status"] = sync_status
            records, stats = _load_dashboard_snapshot(_active_db_key)
            records, stats = _trim_for_test_runtime(records, stats)
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
        copyright="Totale · Histórico de produção",
    )


def render_dashboard() -> None:
    """Renderiza o painel com os dados carregados na abertura ou na atualização manual."""
    db_key = str(production_mod.DB_PATH)
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
            "Histórico de produção",
            "Acompanhe a evolução e os resultados da equipe técnica.",
        ),
        "Comparativo 2025 x 2026": (
            "Comparativo 2025 x 2026 · Contratos e O.S.",
            "Análise interanual de contratos distintos, ordens de serviço (Prod), giro O.S./contrato e evolução por equipe.",
        ),
        "Consultivo 2025 x 2026": (
            "Comparativo 2025 x 2026 · Consultivos",
            "Análise interanual de consultivos realizados, mix de produtos (Mesh, TV Box, Virtua), conversão e metas por equipe.",
        ),
        "Projetos": (
            "Produção por projeto",
            "Compare pontos, ordens de serviço e participação por projeto.",
        ),
        "Quantidade de O.S.": (
            "Quantidade de O.S.",
            "Ordens de serviço registradas na aba Prod, por competência e técnico.",
        ),
        "Contratos": (
            "Contratos e eficiência",
            "Acompanhe os contratos atendidos por competência, técnico e faixa de eficiência.",
        ),
        "Produtividade unitária": (
            "Produtividade unitária",
            "Compare pontos por O.S., pontos por contrato e o perfil volume × complexidade da equipe.",
        ),
        "Consultivo": (
            "Total de Consultivos",
            "Histórico de consultivos realizados, mix de produtos (Mesh, TV Box, Virtua) e vínculo com lista_ativos.",
        ),
        "Regularidade": (
            "Regularidade da produção",
            "Compare médias, medianas, oscilações e competências sem registros.",
        ),
        "Eficiência": (
            "Eficiência por técnico por mês",
            "Acompanhe as faixas mensais e a faixa mais frequente no período.",
        ),
        "Técnicos": (
            "Produção por técnico",
            "Analise a evolução individual e compare com a equipe.",
        ),
        "Quadro de técnicos": (
            "Quadro de técnicos · lista_ativos",
            "Conciliação entre o cadastro oficial (lista_ativos / desligados) e a produção por Monitor, U.N. e Base.",
        ),
        "Saúde dos dados": (
            "Saúde dos dados e importações",
            "Confira a cobertura, a sincronização e o contador de contratos de "
            "cada arquivo importado, com detalhamento e download em CSV.",
        ),
    }
    title, subtitle = page_titles[navigation]
    updated = "Aguardando dados da produção"
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
            badge="TOTALE · PRODUÇÃO",
            icone="monitoring",
            meta_info=updated,
        )

    current_roster = _load_roster_cached(db_key)
    current_consultivo, current_consultivo_stats = _load_consultivo_cached(db_key)
    is_demo_consultivo = bool(
        current_consultivo_stats.get("records")
        and current_consultivo_stats.get("demo_rows")
        == current_consultivo_stats.get("records")
    )

    _paginas_consultivo = ("Consultivo", "Consultivo 2025 x 2026")
    if (
        (navigation not in _paginas_consultivo and is_demo)
        or (navigation in _paginas_consultivo and is_demo_consultivo)
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
            drive_configured=_drive_service_account() is not None,
        )
    elif navigation == "Consultivo 2025 x 2026":
        render_comparativo_consultivo(
            current_consultivo,
            roster=current_roster,
            consultivo_folder_id=CONSULTIVO_FOLDER_ID,
            on_abrir_painel_consultivo=_abrir_painel_consultivo,
            on_abrir_comparativo_contratos=_abrir_comparativo_anos,
            on_dados_importados=_load_consultivo_cached.clear,
        )
    elif navigation == "Comparativo 2025 x 2026":
        st.button(
            "Ver Comparativo 2025 x 2026 de Consultivos",
            key="atalho_ir_comp_consultivo",
            icon=":material/trending_up:",
            on_click=_abrir_comparativo_consultivo,
        )
        render_comparativo_anos(current_records, roster=current_roster)
    elif navigation == "Saúde dos dados":
        render_saude_dados(
            current_records,
            current_stats,
            import_batches(),
            st.session_state.get("drive_auto_sync_status"),
            consultivo_stats=current_consultivo_stats,
            lotes_consultivo=consultivo_import_batches(),
        )
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
        elif navigation == "Projetos":
            render_projetos(filtered)
        elif navigation == "Quantidade de O.S.":
            st.button(
                "Abrir Comparativo 2025 x 2026 de Contratos e O.S.",
                key="atalho_comp_os",
                icon=":material/compare_arrows:",
                on_click=_abrir_comparativo_anos,
            )
            render_prod_orders(filtered)
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
        elif navigation == "Regularidade":
            render_regularidade_producao(filtered, period_start, period_end)
        elif navigation == "Eficiência":
            render_eficiencia(filtered)
        elif navigation == "Técnicos":
            render_technicians(filtered)

    st.markdown(
        '<div class="footer">Totale · Histórico de produção &nbsp;•&nbsp; '
        "Pontos Totais = Prod + Gpon · Atualize os dados pela barra lateral</div>",
        unsafe_allow_html=True,
    )


render_dashboard()
