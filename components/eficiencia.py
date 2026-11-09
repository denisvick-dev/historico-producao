"""Eficiência mensal por técnico e por contrato no recorte selecionado."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import Cores, Fontes, formatar_numero_br, render_kpi_card
from production import clean_contract, is_valid_contract, month_label

FAIXAS = [f"Faixa {numero}" for numero in range(1, 6)]
CORES_FAIXAS = {
    "Faixa 1": ("#DBEAFE", "#1D4ED8"),
    "Faixa 2": ("#DCFCE7", "#15803D"),
    "Faixa 3": ("#FEF3C7", "#B45309"),
    "Faixa 4": ("#FFEDD5", "#C2410C"),
    "Faixa 5": ("#EDE9FE", "#6D28D9"),
}


def calcular_eficiencia(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Soma os pontos por técnico e mês e encontra a(s) faixa(s) mais frequente(s).

    Meses sem registros não são considerados. Empates são preservados.
    """
    detalhes_colunas = ["Técnico", "Competência", "Pontos", "Faixa"]
    resumo_colunas = ["Técnico", "Meses com registros", *FAIXAS, "Faixa mais frequente"]
    if frame.empty or not {"technician", "points"}.issubset(frame.columns):
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(columns=resumo_colunas)
    coluna_data = "period" if "period" in frame.columns else "reference_date"
    if coluna_data not in frame.columns:
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(columns=resumo_colunas)
    work = frame.copy()
    work["Competência"] = pd.to_datetime(work[coluna_data], errors="coerce").dt.to_period("M").dt.to_timestamp()
    work["Técnico"] = work["technician"].fillna("Sem técnico").astype(str).str.strip().replace("", "Sem técnico")
    work["Pontos"] = pd.to_numeric(work["points"], errors="coerce")
    work = work.dropna(subset=["Competência", "Pontos"])
    if work.empty:
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(columns=resumo_colunas)
    detalhes = work.groupby(["Técnico", "Competência"], as_index=False)["Pontos"].sum()
    # Limites contínuos: 400 pertence à faixa 5, sem lacunas entre faixas.
    detalhes["Faixa"] = pd.cut(detalhes["Pontos"], bins=[float("-inf"), 300, 350, 375, 400, float("inf")], labels=FAIXAS, right=False).astype(str)
    contagem = pd.crosstab(detalhes["Técnico"], detalhes["Faixa"]).reindex(columns=FAIXAS, fill_value=0)
    resumo = contagem.copy()
    resumo.insert(0, "Meses com registros", contagem.sum(axis=1))
    resumo["Faixa mais frequente"] = contagem.apply(
        lambda linha: " / ".join(linha.index[linha.eq(linha.max())]), axis=1
    )
    resumo = resumo.reset_index()[resumo_colunas]
    return detalhes[detalhes_colunas], resumo


def _estilo_faixa(faixa: object) -> str:
    cores = CORES_FAIXAS.get(str(faixa))
    if cores is None:
        return ""
    fundo, texto = cores
    return f"background-color: {fundo}; color: {texto}; font-weight: 600"


def _estilo_resumo_linha(linha: pd.Series) -> pd.Series:
    estilos = pd.Series("", index=linha.index, dtype="object")
    if pd.to_numeric(linha["Meses com registros"], errors="coerce") > 0:
        estilos["Meses com registros"] = (
            "background-color: #E8EEF8; color: #012869; font-weight: 600"
        )

    for faixa in FAIXAS:
        if pd.to_numeric(linha[faixa], errors="coerce") > 0:
            estilos[faixa] = _estilo_faixa(faixa)

    frequentes = str(linha["Faixa mais frequente"]).split(" / ")
    if len(frequentes) == 1:
        estilos["Faixa mais frequente"] = _estilo_faixa(frequentes[0])
    else:
        estilos["Faixa mais frequente"] = (
            "background-color: #E0F2FE; color: #075985; font-weight: 600"
        )
    return estilos


def render_eficiencia(frame: pd.DataFrame) -> None:
    detalhes, resumo = calcular_eficiencia(frame)
    if detalhes.empty:
        st.info("Não há competências válidas para calcular a eficiência.")
        return

    tecnicos = ["Todos"] + sorted(detalhes["Técnico"].dropna().astype(str).unique().tolist())
    tecnico_selecionado = st.selectbox(
        "Filtrar por técnico",
        tecnicos,
        index=0,
        help="Selecione um técnico para reduzir o detalhamento e o resumo da eficiência.",
        key="eficiencia_tecnico_filter",
    )

    if tecnico_selecionado != "Todos":
        detalhes = detalhes[detalhes["Técnico"].eq(tecnico_selecionado)]
        resumo = resumo[resumo["Técnico"].eq(tecnico_selecionado)]

    if detalhes.empty:
        st.info("Não há registros para o técnico selecionado no recorte atual.")
        return

    st.markdown("### Eficiência por técnico por mês")
    st.caption(
        "Pontos Totais = Prod + Gpon. Faixa 1: menos de 300; Faixa 2: 300 a menos de 350; "
        "Faixa 3: 350 a menos de 375; Faixa 4: 375 a menos de 400; Faixa 5: 400 ou mais pontos."
    )
    st.markdown("**Faixa mais frequente no período**")
    st.caption(
        "A faixa mais frequente é aquela com mais meses registrados. Empates são "
        "exibidos juntos; meses sem registros não são classificados."
    )
    st.caption(
        "As cores destacam as faixas com registros e identificam a mais frequente; "
        "empates são destacados em azul."
    )
    st.dataframe(
        resumo.style.apply(_estilo_resumo_linha, axis=1),
        hide_index=True,
        width="stretch",
        alt="Frequência das faixas por técnico",
    )
    st.markdown("**Detalhamento mensal**")
    exibicao = detalhes.copy()
    exibicao["Competência"] = exibicao["Competência"].map(month_label)
    st.dataframe(
        exibicao.style.map(_estilo_faixa, subset=["Faixa"]),
        hide_index=True,
        width="stretch",
        alt="Pontos e faixa mensal por técnico",
        column_config={"Pontos": st.column_config.NumberColumn(format="%.2f")},
    )
    st.download_button("Baixar eficiência mensal em CSV", data=exibicao.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), file_name="eficiencia_mensal.csv", mime="text/csv")


def resumir_eficiencia_contrato(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Detalhamento contrato·mês, resumo por contrato e distribuição de faixas.

    Linhas sem contrato válido ficam de fora. Faixas de pontos por contrato
    no mês: Faixa 1 < 300; Faixa 2 [300, 350); Faixa 3 [350, 375); Faixa 4
    [375, 400); Faixa 5 >= 400.
    """
    detalhes_colunas = ["Contrato", "Competência", "Pontos", "Faixa"]
    resumo_colunas = [
        "Contrato",
        "Meses com registros",
        "Pontos totais",
        "Faixa mais frequente",
    ]
    faixas_zero = pd.Series(0, index=FAIXAS, name="Contratos", dtype="int64")
    if frame.empty or "points" not in frame.columns:
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )
    fonte = "period" if "period" in frame.columns else "reference_date"
    if fonte not in frame.columns:
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )
    work = frame.copy()
    work["Pontos"] = pd.to_numeric(work["points"], errors="coerce")
    work["Competência"] = (
        pd.to_datetime(work[fonte], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    if "contract" not in work.columns:
        work["contract"] = "Sem contrato"
    work["Contrato"] = work["contract"].map(clean_contract)
    work = work.loc[work["Contrato"].map(is_valid_contract)]
    work = work.dropna(subset=["Competência", "Pontos"])
    if work.empty:
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )

    detalhes = work.groupby(["Contrato", "Competência"], as_index=False)["Pontos"].sum()
    # Limites contínuos: 400 pertence à faixa 5, sem lacunas entre faixas.
    detalhes["Faixa"] = pd.cut(
        detalhes["Pontos"],
        bins=[float("-inf"), 300, 350, 375, 400, float("inf")],
        labels=FAIXAS,
        right=False,
    ).astype(str)

    resumo = (
        detalhes.groupby("Contrato", as_index=False)
        .agg(
            **{
                "Meses com registros": ("Competência", "nunique"),
                "Pontos totais": ("Pontos", "sum"),
            }
        )
    )
    resumo["Faixa mais frequente"] = resumo["Contrato"].map(
        detalhes.groupby("Contrato")["Faixa"].apply(
            lambda faixas: faixas.value_counts().idxmax()
        )
    )
    resumo = (
        resumo.sort_values(["Pontos totais", "Contrato"], ascending=[False, True])
        .reset_index(drop=True)[resumo_colunas]
    )
    faixas = detalhes["Faixa"].value_counts().reindex(FAIXAS, fill_value=0)
    faixas.name = "Contratos"
    return detalhes[detalhes_colunas], resumo, faixas.astype("int64")


CORES_FAIXAS_BARRA = ["#1D4ED8", "#15803D", "#B45309", "#C2410C", "#6D28D9"]


def _grafico_distribuicao_faixas(faixas: pd.Series) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=list(FAIXAS),
            y=[int(valor) for valor in faixas.reindex(FAIXAS, fill_value=0)],
            marker_color=CORES_FAIXAS_BARRA,
            text=[int(valor) for valor in faixas.reindex(FAIXAS, fill_value=0)],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{y} contrato(s)·mês<extra></extra>",
        )
    )
    fig.update_layout(
        height=260,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.4,
        showlegend=False,
        font={"family": Fontes.TEXTO, "color": Cores.TEXTO_3, "size": 11},
        hoverlabel={"bgcolor": "white", "font_color": Cores.PRIMARIA},
    )
    fig.update_xaxes(showgrid=False, zeroline=False, fixedrange=True)
    fig.update_yaxes(
        gridcolor="#E6EDF5",
        zeroline=False,
        fixedrange=True,
        dtick=1,
        rangemode="tozero",
        title="Contrato·mês",
    )
    return fig


def _baixar_csv(frame: pd.DataFrame, nome: str, chave_prefixo: str) -> None:
    st.download_button(
        "Baixar em CSV",
        data=frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=nome,
        mime="text/csv",
        key=f"{chave_prefixo}_{nome}",
    )


def render_eficiencia_contrato(frame: pd.DataFrame) -> None:
    """Seção enxuta de eficiência por contrato da aba unificada."""
    st.markdown("### Eficiência por contrato")
    st.caption(
        "Faixa 1: menos de 300; Faixa 2: 300 a menos de 350; Faixa 3: 350 a "
        "menos de 375; Faixa 4: 375 a menos de 400; Faixa 5: 400 ou mais "
        "pontos por contrato·mês. Registros sem contrato válido não entram "
        "na análise."
    )
    if frame.empty:
        st.info("Não há registros para calcular a eficiência por contrato.")
        return

    tecnico_col = "technician" if "technician" in frame.columns else None
    tecnicos = ["Todos"]
    if tecnico_col:
        tecnicos.extend(sorted(frame[tecnico_col].dropna().astype(str).unique().tolist()))
    tecnico_selecionado = st.selectbox(
        "Filtrar por técnico",
        tecnicos,
        index=0,
        help="Ajusta o recorte para um técnico específico antes da análise por contrato.",
        key="eficiencia_contrato_tecnico_filter",
    )
    recorte = (
        frame[frame[tecnico_col].eq(tecnico_selecionado)]
        if tecnico_selecionado != "Todos" and tecnico_col
        else frame
    )

    detalhes, resumo, faixas = resumir_eficiencia_contrato(recorte)
    if detalhes.empty:
        st.info("Nenhum contrato válido para o técnico selecionado no recorte atual.")
        return

    cards = st.columns(3)
    with cards[0]:
        render_kpi_card(
            "CONTRATOS ATIVOS",
            formatar_numero_br(len(resumo)),
            "Contratos distintos com registros no recorte",
            "CT",
            card_class="kpi-card--azul",
        )
    with cards[1]:
        render_kpi_card(
            "MESES DO PERÍODO",
            formatar_numero_br(detalhes["Competência"].nunique()),
            "Competências com registros por contrato",
            "MES",
            card_class="kpi-card--laranja",
        )
    with cards[2]:
        render_kpi_card(
            "PONTOS TOTAIS",
            formatar_numero_br(detalhes["Pontos"].sum(), 2),
            "Soma dos pontos dos contratos no recorte",
            "PTS",
            card_class="kpi-card--verde",
        )

    grafico_col, resumo_col = st.columns([1, 1.35], gap="medium")
    with grafico_col, st.container(border=True):
        st.markdown("**Distribuição das faixas**")
        st.plotly_chart(
            _grafico_distribuicao_faixas(faixas),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    with resumo_col, st.container(border=True):
        st.markdown("**Resumo por contrato**")
        st.dataframe(
            resumo.style.apply(
                lambda row: pd.Series(
                    {
                        "Meses com registros": "background-color: #E8EEF8; color: #012869; font-weight: 600",
                        "Pontos totais": "background-color: #F1F5F9; color: #475569; font-weight: 600",
                        "Faixa mais frequente": _estilo_faixa(row["Faixa mais frequente"]),
                    }
                ),
                axis=1,
            ),
            hide_index=True,
            width="stretch",
            height=280,
            alt="Resumo da eficiência por contrato",
            column_config={
                "Meses com registros": st.column_config.NumberColumn(format="%d"),
                "Pontos totais": st.column_config.NumberColumn(format="%.2f"),
                "Faixa mais frequente": st.column_config.TextColumn(width="small"),
            },
        )
        _baixar_csv(resumo, "eficiencia_por_contrato.csv", "download_eficiencia_contrato")

    with st.expander("Detalhamento mensal por contrato"):
        exibicao = detalhes.copy()
        exibicao["Competência"] = exibicao["Competência"].map(month_label)
        st.dataframe(
            exibicao.style.map(_estilo_faixa, subset=["Faixa"]),
            hide_index=True,
            width="stretch",
            alt="Detalhamento mensal de eficiência por contrato",
            column_config={
                "Pontos": st.column_config.NumberColumn(format="%.2f"),
                "Faixa": st.column_config.TextColumn(width="small"),
            },
        )
        _baixar_csv(exibicao, "eficiencia_por_contrato_mensal.csv", "download_eficiencia_contrato_mensal")
