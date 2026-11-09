"""Dashboards complementares de projetos, resumo executivo e saúde dos dados."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from production import format_points, month_label, summarize, summarize_os

AZUL_TOTALE = "#012869"
LARANJA_TOTALE = "#F37C04"
VERDE_TOTALE = "#047857"
CINZA_TOTALE = "#64748B"


# ====================================================
# 📐 CÁLCULOS SEM ESTADO DA INTERFACE
# ====================================================
def resumir_projetos(frame: pd.DataFrame) -> pd.DataFrame:
    """Consolida pontos, O.S., técnicos e participação por projeto."""
    colunas = [
        "project",
        "points_prod",
        "points_gpon",
        "points_total",
        "os_count",
        "technicians",
        "share_pct",
    ]
    if frame.empty:
        return pd.DataFrame(columns=colunas)

    pontos = summarize(frame, "project")
    ordens = summarize_os(frame, "project")
    tecnicos = (
        frame.groupby("project", as_index=False, dropna=False)["technician"]
        .nunique()
        .rename(columns={"technician": "technicians"})
    )
    resultado = pontos.merge(ordens, on="project", how="left").merge(
        tecnicos, on="project", how="left"
    )
    resultado["os_count"] = resultado["os_count"].fillna(0).astype(int)
    resultado["technicians"] = resultado["technicians"].fillna(0).astype(int)
    total = float(resultado["points_total"].sum())
    resultado["share_pct"] = (
        resultado["points_total"].div(total).mul(100.0) if total else 0.0
    )
    return (
        resultado[colunas]
        .sort_values(["points_total", "project"], ascending=[False, True])
        .reset_index(drop=True)
    )


def _serie_competencias(frame: pd.DataFrame) -> pd.Series:
    """Devolve o mês de cada linha, aceitando o campo derivado ou a data original."""
    coluna = "period" if "period" in frame.columns else "reference_date"
    if coluna not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    return (
        pd.to_datetime(frame[coluna], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp()
    )


def _janela_mensal(
    frame: pd.DataFrame,
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
) -> tuple[pd.DatetimeIndex, pd.Series]:
    """Retorna a sequência contínua de meses do recorte e os meses por registro."""
    competencias = _serie_competencias(frame)
    validas = competencias.dropna()
    if validas.empty:
        return pd.DatetimeIndex([]), competencias

    inicio_mes = (
        pd.Timestamp(inicio).to_period("M").to_timestamp()
        if inicio is not None
        else validas.min()
    )
    fim_mes = (
        pd.Timestamp(fim).to_period("M").to_timestamp()
        if fim is not None
        else validas.max()
    )
    if inicio_mes > fim_mes:
        return pd.DatetimeIndex([]), competencias
    return pd.date_range(inicio_mes, fim_mes, freq="MS"), competencias


def resumir_regularidade(
    frame: pd.DataFrame,
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Compara médias/medianas ativas, oscilações e meses sem registro por técnico.

    A média, mediana e variação usam apenas competências com registros; lacunas
    são contabilizadas separadamente para não confundir ausência de dados com
    produção igual a zero.
    """
    colunas = [
        "technician",
        "active_months",
        "months_without_records",
        "missing_periods",
        "mean_active_monthly_points",
        "median_active_monthly_points",
        "coefficient_variation_pct",
        "peak_month",
        "peak_points",
        "peak_vs_median_pct",
        "regularity",
    ]
    if (
        frame.empty
        or "technician" not in frame.columns
        or "points" not in frame.columns
    ):
        return pd.DataFrame(columns=colunas)

    periods, competencias = _janela_mensal(frame, inicio, fim)
    if periods.empty:
        return pd.DataFrame(columns=colunas)

    work = frame.copy()
    work["_competencia"] = competencias
    work["_tecnico"] = work["technician"].fillna("Sem técnico").astype(str).str.strip()
    work["_pontos"] = pd.to_numeric(work["points"], errors="coerce").fillna(0.0)
    work = work[work["_competencia"].isin(periods)]
    if work.empty:
        return pd.DataFrame(columns=colunas)

    monthly_points = (
        work.groupby(["_tecnico", "_competencia"])["_pontos"]
        .sum()
        .unstack(fill_value=0.0)
    )
    monthly_records = (
        work.groupby(["_tecnico", "_competencia"]).size().unstack(fill_value=0)
    )
    technicians = sorted(monthly_points.index.astype(str).tolist())
    monthly_points = monthly_points.reindex(
        index=technicians, columns=periods, fill_value=0.0
    )
    monthly_records = monthly_records.reindex(
        index=technicians, columns=periods, fill_value=0
    )

    summaries: list[dict[str, object]] = []
    for technician in technicians:
        recorded = monthly_records.loc[technician].gt(0)
        active_values = monthly_points.loc[technician, recorded].astype(float)
        active_months = int(recorded.sum())
        missing = periods[~recorded.to_numpy()]
        mean_points = float(active_values.mean()) if active_months else 0.0
        median_points = float(active_values.median()) if active_months else 0.0
        std_points = float(active_values.std(ddof=0)) if active_months else 0.0
        if active_months >= 2 and mean_points > 0:
            variation = std_points / mean_points * 100.0
        elif active_months >= 2 and std_points == 0:
            variation = 0.0
        else:
            variation = float("nan")

        if active_months:
            peak_month_value = active_values.idxmax()
            peak_points = float(active_values.loc[peak_month_value])
            peak_month = month_label(peak_month_value)
        else:
            peak_points = 0.0
            peak_month = "—"
        peak_vs_median = (
            (peak_points / median_points - 1.0) * 100.0
            if median_points > 0
            else float("nan")
        )

        if active_months < 3:
            regularity = "Base curta"
        elif mean_points <= 0:
            regularity = "Sem pontos"
        elif pd.isna(variation):
            regularity = "Base insuficiente"
        elif variation <= 25:
            regularity = "Regular"
        elif variation <= 50:
            regularity = "Oscilação moderada"
        else:
            regularity = "Alta oscilação"

        summaries.append(
            {
                "technician": technician,
                "active_months": active_months,
                "months_without_records": len(missing),
                "missing_periods": " · ".join(month_label(period) for period in missing)
                or "—",
                "mean_active_monthly_points": mean_points,
                "median_active_monthly_points": median_points,
                "coefficient_variation_pct": variation,
                "peak_month": peak_month,
                "peak_points": peak_points,
                "peak_vs_median_pct": peak_vs_median,
                "regularity": regularity,
            }
        )

    return (
        pd.DataFrame(summaries, columns=colunas)
        .sort_values(
            ["months_without_records", "coefficient_variation_pct", "technician"],
            ascending=[False, False, True],
            na_position="last",
        )
        .reset_index(drop=True)
    )


def matriz_sazonalidade(
    frame: pd.DataFrame,
    dimensao: str = "technician",
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
    top_n: int = 12,
) -> pd.DataFrame:
    """Monta uma matriz de Pontos Totais por competência e técnico ou projeto."""
    if dimensao not in {"technician", "project"}:
        raise ValueError("A dimensão deve ser 'technician' ou 'project'.")
    if frame.empty or dimensao not in frame.columns or "points" not in frame.columns:
        return pd.DataFrame()

    periods, competencias = _janela_mensal(frame, inicio, fim)
    if periods.empty:
        return pd.DataFrame()

    work = frame.copy()
    work["_competencia"] = competencias
    placeholder = "Sem técnico" if dimensao == "technician" else "Sem projeto"
    work["_entidade"] = (
        work[dimensao]
        .fillna(placeholder)
        .astype(str)
        .str.strip()
        .replace("", placeholder)
    )
    work["_pontos"] = pd.to_numeric(work["points"], errors="coerce").fillna(0.0)
    work = work[work["_competencia"].isin(periods)]
    if work.empty:
        return pd.DataFrame()

    monthly = work.groupby(["_entidade", "_competencia"])["_pontos"].sum()
    totals = monthly.groupby(level=0).sum()
    ranking = (
        totals.rename("points_total")
        .rename_axis("entity")
        .reset_index()
        .sort_values(["points_total", "entity"], ascending=[False, True])
    )
    entities = ranking.head(max(int(top_n), 1))["entity"].tolist()
    matrix = (
        monthly.unstack()
        .reindex(index=entities, columns=periods, fill_value=0.0)
        .fillna(0.0)
    )
    matrix.index.name = dimensao
    return matrix


def comparar_tecnicos(atual: pd.DataFrame, anterior: pd.DataFrame) -> pd.DataFrame:
    """Compara pontos por técnico e identifica novos/sem produção no recorte."""
    colunas = [
        "Técnico",
        "Pontos atuais",
        "Pontos anteriores",
        "Diferença de pontos",
        "Variação (%)",
        "Status",
    ]
    atual_por_tecnico = (
        summarize(atual, "technician").set_index("technician")["points_total"]
        if not atual.empty
        else pd.Series(dtype="float64", name="points_total")
    )
    anterior_por_tecnico = (
        summarize(anterior, "technician").set_index("technician")["points_total"]
        if not anterior.empty
        else pd.Series(dtype="float64", name="points_total")
    )
    tecnicos = atual_por_tecnico.index.union(anterior_por_tecnico.index)
    if len(tecnicos) == 0:
        return pd.DataFrame(columns=colunas)

    resultado = pd.DataFrame(
        {
            "Pontos atuais": atual_por_tecnico.reindex(tecnicos).fillna(0.0),
            "Pontos anteriores": anterior_por_tecnico.reindex(tecnicos).fillna(0.0),
        }
    )
    resultado["Diferença de pontos"] = (
        resultado["Pontos atuais"] - resultado["Pontos anteriores"]
    )
    resultado["Variação (%)"] = resultado.apply(
        lambda linha: (
            (linha["Pontos atuais"] / linha["Pontos anteriores"] - 1) * 100
            if linha["Pontos anteriores"] > 0
            else None
        ),
        axis=1,
    )

    def _status(linha: pd.Series) -> str:
        if anterior.empty:
            return "Sem base anterior"
        if linha["Pontos anteriores"] == 0 and linha["Pontos atuais"] > 0:
            return "Novo na janela"
        if linha["Pontos atuais"] == 0 and linha["Pontos anteriores"] > 0:
            return "Sem produção atual"
        if linha["Pontos atuais"] > linha["Pontos anteriores"]:
            return "Alta"
        if linha["Pontos atuais"] < linha["Pontos anteriores"]:
            return "Queda"
        return "Estável"

    resultado["Status"] = resultado.apply(_status, axis=1)
    resultado.index.name = "Técnico"
    resultado = resultado.reset_index()
    return (
        resultado[colunas]
        .sort_values(
            ["Pontos atuais", "Pontos anteriores", "Técnico"],
            ascending=[False, False, True],
        )
        .reset_index(drop=True)
    )


def resumir_saude_dados(frame: pd.DataFrame) -> dict[str, int | float]:
    """Calcula indicadores de cobertura sem atribuir qualidade não observável."""
    total = len(frame)
    if frame.empty:
        return {
            "registros": 0,
            "tecnicos": 0,
            "projetos_identificados": 0,
            "sem_projeto": 0,
            "percentual_sem_projeto": 0.0,
            "registros_demo": 0,
            "registros_producao": 0,
        }

    if "technician" in frame.columns:
        tecnicos = (
            frame["technician"]
            .astype("string")
            .str.strip()
            .replace("", pd.NA)
            .nunique()
        )
    else:
        tecnicos = 0

    if "project" in frame.columns:
        projetos = frame["project"].astype("string").str.strip()
        sem_projeto_mask = (
            projetos.isna()
            | projetos.eq("")
            | projetos.str.casefold().eq("sem projeto")
        )
        sem_projeto = int(sem_projeto_mask.sum())
        projetos_identificados = int(projetos.loc[~sem_projeto_mask].nunique())
    else:
        sem_projeto = total
        projetos_identificados = 0

    if "is_demo" in frame.columns:
        registros_demo = int(
            pd.to_numeric(frame["is_demo"], errors="coerce").fillna(0).eq(1).sum()
        )
    else:
        registros_demo = 0

    return {
        "registros": total,
        "tecnicos": int(tecnicos),
        "projetos_identificados": projetos_identificados,
        "sem_projeto": sem_projeto,
        "percentual_sem_projeto": sem_projeto / total * 100 if total else 0.0,
        "registros_demo": registros_demo,
        "registros_producao": total - registros_demo,
    }


def rotulo_janelas_comparacao(
    atual: pd.DataFrame,
    *,
    meses: int | None = None,
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
) -> str:
    """Descreve os meses da janela atual e da janela equivalente anterior."""
    if atual.empty or "period" not in atual.columns:
        return "Sem competências suficientes para montar a comparação."

    periodos = pd.to_datetime(atual["period"], errors="coerce").dropna()
    if periodos.empty:
        return "Sem competências suficientes para montar a comparação."

    janela_explicita = inicio is not None and fim is not None
    inicio_data = (
        pd.Timestamp(inicio) if inicio is not None else pd.Timestamp(periodos.min())
    )
    fim_data = pd.Timestamp(fim) if fim is not None else pd.Timestamp(periodos.max())
    inicio_mes = inicio_data.to_period("M").to_timestamp()
    fim_mes = fim_data.to_period("M").to_timestamp()
    quantidade = meses or (
        (fim_mes.year - inicio_mes.year) * 12 + fim_mes.month - inicio_mes.month + 1
    )
    quantidade = max(int(quantidade), 1)
    anterior_inicio_data = inicio_data - pd.DateOffset(months=quantidade)
    anterior_fim_data = inicio_data - pd.Timedelta(days=1)
    if janela_explicita:
        return (
            f"Janela atual: {inicio_data:%d/%m/%Y} a {fim_data:%d/%m/%Y} · "
            f"janela anterior: {anterior_inicio_data:%d/%m/%Y} "
            f"a {anterior_fim_data:%d/%m/%Y}."
        )

    anterior_inicio = inicio_mes - pd.DateOffset(months=quantidade)
    anterior_fim = inicio_mes - pd.Timedelta(days=1)
    atual_rotulo = (
        month_label(inicio_mes)
        if inicio_mes == fim_mes
        else f"{month_label(inicio_mes)}–{month_label(fim_mes)}"
    )
    anterior_rotulo = (
        month_label(anterior_inicio)
        if anterior_inicio.to_period("M") == anterior_fim.to_period("M")
        else f"{month_label(anterior_inicio)}–{month_label(anterior_fim)}"
    )
    return (
        f"Janela atual: {atual_rotulo} · janela anterior: {anterior_rotulo} "
        f"({quantidade} competência(s))."
    )


def selecionar_periodo_anterior(
    records: pd.DataFrame,
    filtrado: pd.DataFrame,
    tecnicos: list[str],
    meses: int | None,
    projetos: list[str],
    inicio_periodo: pd.Timestamp | None = None,
    fim_periodo: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Seleciona intervalo equivalente anterior, mantendo filtros de equipe/projeto."""
    if filtrado.empty or records.empty or "period" not in filtrado.columns:
        return records.iloc[0:0]
    periodos = pd.to_datetime(filtrado["period"], errors="coerce").dropna()
    if periodos.empty:
        return records.iloc[0:0]

    inicio = (
        pd.Timestamp(inicio_periodo)
        if inicio_periodo is not None
        else pd.Timestamp(periodos.min())
    )
    fim = (
        pd.Timestamp(fim_periodo)
        if fim_periodo is not None
        else pd.Timestamp(periodos.max())
    )
    primeiro_mes = inicio.to_period("M").to_timestamp()
    ultimo_mes = fim.to_period("M").to_timestamp()
    quantidade = meses or (
        (ultimo_mes.year - primeiro_mes.year) * 12
        + ultimo_mes.month
        - primeiro_mes.month
        + 1
    )
    quantidade = max(int(quantidade), 1)
    inicio_anterior = inicio - pd.DateOffset(months=quantidade)
    fim_anterior = inicio - pd.Timedelta(days=1)
    return records[
        records["technician"].isin(tecnicos)
        & records["project"].isin(projetos)
        & records["reference_date"].between(inicio_anterior, fim_anterior)
    ]


# ====================================================
# 📊 ESTILO E GRÁFICOS
# ====================================================
def _estilizar_figura(fig: go.Figure, *, altura: int = 340) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin={"l": 8, "r": 18, "t": 22, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={
            "family": "Inter, Segoe UI, sans-serif",
            "color": CINZA_TOTALE,
            "size": 11,
        },
        hoverlabel={"bgcolor": "white", "font_color": AZUL_TOTALE},
        bargap=0.3,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, fixedrange=True)
    fig.update_yaxes(
        gridcolor="#E6EDF5",
        zeroline=False,
        fixedrange=True,
        separatethousands=True,
    )
    return fig


def _section_heading(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>',
        unsafe_allow_html=True,
    )


def _grafico_ranking_projetos(resumo: pd.DataFrame) -> go.Figure:
    dados = resumo.nlargest(12, "points_total").sort_values("points_total")
    fig = go.Figure()
    fig.add_bar(
        y=dados["project"],
        x=dados["points_prod"],
        name="Prod",
        orientation="h",
        marker_color=AZUL_TOTALE,
        hovertemplate="%{y}<br>Prod: %{x:,.2f} pontos<extra></extra>",
    )
    fig.add_bar(
        y=dados["project"],
        x=dados["points_gpon"],
        name="Gpon",
        orientation="h",
        marker_color=LARANJA_TOTALE,
        hovertemplate="%{y}<br>Gpon: %{x:,.2f} pontos<extra></extra>",
    )
    fig.update_layout(
        barmode="stack",
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    fig.update_xaxes(title="Pontos", separatethousands=True)
    fig.update_yaxes(showgrid=False)
    return _estilizar_figura(fig, altura=max(330, len(dados) * 34 + 90))


def _grafico_evolucao_projeto(frame: pd.DataFrame) -> go.Figure:
    mensal = summarize(frame, "period").sort_values("period")
    mensal["competencia"] = mensal["period"].map(month_label)
    fig = go.Figure()
    fig.add_bar(
        x=mensal["competencia"],
        y=mensal["points_prod"],
        name="Prod",
        marker_color=AZUL_TOTALE,
        hovertemplate="<b>%{x}</b><br>Prod: %{y:,.2f} pontos<extra></extra>",
    )
    fig.add_bar(
        x=mensal["competencia"],
        y=mensal["points_gpon"],
        name="Gpon",
        marker_color=LARANJA_TOTALE,
        hovertemplate="<b>%{x}</b><br>Gpon: %{y:,.2f} pontos<extra></extra>",
    )
    fig.update_layout(
        barmode="stack",
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    fig.update_yaxes(title="Pontos", separatethousands=True)
    return _estilizar_figura(fig)


def _contar_os(frame: pd.DataFrame) -> int:
    resumo = summarize_os(frame, [])
    return int(resumo.iloc[0]["os_count"]) if not resumo.empty else 0


def _grafico_mix_pontos(atual: pd.DataFrame, anterior: pd.DataFrame) -> go.Figure:
    atual_total = summarize(atual, [])
    anterior_total = summarize(anterior, [])
    fig = go.Figure()
    for nome, resumo, cor in (
        ("Janela atual", atual_total, AZUL_TOTALE),
        ("Janela anterior", anterior_total, LARANJA_TOTALE),
    ):
        if resumo.empty:
            continue
        fig.add_bar(
            x=["Prod", "Gpon"],
            y=[
                float(resumo.iloc[0]["points_prod"]),
                float(resumo.iloc[0]["points_gpon"]),
            ],
            name=nome,
            marker_color=cor,
            hovertemplate="%{x}<br>%{y:,.2f} pontos<extra></extra>",
        )
    fig.update_layout(
        barmode="group",
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    fig.update_yaxes(title="Pontos", separatethousands=True)
    return _estilizar_figura(fig)


def _grafico_distribuicao_tecnica(
    atual: pd.DataFrame, anterior: pd.DataFrame
) -> go.Figure:
    fig = go.Figure()
    for nome, frame, cor in (
        ("Janela atual", atual, AZUL_TOTALE),
        ("Janela anterior", anterior, LARANJA_TOTALE),
    ):
        resumo = summarize(frame, "technician")
        if resumo.empty:
            continue
        fig.add_box(
            y=resumo["points_total"],
            name=nome,
            marker_color=cor,
            boxpoints="outliers",
            hovertemplate="%{y:,.2f} pontos<extra></extra>",
        )
    fig.update_yaxes(title="Pontos por técnico", separatethousands=True)
    return _estilizar_figura(fig)


# ====================================================
# 🧭 PÁGINA: PRODUÇÃO POR PROJETO
# ====================================================
def render_projetos(frame: pd.DataFrame) -> None:
    """Mostra participação, evolução e distribuição da produção por projeto."""
    if frame.empty:
        st.info("Não há produção para os filtros selecionados.")
        return

    resumo = resumir_projetos(frame)
    total_pontos = float(resumo["points_total"].sum())
    total_os = int(resumo["os_count"].sum())
    nomes_projeto = resumo["project"].astype("string").str.strip()
    projetos_identificados = (
        nomes_projeto.notna()
        & nomes_projeto.ne("")
        & nomes_projeto.str.casefold().ne("sem projeto")
    )
    total_projetos = int(resumo.loc[projetos_identificados, "project"].nunique())
    total_tecnicos = int(frame["technician"].nunique())

    cards = st.columns(4)
    cards[0].metric("Pontos totais", format_points(total_pontos))
    cards[1].metric("O.S. (linhas Prod)", f"{total_os:,}".replace(",", "."))
    cards[2].metric("Projetos identificados", f"{total_projetos:,}".replace(",", "."))
    cards[3].metric("Técnicos ativos", f"{total_tecnicos:,}".replace(",", "."))

    st.markdown("### Comparativo de projetos")
    st.caption(
        "Os pontos totais somam Prod + Gpon; a contagem de O.S. considera "
        "somente as linhas válidas da aba Prod."
    )
    ranking_col, trend_col = st.columns([1.2, 1])
    with ranking_col, st.container(border=True):
        st.markdown("**Projetos por pontos · Top 12**")
        st.plotly_chart(
            _grafico_ranking_projetos(resumo),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    with trend_col, st.container(border=True):
        st.markdown("**Evolução mensal do projeto**")
        projetos = resumo["project"].astype(str).tolist()
        projeto_escolhido = st.selectbox(
            "Projeto",
            projetos,
            key="project_monthly_focus",
            label_visibility="collapsed",
        )
        st.plotly_chart(
            _grafico_evolucao_projeto(
                frame.loc[frame["project"].astype(str).eq(projeto_escolhido)]
            ),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    tabela = resumo.rename(
        columns={
            "project": "Projeto",
            "points_prod": "Prod",
            "points_gpon": "Gpon",
            "points_total": "Pontos totais",
            "os_count": "O.S. (Prod)",
            "technicians": "Técnicos",
            "share_pct": "Participação (%)",
        }
    )
    st.markdown("### Resumo por projeto")
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        alt="Resumo da produção, ordens de serviço e participação por projeto",
        column_config={
            "Projeto": st.column_config.TextColumn(width="medium"),
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos totais": st.column_config.NumberColumn(format="%.2f"),
            "O.S. (Prod)": st.column_config.NumberColumn(format="%d"),
            "Técnicos": st.column_config.NumberColumn(format="%d"),
            "Participação (%)": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.download_button(
        "Baixar resumo por projeto em CSV",
        data=tabela.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name="producao_por_projeto.csv",
        mime="text/csv",
        key="project_dashboard_download",
    )

    with st.expander("Detalhamento por técnico e projeto"):
        detalhe_pontos = summarize(frame, ["project", "technician"])
        detalhe_os = summarize_os(frame, ["project", "technician"])
        detalhe = detalhe_pontos.merge(
            detalhe_os, on=["project", "technician"], how="left"
        )
        detalhe["os_count"] = detalhe["os_count"].fillna(0).astype(int)
        detalhe = detalhe.rename(
            columns={
                "project": "Projeto",
                "technician": "Técnico",
                "points_prod": "Prod",
                "points_gpon": "Gpon",
                "points_total": "Pontos totais",
                "os_count": "O.S. (Prod)",
            }
        )
        st.dataframe(
            detalhe,
            width="stretch",
            hide_index=True,
            alt="Pontos e ordens de serviço por técnico e projeto",
            column_config={
                "Prod": st.column_config.NumberColumn(format="%.2f"),
                "Gpon": st.column_config.NumberColumn(format="%.2f"),
                "Pontos totais": st.column_config.NumberColumn(format="%.2f"),
                "O.S. (Prod)": st.column_config.NumberColumn(format="%d"),
            },
        )


# ====================================================
# 🧭 PÁGINA: RESUMO EXECUTIVO COMPARATIVO
# ====================================================
def render_resumo_executivo(
    atual: pd.DataFrame,
    anterior: pd.DataFrame,
    *,
    meses: int | None = None,
    periodo_inicio: pd.Timestamp | None = None,
    periodo_fim: pd.Timestamp | None = None,
) -> None:
    """Compara a janela filtrada com as competências imediatamente anteriores."""
    if atual.empty:
        st.info("Não há produção para os filtros selecionados.")
        return

    atual_total = summarize(atual, []).iloc[0]
    anterior_total = summarize(anterior, []).iloc[0] if not anterior.empty else None
    atual_os = _contar_os(atual)
    anterior_os = _contar_os(anterior)
    atual_tecnicos = summarize(atual, "technician")["points_total"]
    anterior_tecnicos = (
        summarize(anterior, "technician")["points_total"]
        if not anterior.empty
        else pd.Series(dtype="float64")
    )

    def _delta_pct(valor: float, base: float) -> str | None:
        if base <= 0:
            return None
        return f"{(valor / base - 1) * 100:+.1f}%".replace(".", ",")

    delta_total = (
        _delta_pct(
            float(atual_total["points_total"]), float(anterior_total["points_total"])
        )
        if anterior_total is not None
        else None
    )
    delta_os = _delta_pct(atual_os, anterior_os) if anterior_os else None
    mediana_atual = float(atual_tecnicos.median()) if not atual_tecnicos.empty else 0.0
    mediana_anterior = (
        float(anterior_tecnicos.median()) if not anterior_tecnicos.empty else 0.0
    )
    delta_mediana = (
        _delta_pct(mediana_atual, mediana_anterior) if mediana_anterior > 0 else None
    )
    delta_tecnicos = (
        f"{len(atual_tecnicos) - len(anterior_tecnicos):+d} vs anterior"
        if not anterior.empty
        else None
    )

    cards = st.columns(4)
    cards[0].metric(
        "Pontos totais", format_points(atual_total["points_total"]), delta_total
    )
    cards[1].metric("O.S. (linhas Prod)", f"{atual_os:,}".replace(",", "."), delta_os)
    cards[2].metric(
        "Técnicos ativos", f"{len(atual_tecnicos):,}".replace(",", "."), delta_tecnicos
    )
    cards[3].metric(
        "Mediana de pontos por técnico", format_points(mediana_atual), delta_mediana
    )

    st.caption(
        rotulo_janelas_comparacao(
            atual,
            meses=meses,
            inicio=periodo_inicio,
            fim=periodo_fim,
        )
    )
    if anterior.empty:
        st.info(
            "Ainda não há registros na janela anterior para calcular "
            "variações comparáveis."
        )
    else:
        st.caption(
            "As variações percentuais usam a janela anterior como base. "
            "Técnicos sem base anterior aparecem como novos, sem percentual calculado."
        )

    st.markdown("### Composição e distribuição")
    mix_col, distribution_col = st.columns([1, 1])
    with mix_col, st.container(border=True):
        st.markdown("**Pontos por origem · atual x anterior**")
        st.plotly_chart(
            _grafico_mix_pontos(atual, anterior),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    with distribution_col, st.container(border=True):
        st.markdown("**Distribuição dos pontos por técnico**")
        st.plotly_chart(
            _grafico_distribuicao_tecnica(atual, anterior),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    comparativo = comparar_tecnicos(atual, anterior)
    if not comparativo.empty:
        altas = comparativo.loc[comparativo["Status"].eq("Alta")]
        quedas = comparativo.loc[
            comparativo["Status"].isin(["Queda", "Sem produção atual"])
        ]
        if not anterior.empty and (not altas.empty or not quedas.empty):
            destaque_cols = st.columns(2)
            if not altas.empty:
                maior_alta = altas.nlargest(1, "Diferença de pontos").iloc[0]
                destaque_cols[0].metric(
                    "Maior alta em pontos",
                    str(maior_alta["Técnico"]),
                    f"+{format_points(maior_alta['Diferença de pontos'])}",
                )
            if not quedas.empty:
                maior_queda = quedas.nsmallest(1, "Diferença de pontos").iloc[0]
                destaque_cols[1].metric(
                    "Maior queda em pontos",
                    str(maior_queda["Técnico"]),
                    f"-{format_points(abs(maior_queda['Diferença de pontos']))}",
                )

        st.markdown("### Variação por técnico")
        st.dataframe(
            comparativo,
            width="stretch",
            hide_index=True,
            alt="Comparação de pontos e variação por técnico",
            column_config={
                "Técnico": st.column_config.TextColumn(width="medium"),
                "Pontos atuais": st.column_config.NumberColumn(format="%.2f"),
                "Pontos anteriores": st.column_config.NumberColumn(format="%.2f"),
                "Diferença de pontos": st.column_config.NumberColumn(format="%+.2f"),
                "Variação (%)": st.column_config.NumberColumn(format="%+.1f%%"),
                "Status": st.column_config.TextColumn(width="medium"),
            },
        )


# ====================================================
# 🧭 PÁGINA: SAÚDE DOS DADOS E IMPORTAÇÕES
# ====================================================
def _formatar_data_importacao(valor: object) -> str:
    if valor is None or pd.isna(valor) or not str(valor).strip():
        return "—"
    data = pd.to_datetime(valor, errors="coerce", utc=True)
    if pd.isna(data):
        return str(valor)
    return data.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M BRT")


def _formatar_data_referencia(valor: object) -> str:
    data = pd.to_datetime(valor, errors="coerce")
    return data.strftime("%d/%m/%Y") if pd.notna(data) else "—"


def _render_detalhe_arquivo(frame: pd.DataFrame) -> None:
    """Detalha os registros de um arquivo importado com a coluna Qtde_Contrato."""
    st.markdown("### Detalhamento do arquivo")
    if frame.empty or "source_file" not in frame.columns:
        st.info("Não há registros de arquivos importados para detalhar.")
        return
    arquivos = sorted({str(valor) for valor in frame["source_file"].dropna()})
    if not arquivos:
        st.info("Não há registros de arquivos importados para detalhar.")
        return
    st.caption(
        "Qtde_Contrato repete, em cada linha, o total de contratos distintos do "
        "arquivo selecionado — a mesma contagem da coluna Contratos."
    )
    arquivo = st.selectbox("Arquivo importado", arquivos, key="saude_arquivo_detalhe")
    detalhe = frame.loc[frame["source_file"].astype(str).eq(arquivo)].copy()
    total_contratos = (
        int(detalhe["contracts_qty"].max()) if "contracts_qty" in detalhe else 0
    )
    cards = st.columns(3)
    cards[0].metric("Registros no arquivo", f"{len(detalhe):,}".replace(",", "."))
    cards[1].metric("Qtde_Contrato", f"{total_contratos:,}".replace(",", "."))
    cards[2].metric(
        "Técnicos no arquivo",
        f"{detalhe['technician'].nunique():,}".replace(",", "."),
    )

    colunas = {
        "wo": "O.S.",
        "project": "Projeto",
        "contract": "Contrato",
        "technician": "Técnico",
        "reference_date": "Data",
        "points": "Pontos",
        "source_sheet": "Origem",
        "contracts_qty": "Qtde_Contrato",
    }
    disponiveis = {
        chave: rotulo for chave, rotulo in colunas.items() if chave in detalhe
    }
    tabela = detalhe[list(disponiveis)].rename(columns=disponiveis)
    if "Data" in tabela.columns:
        tabela["Data"] = pd.to_datetime(tabela["Data"], errors="coerce").dt.strftime(
            "%d/%m/%Y"
        )
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        alt="Registros do arquivo importado com a quantidade de contratos",
        column_config={
            "O.S.": st.column_config.TextColumn(width="medium"),
            "Projeto": st.column_config.TextColumn(width="medium"),
            "Contrato": st.column_config.TextColumn(width="small"),
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Data": st.column_config.TextColumn(width="small"),
            "Pontos": st.column_config.NumberColumn(format="%.2f"),
            "Origem": st.column_config.TextColumn(width="small"),
            "Qtde_Contrato": st.column_config.NumberColumn(format="%d"),
        },
    )
    nome = re.sub(r"[^\w.-]+", "_", arquivo.split(" [")[0]).strip("._") or "arquivo"
    st.download_button(
        "Baixar arquivo enriquecido em CSV",
        data=tabela.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name=f"{nome}_com_qtde_contrato.csv",
        mime="text/csv",
        key=f"saude_download_arquivo_{arquivos.index(arquivo)}",
    )


def render_saude_dados(
    frame: pd.DataFrame,
    stats: Mapping[str, Any],
    lotes: pd.DataFrame | None,
    status_sincronizacao: Mapping[str, Any] | None,
) -> None:
    """Apresenta cobertura, atualizações e arquivos importados da base local."""
    resumo = resumir_saude_dados(frame)
    cards = st.columns(4)
    cards[0].metric("Registros", f"{resumo['registros']:,}".replace(",", "."))
    cards[1].metric("Técnicos", f"{resumo['tecnicos']:,}".replace(",", "."))
    cards[2].metric(
        "Projetos identificados",
        f"{resumo['projetos_identificados']:,}".replace(",", "."),
    )
    cards[3].metric(
        "Sem projeto",
        f"{resumo['sem_projeto']:,}".replace(",", "."),
    )
    percentual_sem_projeto = f"{resumo['percentual_sem_projeto']:.1f}".replace(".", ",")
    st.caption(
        f"{percentual_sem_projeto}% dos registros estão classificados como Sem projeto."
    )

    inicio = _formatar_data_referencia(stats.get("first_date"))
    fim = _formatar_data_referencia(stats.get("last_date"))
    ultima_importacao = _formatar_data_importacao(stats.get("last_import"))
    st.caption(
        f"Período de referência: {inicio} a {fim} · "
        f"última gravação no banco: {ultima_importacao}."
    )

    demo = int(resumo["registros_demo"])
    if demo:
        registros_demo = f"{demo:,}".replace(",", ".")
        registros_producao = f"{int(resumo['registros_producao']):,}".replace(",", ".")
        st.warning(
            f"A base contém {registros_demo} registro(s) de demonstração e "
            f"{registros_producao} registro(s) de produção. "
            "Os dados de demonstração estão identificados e não devem ser "
            "tratados como produção real."
        )

    st.markdown("### Sincronização com Google Drive")
    if status_sincronizacao:
        tipo = str(status_sincronizacao.get("type", "info"))
        mensagem = str(
            status_sincronizacao.get(
                "message", "Status da sincronização não informado."
            )
        )
        renderizador = {
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "info": st.info,
        }.get(tipo, st.info)
        renderizador(mensagem)
        problemas = status_sincronizacao.get("issues", [])
        if isinstance(problemas, (list, tuple)) and problemas:
            with st.expander(f"Detalhes da importação ({len(problemas)})"):
                for problema in problemas:
                    st.write(f"• {problema}")
    else:
        st.info("Ainda não há status de sincronização nesta sessão.")

    st.markdown("### Arquivos importados")
    if lotes is None or lotes.empty:
        st.info("Nenhum lote de importação encontrado na base.")
        return

    tabela = lotes.copy()
    tabela["imported_at"] = tabela["imported_at"].map(_formatar_data_importacao)
    tabela = tabela.rename(
        columns={
            "source_file": "Arquivo",
            "origins": "Origem",
            "rows_count": "Registros",
            "contracts_count": "Contratos",
            "points": "Pontos somados",
            "imported_at": "Importado em",
        }
    )
    st.caption(
        "O contador de contratos por arquivo considera identificadores "
        "distintos; registros sem contrato não entram na contagem."
    )
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        alt=(
            "Arquivos importados, origem, registros, contratos distintos "
            "e pontos somados"
        ),
        column_config={
            "Arquivo": st.column_config.TextColumn(width="large"),
            "Origem": st.column_config.TextColumn(width="small"),
            "Registros": st.column_config.NumberColumn(format="%d"),
            "Contratos": st.column_config.NumberColumn(format="%d"),
            "Pontos somados": st.column_config.NumberColumn(format="%.2f"),
            "Importado em": st.column_config.TextColumn(width="medium"),
        },
    )
    st.download_button(
        "Baixar lotes de importação em CSV",
        data=tabela.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
        file_name="lotes_importacao.csv",
        mime="text/csv",
        key="data_health_download",
    )

    _render_detalhe_arquivo(frame)


def render_regularidade_producao(
    frame: pd.DataFrame,
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
) -> None:
    """Exibe médias, medianas, oscilações e lacunas mensais por técnico."""
    if frame.empty:
        st.info("Não há produção para calcular a regularidade no recorte selecionado.")
        return

    resumo = resumir_regularidade(frame, inicio, fim)
    periods, competencias = _janela_mensal(frame, inicio, fim)
    if resumo.empty or periods.empty:
        st.info("Não há competências válidas para calcular a regularidade.")
        return

    work = frame.copy()
    work["_competencia"] = competencias
    work["_pontos"] = pd.to_numeric(work["points"], errors="coerce").fillna(0.0)
    mensal_equipe = (
        work.groupby("_competencia")["_pontos"].sum().reindex(periods, fill_value=0.0)
    )
    media_equipe = float(mensal_equipe.mean())
    mediana_equipe = float(mensal_equipe.median())
    lacunas = int(resumo["months_without_records"].sum())
    oscilacao_alta = int(resumo["regularity"].eq("Alta oscilação").sum())

    _section_heading(
        "Regularidade da produção",
        "Compare média e mediana, identifique oscilações e competências sem registros.",
    )
    cards = st.columns(4)
    with cards[0]:
        st.metric(
            "Média mensal da equipe",
            f"{format_points(media_equipe)} pontos",
            help="Inclui competências sem produção no período selecionado.",
        )
    with cards[1]:
        st.metric(
            "Mediana mensal da equipe",
            f"{format_points(mediana_equipe)} pontos",
            help="Inclui competências sem produção no período selecionado.",
        )
    with cards[2]:
        st.metric("Técnicos com alta oscilação", str(oscilacao_alta))
    with cards[3]:
        st.metric("Lacunas técnico-mês", str(lacunas))

    labels = [month_label(period) for period in periods]
    fig = go.Figure()
    fig.add_scatter(
        x=labels,
        y=mensal_equipe.to_numpy(),
        mode="lines+markers",
        name="Pontos da equipe",
        line={"color": AZUL_TOTALE, "width": 3},
        marker={"size": 7},
        hovertemplate="<b>%{x}</b><br>%{y:,.2f} pontos<extra></extra>",
    )
    fig.add_hline(
        y=media_equipe,
        line_color=LARANJA_TOTALE,
        line_dash="dash",
        annotation_text="Média",
        annotation_position="top left",
    )
    fig.add_hline(
        y=mediana_equipe,
        line_color=VERDE_TOTALE,
        line_dash="dot",
        annotation_text="Mediana",
        annotation_position="bottom left",
    )
    fig.update_layout(hovermode="x unified")
    fig.update_yaxes(title="Pontos Totais", rangemode="tozero", separatethousands=True)
    with st.container(border=True):
        st.markdown("**Pontos da equipe por competência**")
        st.plotly_chart(
            _estilizar_figura(fig),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    display = resumo.rename(
        columns={
            "technician": "Técnico",
            "active_months": "Meses com registros",
            "months_without_records": "Meses sem registro",
            "missing_periods": "Competências sem registro",
            "mean_active_monthly_points": "Média nos meses ativos",
            "median_active_monthly_points": "Mediana nos meses ativos",
            "coefficient_variation_pct": "Oscilação (CV %)",
            "peak_month": "Competência de pico",
            "peak_points": "Pontos no pico",
            "peak_vs_median_pct": "Pico vs mediana (%)",
            "regularity": "Classificação",
        }
    )
    display = display[
        [
            "Técnico",
            "Classificação",
            "Meses com registros",
            "Meses sem registro",
            "Competências sem registro",
            "Média nos meses ativos",
            "Mediana nos meses ativos",
            "Oscilação (CV %)",
            "Competência de pico",
            "Pontos no pico",
            "Pico vs mediana (%)",
        ]
    ]
    styled = display.style.map(
        lambda value: {
            "Regular": "background-color: #DCFCE7; color: #166534; font-weight: 600;",
            "Oscilação moderada": "background-color: #FEF3C7; color: #92400E; font-weight: 600;",
            "Alta oscilação": "background-color: #FEE2E2; color: #991B1B; font-weight: 600;",
            "Base curta": "background-color: #E2E8F0; color: #334155;",
            "Sem pontos": "background-color: #E2E8F0; color: #334155;",
        }.get(value, ""),
        subset=["Classificação"],
    ).map(
        lambda value: (
            "background-color: #FEF3C7; color: #92400E; font-weight: 600;"
            if value > 0
            else ""
        ),
        subset=["Meses sem registro"],
    )
    st.caption(
        "Na tabela, média e mediana consideram apenas competências com registros; "
        "as lacunas são listadas à parte. A oscilação é o coeficiente de variação "
        "(desvio-padrão ÷ média) e só recebe classificação a partir de três meses ativos."
    )
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        alt="Média, mediana, oscilação e competências sem registro por técnico",
        column_config={
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Classificação": st.column_config.TextColumn(width="medium"),
            "Meses com registros": st.column_config.NumberColumn(format="%d"),
            "Meses sem registro": st.column_config.NumberColumn(format="%d"),
            "Competências sem registro": st.column_config.TextColumn(width="large"),
            "Média nos meses ativos": st.column_config.NumberColumn(format="%.2f"),
            "Mediana nos meses ativos": st.column_config.NumberColumn(format="%.2f"),
            "Oscilação (CV %)": st.column_config.NumberColumn(format="%.1f%%"),
            "Competência de pico": st.column_config.TextColumn(width="small"),
            "Pontos no pico": st.column_config.NumberColumn(format="%.2f"),
            "Pico vs mediana (%)": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )


def render_sazonalidade(
    frame: pd.DataFrame,
    inicio: pd.Timestamp | None = None,
    fim: pd.Timestamp | None = None,
) -> None:
    """Exibe mapa de calor mensal de Pontos Totais por técnico ou projeto."""
    if frame.empty:
        st.info("Não há produção para exibir no mapa de sazonalidade.")
        return

    _section_heading(
        "Sazonalidade da produção",
        "Compare a intensidade dos Pontos Totais por competência, técnico ou projeto.",
    )
    dimension_col, count_col = st.columns([1, 1])
    with dimension_col:
        dimension_label = st.selectbox(
            "Agrupar por",
            ["Técnico", "Projeto"],
            key="seasonality_dimension",
        )
    dimension = "technician" if dimension_label == "Técnico" else "project"
    with count_col:
        top_n = st.slider(
            "Máximo de entidades exibidas",
            min_value=1,
            max_value=20,
            value=12,
            key="seasonality_top_n",
        )

    matrix = matriz_sazonalidade(
        frame,
        dimension,
        inicio,
        fim,
        top_n=top_n,
    )
    if matrix.empty:
        st.info("Não há dados suficientes para montar o mapa de calor.")
        return

    month_labels = [month_label(period) for period in matrix.columns]
    values = matrix.to_numpy(dtype=float)
    maximum = float(values.max()) if values.size else 0.0
    entity_label = "Técnico" if dimension == "technician" else "Projeto"
    fig = go.Figure(
        data=go.Heatmap(
            z=values,
            x=month_labels,
            y=matrix.index.astype(str).tolist(),
            zmin=0,
            zmax=maximum if maximum > 0 else 1,
            colorscale=[
                [0.0, "#F8FAFC"],
                [0.12, "#DBEAFE"],
                [0.55, "#60A5FA"],
                [1.0, AZUL_TOTALE],
            ],
            colorbar={"title": {"text": "Pontos"}},
            hovertemplate="<b>%{y}</b><br>%{x}<br>%{z:,.2f} pontos<extra></extra>",
        )
    )
    fig.update_xaxes(title="Competência", tickangle=0)
    fig.update_yaxes(title=entity_label, autorange="reversed")
    with st.container(border=True):
        st.markdown("**Pontos Totais por competência**")
        st.plotly_chart(
            _estilizar_figura(fig, altura=max(380, min(800, 150 + len(matrix) * 32))),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    entity_plural = entity_label.lower() + ("s" if len(matrix) != 1 else "")
    st.caption(
        f"Exibindo {len(matrix)} {entity_plural} com mais pontos no recorte. "
        "As competências sem pontos aparecem na escala mínima; passe o cursor sobre "
        "uma célula para consultar o valor exato."
    )

    export = matrix.copy()
    export.columns = month_labels
    export.index.name = entity_label
    export = export.reset_index()
    with st.expander("Ver tabela de valores"):
        st.dataframe(
            export,
            width="stretch",
            hide_index=True,
            alt=f"Pontos Totais por competência e {entity_label.lower()}",
            column_config={
                entity_label: st.column_config.TextColumn(width="medium"),
                **{
                    label: st.column_config.NumberColumn(format="%.2f")
                    for label in month_labels
                },
            },
        )
        st.download_button(
            "Baixar mapa de sazonalidade em CSV",
            data=export.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
            file_name=f"sazonalidade_{dimension}.csv",
            mime="text/csv",
            key="seasonality_csv_download",
        )


__all__ = [
    "comparar_tecnicos",
    "matriz_sazonalidade",
    "render_projetos",
    "render_regularidade_producao",
    "render_resumo_executivo",
    "render_saude_dados",
    "render_sazonalidade",
    "resumir_projetos",
    "resumir_regularidade",
    "resumir_saude_dados",
    "rotulo_janelas_comparacao",
    "selecionar_periodo_anterior",
]
