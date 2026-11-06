"""Eficiência mensal por técnico no recorte selecionado."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from production import month_label

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


def _normalizar_coluna(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    normalizados = {
        str(column).strip().lower().replace(" ", "").replace("_", "").replace("-", ""): column
        for column in frame.columns
        if isinstance(column, str)
    }
    for alias in aliases:
        chave = alias.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
        if chave in normalizados:
            return normalizados[chave]
    for chave, coluna in normalizados.items():
        if any(alias in chave for alias in (a.strip().lower().replace(" ", "").replace("_", "").replace("-", "") for a in aliases)):
            return coluna
    return None


def render_eficiencia_wo(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("Não há registros para calcular a eficiência por contrato.")
        return

    contract_col = _normalizar_coluna(
        frame,
        (
            "contrato",
            "contract",
            "contratocod",
            "numero_contrato",
            "numerocontrato",
        ),
    )

    if contract_col is None:
        contract_col = "contract" if "contract" in frame.columns else None

    work = frame.copy()
    if contract_col is None:
        work["contract"] = "Sem contrato"
        contract_col = "contract"

    if "contract" not in work.columns:
        work["contract"] = "Sem contrato"

    work["Pontos"] = pd.to_numeric(work["points"], errors="coerce")
    work["Competência"] = (
        pd.to_datetime(work["reference_date"], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    work["Contrato"] = (
        work[contract_col].fillna("Sem contrato").astype(str).str.strip().replace("", "Sem contrato")
    )
    work = work.dropna(subset=["Competência", "Pontos"])

    if work.empty:
        st.info("Não há pontos válidos para calcular a eficiência por contrato.")
        return

    tecnico_col = "technician" if "technician" in work.columns else None
    tecnicos = ["Todos"]
    if tecnico_col:
        tecnicos.extend(sorted(work[tecnico_col].dropna().astype(str).unique().tolist()))
    tecnico_selecionado = st.selectbox(
        "Filtrar por técnico",
        tecnicos,
        index=0,
        help="Ajusta o recorte para um técnico específico antes da análise por contrato.",
        key="eficiencia_contrato_tecnico_filter",
    )

    if tecnico_selecionado != "Todos" and tecnico_col:
        work = work[work[tecnico_col].eq(tecnico_selecionado)]

    if work.empty:
        st.info("Não há registros para o técnico selecionado no recorte atual.")
        return

    detalhes = work.groupby(["Contrato", "Competência"], as_index=False)["Pontos"].sum()
    detalhes["Faixa"] = pd.cut(
        detalhes["Pontos"],
        bins=[float("-inf"), 300, 350, 375, 400, float("inf")],
        labels=FAIXAS,
        right=False,
    ).astype(str)

    resumo = (
        detalhes.groupby(["Contrato"], as_index=False)
        .agg(
            Meses_com_registros=("Competência", "nunique"),
            Pontos_totais=("Pontos", "sum"),
        )
    )
    resumo["Faixa mais frequente"] = resumo["Contrato"].map(
        detalhes.groupby("Contrato")["Faixa"].apply(
            lambda faixas: faixas.value_counts().idxmax()
        )
    )

    st.markdown("### Eficiência por contrato")
    st.caption(
        "A tabela resume o total de pontos por contrato e mostra a contagem de contratos ativos no período."
    )
    col1, col2, col3 = st.columns(3)
    col1.metric("Contratos ativos", f"{resumo['Contrato'].nunique():,}".replace(",", "."))
    col2.metric("Meses do período", f"{detalhes['Competência'].nunique():,}".replace(",", "."))
    col3.metric("Pontos totais", f"{detalhes['Pontos'].sum():,.2f}".replace(",", "."))

    st.markdown("**Contagem de contratos por técnico**")
    contagem_por_tecnico = (
        work.groupby("technician", as_index=False)["Contrato"]
        .nunique()
        .rename(columns={"technician": "Técnico", "Contrato": "Contratos ativos"})
        .sort_values("Contratos ativos", ascending=False)
    )
    st.dataframe(
        contagem_por_tecnico,
        hide_index=True,
        width="stretch",
        alt="Contagem de contratos ativos por técnico",
        column_config={
            "Contratos ativos": st.column_config.NumberColumn(format="%d")
        },
    )

    st.markdown("**Eficiência por contrato de cada técnico**")
    tecnico_contrato = (
        work.groupby(["technician", "Contrato"], as_index=False)
        .agg(Pontos_totais=("Pontos", "sum"), Quantidade_registros=("Contrato", "size"))
        .rename(columns={"technician": "Técnico", "Contrato": "Contrato"})
        .sort_values(["Técnico", "Pontos_totais"], ascending=[True, False])
    )
    st.dataframe(
        tecnico_contrato,
        hide_index=True,
        width="stretch",
        alt="Eficiência por contrato de cada técnico",
        column_config={
            "Pontos_totais": st.column_config.NumberColumn(format="%.2f"),
            "Quantidade_registros": st.column_config.NumberColumn(format="%d"),
        },
    )

    resumo_exibicao = resumo.rename(
        columns={
            "Meses_com_registros": "Meses com registros",
            "Pontos_totais": "Pontos totais",
            "Faixa mais frequente": "Faixa mais frequente",
        }
    )
    st.dataframe(
        resumo_exibicao.style.apply(
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
        alt="Resumo da eficiência por contrato",
        column_config={
            "Meses com registros": st.column_config.NumberColumn(format="%d"),
            "Pontos totais": st.column_config.NumberColumn(format="%.2f"),
            "Faixa mais frequente": st.column_config.TextColumn(width="small"),
        },
    )

    st.markdown("**Detalhamento mensal por contrato**")
    exibicao = detalhes.copy()
    exibicao["Competência"] = exibicao["Competência"].map(month_label)
    exibicao = exibicao[["Contrato", "Competência", "Pontos", "Faixa"]]
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
