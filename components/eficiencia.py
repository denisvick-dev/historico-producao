"""Eficiência mensal por técnico no recorte selecionado."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from production import month_label

FAIXAS = [f"Faixa {numero}" for numero in range(1, 6)]


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


def render_eficiencia(frame: pd.DataFrame) -> None:
    detalhes, resumo = calcular_eficiencia(frame)
    if detalhes.empty:
        st.info("Não há competências válidas para calcular a eficiência.")
        return
    st.markdown("### Eficiência por técnico por mês")
    st.caption(
        "Pontos Totais = Prod + Gpon. Faixa 1: menos de 300; Faixa 2: 300 a menos de 350; "
        "Faixa 3: 350 a menos de 375; Faixa 4: 375 a menos de 400; Faixa 5: 400 ou mais pontos."
    )
    st.markdown("**Faixa mais frequente no período**")
    st.caption("A faixa mais frequente é aquela com mais meses registrados. Empates são exibidos juntos; meses sem registros não são classificados.")
    st.dataframe(resumo, hide_index=True, width="stretch", alt="Frequência das faixas por técnico")
    st.markdown("**Detalhamento mensal**")
    exibicao = detalhes.copy()
    exibicao["Competência"] = exibicao["Competência"].map(month_label)
    st.dataframe(exibicao, hide_index=True, width="stretch", alt="Pontos e faixa mensal por técnico", column_config={"Pontos": st.column_config.NumberColumn(format="%.2f")})
    st.download_button("Baixar eficiência mensal em CSV", data=exibicao.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"), file_name="eficiencia_mensal.csv", mime="text/csv")
