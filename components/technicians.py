"""Componentes da página de análise por técnico."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from production import format_points, month_label, summarize

from .charts import chart_layout
from .layout import initials, metric_card, section_heading
from .styles import CHART_CONFIG, COLORS


def render_technicians(filtered: pd.DataFrame) -> None:
    section_heading("Perfil do técnico", "Evolução individual e comparação com a média da equipe")
    ranking = summarize(filtered, "technician").sort_values("points_total", ascending=False)
    names = ranking["technician"].tolist()
    selected = st.selectbox("Selecione o técnico", names, label_visibility="collapsed")
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
    best = monthly.loc[monthly["points_total"].idxmax()]
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
        textfont=dict(size=10, color="#47635a"),
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>%{y:,.0f} pontos<extra></extra>",
    )
    fig.add_scatter(
        x=team_monthly["label"],
        y=team_monthly["team_average"],
        name="Média da equipe",
        mode="lines+markers",
        line=dict(color="#d19a48", width=2, dash="dot"),
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
