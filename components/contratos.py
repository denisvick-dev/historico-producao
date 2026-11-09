"""Contador de contratos distintos no recorte de produção.

A aba **Contratos** responde três perguntas:

• **Quanto?** — o contador em destaque soma os identificadores de contrato
  distintos no período e nos filtros selecionados.
• **Quem?** — o contador por técnico mostra quantos contratos cada técnico
  atendeu no recorte.
• **Quando?** — a evolução mensal mostra os contratos ativos em cada
  competência e o acumulado distinto até aquele mês.

Os cálculos ficam em funções puras (testáveis sem Streamlit); o layout apenas
consome os DataFrames resultantes.
"""

from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import Cores, Fontes, formatar_numero_br
from production import clean_contract, month_label, normalize_text

COLUNAS_RESUMO = ["Projeto", "Técnico", "Contratos"]
COLUNAS_TECNICO = ["Técnico", "Contratos", "Participação (%)"]
COLUNAS_MENSAL = ["Competência", "Contratos ativos", "Contratos acumulados"]
CHART_CONFIG = {"displayModeBar": False, "responsive": True}

AZUL_TOTALE = Cores.PRIMARIA
LARANJA_TOTALE = Cores.SECUNDARIA


# ====================================================
# 🧮 CONTAGENS (funções puras)
# ====================================================
MARCADORES_SEM_CONTRATO = {
    "semcontrato",
    "null",
    "na",
    "nan",
    "none",
    "nat",
}


def _registros_com_contrato(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Separa os registros com identificador de contrato válido.

    Retorna a cópia normalizada (coluna ``contract`` limpa) e a quantidade de
    linhas sem contrato — que ficam fora de todas as contagens. O marcador
    ``"Sem contrato"`` gravado pela importação é tratado como ausência, para
    que ele nunca seja contado como se fosse um contrato real.
    """
    if frame.empty or "contract" not in frame.columns:
        return frame.iloc[0:0].copy(), 0
    work = frame.copy()
    work["contract"] = work["contract"].map(clean_contract)
    ausente = work["contract"].isna() | work["contract"].map(normalize_text).isin(
        MARCADORES_SEM_CONTRATO
    )
    return work.loc[~ausente].reset_index(drop=True), int(ausente.sum())


def _rotulo_tecnico(valor: object) -> str:
    if valor is None or pd.isna(valor):
        return "Sem técnico"
    texto = str(valor).strip()
    return texto or "Sem técnico"


def resumir_contratos(frame: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Conta identificadores distintos por projeto e técnico e no recorte inteiro."""
    if frame.empty or not {"project", "technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=COLUNAS_RESUMO), 0, len(frame)
    validos, sem_contrato = _registros_com_contrato(frame)
    validos = validos.assign(technician=validos["technician"].map(_rotulo_tecnico))
    resumo = (
        validos.groupby(["project", "technician"], dropna=False)["contract"]
        .nunique()
        .reset_index(name="Contratos")
        .rename(columns={"project": "Projeto", "technician": "Técnico"})
        .sort_values(["Contratos", "Projeto", "Técnico"], ascending=[False, True, True])
        .reset_index(drop=True)
    )
    return resumo[COLUNAS_RESUMO], int(validos["contract"].nunique()), sem_contrato


def contar_contratos_por_tecnico(frame: pd.DataFrame) -> pd.DataFrame:
    """Contador de contratos distintos por técnico no recorte.

    A participação é a fatia de cada técnico na soma da coluna ``Contratos`` —
    como um mesmo contrato pode atender mais de um técnico, ela descreve a
    distribuição da carga, não a divisão do total distinto do recorte.
    """
    if frame.empty or not {"technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=COLUNAS_TECNICO)
    validos, _ = _registros_com_contrato(frame)
    if validos.empty:
        return pd.DataFrame(columns=COLUNAS_TECNICO)
    work = validos.assign(Técnico=validos["technician"].map(_rotulo_tecnico))
    resumo = (
        work.groupby("Técnico", as_index=False)["contract"]
        .nunique()
        .rename(columns={"contract": "Contratos"})
    )
    soma = int(resumo["Contratos"].sum())
    resumo["Participação (%)"] = (
        (resumo["Contratos"] / soma * 100).round(1) if soma else 0.0
    )
    return resumo.sort_values(
        ["Contratos", "Técnico"], ascending=[False, True]
    ).reset_index(drop=True)[COLUNAS_TECNICO]


def _competencias(frame: pd.DataFrame) -> pd.Series | None:
    """Coluna de competência (mês) a partir de ``period`` ou ``reference_date``."""
    for coluna in ("period", "reference_date"):
        if coluna not in frame.columns:
            continue
        datas = pd.to_datetime(frame[coluna], errors="coerce")
        if datas.notna().any():
            return datas.dt.to_period("M").dt.to_timestamp()
    return None


def contar_contratos_por_mes(frame: pd.DataFrame) -> pd.DataFrame:
    """Contador mensal de contratos ativos e do acumulado distinto.

    Um contrato é **ativo** no mês em que tem ao menos um registro. O
    **acumulado** cresce apenas quando o contrato aparece pela primeira vez,
    por isso a última linha do acumulado coincide com o total distinto do
    recorte. Meses sem registros entre o primeiro e o último aparecem zerados
    para preservar a leitura da série.
    """
    if frame.empty or "contract" not in frame.columns:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    validos, _ = _registros_com_contrato(frame)
    if validos.empty:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    competencias = _competencias(validos)
    if competencias is None:
        return pd.DataFrame(columns=COLUNAS_MENSAL)
    work = validos.assign(Competencia=competencias).dropna(subset=["Competencia"])
    if work.empty:
        return pd.DataFrame(columns=COLUNAS_MENSAL)

    por_mes = work.groupby("Competencia")["contract"].apply(frozenset)
    meses = pd.date_range(start=por_mes.index.min(), end=por_mes.index.max(), freq="MS")
    acumulado: set[str] = set()
    linhas = []
    for mes in meses:
        contratos = set(por_mes.get(mes, frozenset()))
        acumulado |= contratos
        linhas.append(
            {
                "Competência": month_label(mes),
                "Contratos ativos": len(contratos),
                "Contratos acumulados": len(acumulado),
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS_MENSAL)


# ====================================================
# 🎨 GRÁFICOS
# ====================================================
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
        y=mensal["Contratos ativos"],
        name="Ativos no mês",
        marker_color=AZUL_TOTALE,
        hovertemplate="<b>%{x}</b><br>Ativos: %{y}<extra></extra>",
    )
    fig.add_scatter(
        x=mensal["Competência"],
        y=mensal["Contratos acumulados"],
        name="Acumulado distinto",
        mode="lines+markers",
        yaxis="y2",
        line={"color": LARANJA_TOTALE, "width": 3},
        marker={"size": 7, "color": LARANJA_TOTALE},
        hovertemplate="<b>%{x}</b><br>Acumulado: %{y}<extra></extra>",
    )
    fig.update_layout(
        yaxis={"title": "Ativos no mês"},
        yaxis2={
            "title": "Acumulado",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
            "rangemode": "tozero",
        },
        bargap=0.35,
    )
    return _estilizar_figura(fig)


# ====================================================
# 🖥️ RENDERIZAÇÃO
# ====================================================
def _metric_card(
    label: str,
    value: str,
    note: str,
    symbol: str,
    card_class: str = "",
    note_class: str = "",
) -> None:
    st.markdown(
        f"""
        <div class="kpi-card {card_class}">
            <div class="kpi-top"><span class="kpi-label">{html.escape(label)}</span><span class="kpi-dot">{html.escape(symbol)}</span></div>
            <div class="kpi-value">{html.escape(value)}</div>
            <div class="kpi-note {note_class}">{html.escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _contador_destaque(total: int, tecnicos: int, meses: int) -> None:
    apoio = (
        f"{formatar_numero_br(tecnicos)} técnico(s) · "
        f"{formatar_numero_br(meses)} competência(s)"
    )
    st.markdown(
        f"""
        <div class="highlight-card highlight-card--azul">
            <h3>CONTRATOS DISTINTOS NO RECORTE</h3>
            <p class="big-number">{formatar_numero_br(total)}</p>
            <p style="margin:.35rem 0 0;font-size:12px;color:rgba(255,255,255,.86);">{html.escape(apoio)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _baixar_csv(frame: pd.DataFrame, nome: str) -> None:
    st.download_button(
        "Baixar contagem em CSV",
        data=frame.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=nome,
        mime="text/csv",
        key=f"download_contratos_{nome}",
    )


def render_contratos(frame: pd.DataFrame) -> None:
    resumo, total, ausentes = resumir_contratos(frame)
    por_tecnico = contar_contratos_por_tecnico(frame)
    mensal = contar_contratos_por_mes(frame)

    st.markdown("### Contador de contratos")
    st.caption(
        "Contagem de identificadores de contrato distintos no período e filtros "
        "selecionados, considerando Prod e Gpon. Um contrato repetido no mesmo "
        "projeto e técnico é contado uma vez."
    )

    destaque, apoio = st.columns([1.15, 2], gap="medium")
    with destaque:
        _contador_destaque(total, len(por_tecnico), len(mensal))
    with apoio:
        cards = st.columns(3)
        with cards[0]:
            _metric_card(
                "TÉCNICOS COM CONTRATOS",
                formatar_numero_br(len(por_tecnico)),
                "Técnicos com ao menos um contrato no recorte",
                "TC",
                card_class="kpi-card--azul",
            )
        with cards[1]:
            media = por_tecnico["Contratos"].mean() if not por_tecnico.empty else 0.0
            _metric_card(
                "MÉDIA POR TÉCNICO",
                formatar_numero_br(media, 1),
                "Contratos distintos por técnico",
                "MÉD",
                card_class="kpi-card--laranja",
            )
        with cards[2]:
            _metric_card(
                "REGISTROS SEM CONTRATO",
                formatar_numero_br(ausentes),
                "Ficam fora de todas as contagens",
                "!",
                card_class="kpi-card--vermelho" if ausentes else "kpi-card--verde",
                note_class="negative" if ausentes else "positive",
            )

    if ausentes:
        st.warning(
            "Registros sem identificador de contrato não entram na contagem. "
            "Dados importados antes desta atualização precisam ser sincronizados "
            "ou reimportados para preencher o campo."
        )
    if total == 0:
        st.info(
            "Nenhum contrato identificado no recorte. Verifique a coluna Contrato "
            "nos arquivos de origem e a sincronização."
        )
        return
    st.caption(
        "Um mesmo contrato pode aparecer em mais de um projeto ou técnico; por "
        "isso a soma das linhas pode superar o total distinto do recorte."
    )

    st.markdown("### Contador por técnico")
    st.caption(
        "Quantidade de contratos distintos atendidos por técnico no recorte. A "
        "participação é a fatia de cada técnico na soma da coluna, não no total "
        "distinto do recorte."
    )
    grafico_col, tabela_col = st.columns([1.15, 1], gap="medium")
    with grafico_col, st.container(border=True):
        st.markdown("**Ranking por contratos · Top 12**")
        st.plotly_chart(
            _grafico_por_tecnico(por_tecnico),
            width="stretch",
            config=CHART_CONFIG,
        )
    with tabela_col, st.container(border=True):
        st.markdown("**Contagem completa**")
        st.dataframe(
            por_tecnico,
            hide_index=True,
            width="stretch",
            alt="Contador de contratos distintos por técnico",
            column_config={
                "Contratos": st.column_config.NumberColumn(format="%d"),
                "Participação (%)": st.column_config.ProgressColumn(
                    "Participação (%)",
                    format="%.1f%%",
                    min_value=0.0,
                    max_value=100.0,
                ),
            },
        )
        _baixar_csv(por_tecnico, "contratos_por_tecnico.csv")

    st.markdown("### Evolução mensal dos contratos")
    if mensal.empty:
        st.info(
            "Os registros do recorte não têm data de competência válida; não é "
            "possível montar a evolução mensal."
        )
    else:
        st.caption(
            "Barras: contratos com ao menos um registro no mês. Linha: contratos "
            "distintos acumulados até o mês. Meses sem registros aparecem zerados."
        )
        with st.container(border=True):
            st.plotly_chart(
                _grafico_mensal(mensal), width="stretch", config=CHART_CONFIG
            )
            st.dataframe(
                mensal,
                hide_index=True,
                width="stretch",
                alt="Contador mensal de contratos ativos e acumulados",
                column_config={
                    "Contratos ativos": st.column_config.NumberColumn(format="%d"),
                    "Contratos acumulados": st.column_config.NumberColumn(format="%d"),
                },
            )
            _baixar_csv(mensal, "contratos_por_mes.csv")

    with st.expander("Detalhamento por projeto e técnico", expanded=False):
        st.dataframe(
            resumo,
            hide_index=True,
            width="stretch",
            alt="Contratos distintos por projeto e técnico",
        )
        _baixar_csv(resumo, "contratos_por_projeto_tecnico.csv")
