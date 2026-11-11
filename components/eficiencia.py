"""Eficiência mensal por técnico e por contrato no recorte selecionado."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler

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
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(
            columns=resumo_colunas
        )
    coluna_data = "period" if "period" in frame.columns else "reference_date"
    if coluna_data not in frame.columns:
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(
            columns=resumo_colunas
        )
    work = frame.copy()
    work["Competência"] = (
        pd.to_datetime(work[coluna_data], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    work["Técnico"] = (
        work["technician"]
        .fillna("Sem técnico")
        .astype(str)
        .str.strip()
        .replace("", "Sem técnico")
    )
    work["Pontos"] = pd.to_numeric(work["points"], errors="coerce")
    work = work.dropna(subset=["Competência", "Pontos"])
    if work.empty:
        return pd.DataFrame(columns=detalhes_colunas), pd.DataFrame(
            columns=resumo_colunas
        )
    detalhes = cast(
        pd.DataFrame,
        work.groupby(["Técnico", "Competência"], as_index=False)["Pontos"].sum(),
    )
    # Limites contínuos: 400 pertence à faixa 5, sem lacunas entre faixas.
    detalhes["Faixa"] = pd.cut(
        detalhes["Pontos"],
        bins=[float("-inf"), 300, 350, 375, 400, float("inf")],
        labels=FAIXAS,
        right=False,
    ).astype(str)
    contagem = pd.crosstab(detalhes["Técnico"], detalhes["Faixa"]).reindex(
        columns=FAIXAS, fill_value=0
    )
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


def _styled_faixa_table(frame: pd.DataFrame) -> pd.DataFrame | Styler:
    if frame.size > pd.get_option("styler.render.max_elements"):
        return frame
    return frame.style.map(_estilo_faixa, subset=["Faixa"])


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

    tecnicos = ["Todos"] + sorted(
        detalhes["Técnico"].dropna().astype(str).unique().tolist()
    )
    tecnico_selecionado = st.selectbox(
        "Filtrar por técnico",
        tecnicos,
        index=0,
        help="Selecione um técnico para reduzir o detalhamento e o resumo da eficiência.",
        key="eficiencia_tecnico_filter",
    )

    if tecnico_selecionado and tecnico_selecionado != "Todos":
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
        _styled_faixa_table(exibicao),
        hide_index=True,
        width="stretch",
        alt="Pontos e faixa mensal por técnico",
        column_config={"Pontos": st.column_config.NumberColumn(format="%.2f")},
    )
    st.download_button(
        "Baixar eficiência mensal em CSV",
        data=exibicao.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name="eficiencia_mensal.csv",
        mime="text/csv",
    )


def resumir_eficiencia_contrato(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Detalhamento contrato·mês, resumo por contrato e distribuição de faixas.

    Linhas sem contrato válido ficam de fora. Faixas de pontos por contrato
    no mês: Faixa 1 < 300; Faixa 2 [300, 350); Faixa 3 [350, 375); Faixa 4
    [375, 400); Faixa 5 >= 400. Empates na faixa mais frequente são exibidos
    juntos na ordem das faixas.
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

    if "contract" not in frame.columns:
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )

    contratos_raw = frame["contract"].astype("string")
    unicos = contratos_raw.dropna().unique()
    mapa_limpo = {valor: clean_contract(valor) for valor in unicos}
    contratos_limpos = contratos_raw.map(mapa_limpo)
    unicos_limpos = contratos_limpos.dropna().unique()
    mapa_valido = {valor: is_valid_contract(valor) for valor in unicos_limpos}
    validos = contratos_limpos.map(mapa_valido).fillna(False).astype(bool)
    if not validos.any():
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )

    work = pd.DataFrame(
        {
            "Contrato": contratos_limpos.loc[validos].astype(str),
            "Competência": (
                pd.to_datetime(
                    frame.loc[validos, fonte], errors="coerce", format="mixed"
                )
                .dt.to_period("M")
                .dt.to_timestamp()
            ),
            "Pontos": pd.to_numeric(frame.loc[validos, "points"], errors="coerce"),
        },
        index=frame.index[validos],
    ).dropna(subset=["Competência", "Pontos"])
    if work.empty:
        return (
            pd.DataFrame(columns=detalhes_colunas),
            pd.DataFrame(columns=resumo_colunas),
            faixas_zero,
        )

    detalhes = cast(
        pd.DataFrame,
        work.groupby(["Contrato", "Competência"], as_index=False)["Pontos"].sum(),
    )
    # Limites contínuos: 400 pertence à faixa 5, sem lacunas entre faixas.
    detalhes["Faixa"] = pd.cut(
        detalhes["Pontos"],
        bins=[float("-inf"), 300, 350, 375, 400, float("inf")],
        labels=FAIXAS,
        right=False,
    ).astype(str)

    contagem = pd.crosstab(detalhes["Contrato"], detalhes["Faixa"]).reindex(
        columns=FAIXAS, fill_value=0
    )
    faixa_frequente = contagem.apply(
        lambda linha: " / ".join(linha.index[linha.eq(linha.max())]), axis=1
    )

    # Os stubs do pandas não descrevem todas as formas de agregação nomeada.
    resumo = cast(Any, detalhes.groupby("Contrato", as_index=False)).agg(
        **{
            "Meses com registros": ("Competência", "nunique"),
            "Pontos totais": ("Pontos", "sum"),
        }
    )
    resumo["Faixa mais frequente"] = resumo["Contrato"].map(faixa_frequente)
    resumo = resumo.sort_values(
        ["Pontos totais", "Contrato"], ascending=[False, True]
    ).reset_index(drop=True)[resumo_colunas]
    faixas = detalhes["Faixa"].value_counts().reindex(FAIXAS, fill_value=0)
    faixas.name = "Contratos"
    return detalhes[detalhes_colunas], resumo, faixas.astype("int64")


def calcular_matriz_eficiencia_contrato(
    detalhes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Monta matriz de faixas por contrato e evolução mensal por faixa."""
    colunas_matriz = [
        "Contrato",
        "Meses com registros",
        "Pontos totais",
        "Média mensal",
        *FAIXAS,
        "Faixa mais frequente",
    ]
    colunas_evolucao = ["Competência", *FAIXAS]
    if detalhes.empty:
        return (
            pd.DataFrame(columns=colunas_matriz),
            pd.DataFrame(columns=colunas_evolucao),
        )

    contagem = pd.crosstab(detalhes["Contrato"], detalhes["Faixa"]).reindex(
        columns=FAIXAS, fill_value=0
    )
    pontos = detalhes.groupby("Contrato")["Pontos"].sum()
    meses = contagem.sum(axis=1).astype(int)
    media = pontos.div(meses.where(meses.gt(0))).fillna(0.0)
    frequente = contagem.apply(
        lambda linha: " / ".join(linha.index[linha.eq(linha.max())]), axis=1
    )

    matriz = contagem.copy()
    matriz.insert(0, "Média mensal", media)
    matriz.insert(0, "Pontos totais", pontos)
    matriz.insert(0, "Meses com registros", meses)
    matriz["Faixa mais frequente"] = frequente
    matriz = (
        matriz.reset_index()
        .sort_values(["Pontos totais", "Contrato"], ascending=[False, True])
        .reset_index(drop=True)[colunas_matriz]
    )

    evolucao = (
        pd.crosstab(detalhes["Competência"], detalhes["Faixa"])
        .reindex(columns=FAIXAS, fill_value=0)
        .sort_index()
        .reset_index()[colunas_evolucao]
    )
    return matriz, evolucao


CORES_FAIXAS_BARRA = ["#1D4ED8", "#15803D", "#B45309", "#C2410C", "#6D28D9"]


def _grafico_distribuicao_faixas(faixas: pd.Series) -> go.Figure:
    valores = [int(valor) for valor in faixas.reindex(FAIXAS, fill_value=0)]
    maximo = max(valores) if valores else 0
    fig = go.Figure(
        go.Bar(
            x=list(FAIXAS),
            y=valores,
            marker_color=CORES_FAIXAS_BARRA,
            text=valores,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{y} contrato(s)·mês<extra></extra>",
        )
    )
    fig.update_layout(
        height=300,
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
        range=[0, maximo * 1.22 if maximo > 0 else 1],
        rangemode="tozero",
        title="Contrato·mês",
    )
    return fig


def _grafico_evolucao_faixas_contrato(evolucao: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if evolucao.empty:
        return fig
    labels = evolucao["Competência"].map(month_label).tolist()
    for faixa, cor in zip(FAIXAS, CORES_FAIXAS_BARRA, strict=True):
        serie = evolucao[faixa].astype(int)
        if not serie.gt(0).any():
            continue
        fig.add_bar(
            x=labels,
            y=serie,
            name=faixa,
            marker_color=cor,
            hovertemplate=f"<b>%{{x}}</b> · {faixa}<br>%{{y}} contrato(s)<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        height=300,
        margin={"l": 8, "r": 12, "t": 32, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        bargap=0.35,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 10},
        },
        font={"family": Fontes.TEXTO, "color": Cores.TEXTO_3, "size": 11},
        hoverlabel={"bgcolor": "white", "font_color": Cores.PRIMARIA},
    )
    fig.update_xaxes(showgrid=False, zeroline=False, fixedrange=True)
    fig.update_yaxes(
        gridcolor="#E6EDF5",
        zeroline=False,
        fixedrange=True,
        rangemode="tozero",
        title="Contratos ativos",
    )
    return fig


def _estilo_matriz_contrato_linha(linha: pd.Series) -> pd.Series:
    estilos = _estilo_resumo_linha(linha)
    estilos["Pontos totais"] = (
        "background-color: #F1F5F9; color: #475569; font-weight: 600"
    )
    estilos["Média mensal"] = (
        "background-color: #F8FAFC; color: #012869; font-weight: 600"
    )
    return estilos


def _estilizar_matriz_contrato(frame: pd.DataFrame) -> pd.DataFrame | Styler:
    limite = int(pd.get_option("styler.render.max_elements"))
    if frame.size > min(10_000, limite):
        return frame
    return frame.style.apply(_estilo_matriz_contrato_linha, axis=1)


def _baixar_csv(
    frame: pd.DataFrame, rotulo: str, nome: str, chave_prefixo: str
) -> None:
    st.download_button(
        rotulo,
        data=frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=nome,
        mime="text/csv",
        key=f"{chave_prefixo}_{nome}",
    )


def render_eficiencia_contrato(frame: pd.DataFrame) -> None:
    """Renderiza a visão completa de eficiência de contratos (faixas 1 a 5)."""
    st.markdown(
        '<div class="section-heading"><div>'
        "<h2>Eficiência de contratos</h2>"
        "<p>Pontos Totais (Prod + Gpon) somados por contrato em cada competência: "
        "Faixa 1 (&lt; 300) · Faixa 2 (300–349,99) · Faixa 3 (350–374,99) · "
        "Faixa 4 (375–399,99) · Faixa 5 (400+). Registros sem contrato válido não entram na análise.</p>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    if frame.empty:
        st.info("Não há registros para calcular a eficiência por contrato.")
        return

    filtro_tec_col, filtro_faixa_col = st.columns(2)
    tecnico_col = "technician" if "technician" in frame.columns else None
    tecnicos = ["Todos"]
    if tecnico_col:
        tecnicos.extend(
            sorted(
                t
                for t in frame[tecnico_col].dropna().astype(str).str.strip().unique()
                if t
            )
        )
    with filtro_tec_col:
        tecnico_selecionado = st.selectbox(
            "Filtrar por técnico",
            tecnicos,
            index=0,
            help="Restringe os registros a um técnico antes de somar os pontos por contrato e mês.",
            key="eficiencia_contrato_tecnico_filter",
        )
    with filtro_faixa_col:
        faixa_selecionada = st.selectbox(
            "Filtrar por faixa mais frequente",
            ["Todas", *FAIXAS],
            index=0,
            help="Filtra a tabela de contratos pela faixa predominante no período.",
            key="eficiencia_contrato_faixa_filter",
        )

    recorte = (
        frame[frame[tecnico_col].eq(tecnico_selecionado)]
        if tecnico_selecionado != "Todos" and tecnico_col
        else frame
    )

    detalhes, _, faixas = resumir_eficiencia_contrato(recorte)
    if detalhes.empty:
        st.info("Nenhum contrato válido com pontuação disponível para o filtro atual.")
        return

    matriz_contratos, evolucao_mensal = calcular_matriz_eficiencia_contrato(detalhes)
    if faixa_selecionada != "Todas":
        contratos_filtrados = matriz_contratos[
            matriz_contratos["Faixa mais frequente"]
            .astype(str)
            .apply(lambda valor: faixa_selecionada in valor.split(" / "))
        ]
    else:
        contratos_filtrados = matriz_contratos

    total_contrato_mes = len(detalhes)
    media_contrato_mes = float(detalhes["Pontos"].mean())
    qtd_faixa_5 = int(faixas.get("Faixa 5", 0))
    pct_faixa_5 = (
        qtd_faixa_5 / total_contrato_mes * 100.0 if total_contrato_mes else 0.0
    )
    max_faixa = int(faixas.max())
    faixa_predominante = (
        " / ".join(faixas.index[faixas.eq(max_faixa)]) if max_faixa > 0 else "—"
    )

    cards = st.columns(4)
    with cards[0]:
        render_kpi_card(
            "CONTRATOS AVALIADOS",
            formatar_numero_br(len(matriz_contratos)),
            f"{formatar_numero_br(total_contrato_mes)} registros contrato·mês",
            "CT",
            card_class="kpi-card--azul",
        )
    with cards[1]:
        render_kpi_card(
            "MÉDIA POR CONTRATO·MÊS",
            formatar_numero_br(media_contrato_mes, 2),
            f"Em {formatar_numero_br(detalhes['Competência'].nunique())} competência(s)",
            "Ø",
            card_class="kpi-card--laranja",
        )
    with cards[2]:
        render_kpi_card(
            "CONTRATO·MÊS EM FAIXA 5",
            formatar_numero_br(qtd_faixa_5),
            f"{formatar_numero_br(pct_faixa_5, 1)}% com 400+ pontos",
            "F5",
            card_class="kpi-card--verde",
        )
    with cards[3]:
        render_kpi_card(
            "FAIXA PREDOMINANTE",
            faixa_predominante,
            f"{formatar_numero_br(max_faixa)} ocorrência(s) no período",
            "★",
            card_class="kpi-card--roxo",
        )

    dist_col, evol_col = st.columns([1, 1.25], gap="medium")
    with dist_col, st.container(border=True):
        st.markdown("**Distribuição das faixas · Contrato·mês**")
        st.plotly_chart(
            _grafico_distribuicao_faixas(faixas),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    with evol_col, st.container(border=True):
        st.markdown("**Evolução mensal das faixas de contratos**")
        st.plotly_chart(
            _grafico_evolucao_faixas_contrato(evolucao_mensal),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    st.markdown("**Resumo de eficiência por contrato**")
    st.caption(
        "Mostra quantos meses cada contrato operou em cada faixa e a faixa mais frequente "
        "(empates aparecem combinados em azul)."
    )
    if contratos_filtrados.empty:
        st.info(
            f"Nenhum contrato teve '{faixa_selecionada}' como faixa mais frequente."
        )
    else:
        config_colunas: dict[str, Any] = {
            "Contrato": st.column_config.TextColumn(width="medium"),
            "Meses com registros": st.column_config.NumberColumn(format="%d"),
            "Pontos totais": st.column_config.NumberColumn(format="%.2f"),
            "Média mensal": st.column_config.NumberColumn(format="%.2f"),
            "Faixa mais frequente": st.column_config.TextColumn(width="medium"),
        }
        for faixa in FAIXAS:
            config_colunas[faixa] = st.column_config.NumberColumn(format="%d")

        st.dataframe(
            _estilizar_matriz_contrato(contratos_filtrados),
            hide_index=True,
            width="stretch",
            alt="Resumo da eficiência e frequência de faixas por contrato",
            column_config=config_colunas,
        )
        _baixar_csv(
            contratos_filtrados,
            "Baixar eficiência de contratos em CSV",
            "eficiencia_por_contrato.csv",
            "download_eficiencia_contrato",
        )

    with st.expander("Detalhamento mensal por contrato"):
        exibicao = (
            detalhes[detalhes["Contrato"].isin(contratos_filtrados["Contrato"])]
            .sort_values(
                ["Competência", "Pontos", "Contrato"], ascending=[False, False, True]
            )
            .copy()
        )
        exibicao["Competência"] = exibicao["Competência"].map(month_label)
        st.dataframe(
            _styled_faixa_table(exibicao),
            hide_index=True,
            width="stretch",
            alt="Detalhamento mensal de eficiência por contrato",
            column_config={
                "Pontos": st.column_config.NumberColumn(format="%.2f"),
                "Faixa": st.column_config.TextColumn(width="small"),
            },
        )
        _baixar_csv(
            exibicao,
            "Baixar eficiência mensal de contratos em CSV",
            "eficiencia_por_contrato_mensal.csv",
            "download_eficiencia_contrato_mensal",
        )
