"""Painel de Quadro de Técnicos interligado à planilha lista_ativos."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler

from components.componentes import render_kpi_card, render_ticker
from components.painel_quantidades import (
    AZUL_TOTALE,
    CHART_CONFIG,
    LARANJA_TOTALE,
    chart_layout,
    csv_download,
    section_heading,
)
from production import (
    DEFAULT_ROSTER_SHEET_ID,
    GPON,
    PROD,
    ROSTER_STATUS_ORDER,
    clean_contract,
    extract_spreadsheet_id,
    format_points,
    is_valid_contract,
    normalize_text,
)

COLUNAS_QUADRO = [
    "RE",
    "Login",
    "Técnico",
    "Situação",
    "Monitor",
    "U.N.",
    "Base",
    "Prod",
    "Gpon",
    "Pontos Totais",
    "O.S. (Prod)",
    "Contratos",
    "Meses com produção",
    "Com produção",
    "Última modificação",
    "Data desligamento",
    "Motivo",
]

_CORES_SITUACAO: dict[str, tuple[str, str]] = {
    "ATIVO": ("#DCFCE7", "#166534"),
    "FÉRIAS": ("#DBEAFE", "#1E40AF"),
    "AFASTADO": ("#FEF3C7", "#92400E"),
    "INOPERANTE": ("#FFEDD5", "#9A3412"),
    "DESLIGADO": ("#F1F5F9", "#475569"),
    "Não cadastrado": ("#FAF5FF", "#6D28D9"),
}


def _agregar_producao_por_chave(production_frame: pd.DataFrame) -> pd.DataFrame:
    colunas = [
        "technician_key",
        "technician_prod",
        "points_prod",
        "points_gpon",
        "points_total",
        "os_count",
        "contracts_count",
        "active_months",
    ]
    if production_frame.empty or "technician" not in production_frame.columns:
        return pd.DataFrame(columns=colunas)

    work = production_frame.copy()
    unique_tech = work["technician"].dropna().unique()
    key_map = {val: normalize_text(val) for val in unique_tech}
    work["technician_key"] = work["technician"].map(key_map).fillna("")
    work = work[work["technician_key"].ne("")]
    if work.empty:
        return pd.DataFrame(columns=colunas)

    work["points"] = pd.to_numeric(work.get("points", 0.0), errors="coerce").fillna(0.0)
    source = (
        work["source_sheet"].astype(str)
        if "source_sheet" in work.columns
        else pd.Series(PROD, index=work.index)
    )
    work["points_prod"] = work["points"].where(source.eq(PROD), 0.0)
    work["points_gpon"] = work["points"].where(source.eq(GPON), 0.0)
    work["is_os"] = source.eq(PROD).astype(int)

    if "period" in work.columns:
        work["period_norm"] = pd.to_datetime(
            work["period"], errors="coerce", format="mixed"
        )
    elif "reference_date" in work.columns:
        datas = pd.to_datetime(work["reference_date"], errors="coerce", format="mixed")
        work["period_norm"] = datas.dt.to_period("M").dt.to_timestamp()
    else:
        work["period_norm"] = pd.NaT

    agrupado = work.groupby("technician_key", as_index=False).agg(
        technician_prod=("technician", "first"),
        points_prod=("points_prod", "sum"),
        points_gpon=("points_gpon", "sum"),
        os_count=("is_os", "sum"),
        active_months=("period_norm", "nunique"),
    )
    agrupado["points_total"] = agrupado["points_prod"] + agrupado["points_gpon"]

    contratos_por_chave: pd.Series = pd.Series(dtype="int64")
    if "contract" in work.columns:
        unicos_ct = work["contract"].dropna().unique()
        mapa_valido = {val: is_valid_contract(val) for val in unicos_ct}
        mapa_limpo = {
            val: clean_contract(val) for val in unicos_ct if mapa_valido.get(val, False)
        }
        validos = work[work["contract"].map(mapa_valido).fillna(False)].copy()
        if not validos.empty:
            validos["contract_clean"] = validos["contract"].map(mapa_limpo)
            pares = validos[
                ["technician_key", "period_norm", "contract_clean"]
            ].drop_duplicates()
            contratos_por_chave = pares.groupby("technician_key").size()

    agrupado["contracts_count"] = (
        agrupado["technician_key"].map(contratos_por_chave).fillna(0).astype(int)
    )
    return agrupado[colunas]


def conciliar_quadro_tecnicos(
    roster: pd.DataFrame,
    production_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Cruza o cadastro (lista_ativos + desligados) com a produção do recorte."""
    prod_agg = _agregar_producao_por_chave(production_frame)

    if roster.empty and prod_agg.empty:
        return pd.DataFrame(columns=COLUNAS_QUADRO)

    if roster.empty:
        base_df = prod_agg.copy()
        base_df["RE"] = ""
        base_df["Login"] = ""
        base_df["Técnico"] = base_df["technician_prod"]
        base_df["Situação"] = "Não cadastrado"
        base_df["Monitor"] = "Sem monitor"
        base_df["U.N."] = "Sem U.N."
        base_df["Base"] = "Sem base"
        base_df["Última modificação"] = ""
        base_df["Data desligamento"] = ""
        base_df["Motivo"] = ""
    else:
        cad = roster.drop_duplicates("technician_key").copy()
        merged = cad.merge(prod_agg, on="technician_key", how="outer")
        merged["Técnico"] = merged["technician"].fillna(merged["technician_prod"])
        merged["RE"] = merged["re_code"].fillna("")
        merged["Login"] = merged["login"].fillna("")
        merged["Situação"] = merged["status"].fillna("Não cadastrado")
        merged["Monitor"] = merged["monitor"].fillna("Sem monitor")
        merged["U.N."] = merged["un"].fillna("Sem U.N.")
        merged["Base"] = merged["base"].fillna("Sem base")
        merged["Última modificação"] = merged["last_modified"].fillna("")
        merged["Data desligamento"] = merged["termination_date"].fillna("")
        merged["Motivo"] = merged["termination_reason"].fillna("")
        base_df = merged

    for num_col in ("points_prod", "points_gpon", "points_total"):
        base_df[num_col] = pd.to_numeric(base_df[num_col], errors="coerce").fillna(0.0)
    for int_col in ("os_count", "contracts_count", "active_months"):
        base_df[int_col] = (
            pd.to_numeric(base_df[int_col], errors="coerce").fillna(0).astype(int)
        )

    base_df["Prod"] = base_df["points_prod"]
    base_df["Gpon"] = base_df["points_gpon"]
    base_df["Pontos Totais"] = base_df["points_total"]
    base_df["O.S. (Prod)"] = base_df["os_count"]
    base_df["Contratos"] = base_df["contracts_count"]
    base_df["Meses com produção"] = base_df["active_months"]
    base_df["Com produção"] = (
        base_df["Pontos Totais"].gt(0).map(lambda v: "Sim" if v else "Não")
    )

    ordem_map = {status: idx for idx, status in enumerate(ROSTER_STATUS_ORDER)}
    base_df["_ord"] = base_df["Situação"].map(ordem_map).fillna(99).astype(int)
    base_df = base_df.sort_values(
        ["_ord", "Pontos Totais", "Técnico"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    return base_df[COLUNAS_QUADRO]


def _estilo_situacao(valor: object) -> str:
    chave = str(valor or "")
    cores = _CORES_SITUACAO.get(chave)
    if cores is None:
        return ""
    bg, fg = cores
    return f"background-color: {bg}; color: {fg}; font-weight: 700;"


def _estilizar_tabela_quadro(tabela: pd.DataFrame) -> Styler | pd.DataFrame:
    limite = int(pd.get_option("styler.render.max_elements"))
    if tabela.size > limite:
        return tabela
    return tabela.style.map(_estilo_situacao, subset=["Situação"])


def _grafico_cobertura_por_base(quadro: pd.DataFrame) -> go.Figure:
    ativos = quadro[quadro["Situação"].eq("ATIVO")].copy()
    fig = go.Figure()
    if ativos.empty:
        return chart_layout(fig)

    resumo = (
        ativos.assign(
            com_prod=ativos["Pontos Totais"].gt(0).astype(int),
            sem_prod=ativos["Pontos Totais"].le(0).astype(int),
        )
        .groupby("Base", as_index=False)[["com_prod", "sem_prod"]]
        .sum()
    )
    resumo["total"] = resumo["com_prod"] + resumo["sem_prod"]
    resumo = resumo.sort_values("total", ascending=False)

    fig.add_bar(
        x=resumo["Base"],
        y=resumo["com_prod"],
        name="Ativos com produção",
        marker_color=AZUL_TOTALE,
        text=resumo["com_prod"],
        textposition="inside",
        hovertemplate="<b>%{x}</b><br>Com produção: %{y}<extra></extra>",
    )
    fig.add_bar(
        x=resumo["Base"],
        y=resumo["sem_prod"],
        name="Ativos sem produção",
        marker_color=LARANJA_TOTALE,
        text=resumo["sem_prod"],
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{x}</b><br>Sem produção: %{y}<extra></extra>",
    )
    maximo = int(resumo["total"].max()) if not resumo.empty else 1
    fig.update_layout(
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_yaxes(range=[0, max(1, maximo * 1.22)])
    return chart_layout(fig, height=340)


def _grafico_pontos_por_monitor(quadro: pd.DataFrame) -> go.Figure:
    com_pontos = quadro[quadro["Pontos Totais"].gt(0)].copy()
    fig = go.Figure()
    if com_pontos.empty:
        return chart_layout(fig)

    por_monitor = (
        com_pontos.groupby("Monitor", as_index=False)
        .agg(
            pontos=("Pontos Totais", "sum"),
            tecnicos=("Técnico", "nunique"),
        )
        .sort_values("pontos", ascending=False)
        .head(15)
        .sort_values("pontos", ascending=True)
    )
    fig.add_bar(
        y=por_monitor["Monitor"],
        x=por_monitor["pontos"],
        orientation="h",
        marker_color=AZUL_TOTALE,
        text=[format_points(v) for v in por_monitor["pontos"]],
        textposition="outside",
        cliponaxis=False,
        customdata=por_monitor[["tecnicos"]].to_numpy(),
        hovertemplate=(
            "<b>%{y}</b><br>Pontos Totais: %{x:,.2f}<br>"
            "Técnicos com produção: %{customdata[0]}<extra></extra>"
        ),
    )
    maximo = float(por_monitor["pontos"].max()) if not por_monitor.empty else 1.0
    fig.update_xaxes(range=[0, maximo * 1.28 if maximo else 1], showticklabels=False)
    fig.update_yaxes(showgrid=False)
    altura = max(300, len(por_monitor) * 30 + 70)
    chart_layout(fig, height=altura)
    fig.update_layout(margin=dict(l=8, r=85, t=15, b=8), showlegend=False)
    return fig


def render_quadro_tecnicos(
    production_frame: pd.DataFrame,
    roster: pd.DataFrame,
    *,
    sheet_id: str = DEFAULT_ROSTER_SHEET_ID,
) -> None:
    """Renderiza a aba dedicada de conciliação entre lista_ativos/desligados e produção."""
    clean_id = extract_spreadsheet_id(sheet_id) or DEFAULT_ROSTER_SHEET_ID
    sheet_url = f"https://docs.google.com/spreadsheets/d/{clean_id}"

    with st.container(border=True):
        st.markdown(
            f"**Planilha cadastral vinculada:** "
            f"[lista_ativos (`{clean_id}`)]({sheet_url})  \n"
            "<span style='color:#64748B;font-size:12.5px;'>"
            "Abas monitoradas: <code>lista_ativos</code> (ATIVO, FÉRIAS, AFASTADO, INOPERANTE) "
            "e <code>desligados</code>. Nos demais painéis, o filtro padrão restringe a "
            "<strong>Situação = ATIVO</strong>. Use “Atualizar dados” na barra lateral "
            "para sincronizar a planilha."
            "</span>",
            unsafe_allow_html=True,
        )

    quadro_completo = conciliar_quadro_tecnicos(roster, production_frame)
    if quadro_completo.empty:
        st.info(
            "Ainda não há colaboradores cadastrados nem registros de produção para conciliar."
        )
        return

    ativos_df = quadro_completo[quadro_completo["Situação"].eq("ATIVO")]
    total_ativos = len(ativos_df)
    ativos_com_prod = int(ativos_df["Pontos Totais"].gt(0).sum())
    ativos_sem_prod = total_ativos - ativos_com_prod
    desligados_total = int(quadro_completo["Situação"].eq("DESLIGADO").sum())
    outras_situacoes = int(
        quadro_completo["Situação"].isin(["FÉRIAS", "AFASTADO", "INOPERANTE"]).sum()
    )
    nao_cadastrados = int(quadro_completo["Situação"].eq("Não cadastrado").sum())

    render_ticker(
        [
            ("Técnicos ATIVO", str(total_ativos)),
            ("Ativos com produção", str(ativos_com_prod)),
            ("Ativos sem produção", str(ativos_sem_prod)),
            ("Férias / Afastados / Inop.", str(outras_situacoes)),
            ("Desligados", str(desligados_total)),
            ("Produção não cadastrada", str(nao_cadastrados)),
        ],
        label="Resumo do quadro de técnicos",
    )

    with st.container(border=True):
        f1, f2, f3, f4 = st.columns([1.35, 1.35, 1.15, 1.0])
        situacoes_disp = [
            s
            for s in ROSTER_STATUS_ORDER
            if s in set(quadro_completo["Situação"].unique())
        ]
        for extra in sorted(quadro_completo["Situação"].unique()):
            if extra not in situacoes_disp:
                situacoes_disp.append(extra)
        with f1:
            sel_situacoes = st.multiselect(
                "Situação cadastral",
                situacoes_disp,
                default=[],
                placeholder="Todas as situações",
                key="quadro_situacao_filter",
            )
        with f2:
            monitores_disp = sorted(quadro_completo["Monitor"].unique())
            sel_monitores = st.multiselect(
                "Monitor",
                monitores_disp,
                default=[],
                placeholder="Todos os monitores",
                key="quadro_monitor_filter",
            )
        with f3:
            bases_disp = sorted(quadro_completo["Base"].unique())
            sel_bases = st.multiselect(
                "Base",
                bases_disp,
                default=[],
                placeholder="Todas as bases",
                key="quadro_base_filter",
            )
        with f4:
            filtro_prod = st.selectbox(
                "Produção no período",
                ["Todos", "Com produção", "Sem produção"],
                key="quadro_producao_filter",
            )

    recorte = quadro_completo.copy()
    if sel_situacoes:
        recorte = recorte[recorte["Situação"].isin(sel_situacoes)]
    if sel_monitores:
        recorte = recorte[recorte["Monitor"].isin(sel_monitores)]
    if sel_bases:
        recorte = recorte[recorte["Base"].isin(sel_bases)]
    if filtro_prod == "Com produção":
        recorte = recorte[recorte["Pontos Totais"].gt(0)]
    elif filtro_prod == "Sem produção":
        recorte = recorte[recorte["Pontos Totais"].le(0)]

    cobertura_pct = (
        f"{ativos_com_prod / total_ativos * 100:.1f}%".replace(".", ",")
        if total_ativos
        else "0,0%"
    )
    kpis = st.columns(4)
    with kpis[0]:
        render_kpi_card(
            "TÉCNICOS ATIVOS",
            f"{total_ativos:,}".replace(",", "."),
            f"{ativos_com_prod} com produção ({cobertura_pct})",
            "✓",
            "kpi-card--azul",
        )
    with kpis[1]:
        render_kpi_card(
            "ATIVOS SEM PRODUÇÃO",
            f"{ativos_sem_prod:,}".replace(",", "."),
            "Cadastrados como ATIVO sem pontos no período",
            "!",
            "kpi-card--laranja",
        )
    with kpis[2]:
        render_kpi_card(
            "FÉRIAS / AFAST. / DESLIG.",
            f"{outras_situacoes + desligados_total:,}".replace(",", "."),
            f"{outras_situacoes} afast./férias/inop. · {desligados_total} desligados",
            "◎",
            "kpi-card--verde",
        )
    with kpis[3]:
        render_kpi_card(
            "PRODUÇÃO NÃO CADASTRADA",
            f"{nao_cadastrados:,}".replace(",", "."),
            "Com pontos no período e ausentes na planilha",
            "?",
            "kpi-card--roxo",
        )

    section_heading(
        "Distribuição operacional do quadro",
        "Cobertura produtiva dos técnicos ATIVO por base e pontuação acumulada por monitor.",
    )
    col_base, col_mon = st.columns(2)
    with col_base, st.container(border=True):
        st.markdown("**Técnicos ATIVO por Base (com × sem produção)**")
        st.plotly_chart(
            _grafico_cobertura_por_base(recorte),
            width="stretch",
            config=CHART_CONFIG,
        )
    with col_mon, st.container(border=True):
        st.markdown("**Pontos Totais por Monitor · Top 15**")
        st.plotly_chart(
            _grafico_pontos_por_monitor(recorte),
            width="stretch",
            config=CHART_CONFIG,
        )

    section_heading(
        "Conciliação cadastral e produção",
        f"Exibindo {len(recorte)} de {len(quadro_completo)} colaborador(es) conciliados no período.",
    )
    colunas_exibicao = [
        "RE",
        "Login",
        "Técnico",
        "Situação",
        "Monitor",
        "U.N.",
        "Base",
        "Prod",
        "Gpon",
        "Pontos Totais",
        "O.S. (Prod)",
        "Contratos",
        "Meses com produção",
        "Última modificação",
    ]
    if recorte["Data desligamento"].astype(str).str.strip().ne("").any():
        colunas_exibicao.extend(["Data desligamento", "Motivo"])

    tabela_exibicao = recorte[colunas_exibicao].reset_index(drop=True)
    st.dataframe(
        _estilizar_tabela_quadro(tabela_exibicao),
        width="stretch",
        hide_index=True,
        alt="Quadro cadastral de técnicos cruzado com a produção no período",
        column_config={
            "RE": st.column_config.TextColumn(width="small"),
            "Login": st.column_config.TextColumn(width="small"),
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Situação": st.column_config.TextColumn(width="small"),
            "Monitor": st.column_config.TextColumn(width="medium"),
            "U.N.": st.column_config.TextColumn(width="small"),
            "Base": st.column_config.TextColumn(width="small"),
            "Prod": st.column_config.NumberColumn(format="%.2f"),
            "Gpon": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
            "O.S. (Prod)": st.column_config.NumberColumn(format="%d"),
            "Contratos": st.column_config.NumberColumn(format="%d"),
            "Meses com produção": st.column_config.NumberColumn(format="%d"),
        },
    )
    st.download_button(
        "Baixar quadro de técnicos em CSV",
        data=csv_download(tabela_exibicao),
        file_name="quadro_tecnicos_totale.csv",
        mime="text/csv",
        key="quadro_tecnicos_download",
    )
