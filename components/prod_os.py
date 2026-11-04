"""Painel de quantidade de ordens de serviço originadas da aba Prod."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import Cores, Fontes, formatar_numero_br
from production import PROD, month_label, summarize_os

AZUL_TOTALE = Cores.PRIMARIA
LARANJA_TOTALE = Cores.SECUNDARIA
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def _metric_card(label: str, value: str, note: str, symbol: str) -> None:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-top"><span class="kpi-label">{label}</span><span class="kpi-dot">{symbol}</span></div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_heading(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>',
        unsafe_allow_html=True,
    )


def _csv_download(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def _chart_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=12, t=15, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=Cores.TEXTO_3, size=11),
        bargap=0.35,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(size=10))
    fig.update_yaxes(
        gridcolor="#e6edf5",
        zeroline=False,
        fixedrange=True,
        tickfont=dict(size=10),
        separatethousands=True,
    )
    return fig


def render_prod_orders(filtered: pd.DataFrame) -> None:
    """Renderiza contagem mensal e por técnico das linhas da aba Prod.

    O importador armazena uma linha por registro válido da planilha, portanto
    cada linha da origem Prod representa uma O.S. para fins de contagem.
    """
    prod = filtered[filtered["source_sheet"].eq(PROD)]
    if prod.empty:
        st.info("Não há O.S. da aba Prod para os filtros selecionados.")
        return

    total_os = len(prod)
    active_technicians = prod["technician"].nunique()
    monthly = summarize_os(prod, "period").sort_values("period")
    ranking = (
        summarize_os(prod, "technician")
        .nlargest(15, "os_count")
        .sort_values("os_count", ascending=True)
    )
    detail = summarize_os(prod, ["period", "technician"])
    detail = detail.sort_values(["period", "os_count"], ascending=[False, False])

    columns = st.columns(3)
    with columns[0]:
        _metric_card(
            "TOTAL DE O.S.",
            formatar_numero_br(total_os),
            "Linhas válidas da aba Prod no período",
            "O.S.",
        )
    with columns[1]:
        _metric_card(
            "TÉCNICOS COM O.S.",
            formatar_numero_br(active_technicians),
            "Técnicos com produção Prod",
            "P",
        )
    with columns[2]:
        average = total_os / active_technicians if active_technicians else 0
        formatted_average = f"{average:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        _metric_card(
            "MÉDIA DE O.S. POR TÉCNICO",
            formatted_average,
            "No recorte selecionado",
            "Ø",
        )

    _section_heading(
        "Quantidade de O.S.",
        "Cada linha válida importada da aba Prod é contabilizada como uma O.S.",
    )
    monthly["label"] = monthly["period"].map(month_label)
    monthly_fig = go.Figure()
    monthly_fig.add_bar(
        x=monthly["label"],
        y=monthly["os_count"],
        name="O.S.",
        marker_color=AZUL_TOTALE,
        text=monthly["os_count"],
        textposition="outside",
        textfont=dict(size=10, color=AZUL_TOTALE),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} O.S.<extra></extra>",
    )
    maximum = monthly["os_count"].max() if not monthly.empty else 1
    monthly_fig.update_yaxes(
        range=[0, maximum * 1.2 if maximum else 1], title="Quantidade de O.S."
    )
    _chart_layout(monthly_fig)

    ranking_fig = go.Figure()
    ranking_fig.add_bar(
        x=ranking["os_count"],
        y=ranking["technician"],
        orientation="h",
        marker_color=LARANJA_TOTALE,
        text=ranking["os_count"],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="%{y}<br>%{x:,.0f} O.S.<extra></extra>",
    )
    _chart_layout(ranking_fig, height=max(320, len(ranking) * 28 + 70))
    ranking_fig.update_layout(margin=dict(l=8, r=45, t=15, b=8))
    ranking_fig.update_xaxes(showgrid=False, showticklabels=False)

    monthly_col, ranking_col = st.columns([1, 1.1])
    with monthly_col:
        with st.container(border=True):
            st.markdown("**Evolução mensal de O.S.**")
            st.plotly_chart(monthly_fig, width="stretch", config=CHART_CONFIG)
    with ranking_col:
        with st.container(border=True):
            st.markdown("**O.S. por técnico · Top 15**")
            st.plotly_chart(ranking_fig, width="stretch", config=CHART_CONFIG)

    _section_heading("O.S. por técnico e competência", "Detalhamento das linhas válidas da aba Prod")
    detail["Competência"] = detail["period"].map(month_label)
    detail = detail.rename(columns={"technician": "Técnico", "os_count": "Quantidade de O.S."})
    detail = detail[["Competência", "Técnico", "Quantidade de O.S."]]
    st.dataframe(
        detail,
        width="stretch",
        hide_index=True,
        column_config={"Quantidade de O.S.": st.column_config.NumberColumn(format="%d")},
    )
    st.download_button(
        "Baixar quantidade de O.S. em CSV",
        data=_csv_download(detail),
        file_name="quantidade_os_prod.csv",
        mime="text/csv",
    )
