from __future__ import annotations

import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from production import (
    DEMO_SOURCE,
    GPON,
    PROD,
    clear_database,
    clear_demonstration,
    create_demonstration,
    database_stats,
    format_points,
    import_batches,
    init_database,
    load_records,
    month_label,
    process_upload,
    save_records,
    summarize,
)
from drive_import import DriveImportError, import_drive_folder
from components.prod_os import render_prod_orders

DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq"
DRIVE_FOLDER_ID = "1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq"
COLORS = {
    "ink": "#012869",
    "green": "#012869",
    "mint": "#F37C04",
    "pale": "#E8EEF8",
    "text": "#122033",
    "muted": "#64748b",
    "grid": "#e6edf5",
    "background": "#f3f6fb",
}

st.set_page_config(
    page_title="Histórico de produção | Totale",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');

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
    html, body, [class*="css"], .stApp { font-family: 'DM Sans', 'Segoe UI', sans-serif; }
    .stApp { background: var(--background); color: var(--text); }
    #MainMenu, footer { visibility: hidden; }
    [data-testid="stHeader"] { background: rgba(243,246,251,.88); }
    [data-testid="stMainBlockContainer"] { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { background: #012869; border-right: 0; }
    [data-testid="stSidebar"] > div:first-child { padding: 1.8rem 1.15rem 1rem; }
    [data-testid="stSidebar"] * { color: #e7f1ed; }
    [data-testid="stSidebar"] .brand { display:flex; align-items:center; gap:.75rem; padding: 0 .45rem 1.6rem; }
    [data-testid="stSidebar"] .brand-mark {
        width: 40px; height: 40px; border-radius: 12px; background:#F37C04; color:#012869;
        display:flex; align-items:center; justify-content:center; font-size:24px; font-weight:700;
    }
    [data-testid="stSidebar"] .brand-name { font-size:22px; line-height:1.1; font-weight:700; letter-spacing:-.5px; }
    [data-testid="stSidebar"] .brand-sub { font-size:11px; color:#b9cae3; letter-spacing:1.7px; text-transform:uppercase; margin-top:4px; }
    [data-testid="stSidebar"] .nav-caption { color:#b9cae3; font-size:10px; letter-spacing:1.5px; font-weight:700; padding:0 .65rem .5rem; }
    [data-testid="stSidebar"] [role="radiogroup"] { gap: .3rem; }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        width:100%; padding:.72rem .8rem; border-radius:9px; transition:all .15s; cursor:pointer;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover { background:rgba(255,255,255,.07); }
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:rgba(255,255,255,.12); border-left:3px solid #F37C04; }
    [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child { display:none; }
    [data-testid="stSidebar"] [role="radiogroup"] label p { font-size:14px; font-weight:500; }
    [data-testid="stSidebar"] hr { border-color:rgba(255,255,255,.12); margin:1.2rem .4rem; }
    [data-testid="stSidebar"] .sidebar-foot { color:#b9cae3; font-size:12px; line-height:1.55; padding:0 .45rem; }
    [data-testid="stSidebar"] .sidebar-foot strong { color:#ffffff; font-weight:600; }

    h1, h2, h3 { color:#012869; letter-spacing:-.035em; }
    h1 { font-size:2rem !important; font-weight:700 !important; margin-bottom:.1rem !important; }
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
    .kpi-card { background:#fff; border:1px solid var(--line); border-radius:13px; padding:1.15rem 1.25rem 1rem; min-height:134px; }
    .kpi-top { display:flex; align-items:center; justify-content:space-between; gap:.5rem; }
    .kpi-label { font-size:12px; font-weight:600; color:#667b75; }
    .kpi-dot { width:28px; height:28px; border-radius:8px; background:#FFF3E6; display:flex; align-items:center; justify-content:center; font-size:13px; color:var(--green); font-weight:700; }
    .kpi-value { font-size:28px; line-height:1.15; letter-spacing:-1px; font-weight:700; color:#012869; margin:.7rem 0 .25rem; }
    .kpi-note { font-size:11px; color:#81918c; }
    .kpi-note.positive { color:#218361; }
    .kpi-note.negative { color:#bc5d58; }
    .section-heading { margin:1.45rem 0 .75rem; display:flex; justify-content:space-between; align-items:end; }
    .section-heading h2 { margin:0 !important; }
    .section-heading p { margin:.15rem 0 0; font-size:12px; }
    [data-testid="stVerticalBlockBorderWrapper"] { background:#fff; border-color:var(--line) !important; border-radius:13px !important; }
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] { gap:.8rem; }
    [data-testid="stPlotlyChart"] { border-radius:8px; }
    .stButton > button, .stDownloadButton > button { border-radius:8px; font-weight:600; min-height:2.55rem; }
    .stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] { background:#012869; border-color:#012869; }
    .stButton > button[kind="primary"]:hover { background:#011838; border-color:#011838; }
    .stTextInput input, .stSelectbox > div > div, .stMultiSelect > div > div, .stDateInput > div > div { border-radius:8px; }
    [data-testid="stFileUploader"] { background:#f8faff; border:1px dashed #b9cae3; border-radius:12px; padding:.4rem; }
    [data-testid="stDataFrame"] { border:1px solid #e6edf5; border-radius:9px; overflow:hidden; }
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
        font=dict(family="DM Sans, Segoe UI, sans-serif", color=COLORS["muted"], size=11),
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
        hovertemplate="<b>%{x}</b><br>Prod: %{y:,.0f} pontos<extra></extra>",
    )
    fig.add_bar(
        x=monthly["label"],
        y=monthly["points_gpon"],
        name="Gpon",
        marker_color=COLORS["mint"],
        hovertemplate="<b>%{x}</b><br>Gpon: %{y:,.0f} pontos<extra></extra>",
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
        hovertemplate="%{y}<br>Prod: %{x:,.0f}<extra></extra>",
    )
    fig.add_bar(
        y=data["technician"],
        x=data["points_gpon"],
        name="Gpon",
        orientation="h",
        marker_color=COLORS["mint"],
        hovertemplate="%{y}<br>Gpon: %{x:,.0f}<extra></extra>",
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


def template_file() -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(columns=["Data", "Técnico", "Pontos"]).to_excel(
            writer, sheet_name=PROD, index=False
        )
        pd.DataFrame(columns=["Data", "Técnico", "Pontos"]).to_excel(
            writer, sheet_name=GPON, index=False
        )
    return output.getvalue()


def csv_download(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def apply_filters(records: pd.DataFrame) -> tuple[pd.DataFrame, list[str], int | None]:
    """Renderiza filtros compartilhados e devolve também a janela em meses."""
    all_technicians = sorted(records["technician"].unique())
    with st.container(border=True):
        period_col, technician_col, spacer = st.columns([1.25, 1.8, 0.3])
        with period_col:
            period_choice = st.selectbox(
                "Período de análise",
                ["Todo o período", "Últimos 3 meses", "Últimos 6 meses", "Últimos 12 meses", "Personalizado"],
                index=3,
                key="period_filter",
            )
        with technician_col:
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
    if selected_technicians:
        filtered = filtered[filtered["technician"].isin(selected_technicians)]
    return filtered, selected_technicians or all_technicians, months


def previous_period(
    records: pd.DataFrame, filtered: pd.DataFrame, technicians: list[str], months: int | None
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
        & records["reference_date"].between(previous_start, previous_end)
    ]


def render_metrics(
    filtered: pd.DataFrame, records: pd.DataFrame, technicians: list[str], months: int | None
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

    previous = previous_period(records, filtered, technicians, months)
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


def render_overview(filtered: pd.DataFrame, records: pd.DataFrame, technicians: list[str], months: int | None) -> None:
    render_metrics(filtered, records, technicians, months)
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
    st.dataframe(
        table[["Posição", "Técnico", "Prod", "Gpon", "Pontos Totais", "Média mensal", "Variação no último mês"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Posição": st.column_config.NumberColumn(format="%dº", width="small"),
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Prod": st.column_config.NumberColumn(format="%.0f"),
            "Gpon": st.column_config.NumberColumn(format="%.0f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.0f"),
            "Média mensal": st.column_config.NumberColumn(format="%.0f"),
            "Variação no último mês": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )


def render_history(filtered: pd.DataFrame) -> None:
    section_heading("Histórico mensal", "Consulte, compare e exporte todas as competências do recorte")
    history = summarize(filtered, ["period", "technician"])
    history = history.sort_values(["period", "points_total"], ascending=[False, False])
    ranking = summarize(filtered, "technician")
    top_names = ranking.nlargest(12, "points_total")["technician"].tolist()

    pivot = history[history["technician"].isin(top_names)].pivot_table(
        index="technician", columns="period", values="points_total", aggfunc="sum", fill_value=0
    )
    if not pivot.empty:
        pivot = pivot.reindex(top_names)
        pivot = pivot.reindex(sorted(pivot.columns), axis=1)
        labels = [month_label(column) for column in pivot.columns]
        heatmap = go.Figure(
            go.Heatmap(
                z=pivot.values,
                x=labels,
                y=pivot.index,
                colorscale=[[0, "#E8EEF8"], [0.45, "#8CA9D4"], [1, "#012869"]],
                showscale=False,
                hovertemplate="%{y}<br>%{x}<br><b>%{z:,.0f} pontos</b><extra></extra>",
                xgap=3,
                ygap=3,
            )
        )
        heatmap.update_xaxes(side="top", showgrid=False, fixedrange=True)
        heatmap.update_yaxes(showgrid=False, autorange="reversed", fixedrange=True)
        heatmap.update_layout(
            height=max(300, len(pivot) * 32 + 70),
            margin=dict(l=8, r=8, t=15, b=5),
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(family="DM Sans, Segoe UI, sans-serif", size=10, color=COLORS["muted"]),
        )
        with st.container(border=True):
            st.markdown("**Mapa de produção · Pontos Totais**")
            st.plotly_chart(heatmap, width="stretch", config=CHART_CONFIG)

    display = history.copy()
    display["Competência"] = display["period"].map(month_label)
    display = display.rename(
        columns={
            "technician": "Técnico",
            "points_prod": "Pontos Prod",
            "points_gpon": "Pontos Gpon",
            "points_total": "Pontos Totais",
        }
    )
    display = display[["Competência", "Técnico", "Pontos Prod", "Pontos Gpon", "Pontos Totais"]]
    download_col, info_col = st.columns([1.3, 4])
    with download_col:
        st.download_button(
            "Baixar histórico em CSV",
            data=csv_download(display),
            file_name="historico_producao.csv",
            mime="text/csv",
            width="stretch",
        )
    with info_col:
        st.markdown(
            f'<div class="small-muted" style="padding-top:10px">{len(display):,} registros mensais no recorte atual.</div>'.replace(",", "."),
            unsafe_allow_html=True,
        )
    st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        height=480,
        column_config={
            "Pontos Prod": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_technicians(filtered: pd.DataFrame) -> None:
    section_heading("Perfil do técnico", "Evolução individual e comparação com a média da equipe")
    ranking = summarize(filtered, "technician").sort_values("points_total", ascending=False)
    names = ranking["technician"].tolist()
    if not names:
        st.info("Nenhum técnico disponível no recorte atual.")
        return
    selected = st.selectbox("Selecione o técnico", names, label_visibility="collapsed")
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
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} pontos<extra></extra>",
    )
    fig.add_scatter(
        x=team_monthly["label"],
        y=team_monthly["team_average"],
        name="Média da equipe",
        mode="lines+markers",
        line=dict(color="#F37C04", width=2, dash="dot"),
        marker=dict(size=6),
        hovertemplate="<b>%{x}</b><br>Média: %{y:,.0f}<extra></extra>",
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
    st.dataframe(
        detail[["Competência", "Prod", "Gpon", "Pontos Totais"]],
        width="stretch",
        hide_index=True,
        column_config={
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def render_import(is_demo: bool) -> None:
    section_heading("Importar e gerenciar dados", "Atualize o histórico com as planilhas de produção da equipe")
    feedback = st.session_state.pop("import_feedback", None)
    if feedback:
        if feedback["type"] == "success":
            st.success(feedback["message"])
        else:
            st.warning(feedback["message"])
        for issue in feedback.get("issues", []):
            st.caption(issue)

    def finish_import(
        records: list[dict], issues: list[str], successful_files: int
    ) -> None:
        if records:
            count = save_records(records)
            message = (
                f"{count} registros importados de {successful_files} arquivo(s). "
                "O histórico já foi atualizado."
            )
            if is_demo:
                message += " Os dados de demonstração foram removidos."
            st.session_state["import_feedback"] = {
                "type": "success",
                "message": message,
                "issues": issues[:40],
            }
        else:
            st.session_state["import_feedback"] = {
                "type": "warning",
                "message": "Nenhum registro válido foi importado. Revise os avisos abaixo.",
                "issues": issues[:40],
            }
        st.rerun()

    upload_col, help_col = st.columns([1.65, 1])
    with upload_col:
        with st.container(border=True):
            st.markdown("**Importar diretamente do Google Drive**")
            st.markdown(
                '<div class="small-muted">Lê as planilhas da pasta compartilhada com a conta de serviço configurada neste app.</div>',
                unsafe_allow_html=True,
            )
            drive_option_col, drive_date_col = st.columns(2)
            with drive_option_col:
                drive_csv_origin = st.selectbox(
                    "Origem dos arquivos CSV no Drive",
                    [PROD, GPON],
                    key="drive_csv_origin",
                )
            with drive_date_col:
                drive_default_date = st.date_input(
                    "Competência padrão para o Drive",
                    value=None,
                    key="drive_default_date",
                    help="Usada quando o arquivo não tiver data e o nome não indicar ano e mês.",
                )
            if st.button(
                "Importar da pasta do Drive",
                type="primary",
                width="stretch",
            ):
                if "gcp_service_account" not in st.secrets:
                    st.session_state["import_feedback"] = {
                        "type": "warning",
                        "message": (
                            "Configure as credenciais da conta de serviço em "
                            ".streamlit/secrets.toml e compartilhe a pasta do Drive com ela."
                        ),
                        "issues": [],
                    }
                    st.rerun()
                try:
                    records, issues, successful_files = import_drive_folder(
                        st.secrets["gcp_service_account"],
                        DRIVE_FOLDER_ID,
                        csv_origin=drive_csv_origin,
                        default_date=drive_default_date,
                    )
                except DriveImportError as error:
                    st.session_state["import_feedback"] = {
                        "type": "warning",
                        "message": f"Falha ao importar do Google Drive: {error}",
                        "issues": [],
                    }
                    st.rerun()
                finish_import(records, issues, successful_files)

            st.divider()
            st.markdown("**1. Selecione os arquivos**")
            st.markdown(
                '<div class="small-muted">Envie um ou mais arquivos. Ao reenviar um arquivo com o mesmo nome, seus registros serão substituídos sem duplicar o histórico.</div>',
                unsafe_allow_html=True,
            )
            files = st.file_uploader(
                "Planilhas de produção",
                type=["xlsx", "xls", "csv"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            option_col, date_col = st.columns(2)
            with option_col:
                csv_origin = st.selectbox(
                    "Origem para arquivos CSV",
                    [PROD, GPON],
                    help="Arquivos Excel usam automaticamente o nome das abas.",
                )
            with date_col:
                default_date = st.date_input(
                    "Competência padrão (opcional)",
                    value=None,
                    help="Usada somente quando o arquivo não tiver coluna de data/competência.",
                )
            if st.button(
                "Processar e importar",
                type="primary",
                disabled=not files,
                width="stretch",
            ):
                all_records = []
                issues = []
                successful_files = 0
                for uploaded in files:
                    try:
                        records, file_issues = process_upload(
                            uploaded.name,
                            uploaded.getvalue(),
                            csv_origin=csv_origin,
                            default_date=default_date,
                        )
                        if records:
                            all_records.extend(records)
                            successful_files += 1
                        issues.extend(f"{uploaded.name} · {issue}" for issue in file_issues[:20])
                    except ValueError as error:
                        issues.append(f"{uploaded.name} · {error}")
                finish_import(all_records, issues, successful_files)

    with help_col:
        with st.container(border=True):
            st.markdown("**2. Confira o formato**")
            st.markdown(
                """
                <div class="small-muted">
                Cada planilha Excel deve conter as abas <b>Prod</b> e/ou <b>Gpon</b>, com:
                <ul>
                    <li><b>Técnico:</b> nome do colaborador</li>
                    <li><b>Pontos:</b> valor produzido</li>
                    <li><b>Data:</b> dia ou competência mensal</li>
                </ul>
                Também reconhecemos Competência, Mês, Colaborador e Pontuação.
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="formula"><b>Pontos Totais = Pontos em Prod + Pontos em Gpon</b></div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "Baixar planilha modelo",
                data=template_file(),
                file_name="modelo_producao.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.link_button("Abrir pasta no Google Drive", DRIVE_FOLDER_URL, width="stretch")

    section_heading("Arquivos na base", "Reenvios com o mesmo nome substituem apenas a origem correspondente")
    batches = import_batches()
    if not batches.empty:
        batches = batches.rename(
            columns={
                "source_file": "Arquivo",
                "origins": "Abas",
                "rows_count": "Registros",
                "points": "Soma de pontos",
                "imported_at": "Importado em",
            }
        )
        batches["Arquivo"] = batches["Arquivo"].replace(DEMO_SOURCE, "Base de demonstração")
        batches["Importado em"] = pd.to_datetime(batches["Importado em"]).dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(batches, width="stretch", hide_index=True)

    stats = database_stats()
    first_date = pd.Timestamp(stats["first_date"]).strftime("%d/%m/%Y") if stats["first_date"] else "—"
    last_date = pd.Timestamp(stats["last_date"]).strftime("%d/%m/%Y") if stats["last_date"] else "—"
    st.markdown(
        f'<div class="small-muted">A base contém <b>{stats["records"]}</b> linhas de {stats["technicians"]} técnicos, com produção entre <b>{first_date}</b> e <b>{last_date}</b>.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Limpar dados"):
        if is_demo:
            st.markdown("Remova a demonstração para começar com uma base vazia.")
            if st.button("Remover dados de demonstração"):
                clear_demonstration()
                st.session_state.pop("period_filter", None)
                st.rerun()
        st.warning("A limpeza completa apaga todos os registros importados. Essa ação não pode ser desfeita.")
        confirmation = st.checkbox("Confirmo que desejo apagar toda a base de produção")
        if st.button("Apagar toda a base", disabled=not confirmation):
            clear_database()
            for key in ("period_filter", "technician_filter", "custom_start", "custom_end"):
                st.session_state.pop(key, None)
            st.rerun()


# Inicialização e navegação ---------------------------------------------------
init_database()
create_demonstration()
records = load_records()
stats = database_stats()
is_demo = bool(stats["records"] and stats["demo_rows"] == stats["records"])

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
        ["Visão geral", "Prod", "Histórico", "Técnicos", "Importar dados"],
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

page_titles = {
    "Visão geral": ("Histórico de produção", "Acompanhe a evolução e os resultados da equipe técnica."),
    "Prod": ("Quantidade de O.S. · Prod", "Acompanhe o volume de ordens de serviço da aba Prod."),
    "Histórico": ("Histórico de produção", "Detalhamento mensal da produção por técnico."),
    "Técnicos": ("Produção por técnico", "Analise a evolução individual e compare com a equipe."),
    "Importar dados": ("Base de produção", "Importação, validação e gestão das planilhas."),
}
title, subtitle = page_titles[navigation]
title_col, meta_col = st.columns([3.4, 1])
with title_col:
    st.markdown(f"<h1>{title}</h1><div class='page-subtitle'>{subtitle}</div>", unsafe_allow_html=True)
with meta_col:
    updated = "Sem importações"
    if stats["last_import"]:
        updated = pd.Timestamp(stats["last_import"]).strftime("Atualizado em %d/%m/%Y<br>%H:%M")
    st.markdown(
        f"<div class='header-meta'><strong>Base de produção</strong><br>{updated}</div>",
        unsafe_allow_html=True,
    )

if is_demo:
    st.markdown(
        """
        <div class="demo-banner">
            <strong>Dados de demonstração.</strong> Explore o painel à vontade. Ao importar a primeira planilha real, esta base será substituída automaticamente.
        </div>
        """,
        unsafe_allow_html=True,
    )

if navigation == "Importar dados":
    render_import(is_demo)
elif records.empty:
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
    st.download_button(
        "Baixar planilha modelo",
        data=template_file(),
        file_name="modelo_producao.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    filtered, technicians, months = apply_filters(records)
    if filtered.empty:
        st.info("Não há produção para os filtros selecionados. Ajuste o período ou os técnicos.")
    elif navigation == "Visão geral":
        render_overview(filtered, records, technicians, months)
    elif navigation == "Prod":
        render_prod_orders(filtered)
    elif navigation == "Histórico":
        render_history(filtered)
    elif navigation == "Técnicos":
        render_technicians(filtered)

st.markdown(
    '<div class="footer">Totale · Histórico de produção &nbsp;•&nbsp; Pontos Totais = Prod + Gpon</div>',
    unsafe_allow_html=True,
)
