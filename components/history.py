"""Componentes da página de histórico mensal."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from production import month_label, summarize

from .layout import csv_download, section_heading
from .styles import CHART_CONFIG, COLORS


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
                colorscale=[[0, "#f0f6f3"], [0.45, "#a9ddc5"], [1, "#176449"]],
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
