"""Elementos visuais compartilhados pelos painéis de quantidade."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import Cores, Fontes

AZUL_TOTALE = Cores.PRIMARIA
LARANJA_TOTALE = Cores.SECUNDARIA
CHART_CONFIG = {"displayModeBar": False, "responsive": True}


def metric_card(label: str, value: str, note: str, symbol: str) -> None:
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


def section_heading(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>',
        unsafe_allow_html=True,
    )


def csv_download(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def chart_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=12, t=15, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=Cores.TEXTO_3, size=11),
        bargap=0.35,
    )
    fig.update_xaxes(
        showgrid=False, zeroline=False, fixedrange=True, tickfont=dict(size=10)
    )
    fig.update_yaxes(
        gridcolor="#e6edf5",
        zeroline=False,
        fixedrange=True,
        tickfont=dict(size=10),
        separatethousands=True,
    )
    return fig


def best_month_style(
    row: pd.Series, *, exclude_columns: tuple[str, ...] = ()
) -> pd.Series:
    styles = pd.Series("", index=row.index, dtype="object")
    if row.get("Técnico") == "Total geral":
        return styles

    month_columns = [
        column
        for column in row.index
        if column not in {"Técnico", "Total", *exclude_columns}
    ]
    if not month_columns:
        return styles

    monthly_values = pd.to_numeric(row[month_columns], errors="coerce")
    best_value = monthly_values.max()
    if pd.isna(best_value) or best_value <= 0:
        return styles

    best_months = monthly_values[monthly_values.eq(best_value)].index
    styles.loc[best_months] = (
        "background-color: #DCFCE7; color: #166534; font-weight: 600"
    )
    return styles


def total_column_style(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return "background-color: #E8EEF8; color: #012869; font-weight: 600"
