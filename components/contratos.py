"""Visão de contratos: carteira do recorte, evolução e conferência das origens.

A carteira usa identificadores distintos dos registros filtrados. A contagem
por arquivo usa contracts_qty, que representa o arquivo inteiro e pode incluir
registros fora do filtro. As duas métricas não são intercambiáveis.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_kpi_card,
)
from production import clean_contract, is_valid_contract, month_label

COLUNAS_RESUMO = ["Projeto", "Técnico", "Contratos distintos"]
COLUNAS_TECNICO = ["Técnico", "Contratos", "Participação (%)"]
COLUNAS_MENSAL = ["Competência", "Contratos no mês", "Acumulado (soma)"]
COLUNAS_ARQUIVO = ["Arquivo", "Origem", "Registros com contrato", "Contratos"]
CHART_CONFIG = {"displayModeBar": False, "responsive": True}

AZUL_TOTALE = Cores.PRIMARIA


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
        return frame.iloc[0:0].copy(), len(frame)
    # Identificadores importados são textos; normalizá-los uma única vez por
    # valor repetido evita milhares de chamadas Python redundantes. Para tipos
    # mistos preservamos a distinção original entre, por exemplo, 1 e 1.0.
    if pd.api.types.infer_dtype(frame["contract"], skipna=True) != "string":
        work = frame.copy()
        work["contract"] = work["contract"].map(clean_contract)
        ausente = ~work["contract"].map(is_valid_contract)
        return work.loc[~ausente].reset_index(drop=True), int(ausente.sum())
    codigos, valores = pd.factorize(frame["contract"], sort=False)
    normalizados = [clean_contract(valor) for valor in valores]
    validos_unicos = [is_valid_contract(valor) for valor in normalizados]
    # O código -1 representa qualquer valor nulo e aponta para o último item.
    contratos = np.asarray([*normalizados, None], dtype=object)[codigos]
    mascara = np.asarray([*validos_unicos, False], dtype=bool)[codigos]
    work = frame.loc[mascara].copy().reset_index(drop=True)
    work["contract"] = contratos[mascara]
    return work, int((~mascara).sum())


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
        frame.assign(
            _arquivo=_chave_arquivo(frame["source_file"]),
            _qtde=_qtde_numerico(frame["contracts_qty"]),
        )
        .groupby("_arquivo")["_qtde"]
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
    frame: pd.DataFrame,
    *,
    _prevalidated: bool = False,
    _validos: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Contador de contratos em cada arquivo importado, a partir da Qtde_Contrato.

    A coluna ``Contratos`` reflete o total do arquivo inteiro, sem aplicar
    os filtros do recorte. ``Registros com contrato`` conta as linhas válidas
    do recorte. Arquivos sem registros válidos também aparecem. Sem
    ``contracts_qty``, usa ``nunique(contract)`` no recorte.
    """
    if frame.empty or "source_file" not in frame.columns:
        return pd.DataFrame(columns=COLUNAS_ARQUIVO)
    validos = _validos
    if validos is None:
        validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    work = frame.assign(Arquivo=_chave_arquivo(frame["source_file"]))
    validos = validos.assign(Arquivo=_chave_arquivo(validos["source_file"]))
    resumo = pd.DataFrame({"Arquivo": sorted(work["Arquivo"].unique())})
    contagem = validos.groupby("Arquivo").size()
    resumo["Registros com contrato"] = (
        resumo["Arquivo"].map(contagem).fillna(0).astype(int)
    )
    if "contracts_qty" in work.columns:
        qtde = (
            work.assign(_qtde=_qtde_numerico(work["contracts_qty"]))
            .groupby("Arquivo")["_qtde"]
            .max()
        )
    elif "contract" in validos.columns:
        qtde = validos.groupby("Arquivo")["contract"].nunique()
    else:
        qtde = pd.Series(dtype="int64")
    resumo["Contratos"] = resumo["Arquivo"].map(qtde).fillna(0).astype(int)
    if "source_sheet" in work.columns:
        origens = work.groupby("Arquivo")["source_sheet"].agg(
            lambda valores: (
                " / ".join(
                    sorted(
                        {str(valor) for valor in valores.dropna() if str(valor).strip()}
                    )
                )
                or "—"
            )
        )
        resumo["Origem"] = resumo["Arquivo"].map(origens).fillna("—")
    else:
        resumo["Origem"] = "—"
    return resumo.sort_values(
        ["Contratos", "Arquivo"], ascending=[False, True], kind="mergesort"
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
        arquivos = work.assign(
            Arquivo=_chave_arquivo(work["source_file"]),
            contracts_qty=_qtde_numerico(work["contracts_qty"]),
        )
        por_arquivo = (
            arquivos.groupby(["Competencia", "Arquivo"])["contracts_qty"]
            .max()
            .reset_index()
        )
        por_mes = _qtde_numerico(
            por_arquivo.groupby("Competencia")["contracts_qty"].sum()
        )
    else:
        por_mes = (
            work.assign(contracts_qty=_qtde_numerico(work["contracts_qty"]))
            .groupby("Competencia")["contracts_qty"]
            .max()
        )

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
    detalhe = work.groupby(["Técnico", "Mês"], as_index=False).agg(
        Contratos=("contract", "nunique")
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


COLUNAS_CARTEIRA = [
    "Contrato",
    "Projetos",
    "Técnicos",
    "Registros",
    "Pontos",
    "Primeiro registro",
    "Último registro",
]


def resumir_carteira(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> pd.DataFrame:
    """Uma linha por identificador válido, considerando somente o recorte."""
    if frame.empty or "contract" not in frame.columns:
        return pd.DataFrame(columns=COLUNAS_CARTEIRA)
    validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    if validos.empty:
        return pd.DataFrame(columns=COLUNAS_CARTEIRA)
    work = validos.copy()
    for coluna in ("project", "technician"):
        if coluna not in work:
            work[coluna] = None
    work["project"] = (
        work["project"]
        .fillna("Sem projeto")
        .astype(str)
        .str.strip()
        .replace("", "Sem projeto")
    )
    work["technician"] = work["technician"].map(_rotulo_tecnico)
    work["_pontos"] = (
        pd.to_numeric(work["points"], errors="coerce").fillna(0)
        if "points" in work
        else 0.0
    )
    # Datas reais são preferíveis à competência para identificar o intervalo.
    datas = (
        pd.to_datetime(work["reference_date"], errors="coerce")
        if "reference_date" in work
        else pd.Series(pd.NaT, index=work.index)
    )
    if "period" in work:
        datas = datas.fillna(pd.to_datetime(work["period"], errors="coerce"))
    work["_data"] = datas

    # Agregações numéricas usam operações nativas. Projetos e técnicos são
    # deduplicados antes de concatenar: carteiras grandes costumam ter apenas
    # um valor por contrato, evitando duas chamadas Python por grupo.
    resultado = work.groupby("contract", as_index=False).agg(
        Registros=("contract", "size"),
        Pontos=("_pontos", "sum"),
        **{
            "Primeiro registro": ("_data", "min"),
            "Último registro": ("_data", "max"),
        },
    )
    for coluna, nome in (("project", "Projetos"), ("technician", "Técnicos")):
        pares = (
            work[["contract", coluna]]
            .drop_duplicates()
            .sort_values(["contract", coluna])
        )
        repetidos = pares["contract"].duplicated(keep=False)
        unicos = pares.loc[~repetidos].set_index("contract")[coluna]
        multiplos = pares.loc[repetidos].groupby("contract")[coluna].agg(" · ".join)
        resultado[nome] = resultado["contract"].map(pd.concat([unicos, multiplos]))
    resultado = resultado.rename(columns={"contract": "Contrato"})

    return resultado.sort_values(
        ["Registros", "Contrato"], ascending=[False, True]
    ).reset_index(drop=True)[COLUNAS_CARTEIRA]


def contratos_distintos_por_mes(
    frame: pd.DataFrame, *, _prevalidated: bool = False
) -> pd.DataFrame:
    """Contratos distintos por competência; um contrato pode aparecer em vários meses."""
    colunas = ["Competência", "Contratos"]
    if frame.empty or "contract" not in frame.columns:
        return pd.DataFrame(columns=colunas)
    validos, _ = (frame, 0) if _prevalidated else _registros_com_contrato(frame)
    competencias = _competencias(validos)
    if validos.empty or competencias is None:
        return pd.DataFrame(columns=colunas)
    work = validos.assign(_mes=competencias).dropna(subset=["_mes"])
    if work.empty:
        return pd.DataFrame(columns=colunas)
    contagem = work.groupby("_mes")["contract"].nunique()
    meses = pd.date_range(contagem.index.min(), contagem.index.max(), freq="MS")
    return pd.DataFrame(
        {
            "Competência": [month_label(mes) for mes in meses],
            "Contratos": contagem.reindex(meses, fill_value=0).to_numpy(),
        }
    )


def _grafico_carteira_mensal(mensal: pd.DataFrame) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=mensal["Competência"],
            y=mensal["Contratos"],
            marker_color=AZUL_TOTALE,
            text=mensal["Contratos"],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>%{y} contratos distintos<extra></extra>",
        )
    )
    fig.update_layout(showlegend=False, bargap=0.4)
    fig.update_yaxes(title="Contratos distintos", dtick=1)
    return _estilizar_figura(fig)


# Apenas colunas usadas nesta página participam do cache. O hash completo evita
# a amostragem automática de DataFrames grandes pelo Streamlit, que poderia
# reutilizar resultados obsoletos após alterações fora da amostra.
_COLUNAS_PAINEL = (
    "contract",
    "technician",
    "project",
    "points",
    "reference_date",
    "period",
    "source_file",
    "source_sheet",
    "contracts_qty",
)
_TAMANHO_PAGINA = 200


def _chave_painel(frame: pd.DataFrame) -> str:
    colunas = [coluna for coluna in _COLUNAS_PAINEL if coluna in frame.columns]
    recorte = frame.loc[:, colunas]
    digest = hashlib.sha256()
    digest.update(
        repr([(coluna, str(recorte[coluna].dtype)) for coluna in colunas]).encode()
    )
    digest.update(pd.util.hash_pandas_object(recorte, index=True).values.tobytes())
    # pandas pode produzir o mesmo hash para 1 e "1" em colunas object.
    # A distinção importa para datas e para misturas de tipos no recorte.
    for coluna in colunas:
        serie = recorte[coluna]
        if serie.dtype == object:
            tipo = pd.api.types.infer_dtype(serie, skipna=True)
            digest.update(tipo.encode())
            if tipo.startswith("mixed"):
                tipos = serie.map(
                    lambda valor: f"{type(valor).__module__}.{type(valor).__qualname__}"
                )
                digest.update(
                    pd.util.hash_pandas_object(tipos, index=False).values.tobytes()
                )
    return digest.hexdigest()


@st.cache_data(max_entries=4, show_spinner=False)
def _dados_painel(chave: str, _frame: pd.DataFrame) -> dict:
    """Calcula uma vez por conteúdo e retorna apenas agregados da página."""
    validos, ausentes = _registros_com_contrato(_frame)
    total_arquivos, _ = somar_qtde_contrato(_frame, _validos=validos)
    resumo, _, _ = resumir_contratos(validos, _prevalidated=True)
    return {
        "ausentes": ausentes,
        "registros_validos": len(validos),
        "carteira": resumir_carteira(validos, _prevalidated=True),
        "tecnicos": contar_contratos_por_tecnico(validos, _prevalidated=True),
        "mensal": contratos_distintos_por_mes(validos, _prevalidated=True),
        "total_arquivos": total_arquivos,
        "matriz": contar_contratos_por_tecnico_mes(validos, _prevalidated=True),
        "resumo": resumo,
        "por_arquivo": contar_contratos_por_arquivo(_frame, _validos=validos),
        "mensal_arquivos": contar_contratos_por_mes(_frame),
    }


def render_contratos(frame: pd.DataFrame) -> None:
    """Painel da carteira e suas fontes, respeitando os filtros globais."""
    if frame.empty:
        st.info(
            "Não há registros para os filtros selecionados. Ajuste os filtros para consultar contratos."
        )
        return

    recorte = frame.loc[
        :, [coluna for coluna in _COLUNAS_PAINEL if coluna in frame.columns]
    ]
    chave = _chave_painel(recorte)
    dados = _dados_painel(chave, recorte)
    carteira = dados["carteira"]
    tecnicos = dados["tecnicos"]
    mensal = dados["mensal"]
    total_arquivos = dados["total_arquivos"]
    ausentes = dados["ausentes"]

    cards = st.columns(4)
    indicadores = [
        (
            "CONTRATOS DISTINTOS",
            len(carteira),
            "Identificadores únicos no recorte",
            "CT",
            "kpi-card--azul",
        ),
        (
            "REGISTROS COM CONTRATO",
            dados["registros_validos"],
            "Linhas com contrato identificado",
            "RG",
            "kpi-card--verde",
        ),
        (
            "TÉCNICOS",
            len(tecnicos),
            "Com contrato no recorte",
            "TC",
            "kpi-card--laranja",
        ),
        (
            "CONTAGEM POR ARQUIVO",
            total_arquivos,
            "Soma dos totais dos arquivos presentes",
            "ARQ",
            "kpi-card--azul",
        ),
    ]
    for coluna, (label, valor, nota, simbolo, classe) in zip(cards, indicadores):
        with coluna:
            render_kpi_card(
                label, formatar_numero_br(valor), nota, simbolo, card_class=classe
            )

    st.caption(
        "Contratos distintos considera apenas os registros filtrados. A contagem por arquivo "
        "soma o total original de cada arquivo presente no recorte, mesmo quando apenas parte "
        "dele está filtrada; um contrato pode aparecer em mais de um arquivo."
        if "contracts_qty" in frame.columns
        else "Sem contagem por arquivo disponível, o indicador usa os contratos distintos do recorte."
    )
    if ausentes:
        st.warning(
            f"{formatar_numero_br(ausentes)} registro(s) sem contrato válido ficaram fora da carteira, da evolução e do ranking."
        )
    if carteira.empty:
        st.info(
            "Nenhum contrato identificado neste recorte. Verifique os filtros e os arquivos importados."
        )
    else:
        _section_heading(
            "Visão da carteira",
            "Como os contratos se distribuem no período e entre a equipe.",
        )
        evolucao_col, ranking_col = st.columns([1.15, 1], gap="medium")
        with evolucao_col, st.container(border=True):
            st.markdown("**Contratos por competência**")
            st.caption(
                "Identificadores distintos em cada mês; um contrato pode aparecer em mais de um mês."
            )
            if mensal.empty:
                st.info("Não há competências válidas para exibir a evolução.")
            else:
                st.plotly_chart(
                    _grafico_carteira_mensal(mensal),
                    width="stretch",
                    config=CHART_CONFIG,
                )
                with st.expander("Ver dados mensais"):
                    st.dataframe(mensal, hide_index=True, width="stretch")
                    _baixar_csv(mensal, "contratos_distintos_por_mes.csv")
        with ranking_col, st.container(border=True):
            st.markdown("**Contratos por técnico · Top 12**")
            st.caption(
                "Identificadores distintos por técnico; o mesmo contrato pode pertencer a mais de um técnico."
            )
            if tecnicos.empty:
                st.info("Não há técnicos para exibir.")
            else:
                st.plotly_chart(
                    _grafico_por_tecnico(tecnicos), width="stretch", config=CHART_CONFIG
                )

        _section_heading(
            "Explorar contratos",
            "Consulte os identificadores e a atividade associada no recorte selecionado.",
        )
        busca = st.text_input(
            "Buscar contrato",
            placeholder="Digite o número ou identificador",
            key="contratos_busca",
        )
        consulta_key = (chave, busca.strip())
        if st.session_state.get("contratos_consulta_atual") != consulta_key:
            st.session_state["contratos_consulta_atual"] = consulta_key
            st.session_state["contratos_pagina"] = 1
            st.session_state.pop("contratos_exportacao", None)
        encontrados = (
            carteira[
                carteira["Contrato"].str.contains(
                    busca.strip(), case=False, regex=False
                )
            ]
            if busca.strip()
            else carteira
        )
        st.caption(
            f"{formatar_numero_br(len(encontrados))} de {formatar_numero_br(len(carteira))} contrato(s) · A busca filtra apenas esta tabela."
        )
        if encontrados.empty:
            st.info("Nenhum contrato encontrado para essa busca.")
        else:
            total_paginas = (len(encontrados) - 1) // _TAMANHO_PAGINA + 1
            pagina = 1
            if total_paginas > 1:
                pagina = st.number_input(
                    "Página",
                    min_value=1,
                    max_value=total_paginas,
                    value=1,
                    step=1,
                    key="contratos_pagina",
                    help=f"Até {_TAMANHO_PAGINA} contratos por página.",
                )
                st.caption(
                    f"Página {pagina} de {total_paginas} · até {_TAMANHO_PAGINA} contratos por página."
                )
            inicio = (pagina - 1) * _TAMANHO_PAGINA
            st.dataframe(
                encontrados.iloc[inicio : inicio + _TAMANHO_PAGINA],
                hide_index=True,
                width="stretch",
                column_config={
                    "Contrato": st.column_config.TextColumn(width="medium"),
                    "Projetos": st.column_config.TextColumn(width="medium"),
                    "Técnicos": st.column_config.TextColumn(width="medium"),
                    "Pontos": st.column_config.NumberColumn(format="%.1f"),
                    "Primeiro registro": st.column_config.DateColumn(
                        format="DD/MM/YYYY"
                    ),
                    "Último registro": st.column_config.DateColumn(format="DD/MM/YYYY"),
                },
                alt="Carteira de contratos do recorte",
            )
            if len(encontrados) <= _TAMANHO_PAGINA:
                _baixar_csv(encontrados, "carteira_contratos.csv")
            else:
                # Preparação explícita evita converter uma grande carteira em
                # CSV a cada interação; o download inclui todos os resultados.
                export_key = consulta_key
                export = st.session_state.get("contratos_exportacao")
                if st.button("Preparar CSV completo", key="contratos_preparar_csv"):
                    export = (
                        export_key,
                        encontrados.to_csv(index=False, sep=";", decimal=",").encode(
                            "utf-8-sig"
                        ),
                    )
                    st.session_state["contratos_exportacao"] = export
                if export:
                    st.download_button(
                        "Baixar carteira completa em CSV",
                        data=export[1],
                        file_name="carteira_contratos.csv",
                        mime="text/csv",
                        key="download_contratos_carteira_completa",
                    )

        _section_heading(
            "Detalhamento da equipe",
            "Compare os contratos atendidos por técnico em cada competência.",
        )
        matriz = dados["matriz"]
        if matriz.empty:
            st.info("Não há competências válidas para montar a matriz por técnico.")
        else:
            destacar = matriz.size <= 10_000
            st.caption(
                "Cada célula conta contratos distintos no mês. O total soma os meses, não os contratos únicos do período. "
                + (
                    "O melhor mês aparece em verde."
                    if destacar
                    else "Destaque de cores desativado para matrizes grandes."
                )
            )
            visualizacao = (
                matriz.style.apply(_best_month_style, axis=1).map(
                    _total_column_style, subset=["Total"]
                )
                if destacar
                else matriz
            )
            st.dataframe(
                visualizacao,
                width="stretch",
                hide_index=True,
                column_config={
                    "Participação (%)": st.column_config.ProgressColumn(
                        "Participação (%)",
                        format="%.1f%%",
                        min_value=0.0,
                        max_value=100.0,
                    )
                },
                alt="Contratos distintos por técnico e competência",
            )
            _baixar_csv(matriz, "contratos_por_tecnico_mes.csv")
        resumo = dados["resumo"]
        with st.expander("Ver contratos por projeto e técnico"):
            st.caption(
                "Contratos distintos em cada combinação de projeto e técnico; um contrato pode aparecer em mais de uma combinação."
            )
            st.dataframe(resumo, hide_index=True, width="stretch")
            _baixar_csv(resumo, "contratos_por_projeto_tecnico.csv")

    _section_heading(
        "Conferência das origens",
        "Entenda a contagem por arquivo e sua relação com os filtros.",
    )
    with st.expander("Ver arquivos e contagem de origem"):
        st.caption(
            "A contagem de cada arquivo reflete seu total original, não apenas as linhas filtradas. Registros com contrato conta as linhas válidas do recorte."
            if "contracts_qty" in frame.columns
            else "Sem contagem de origem disponível, cada arquivo mostra os contratos distintos de suas linhas no recorte. A soma dos arquivos pode superar os contratos distintos do recorte."
        )
        por_arquivo = dados["por_arquivo"]
        if por_arquivo.empty:
            st.info("Não há arquivo de origem associado aos registros deste recorte.")
        else:
            st.dataframe(por_arquivo, hide_index=True, width="stretch")
            _baixar_csv(por_arquivo, "contratos_por_arquivo.csv")
        mensal_arquivos = dados["mensal_arquivos"]
        if not mensal_arquivos.empty:
            st.markdown("**Contagem de origem por competência**")
            st.caption(
                "Soma dos totais dos arquivos presentes em cada mês. Um arquivo com registros em mais de um mês é contado em cada um; o acumulado soma os meses."
            )
            st.dataframe(mensal_arquivos, hide_index=True, width="stretch")
            _baixar_csv(mensal_arquivos, "contratos_por_mes.csv")
