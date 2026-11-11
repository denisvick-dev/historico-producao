"""Quantidade de contratos atendidos por técnico e competência.

A contagem considera contratos distintos dentro de cada combinação de técnico
e mês, usando os registros filtrados de todas as origens. O mesmo contrato pode
ser contado novamente por outro técnico ou em outro mês. Assim, todos os totais
são somas da matriz e não equivalem a contratos únicos no período nem à
Qtde_Contrato do arquivo inteiro.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler

from components.componentes import formatar_numero_br, render_ticker
from components.eficiencia import render_eficiencia_contrato
from components.painel_quantidades import (
    AZUL_TOTALE,
    CHART_CONFIG,
    LARANJA_TOTALE,
    best_month_style as _best_month_style,
    chart_layout as _chart_layout,
    csv_download as _csv_download,
    metric_card as _metric_card,
    section_heading as _section_heading,
    total_column_style as _total_column_style,
)
from production import clean_contract, is_valid_contract, month_label

REGRA_CONTAGEM = (
    "Contratos distintos por técnico e competência, considerando todas as origens. "
    "Um contrato atendido por mais de um técnico ou em meses diferentes é contado "
    "novamente; os totais somam essas contagens e não são contratos únicos do período. "
    "A contagem usa os registros filtrados, não a Qtde_Contrato do arquivo inteiro."
)


def resumir_contratos(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int, int]:
    """Retorna evolução, ranking, matriz e quantidades de linhas excluídas.

    Linhas sem contrato válido são excluídas primeiro. Das restantes, as que
    não têm técnico ou competência também são excluídas e informadas à parte.
    Uma linha por contrato/técnico/mês é contada mesmo que apareça em várias
    origens, arquivos ou projetos dentro do recorte.
    """
    mensal_vazio = pd.DataFrame(columns=["period", "contratos"])
    ranking_vazio = pd.DataFrame(columns=["technician", "contratos"])
    matriz_vazia = pd.DataFrame(
        columns=["Técnico", "Total", "Meses com produção", "Média mensal"]
    )
    if frame.empty:
        return mensal_vazio, ranking_vazio, matriz_vazia, 0, 0
    if "contract" not in frame:
        return mensal_vazio, ranking_vazio, matriz_vazia, len(frame), 0

    # A importação fornece identificadores textuais. Normalizar valores únicos
    # evita executar a mesma validação em cada linha de arquivos grandes.
    contratos = frame["contract"].astype("string")
    valores = contratos.dropna().unique()
    normalizados = {valor: clean_contract(valor) for valor in valores}
    contratos = contratos.map(normalizados)
    validos_unicos = {
        valor: is_valid_contract(valor) for valor in contratos.dropna().unique()
    }
    validos = contratos.map(validos_unicos).fillna(False).astype(bool)
    sem_contrato = int((~validos).sum())
    if not validos.any():
        return mensal_vazio, ranking_vazio, matriz_vazia, sem_contrato, 0

    # Trabalha apenas com as colunas necessárias, preservando os índices do recorte.
    work = pd.DataFrame(
        {"contract": contratos.loc[validos]}, index=frame.index[validos]
    )
    if "technician" in frame:
        work["technician"] = (
            frame.loc[validos, "technician"].astype("string").str.strip()
        )
    else:
        work["technician"] = pd.NA
    datas = pd.Series(pd.NaT, index=work.index, dtype="datetime64[ns]")
    if "period" in frame:
        datas = pd.to_datetime(frame.loc[validos, "period"], errors="coerce")
    if "reference_date" in frame:
        datas = datas.fillna(
            pd.to_datetime(frame.loc[validos, "reference_date"], errors="coerce")
        )
    work["period"] = datas.dt.to_period("M").dt.to_timestamp()
    incompletos = (
        work["technician"].isna()
        | work["technician"]
        .str.casefold()
        .isin(["", "sem técnico", "sem tecnico", "none", "nan", "null"])
        | work["period"].isna()
    )
    sem_tecnico_ou_data = int(incompletos.sum())
    work = work.loc[~incompletos].drop_duplicates(["technician", "period", "contract"])
    if work.empty:
        return (
            mensal_vazio,
            ranking_vazio,
            matriz_vazia,
            sem_contrato,
            sem_tecnico_ou_data,
        )

    detalhe = (
        work.groupby(["technician", "period"], as_index=False)
        .size()
        .rename(columns={"size": "contratos"})
    )
    mensal = (
        detalhe.groupby("period", as_index=False)
        .agg(contratos=("contratos", "sum"))
        .sort_values(by=["period"], ascending=[True])
        .reset_index(drop=True)
    )
    ranking = (
        detalhe.groupby("technician", as_index=False)
        .agg(contratos=("contratos", "sum"))
        .sort_values(by=["contratos", "technician"], ascending=[False, True])
        .reset_index(drop=True)
    )
    matriz = (
        detalhe.pivot(index="technician", columns="period", values="contratos")
        .reindex(columns=mensal["period"])
        .fillna(0)
        .astype(int)
    )
    matriz.columns = [month_label(mes) for mes in matriz.columns]
    colunas_meses = list(matriz.columns)
    matriz["Total"] = matriz.sum(axis=1)
    matriz.index.name = "Técnico"
    matriz = (
        matriz.reset_index()
        .sort_values(["Total", "Técnico"], ascending=[False, True])
        .reset_index(drop=True)
    )
    total = {
        "Técnico": "Total geral",
        **{
            coluna: int(matriz[coluna].sum())
            for coluna in matriz.columns
            if coluna != "Técnico"
        },
    }
    matriz = pd.concat([matriz, pd.DataFrame([total])], ignore_index=True)
    matriz["Meses com produção"] = matriz[colunas_meses].gt(0).sum(axis=1).astype(int)
    # No total geral, o denominador são meses em que a equipe teve contratos,
    # não a soma dos meses individuais dos técnicos.
    meses_ativos = matriz["Meses com produção"].where(
        matriz["Meses com produção"].gt(0)
    )
    matriz["Média mensal"] = matriz["Total"].div(meses_ativos).fillna(0.0)
    return mensal, ranking, matriz, sem_contrato, sem_tecnico_ou_data


def render_contratos(filtered: pd.DataFrame) -> None:
    """Exibe quantidade de contratos e eficiência por contrato em sub-abas."""
    mensal, ranking, matriz, sem_contrato, incompletos = resumir_contratos(filtered)
    if mensal.empty:
        render_ticker(
            [("Contratos", "Nenhum contrato válido para os filtros selecionados")],
            label="Indicadores de contratos",
        )
        st.info(
            "Não há contratos com técnico e competência válidos para os filtros selecionados."
        )
        if sem_contrato or incompletos:
            st.caption(
                f"Registros excluídos: {formatar_numero_br(sem_contrato)} sem contrato válido e {formatar_numero_br(incompletos)} sem técnico ou data válida."
            )
        return

    total = int(mensal["contratos"].sum())
    ativos = len(ranking)
    ultimo = mensal.iloc[-1]
    pico_idx = int(mensal["contratos"].argmax())
    pico = mensal.iloc[pico_idx]
    destaque = ranking.iloc[0]
    render_ticker(
        [
            ("Total de contratos", formatar_numero_br(total)),
            (
                "Competência mais recente",
                f"{month_label(ultimo['period'])} · {formatar_numero_br(ultimo['contratos'])} contratos",
            ),
            (
                "Mês com mais contratos",
                f"{month_label(pico['period'])} · {formatar_numero_br(pico['contratos'])} contratos",
            ),
            (
                "Técnico destaque",
                f"{destaque['technician']} · {formatar_numero_br(destaque['contratos'])} contratos",
            ),
            ("Técnicos ativos", formatar_numero_br(ativos)),
        ],
        label="Indicadores de contratos",
    )

    aba_quantidade, aba_eficiencia = st.tabs(
        ["Quantidade de contratos", "Eficiência de contratos"]
    )

    with aba_quantidade:
        cards = st.columns(3)
        with cards[0]:
            _metric_card(
                "TOTAL DE CONTRATOS",
                formatar_numero_br(total),
                "Soma por técnico e competência",
                "CT",
            )
        with cards[1]:
            _metric_card(
                "TÉCNICOS COM CONTRATOS",
                formatar_numero_br(ativos),
                "Técnicos com contratos no recorte",
                "T",
            )
        with cards[2]:
            _metric_card(
                "MÉDIA POR TÉCNICO",
                formatar_numero_br(total / ativos, 1),
                "Total por técnico no recorte",
                "Ø",
            )

        _section_heading("Quantidade de contratos", REGRA_CONTAGEM)
        if sem_contrato or incompletos:
            st.caption(
                f"Registros excluídos: {formatar_numero_br(sem_contrato)} sem contrato válido e {formatar_numero_br(incompletos)} sem técnico ou data válida."
            )

        grafico_mensal = go.Figure()
        grafico_mensal.add_bar(
            x=mensal["period"].map(month_label),
            y=mensal["contratos"],
            marker_color=AZUL_TOTALE,
            text=mensal["contratos"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} contratos<extra></extra>",
        )
        maximo = int(mensal["contratos"].max())
        grafico_mensal.update_yaxes(
            range=[0, maximo * 1.2 if maximo else 1], title="Contratos"
        )
        _chart_layout(grafico_mensal)
        top = ranking.head(15).iloc[::-1]
        grafico_ranking = go.Figure()
        grafico_ranking.add_bar(
            x=top["contratos"],
            y=top["technician"],
            orientation="h",
            marker_color=LARANJA_TOTALE,
            text=top["contratos"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}<br>%{x:,.0f} contratos<extra></extra>",
        )
        _chart_layout(grafico_ranking, height=max(320, len(top) * 28 + 70))
        grafico_ranking.update_layout(margin=dict(l=8, r=45, t=15, b=8))
        grafico_ranking.update_xaxes(showgrid=False, showticklabels=False)
        mensal_col, ranking_col = st.columns([1, 1.1])
        with mensal_col, st.container(border=True):
            st.markdown("**Evolução mensal de contratos**")
            st.plotly_chart(grafico_mensal, width="stretch", config=CHART_CONFIG)
        with ranking_col, st.container(border=True):
            st.markdown("**Contratos por técnico · Top 15**")
            st.plotly_chart(grafico_ranking, width="stretch", config=CHART_CONFIG)

        _section_heading(
            "Contratos por técnico",
            "Maior quantidade mensal em verde; empates podem destacar mais de uma competência. O total soma os meses.",
        )
        count_columns = {
            coluna: st.column_config.NumberColumn(format="%d")
            for coluna in matriz.columns
            if coluna not in {"Técnico", "Média mensal"}
        }
        count_columns["Média mensal"] = st.column_config.NumberColumn(
            "Média mensal",
            format="%.0f",
            help="Total de contratos dividido pelos meses com contratos no recorte.",
        )
        st.caption(
            "Média mensal = total de contratos ÷ meses com produção (meses com pelo menos um contrato válido). "
            "Na linha Total geral, a média usa os meses com contratos de qualquer técnico."
        )
        # Evita o custo e o limite de células do Styler em matrizes muito grandes.
        visualizacao: Styler | pd.DataFrame
        if matriz.size <= 10_000:
            visualizacao = matriz.style.apply(
                _best_month_style,
                axis=1,
                exclude_columns=("Meses com produção", "Média mensal"),
            ).map(_total_column_style, subset=["Total"])
        else:
            visualizacao = matriz
            st.caption("Destaque de cores desativado para matrizes grandes.")
        st.dataframe(
            visualizacao,
            width="stretch",
            hide_index=True,
            column_config=count_columns,
            alt="Contratos por técnico, competência e total",
        )
        st.download_button(
            "Baixar quantidade de contratos em CSV",
            data=_csv_download(matriz),
            file_name="quantidade_contratos.csv",
            mime="text/csv",
            key="download_quantidade_contratos",
        )

    with aba_eficiencia:
        render_eficiencia_contrato(filtered)
