"""Contagem de contratos distintos no recorte de produção."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from production import clean_contract


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
    st.markdown("### Contratos por projeto e técnico")
    st.caption("Contagem de identificadores de contrato distintos no período e filtros selecionados, considerando Prod e Gpon. Um contrato repetido no mesmo projeto e técnico é contado uma vez.")
    cards = st.columns(2)
    cards[0].metric("Contratos distintos no recorte", f"{total:,}".replace(",", "."))
    cards[1].metric("Registros sem contrato", f"{ausentes:,}".replace(",", "."))
    if ausentes:
        st.warning("Registros sem identificador de contrato não entram na contagem. Dados importados antes desta atualização precisam ser sincronizados ou reimportados para preencher o campo.")
    if resumo.empty:
        st.info("Nenhum contrato identificado no recorte. Verifique a coluna Contrato nos arquivos de origem e a sincronização.")
        return
    st.caption("Um mesmo contrato pode aparecer em mais de um projeto ou técnico; por isso a soma das linhas pode superar o total distinto do recorte.")
    st.dataframe(resumo, hide_index=True, width="stretch", alt="Contratos distintos por projeto e técnico")
    st.download_button("Baixar contagem em CSV", data=resumo.to_csv(index=False, sep=";").encode("utf-8-sig"), file_name="contratos_por_projeto_tecnico.csv", mime="text/csv")
