"""Filtros compartilhados entre as páginas do painel."""

from __future__ import annotations

import pandas as pd
import streamlit as st


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
