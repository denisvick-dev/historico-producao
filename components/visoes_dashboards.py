"""Dashboards complementares de projetos, resumo executivo e saúde dos dados."""

from __future__ import annotations

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
            "points": "Pontos somados",
            "imported_at": "Importado em",
        }
    )
    st.dataframe(
        tabela,
        width="stretch",
        hide_index=True,
        column_config={
            "Arquivo": st.column_config.TextColumn(width="large"),
            "Origem": st.column_config.TextColumn(width="small"),
            "Registros": st.column_config.NumberColumn(format="%d"),
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


__all__ = [
    "comparar_tecnicos",
    "render_projetos",
    "render_resumo_executivo",
    "render_saude_dados",
    "resumir_projetos",
    "resumir_saude_dados",
    "rotulo_janelas_comparacao",
    "selecionar_periodo_anterior",
]
