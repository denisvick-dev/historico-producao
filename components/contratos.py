"""Contador de contratos na aba Contratos, baseado na coluna **Qtde_Contrato**.

A aba **Contratos** responde três perguntas:

• **Quanto?** — o contador em destaque soma a coluna ``contracts_qty``
  (Qtde_Contrato) de cada arquivo presente no recorte. A coluna repete, em
  todas as linhas de um arquivo, o total de contratos distintos daquele
  arquivo; por isso somamos uma vez por arquivo (o máximo), nunca as linhas.
  Um contrato que aparece em mais de um mês volta a contar naquele mês — o
  recorte **não** é uma união de contratos distintos.
• **Quem?** — o contador por técnico mostra quantos contratos distintos cada
  técnico atendeu no recorte (a coluna Qtde_Contrato é um valor único por
  arquivo e não separa por técnico, então esta seção conta
  ``nunique(contrato)`` por técnico).
• **Quando?** — a evolução mensal mostra a soma da Qtde_Contrato dos arquivos
  com registros em cada competência (o mesmo contrato pode somar em mais de
  um mês) e a soma acumulada até o mês.

A página segue o mesmo padrão visual do painel **Quantidade de O.S.**: ticker
com os indicadores no topo, linha de KPIs, seções com título próprio e os
gráficos lado a lado em painéis com borda, além da matriz
**Técnico × Competência** de contratos distintos (nunique) com o melhor mês
de cada técnico destacado em verde e a linha ``Total geral`` com a soma da
matriz.

Os cálculos ficam em funções puras (testáveis sem Streamlit); o layout apenas
consome os DataFrames resultantes.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_kpi_card,
    render_ticker,
)
from production import clean_contract, is_valid_contract, month_label

COLUNAS_RESUMO = ["Projeto", "Técnico", "Contratos distintos"]
COLUNAS_TECNICO = ["Técnico", "Contratos", "Participação (%)"]
COLUNAS_MENSAL = ["Competência", "Contratos no mês", "Acumulado (soma)"]
COLUNAS_ARQUIVO = ["Arquivo", "Origem", "Registros com contrato", "Contratos"]
CHART_CONFIG = {"displayModeBar": False, "responsive": True}

AZUL_TOTALE = Cores.PRIMARIA
LARANJA_TOTALE = Cores.SECUNDARIA


# ====================================================
# 🧮 CONTAGENS (funções puras)
# ====================================================
def _registros_com_contrato(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Separa os registros com identificador de contrato válido.

    Retorna a cópia normalizada (coluna ``contract`` limpa) e a quantidade de
    linhas sem contrato — que ficam fora das contagens por técnico e da
    contagem de registros por arquivo. O marcador ``"Sem contrato"`` gravado
    pela importação é tratado como ausência, para que ele nunca seja contado
    como se fosse um contrato real.
    """
    if frame.empty or "contract" not in frame.columns:
        return frame.iloc[0:0].copy(), 0
    work = frame.copy()
    work["contract"] = work["contract"].map(clean_contract)
    ausente = ~work["contract"].map(is_valid_contract)
    return work.loc[~ausente].reset_index(drop=True), int(ausente.sum())


def _rotulo_tecnico(valor: object) -> str:
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return "Sem técnico"
    if isinstance(valor, float) and pd.isna(valor):
        return "Sem técnico"
    texto = str(valor).strip()
    return texto or "Sem técnico"


def _chave_arquivo(serie: pd.Series) -> pd.Series:
    """Normaliza o identificador do arquivo (vazio vira ``Sem arquivo``)."""
    return (
        serie.fillna("Sem arquivo").astype(str).str.strip().replace("", "Sem arquivo")
    )


def _qtde_numerico(serie: pd.Series) -> pd.Series:
    """Converte Qtde_Contrato para número, tratando valores inválidos como 0."""
    return pd.to_numeric(serie, errors="coerce").fillna(0)


def resumir_contratos(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> tuple[pd.DataFrame, int, int]:
    """Conta identificadores distintos por projeto e técnico e no recorte inteiro."""
    colunas = COLUNAS_RESUMO
    if frame.empty or not {"project", "technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=colunas), 0, len(frame)
    validos, sem_contrato = (
        (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    )
    if validos.empty:
        return pd.DataFrame(columns=colunas), 0, sem_contrato
    validos = validos.assign(technician=validos["technician"].map(_rotulo_tecnico))
    resumo = (
        validos.groupby(["project", "technician"], dropna=False)["contract"]
        .nunique()
        .reset_index()
    )
    resumo.columns = colunas
    resumo = resumo.sort_values(
        ["Contratos distintos", "Projeto", "Técnico"],
        ascending=[False, True, True],
    ).reset_index(drop=True)
    return resumo[colunas], int(validos["contract"].nunique()), sem_contrato


def somar_qtde_contrato(
    frame: pd.DataFrame, *, _validos: pd.DataFrame | None = None
) -> tuple[int, int]:
    """Soma a Qtde_Contrato dos arquivos presentes no recorte.

    A coluna repete em todas as linhas de um arquivo o total de contratos
    distintos do arquivo; por isso somamos o valor máximo de cada arquivo
    (nunca as linhas). Retorna ``(soma, quantidade_de_arquivos)``. Sem a
    coluna ``contracts_qty``, cai para a união de contratos distintos do
    recorte (0 arquivo identificado).
    """
    if frame.empty:
        return 0, 0
    if "contracts_qty" not in frame.columns:
        validos = _validos
        if validos is None:
            validos, _ = _registros_com_contrato(frame)
        total = int(validos["contract"].nunique()) if not validos.empty else 0
        return total, 0
    if "source_file" not in frame.columns:
        maior = _qtde_numerico(frame["contracts_qty"]).max()
        return int(maior), 1
    por_arquivo = (
        frame.assign(_arquivo=_chave_arquivo(frame["source_file"]))
        .groupby("_arquivo")["contracts_qty"]
        .max()
    )
    return int(_qtde_numerico(por_arquivo).sum()), int(por_arquivo.shape[0])


def contar_contratos_por_tecnico(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> pd.DataFrame:
    """Conta contratos distintos por técnico e a participação na soma.

    A Qtde_Contrato é um valor único por arquivo e não separa por técnico;
    esta seção conta ``nunique(contrato)`` por técnico no recorte.
    """
    if frame.empty or not {"technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=COLUNAS_TECNICO)
    validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    if validos.empty:
        return pd.DataFrame(columns=COLUNAS_TECNICO)

    work = validos.assign(Técnico=validos["technician"].map(_rotulo_tecnico))
    resumo = (
        work.groupby("Técnico").agg(Contratos=("contract", "nunique")).reset_index()
    )
    soma = int(resumo["Contratos"].sum())
    resumo["Participação (%)"] = (resumo["Contratos"] / soma * 100).round(1)
    return resumo.sort_values(
        ["Contratos", "Técnico"], ascending=[False, True]
    ).reset_index(drop=True)[COLUNAS_TECNICO]


def contar_contratos_por_arquivo(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> pd.DataFrame:
    """Contador de contratos em cada arquivo importado, a partir da Qtde_Contrato.

    A coluna ``Contratos`` repete o valor da coluna Qtde_Contrato do arquivo
    (contratos distintos do arquivo inteiro, sem aplicar os filtros do
    recorte). ``Registros com contrato`` conta apenas as linhas válidas do
    recorte. Sem a coluna ``contracts_qty``, cai para ``nunique(contract)``.
    """
    if frame.empty or not {"source_file", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=COLUNAS_ARQUIVO)
    validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    if validos.empty:
        return pd.DataFrame(columns=COLUNAS_ARQUIVO)
    work = validos.assign(Arquivo=_chave_arquivo(validos["source_file"]))
    resumo = (
        work.groupby("Arquivo", as_index=False)
        .agg(Registros=("contract", "size"))
        .rename(columns={"Registros": "Registros com contrato"})
    )
    if "contracts_qty" in work.columns:
        qtde = work.groupby("Arquivo")["contracts_qty"].max()
        resumo["Contratos"] = (
            _qtde_numerico(resumo["Arquivo"].map(qtde)).fillna(0).astype(int)
        )
    else:
        resumo["Contratos"] = (
            work.groupby("Arquivo")["contract"]
            .nunique()
            .reindex(resumo["Arquivo"])
            .to_numpy()
        )
    if "source_sheet" in work.columns:
        origens = work.groupby("Arquivo")["source_sheet"].agg(
            lambda valores: " / ".join(
                sorted({str(valor) for valor in valores.dropna() if str(valor).strip()})
            )
        )
        resumo["Origem"] = resumo["Arquivo"].map(origens).fillna("—")
    else:
        resumo["Origem"] = "—"
    return resumo.sort_values(
        by=["Contratos", "Arquivo"],
        ascending=[False, True],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)[COLUNAS_ARQUIVO]


def _competencias(frame: pd.DataFrame) -> pd.Series | None:
    """Obtém competências mensais da data do período ou da data de referência."""
    for coluna in ("period", "reference_date"):
        if coluna not in frame.columns:
            continue
        datas = pd.to_datetime(frame[coluna], errors="coerce")
        if datas.notna().any():
            return pd.Series(
                datas.dt.to_period("M").dt.to_timestamp(), index=frame.index
            )
    return None


def contar_contratos_por_mes(frame: pd.DataFrame) -> pd.DataFrame:
    """Evolução mensal a partir da coluna Qtde_Contrato.

    Para cada competência, soma a Qtde_Contrato de cada arquivo que tem
    registros nela — o mesmo contrato pode somar em mais de um mês. A coluna
    ``Acumulado (soma)`` é a soma progressiva dos meses. Meses sem registros
    aparecem zerados. Arquivos que abrangem mais de um mês contam em cada
    competência em que aparecem.
    """
    if frame.empty or "contracts_qty" not in frame.columns:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    competencias = _competencias(frame)
    if competencias is None:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    work = frame.assign(Competencia=competencias).dropna(subset=["Competencia"])
    if work.empty:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    if "source_file" in work.columns:
        arquivos = work.assign(Arquivo=_chave_arquivo(work["source_file"]))
        por_arquivo = (
            arquivos.groupby(["Competencia", "Arquivo"])["contracts_qty"]
            .max()
            .reset_index()
        )
        por_mes = _qtde_numerico(
            por_arquivo.groupby("Competencia")["contracts_qty"].sum()
        )
    else:
        por_mes = _qtde_numerico(work.groupby("Competencia")["contracts_qty"].max())

    meses = pd.date_range(start=por_mes.index.min(), end=por_mes.index.max(), freq="MS")
    acumulado = 0
    linhas = []
    for mes in meses:
        contratos = int(por_mes.get(mes, 0))
        acumulado += contratos
        linhas.append(
            {
                "Competência": month_label(mes),
                "Contratos no mês": contratos,
                "Acumulado (soma)": acumulado,
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS_MENSAL)


def contar_contratos_por_tecnico_mes(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> pd.DataFrame:
    """Matriz Técnico × Competência de contratos distintos (nunique).

    Cada célula conta quantos contratos distintos o técnico atendeu na
    competência — a mesma métrica do ranking por técnico, detalhada por mês.
    A coluna ``Total`` soma os meses; ``Participação (%)`` é a fatia do
    técnico na soma dos totais. Meses sem registros no recorte aparecem
    zerados (mesma lacuna da evolução mensal). A linha ``Total geral`` soma
    cada coluna. Registros sem contrato válido ficam de fora.
    """
    base = ["Técnico", "Total", "Participação (%)"]
    if frame.empty or not {"technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=base)
    validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    competencias = _competencias(validos)
    if validos.empty or competencias is None:
        return pd.DataFrame(columns=base)
    work = validos.assign(
        Técnico=validos["technician"].map(_rotulo_tecnico),
        Mês=competencias,
    ).dropna(subset=["Mês"])
    if work.empty:
        return pd.DataFrame(columns=base)
    detalhe = (
        work.groupby(["Técnico", "Mês"], as_index=False)["contract"]
        .nunique()
        .rename(columns={"contract": "Contratos"})
    )
    meses = pd.date_range(work["Mês"].min(), work["Mês"].max(), freq="MS")
    rotulos = [month_label(mes) for mes in meses]
    matriz = (
        detalhe.pivot(index="Técnico", columns="Mês", values="Contratos")
        .reindex(columns=meses)
        .fillna(0)
        .astype(int)
    )
    matriz.columns = rotulos
    matriz["Total"] = matriz.sum(axis=1)
    total_geral = int(matriz["Total"].sum())
    matriz = matriz.sort_values(
        ["Total", "Técnico"], ascending=[False, True]
    ).reset_index()
    matriz["Participação (%)"] = (
        (matriz["Total"] / total_geral * 100).round(1) if total_geral else 0.0
    )
    total_linha: dict[str, object] = {"Técnico": "Total geral"}
    for coluna in rotulos:
        total_linha[coluna] = int(matriz[coluna].sum())
    total_linha["Total"] = total_geral
    total_linha["Participação (%)"] = 100.0 if total_geral else 0.0
    matriz = pd.concat([matriz, pd.DataFrame([total_linha])], ignore_index=True)
    return matriz[["Técnico", *rotulos, "Total", "Participação (%)"]]


def _estilizar_figura(fig: go.Figure, altura: int = 320) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin={"l": 8, "r": 18, "t": 30, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": Fontes.TEXTO, "color": Cores.TEXTO_3, "size": 11},
        hoverlabel={"bgcolor": "white", "font_color": AZUL_TOTALE},
        legend={"orientation": "h", "y": 1.12, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(showgrid=False, zeroline=False, fixedrange=True)
    fig.update_yaxes(
        gridcolor="#E6EDF5",
        zeroline=False,
        fixedrange=True,
        separatethousands=True,
        rangemode="tozero",
    )
    return fig


def _grafico_por_tecnico(por_tecnico: pd.DataFrame) -> go.Figure:
    dados = por_tecnico.head(12).sort_values("Contratos")
    fig = go.Figure(
        go.Bar(
            x=dados["Contratos"],
            y=dados["Técnico"],
            orientation="h",
            marker_color=AZUL_TOTALE,
            text=dados["Contratos"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>%{x} contrato(s)<extra></extra>",
        )
    )
    fig.update_layout(bargap=0.35, showlegend=False)
    fig.update_xaxes(dtick=1, title=None)
    fig.update_yaxes(showgrid=False)
    return _estilizar_figura(fig, altura=max(280, len(dados) * 32 + 90))


def _grafico_mensal(mensal: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(
        x=mensal["Competência"],
        y=mensal["Contratos no mês"],
        name="Qtde_Contrato no mês",
        marker_color=AZUL_TOTALE,
        hovertemplate="<b>%{x}</b><br>Qtde_Contrato: %{y}<extra></extra>",
    )
    fig.add_scatter(
        x=mensal["Competência"],
        y=mensal["Acumulado (soma)"],
        name="Acumulado (soma)",
        mode="lines+markers",
        yaxis="y2",
        line={"color": LARANJA_TOTALE, "width": 3},
        marker={"size": 7, "color": LARANJA_TOTALE},
        hovertemplate="<b>%{x}</b><br>Acumulado: %{y}<extra></extra>",
    )
    fig.update_layout(
        yaxis={"title": "Contratos no mês"},
        yaxis2={
            "title": "Acumulado (soma)",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "rangemode": "tozero",
        },
        bargap=0.35,
    )
    return _estilizar_figura(fig)


def _section_heading(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>',
        unsafe_allow_html=True,
    )


def _best_month_style(row: pd.Series) -> pd.Series:
    styles = pd.Series("", index=row.index, dtype="object")
    if row.get("Técnico") == "Total geral":
        return styles

    month_columns = [
        column
        for column in row.index
        if column not in {"Técnico", "Total", "Participação (%)"}
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


def _total_column_style(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return "background-color: #E8EEF8; color: #012869; font-weight: 600"


def _baixar_csv(frame: pd.DataFrame, nome: str) -> None:
    st.download_button(
        "Baixar contagem em CSV",
        data=frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=nome,
        mime="text/csv",
        key=f"download_contratos_{nome}",
    )


def render_contratos(frame: pd.DataFrame) -> None:
    if frame.empty:
        render_ticker(
            [("Contratos", "Nenhum registro para os filtros selecionados")],
            label="Indicadores de contratos",
        )
        st.info("Não há registros para os filtros selecionados.")
        return

    registros_validos, ausentes = _registros_com_contrato(frame)
    resumo, _, _ = resumir_contratos(registros_validos, _prevalidated=True)
    total, arquivos = somar_qtde_contrato(frame, _validos=registros_validos)
    por_tecnico = contar_contratos_por_tecnico(
        registros_validos, _prevalidated=True
    )
    mensal = contar_contratos_por_mes(frame)

    ticker_items: list[tuple[str, str]] = [
        ("Total de contratos", formatar_numero_br(total)),
        ("Arquivos no recorte", formatar_numero_br(arquivos)),
    ]
    if not mensal.empty:
        recente = mensal.iloc[-1]
        ticker_items.append(
            (
                "Competência mais recente",
                f"{recente['Competência']} · "
                f"{formatar_numero_br(recente['Contratos no mês'])} no mês",
            )
        )
        pico = mensal.loc[mensal["Contratos no mês"].idxmax()]
        ticker_items.append(
            (
                "Mês com mais contratos",
                f"{pico['Competência']} · "
                f"{formatar_numero_br(pico['Contratos no mês'])}",
            )
        )
    if not por_tecnico.empty:
        destaque = por_tecnico.iloc[0]
        ticker_items.append(
            (
                "Técnico destaque",
                f"{destaque['Técnico']} · "
                f"{formatar_numero_br(destaque['Contratos'])} contrato(s)",
            )
        )
    ticker_items.append(("Técnicos ativos", formatar_numero_br(len(por_tecnico))))
    render_ticker(ticker_items, label="Indicadores de contratos")

    cards_colunas = st.columns(3)
    with cards_colunas[0]:
        render_kpi_card(
            "TOTAL DE CONTRATOS",
            formatar_numero_br(total),
            "Soma da Qtde_Contrato dos arquivos do recorte",
            "CT",
            card_class="kpi-card--azul",
        )
    with cards_colunas[1]:
        render_kpi_card(
            "TÉCNICOS COM CONTRATOS",
            formatar_numero_br(len(por_tecnico)),
            "Técnicos com ao menos um contrato no recorte",
            "TC",
            card_class="kpi-card--laranja",
        )
    with cards_colunas[2]:
        media = por_tecnico["Contratos"].mean() if not por_tecnico.empty else 0.0
        render_kpi_card(
            "MÉDIA POR TÉCNICO",
            formatar_numero_br(media, 1),
            "Contratos distintos por técnico",
            "MÉD",
            card_class="kpi-card--verde",
        )

    if ausentes:
        st.warning(
            f"{formatar_numero_br(ausentes)} registro(s) sem identificador de "
            "contrato não entram nas contagens por técnico nem na contagem de "
            "registros por arquivo. Dados importados antes desta atualização "
            "precisam ser sincronizados ou reimportados para preencher o campo."
        )

    _section_heading(
        "Contratos no recorte",
        "Soma da coluna Qtde_Contrato dos arquivos presentes no recorte: cada "
        "arquivo conta os contratos distintos que trouxe — um contrato que se "
        "repete em outro mês volta a contar naquele mês; o recorte não é uma "
        "união de contratos distintos.",
    )
    if total == 0:
        st.info(
            "Nenhuma Qtde_Contrato positiva nos arquivos do recorte. Verifique "
            "a coluna Contrato nos arquivos de origem e a sincronização."
        )
    else:
        mensal_col, ranking_col = st.columns([1, 1.1], gap="medium")
        with mensal_col, st.container(border=True):
            st.markdown("**Evolução mensal de contratos**")
            if mensal.empty:
                st.info(
                    "Os registros do recorte não têm data de competência válida; "
                    "não é possível montar a evolução mensal."
                )
            else:
                st.caption(
                    "Barras: soma da Qtde_Contrato dos arquivos com registros "
                    "no mês. Linha: soma acumulada até o mês. Meses sem "
                    "registros aparecem zerados."
                )
                st.plotly_chart(
                    _grafico_mensal(mensal), width="stretch", config=CHART_CONFIG
                )
                st.dataframe(
                    mensal,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Contratos no mês": st.column_config.NumberColumn(format="%d"),
                        "Acumulado (soma)": st.column_config.NumberColumn(format="%d"),
                    },
                )
                _baixar_csv(mensal, "contratos_por_mes.csv")
        with ranking_col, st.container(border=True):
            st.markdown("**Contratos por técnico · Top 12**")
            if por_tecnico.empty:
                st.info("Não há contratos por técnico para exibir.")
            else:
                st.plotly_chart(
                    _grafico_por_tecnico(por_tecnico),
                    width="stretch",
                    config=CHART_CONFIG,
                )
                st.caption(
                    "Contratos distintos por técnico no recorte (a Qtde_Contrato "
                    "é um valor único por arquivo e não separa por técnico)."
                )

        _section_heading(
            "Contratos por técnico",
            "Contratos distintos de cada técnico em cada competência — a mesma "
            "métrica do ranking, detalhada por mês. O melhor mês de cada "
            "técnico aparece em verde; a participação é a fatia na soma dos "
            "totais; a linha 'Total geral' soma a matriz.",
        )
        matriz = contar_contratos_por_tecnico_mes(
            registros_validos, _prevalidated=True
        )
        if matriz.empty:
            st.info("Não há registros com contrato para montar a matriz.")
        else:
            count_columns = {
                column: st.column_config.NumberColumn(format="%d")
                for column in matriz.columns
                if column not in {"Técnico", "Participação (%)"}
            }
            st.dataframe(
                matriz.style.apply(_best_month_style, axis=1).map(
                    _total_column_style, subset=["Total"]
                ),
                width="stretch",
                hide_index=True,
                column_config={
                    **count_columns,
                    "Participação (%)": st.column_config.ProgressColumn(
                        "Participação (%)",
                        format="%.1f%%",
                        min_value=0.0,
                        max_value=100.0,
                    ),
                },
                alt="Contratos distintos por técnico, competência e total",
            )
            _baixar_csv(matriz, "contratos_por_tecnico_mes.csv")

        por_arquivo = contar_contratos_por_arquivo(
            registros_validos, _prevalidated=True
        )
        _section_heading(
            "Contratos por arquivo importado",
            "Coluna Qtde_Contrato lida diretamente de cada arquivo — o valor "
            "reflete os contratos distintos do arquivo inteiro e não muda com "
            "os filtros do recorte. Registros com contrato conta as linhas "
            "válidas do recorte.",
        )
        if por_arquivo.empty:
            st.info("Não há arquivo de origem associado aos contratos do recorte.")
        else:
            with st.container(border=True):
                st.dataframe(
                    por_arquivo,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Arquivo": st.column_config.TextColumn(width="large"),
                        "Origem": st.column_config.TextColumn(width="small"),
                        "Registros com contrato": st.column_config.NumberColumn(
                            format="%d"
                        ),
                        "Contratos": st.column_config.NumberColumn(format="%d"),
                    },
                )
                _baixar_csv(por_arquivo, "contratos_por_arquivo.csv")

        with st.expander("Detalhamento por projeto e técnico (contratos distintos)"):
            st.caption(
                "Contagem de contratos distintos por projeto e técnico no recorte "
                "(nunique). Não usa a Qtde_Contrato e pode divergir dela."
            )
            st.dataframe(
                resumo,
                hide_index=True,
                width="stretch",
            )
            _baixar_csv(resumo, "contratos_por_projeto_tecnico.csv")
