from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from production import (
    create_demonstration,
    format_points,
    init_database,
    load_dashboard_snapshot,
    month_label,
    summarize,
    sync_drive_records,
)
from components.componentes import (
    Cores,
    Fontes,
    aplicar_estilo_corp,
    render_hero_totale_1,
    render_sidebar_brand,
    render_sidebar_divider,
    render_sidebar_footer_info,
    render_sidebar_section,
    render_ticker,
)
from components.prod_os import render_prod_orders
from drive_import import DriveImportError, import_drive_folder_snapshot

DRIVE_FOLDER_ID = "1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq"

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

st.set_page_config(
    page_title="Histórico de produção | Totale",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Ativa tipografia, tokens, componentes nativos e tema corporativo do Design System.
aplicar_estilo_corp(tema_sidebar="azul")

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
    [data-testid="stSidebar"] [role="radiogroup"] { gap:.3rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        width:100%; padding:.68rem .75rem; border-radius:10px; transition:all .16s ease;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display:none !important; }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background:var(--totale-sb-nav-hover-bg);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background:var(--totale-sb-nav-active-bg);
        border-left:3px solid var(--totale-sb-nav-active-accent);
        box-shadow:0 4px 12px rgba(0,0,0,.12);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label p { font-size:13px; font-weight:600; }


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
        content:""; position:absolute; z-index:1; inset:0 0 auto; height:3px; pointer-events:none;
        background:linear-gradient(90deg, #012869 0%, #0A48AA 72%, #F37C04 100%);
    }
    .kpi-card:hover { transform:translateY(-3px); border-color:#c8d7eb; box-shadow:0 12px 26px rgba(1,40,105,.11); }
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
    .ticker-viewport {
        overflow:hidden; margin:0 0 1.1rem; border:1px solid #dce6f3; border-radius:12px;
        background:linear-gradient(110deg,#fff,#f8faff); box-shadow:0 4px 14px rgba(1,40,105,.045);
    }
    .ticker-track { display:flex; width:max-content; animation:ticker-scroll 22s linear infinite; }
    .ticker-group {
        display:flex; align-items:center; flex:0 0 max-content; min-width:100vw;
        justify-content:space-around;
    }
    .ticker-item {
        display:inline-flex; align-items:center; gap:.55rem; flex:0 0 auto;
        padding:.78rem 1.25rem; color:#012869; font-size:12px; white-space:nowrap;
    }
    .ticker-item::before { content:""; width:6px; height:6px; border-radius:50%; background:#F37C04; }
    .ticker-label { color:#718198; font-size:10px; font-weight:750; letter-spacing:.07em; text-transform:uppercase; }
    .ticker-item strong { font-weight:750; }
    @keyframes ticker-scroll { to { transform:translateX(-50%); } }
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
    [data-testid="stDataFrame"] {
        --gdg-font-family:'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        --gdg-accent-color:#F37C04;
        --gdg-bg-cell:#ffffff;
        --gdg-bg-cell-medium:#f8faff;
        --gdg-bg-header:#edf3fb;
        --gdg-bg-header-hover:#e5edf8;
        --gdg-bg-header-has-focus:#dce8f7;
        --gdg-text-dark:#122033;
        --gdg-text-medium:#52657d;
        --gdg-text-light:#718198;
        --gdg-text-header:#012869;
        --gdg-border-color:#e2eaf4;
        --gdg-horizontal-border-color:#edf1f7;
        overflow:hidden; border:1px solid #e2eaf4; border-radius:13px;
        background:#fff; box-shadow:0 6px 20px rgba(1,40,105,.06);
    }
    [data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] { border-radius:12px; }
    [data-testid="stTable"] { overflow:hidden; border:1px solid #e2eaf4; border-radius:13px; box-shadow:0 6px 20px rgba(1,40,105,.06); }
    [data-testid="stTable"] table {
        border-collapse:separate; border-spacing:0; font-family:'Inter', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        font-size:13px;
    }
    [data-testid="stTable"] thead th {
        background:#edf3fb !important; color:#012869 !important;
        font-family:'Manrope', 'Inter', 'Segoe UI', Arial, sans-serif;
        font-size:10px !important; font-weight:750 !important; letter-spacing:.075em;
        text-transform:uppercase; border-bottom:1px solid #dce6f3 !important;
    }
    [data-testid="stTable"] tbody tr:nth-child(even) { background:#f8faff; }
    [data-testid="stTable"] tbody tr:hover { background:#fff7ed; }
    [data-testid="stTable"] tbody td { border-bottom:1px solid #edf1f7 !important; color:#26384f; }
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
    @media (max-width: 700px) {
        [data-testid="stMainBlockContainer"] { padding:1rem; }
        .header-meta { display:none; }
        .kpi-card { padding:1rem; min-height:120px; }
        .kpi-value { font-size:23px; }
        .ticker-item { padding:.72rem .85rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}


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



def apply_filters(
    records: pd.DataFrame,
    *,
    show_technicians: bool = True,
) -> tuple[pd.DataFrame, list[str], int | None, list[str]]:
    """Renderiza filtros compartilhados e devolve também a janela em meses."""
    all_technicians = sorted(records["technician"].unique())
    all_projects = sorted(records["project"].dropna().unique())
    with st.container(border=True):
        filter_columns = st.columns(
            [1.15, 1.55, 1.7] if show_technicians else [1.15, 1.55]
        )
        period_col, project_col = filter_columns[:2]
        with period_col:
            period_choice = st.selectbox(
                "Período de análise",
                ["Todo o período", "Últimos 3 meses", "Últimos 6 meses", "Últimos 12 meses", "Personalizado"],
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
            with filter_columns[2]:
                selected_technicians = st.multiselect(
                    "Técnicos",
                    all_technicians,
                    default=[],
                    placeholder="Todos os técnicos",
                    key="technician_filter",
                )

    filtered = records.copy()
    months: int | None = None
    last_date = records["reference_date"].max()
    first_date = records["reference_date"].min()
    if period_choice.startswith("Últimos"):
        months = int(period_choice.split()[1])
        cutoff = (last_date.to_period("M") - (months - 1)).to_timestamp()
        filtered = filtered[filtered["reference_date"] >= cutoff]
    elif period_choice == "Personalizado":
        start_col, end_col, _ = st.columns([1, 1, 3])
        with start_col:
            start = st.date_input(
                "Data inicial",
                value=first_date.date(),
                min_value=first_date.date(),
                max_value=last_date.date(),
                key="custom_start",
            )
        with end_col:
            end = st.date_input(
                "Data final",
                value=last_date.date(),
                min_value=first_date.date(),
                max_value=last_date.date(),
                key="custom_end",
            )
        if start > end:
            st.warning("A data inicial deve ser anterior à data final.")
            start, end = end, start
        filtered = filtered[
            filtered["reference_date"].between(pd.Timestamp(start), pd.Timestamp(end))
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
    )


def previous_period(
    records: pd.DataFrame,
    filtered: pd.DataFrame,
    technicians: list[str],
    months: int | None,
    projects: list[str],
) -> pd.DataFrame:
    if filtered.empty or months is None:
        return filtered.iloc[0:0]
    periods = sorted(filtered["period"].unique())
    count = len(periods)
    if not count:
        return filtered.iloc[0:0]
    first = pd.Timestamp(periods[0])
    previous_start = first - pd.DateOffset(months=count)
    previous_end = first - pd.Timedelta(days=1)
    return records[
        records["technician"].isin(technicians)
        & records["project"].isin(projects)
        & records["reference_date"].between(previous_start, previous_end)
    ]


def render_metrics(
    filtered: pd.DataFrame,
    records: pd.DataFrame,
    technicians: list[str],
    months: int | None,
    projects: list[str],
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

    previous = previous_period(records, filtered, technicians, months, projects)
    previous_total = previous["points"].sum()
    if previous_total:
        variation = (current_total / previous_total - 1) * 100
        note = f"{'↑' if variation >= 0 else '↓'} {abs(variation):.1f}% vs. período anterior".replace(".", ",")
        note_class = "positive" if variation >= 0 else "negative"
    else:
        note = "Soma de Prod + Gpon"
        note_class = ""

    columns = st.columns(4)
    with columns[0]:
        metric_card("PONTOS TOTAIS", format_points(current_total), note, "Σ", note_class)
    with columns[1]:
        share = current_prod / current_total * 100 if current_total else 0
        metric_card("PONTOS EM PROD", format_points(current_prod), f"{share:.1f}% do total".replace(".", ","), "P")
    with columns[2]:
        share = current_gpon / current_total * 100 if current_total else 0
        metric_card("PONTOS EM GPON", format_points(current_gpon), f"{share:.1f}% do total".replace(".", ","), "G")
    with columns[3]:
        metric_card(
            "MÉDIA POR TÉCNICO",
            format_points(average),
            f"{active} {'técnicos ativos' if active != 1 else 'técnico ativo'} no recorte",
            "Ø",
        )


def render_overview(
    filtered: pd.DataFrame,
    records: pd.DataFrame,
    technicians: list[str],
    months: int | None,
    projects: list[str],
) -> None:
    totals = summarize(filtered, [])
    technicians_by_points = summarize(filtered, "technician")
    periods_by_points = summarize(filtered, "period")
    ticker_items = [
        ("Pontos totais", format_points(totals.iloc[0]["points_total"])),
        ("Prod", f'{format_points(totals.iloc[0]["points_prod"])} pontos'),
        ("Gpon", f'{format_points(totals.iloc[0]["points_gpon"])} pontos'),
    ]
    if not technicians_by_points.empty:
        top_technician = technicians_by_points.nlargest(1, "points_total").iloc[0]
        ticker_items.append(
            (
                "Destaque da equipe",
                f'{top_technician["technician"]} · {format_points(top_technician["points_total"])} pontos',
            )
        )
    if not periods_by_points.empty:
        top_period = periods_by_points.nlargest(1, "points_total").iloc[0]
        ticker_items.append(
            (
                "Competência destaque",
                f'{month_label(top_period["period"])} · {format_points(top_period["points_total"])} pontos',
            )
        )
    render_ticker(ticker_items, label="Indicadores da visão geral")

    render_metrics(filtered, records, technicians, months, projects)
    section_heading("Produção da equipe", "Pontos consolidados por competência e por técnico")
    chart_col, ranking_col = st.columns([1.65, 1])
    monthly = summarize(filtered, "period").sort_values("period")
    ranking = summarize(filtered, "technician").sort_values("points_total", ascending=False)
    with chart_col:
        with st.container(border=True):
            st.markdown("**Evolução mensal**")
            st.plotly_chart(production_chart(monthly), width="stretch", config=CHART_CONFIG)
    with ranking_col:
        with st.container(border=True):
            st.markdown("**Ranking de técnicos**")
            st.plotly_chart(ranking_chart(ranking), width="stretch", config=CHART_CONFIG)

    section_heading("Desempenho por técnico", "O total é sempre a soma dos pontos de Prod e Gpon")
    periods_count = max(filtered["period"].nunique(), 1)
    latest_period = filtered["period"].max()
    latest = summarize(filtered[filtered["period"].eq(latest_period)], "technician").set_index("technician")
    previous_month = latest_period - pd.DateOffset(months=1)
    previous = summarize(filtered[filtered["period"].eq(previous_month)], "technician").set_index("technician")

    table = ranking.copy()
    table["Média mensal"] = table["points_total"] / periods_count
    variations = []
    for technician in table["technician"]:
        current_value = latest["points_total"].get(technician, 0)
        previous_value = previous["points_total"].get(technician, 0)
        variations.append((current_value / previous_value - 1) * 100 if previous_value else None)
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
        ["Posição", "Técnico", "Prod", "Gpon", "Pontos Totais", "Média mensal", "Variação no último mês"]
    ]
    st.dataframe(
        display_table.style.map(_monthly_average_style, subset=["Média mensal"]),
        width="stretch",
        hide_index=True,
        column_config={
            "Posição": st.column_config.NumberColumn(format="%dº", width="small"),
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
            "Média mensal": st.column_config.NumberColumn(format="%.2f"),
            "Variação no último mês": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )
    st.caption(
        "Critérios da média mensal: 275–299,99 amarelo · 300–399,99 verde · 400 ou mais azul."
    )


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


def render_technicians(filtered: pd.DataFrame) -> None:
    section_heading("Perfil do técnico", "Filtre por projeto e selecione o técnico para ver seu desempenho.")
    ranking = summarize(filtered, "technician").sort_values("points_total", ascending=False)
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

    st.markdown(
        f"""
        <div class="technician-hero">
            <div class="avatar">{initials(selected)}</div>
            <div><div class="tech-name">{selected}</div><div class="rank-pill">{position}º lugar no ranking do período</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    monthly = summarize(technician_data, "period").sort_values("period")
    best = monthly.sort_values("points_total").iloc[-1]
    average = monthly["points_total"].mean()
    columns = st.columns(4)
    with columns[0]:
        metric_card("PONTOS TOTAIS", format_points(totals["points_total"]), "Prod + Gpon no período", "Σ")
    with columns[1]:
        metric_card("PROD", format_points(totals["points_prod"]), "Pontos acumulados", "P")
    with columns[2]:
        metric_card("GPON", format_points(totals["points_gpon"]), "Pontos acumulados", "G")
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
        columns={"points_prod": "Prod", "points_gpon": "Gpon", "points_total": "Pontos Totais"}
    )
    st.caption(
        "Critérios da média mensal de Pontos Totais: "
        "275–299,99 amarelo · 300–399,99 verde · 400 ou mais azul."
    )
    st.dataframe(
        detail[["Competência", "Prod", "Gpon", "Pontos Totais"]].style.map(
            _monthly_average_style, subset=["Pontos Totais"]
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
        },
    )

@st.cache_resource(show_spinner=False)
def _initialize_demo_once() -> None:
    """Cria a base de demonstração uma vez por processo do app."""
    create_demonstration()


@st.cache_data(ttl=15, show_spinner=False)
def _load_dashboard_snapshot() -> tuple[pd.DataFrame, dict]:
    """Mantém a consulta da base em cache curto para navegação mais fluida."""
    return load_dashboard_snapshot()


def _drive_service_account():
    try:
        return st.secrets["gcp_service_account"]
    except (KeyError, StreamlitSecretNotFoundError):
        return None


# Preserva a sincronização automática da pasta do Drive: ela ocorre ao abrir uma
# nova sessão, antes da leitura/cache do painel. A UI não expõe importação manual.
init_database()
if "drive_auto_sync_attempted" not in st.session_state:
    st.session_state["drive_auto_sync_attempted"] = True
    drive_service_account = _drive_service_account()
    if drive_service_account is not None:
        try:
            drive_result = import_drive_folder_snapshot(
                drive_service_account, DRIVE_FOLDER_ID
            )
        except DriveImportError as error:
            st.session_state["drive_auto_sync_status"] = {
                "type": "warning",
                "message": f"Falha ao atualizar os dados do Drive: {error}",
                "issues": [],
            }
        else:
            count = sync_drive_records(
                drive_result.records,
                drive_result.file_ids,
                drive_result.refreshed_file_ids,
            )
            _load_dashboard_snapshot.clear()
            st.session_state["drive_auto_sync_status"] = {
                "type": "warning" if drive_result.issues else "success",
                "message": (
                    f"Drive sincronizado: {count} registros em "
                    f"{drive_result.successful_files} arquivo(s)."
                ),
                "issues": drive_result.issues[:10],
            }
    else:
        st.session_state["drive_auto_sync_status"] = {
            "type": "info",
            "message": (
                "Atualização automática do Drive não configurada. "
                "Configure a conta de serviço para habilitá-la."
            ),
            "issues": [],
        }

_initialize_demo_once()
records, stats = _load_dashboard_snapshot()

with st.sidebar:
    render_sidebar_brand(
        nome="TOTALE",
        subtitulo="Gestão de produção",
        icone="T",
        tema="azul",
    )
    render_sidebar_section("Acompanhamento", tema="azul")
    nav_labels = {
        "Visão Geral": "▦  Visão Geral",
        "Quantidade de O.S.": "▤  Quantidade de O.S.",
        "Técnicos": "♙  Técnicos",
    }
    navigation = st.radio(
        "Navegação",
        list(nav_labels),
        format_func=nav_labels.get,
        label_visibility="collapsed",
        key="navigation",
    )
    render_sidebar_divider(label="Sincronização", estilo="gradiente", tema="azul")
    render_sidebar_footer_info(
        itens={"Registros": stats["records"], "Técnicos": stats["technicians"]},
        unidade="Consulta automática a cada 60s",
        ambiente="Produção",
        copyright="Totale · Histórico de produção",
        tema="azul",
    )


@st.fragment(run_every="60s")
def render_dashboard() -> None:
    """Painel principal, atualizado em segundo plano sem recarregar a página toda."""
    current_records, current_stats = _load_dashboard_snapshot()
    is_demo = bool(
        current_stats["records"]
        and current_stats["demo_rows"] == current_stats["records"]
    )
    page_titles = {
        "Visão Geral": (
            "Histórico de produção",
            "Acompanhe a evolução e os resultados da equipe técnica.",
        ),
        "Quantidade de O.S.": (
            "Quantidade de O.S.",
            "Ordens de serviço registradas na aba Prod, por competência e técnico.",
        ),
        "Técnicos": (
            "Produção por técnico",
            "Analise a evolução individual e compare com a equipe.",
        ),
    }
    title, subtitle = page_titles[navigation]
    updated = "Aguardando dados da produção"
    if current_stats["last_import"]:
        updated = pd.Timestamp(current_stats["last_import"]).strftime(
            "Atualizado em %d/%m/%Y às %H:%M"
        )
    render_hero_totale_1(
        titulo=title,
        subtitulo=subtitle,
        badge="TOTALE · PRODUÇÃO",
        icone="monitoring",
        meta_info=updated,
    )

    if is_demo:
        st.markdown(
            """
            <div class="demo-banner">
                <strong>Dados de demonstração.</strong>
                Explore os indicadores. Esta amostra será substituída quando os dados de produção estiverem sincronizados na base.
            </div>
            """,
            unsafe_allow_html=True,
        )

    if current_records.empty:
        st.markdown(
            """
            <div class="empty-state">
                <div class="empty-icon">↻</div>
                <h2>Nenhum registro disponível</h2>
                <p>O painel consulta a base automaticamente a cada 60 segundos e exibirá os dados assim que estiverem disponíveis.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        filtered, technicians, months, projects = apply_filters(
            current_records, show_technicians=navigation != "Técnicos"
        )
        if filtered.empty:
            if navigation == "Visão Geral":
                render_ticker(
                    [("Produção", "Nenhum registro nos filtros selecionados")],
                    label="Indicadores da visão geral",
                )
            elif navigation == "Quantidade de O.S.":
                render_ticker(
                    [("Ordens de serviço", "Nenhum registro nos filtros selecionados")],
                    label="Indicadores de quantidade de O.S.",
                )
            st.info("Não há produção para os filtros selecionados. Ajuste o período, projeto ou técnico.")
        elif navigation == "Visão Geral":
            render_overview(filtered, current_records, technicians, months, projects)
        elif navigation == "Quantidade de O.S.":
            render_prod_orders(filtered)
        elif navigation == "Técnicos":
            render_technicians(filtered)

    st.markdown(
        '<div class="footer">Totale · Histórico de produção &nbsp;•&nbsp; '
        'Pontos Totais = Prod + Gpon · Sincronização automática</div>',
        unsafe_allow_html=True,
    )


render_dashboard()
