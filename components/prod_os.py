"""Painel de quantidade de ordens de serviço originadas da aba Prod."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import formatar_numero_br, render_ticker
from components.painel_quantidades import (
    AZUL_TOTALE,
    CHART_CONFIG,
    LARANJA_TOTALE,
)
from components.painel_quantidades import (
    best_month_style as _best_month_style,
)
from components.painel_quantidades import (
    chart_layout as _chart_layout,
)
from components.painel_quantidades import (
    csv_download as _csv_download,
)
from components.painel_quantidades import (
    metric_card as _metric_card,
)
from components.painel_quantidades import (
    section_heading as _section_heading,
)
from components.painel_quantidades import (
    total_column_style as _total_column_style,
)
from production import PROD, month_label, summarize_os


def _technician_monthly_table(
    prod: pd.DataFrame, month_labels: list[str]
) -> pd.DataFrame:
    detail = summarize_os(prod, ["technician", "period"])
    detail["Competência"] = detail["period"].map(month_label)
    table = (
        detail.pivot(index="technician", columns="Competência", values="os_count")
        .reindex(columns=month_labels)
        .fillna(0)
        .astype(int)
    )
    table["Total"] = table.sum(axis=1)
    table = table.sort_values("Total", ascending=False)
    table.loc["Total geral"] = table.sum(axis=0)
    table.index.name = "Técnico"
    return table.reset_index()


def render_prod_orders(filtered: pd.DataFrame) -> None:
    """Renderiza contagem mensal e por técnico das linhas da aba Prod.

    O importador armazena uma linha por registro válido da planilha, portanto
    cada linha da origem Prod representa uma O.S. para fins de contagem.
    """
    prod = filtered[filtered["source_sheet"].eq(PROD)]
    if prod.empty:
        render_ticker(
            [("Ordens de serviço", "Nenhuma O.S. da aba Prod no recorte")],
            label="Indicadores de quantidade de O.S.",
        )
        st.info("Não há O.S. da aba Prod para os filtros selecionados.")
        return

    total_os = len(prod)
    active_technicians = prod["technician"].nunique()
    monthly = summarize_os(prod, "period").sort_values("period")
    technician_totals = summarize_os(prod, "technician").sort_values(
        ["os_count", "technician"], ascending=[False, True]
    )
    top_month = monthly.nlargest(1, "os_count").iloc[0]
    top_technician = technician_totals.iloc[0]
    latest_month = monthly.iloc[-1]
    render_ticker(
        [
            ("Total de O.S.", formatar_numero_br(total_os)),
            (
                "Competência mais recente",
                f"{month_label(latest_month['period'])} · {formatar_numero_br(latest_month['os_count'])} O.S.",
            ),
            (
                "Mês com mais O.S.",
                f"{month_label(top_month['period'])} · {formatar_numero_br(top_month['os_count'])} O.S.",
            ),
            (
                "Técnico destaque",
                f"{top_technician['technician']} · {formatar_numero_br(top_technician['os_count'])} O.S.",
            ),
            ("Técnicos ativos", formatar_numero_br(active_technicians)),
        ],
        label="Indicadores de quantidade de O.S.",
    )
    month_labels = monthly["period"].map(month_label).tolist()
    ranking = (
        summarize_os(prod, "technician")
        .nlargest(15, "os_count")
        .sort_values("os_count", ascending=True)
    )

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
        formatted_average = (
            f"{average:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
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
    with monthly_col, st.container(border=True):
        st.markdown("**Evolução mensal de O.S.**")
        st.plotly_chart(monthly_fig, width="stretch", config=CHART_CONFIG)
    with ranking_col, st.container(border=True):
        st.markdown("**O.S. por técnico · Top 15**")
        st.plotly_chart(ranking_fig, width="stretch", config=CHART_CONFIG)

    _section_heading(
        "O.S. por técnico",
        "Maior quantidade mensal em verde; empates podem destacar mais de uma competência.",
    )
    technician_monthly = _technician_monthly_table(prod, month_labels)
    count_columns = {
        column: st.column_config.NumberColumn(format="%d")
        for column in technician_monthly.columns
        if column != "Técnico"
    }
    st.dataframe(
        technician_monthly.style.apply(_best_month_style, axis=1).map(
            _total_column_style, subset=["Total"]
        ),
        width="stretch",
        hide_index=True,
        column_config=count_columns,
        alt="Quantidade de ordens de serviço por técnico, competência e total",
    )
    st.download_button(
        "Baixar quantidade de O.S. em CSV",
        data=_csv_download(technician_monthly),
        file_name="quantidade_os_prod.csv",
        mime="text/csv",
    )


__all__ = [
    # Constantes
    "AZUL_TOTALE",
    "LARANJA_TOTALE",
    "CHART_CONFIG",
    # Renderização
    "render_prod_orders",
]
