"""Componentes da página Visão geral."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from production import format_points, summarize

from .charts import production_chart, ranking_chart
from .filters import previous_period
from .layout import metric_card, section_heading
from .styles import CHART_CONFIG


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
