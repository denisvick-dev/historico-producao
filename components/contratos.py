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
    colunas = ["Projeto", "Técnico", "Contratos distintos"]
    if frame.empty or not {"project", "technician", "contract"}.issubset(frame.columns):
        return pd.DataFrame(columns=colunas), 0, len(frame)
    work = frame.copy()
    work["contract"] = work["contract"].map(clean_contract)
    sem_contrato = int(work["contract"].isna().sum())
    validos = work.dropna(subset=["contract"])
    resumo = (validos.groupby(["project", "technician"], dropna=False)["contract"]
              .nunique().reset_index(name="Contratos distintos")
              .rename(columns={"project": "Projeto", "technician": "Técnico"})
              .sort_values(["Contratos distintos", "Projeto", "Técnico"], ascending=[False, True, True])
              .reset_index(drop=True))
    return resumo[colunas], int(validos["contract"].nunique()), sem_contrato


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
