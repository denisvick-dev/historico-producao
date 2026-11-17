"""Comparação Lado a Lado de Técnicos para feedbacks 1:1 (Item 2.5).

Permite comparar um técnico selecionado diretamente contra:
1. Outro técnico do recorte atual (``modo="tecnico"``)
2. A média da própria Base (com fallback para a média da equipe) (``modo="media_base"``)
3. O Top Quartil (P75) da equipe no período (``modo="top_quartil"``)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    TemaKPIType,
    formatar_numero_br,
    render_kpi,
    render_section_header,
)
from components.consultivo import normalizar_coluna_data_consultivo
from production import (
    GPON,
    PROD,
    clean_code,
    format_points,
    month_label,
    normalize_text,
    summarize,
)

ModoComparacao = Literal["tecnico", "media_base", "top_quartil"]


@dataclass
class ComparacaoTecnicoResultado:
    """Resultado consolidado de comparação 1:1 entre técnico e referência."""

    tecnico_a: str
    referencia_label: str
    modo: ModoComparacao
    base_tecnico_a: str
    tabela_metricas: pd.DataFrame
    serie_mensal: pd.DataFrame
    radar_normalizado: pd.DataFrame
    pontos_fortes: list[str] = field(default_factory=list)
    oportunidades: list[str] = field(default_factory=list)


def _metricas_individuais_frame(
    records: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None,
    period_start: pd.Timestamp | None,
    period_end: pd.Timestamp | None,
) -> pd.DataFrame:
    """Calcula tabela vetorizada de indicadores por técnico para benchmark."""
    if records.empty:
        return pd.DataFrame()

    work = records.copy()
    work["points"] = pd.to_numeric(work["points"], errors="coerce").fillna(0.0)
    work["pts_prod"] = work["points"].where(work["source_sheet"].eq(PROD), 0.0)
    work["pts_gpon"] = work["points"].where(work["source_sheet"].eq(GPON), 0.0)
    work["is_prod"] = work["source_sheet"].eq(PROD).astype("int32")

    agg = work.groupby("technician", as_index=False).agg(
        points_prod=("pts_prod", "sum"),
        points_gpon=("pts_gpon", "sum"),
        points_total=("points", "sum"),
        os_count=("is_prod", "sum"),
        active_months=("period", "nunique"),
    )

    if "contract" in work.columns:
        valid_c = work.loc[
            work["contract"].notna()
            & work["contract"].astype(str).str.strip().ne("")
            & work["contract"].astype(str).ne("Sem contrato")
        ]
        c_cnt = (
            valid_c.groupby("technician")["contract"].nunique()
            if not valid_c.empty
            else pd.Series(dtype="int64")
        )
        agg["contracts_count"] = agg["technician"].map(c_cnt).fillna(0).astype(int)
    else:
        agg["contracts_count"] = 0

    if "base" in work.columns:
        base_map = (
            work.groupby("technician")["base"].first().fillna("Sem base").astype(str)
        )
        agg["base"] = agg["technician"].map(base_map).fillna("Sem base")
    else:
        agg["base"] = "Sem base"

    if "login" in work.columns:
        login_map = work.groupby("technician")["login"].first().fillna("").astype(str)
        agg["login"] = agg["technician"].map(login_map).fillna("")
    else:
        agg["login"] = ""

    agg["pts_por_os"] = np.where(
        agg["os_count"] > 0, agg["points_total"] / agg["os_count"], 0.0
    )
    agg["pts_por_contrato"] = np.where(
        agg["contracts_count"] > 0, agg["points_total"] / agg["contracts_count"], 0.0
    )
    agg["media_mensal"] = np.where(
        agg["active_months"] > 0, agg["points_total"] / agg["active_months"], 0.0
    )

    # Enriquecimento consultivo vetorizado (passagem única por login / nome normalizado)
    agg["consultivos"] = 0
    agg["produtos_cons"] = 0
    agg["conversao_pct"] = 0.0
    if consultivo_frame is not None and not consultivo_frame.empty:
        c_df = normalizar_coluna_data_consultivo(consultivo_frame)
        if (
            period_start is not None
            and period_end is not None
            and "DATA" in c_df.columns
        ):
            dt = c_df["DATA"]
            c_df = c_df.loc[dt.notna() & dt.between(period_start, period_end)]
        if not c_df.empty:
            login_to_tech: dict[str, str] = {}
            key_to_tech: dict[str, str] = {}
            for tech_v, login_v in zip(
                agg["technician"].tolist(), agg["login"].tolist(), strict=False
            ):
                tech_str = str(tech_v)
                t_key = normalize_text(tech_str)
                if t_key:
                    key_to_tech[t_key] = tech_str
                l_key = clean_code(login_v).upper()
                if l_key:
                    login_to_tech[l_key] = tech_str

            matched = pd.Series("", index=c_df.index, dtype="object")
            if login_to_tech and "LOGIN NETSALES" in c_df.columns:
                uniq_logins = c_df["LOGIN NETSALES"].dropna().astype(str).unique()
                login_norm_map = {
                    raw: login_to_tech.get(clean_code(raw).upper(), "")
                    for raw in uniq_logins
                }
                matched = (
                    c_df["LOGIN NETSALES"].astype(str).map(login_norm_map).fillna("")
                )

            for col_name in ("Técnico", "VENDEDOR"):
                if col_name not in c_df.columns:
                    continue
                missing_mask = matched.eq("")
                if not missing_mask.any():
                    break
                uniq_names = (
                    c_df.loc[missing_mask, col_name].dropna().astype(str).unique()
                )
                name_norm_map = {
                    raw: key_to_tech.get(normalize_text(raw), "") for raw in uniq_names
                }
                matched.loc[missing_mask] = (
                    c_df.loc[missing_mask, col_name]
                    .astype(str)
                    .map(name_norm_map)
                    .fillna("")
                )

            valid_c_rows = c_df.loc[matched.ne("")].copy()
            if not valid_c_rows.empty:
                valid_c_rows["_matched_tech"] = matched.loc[matched.ne("")]
                c_col = (
                    "Qtde. Cons."
                    if "Qtde. Cons." in valid_c_rows.columns
                    else (
                        "QTDE_CONSULTIVO"
                        if "QTDE_CONSULTIVO" in valid_c_rows.columns
                        else None
                    )
                )
                p_col = (
                    "Qtde. Prod."
                    if "Qtde. Prod." in valid_c_rows.columns
                    else (
                        "QTDE_PRODUTOS"
                        if "QTDE_PRODUTOS" in valid_c_rows.columns
                        else None
                    )
                )
                valid_c_rows["_q_cons"] = (
                    pd.to_numeric(valid_c_rows[c_col], errors="coerce").fillna(0)
                    if c_col
                    else 0
                )
                valid_c_rows["_q_prod"] = (
                    pd.to_numeric(valid_c_rows[p_col], errors="coerce").fillna(0)
                    if p_col
                    else 0
                )
                c_grp = valid_c_rows.groupby("_matched_tech", as_index=True).agg(
                    consultivos=("_q_cons", "sum"),
                    produtos_cons=("_q_prod", "sum"),
                )
                agg["consultivos"] = (
                    agg["technician"].map(c_grp["consultivos"]).fillna(0).astype(int)
                )
                agg["produtos_cons"] = (
                    agg["technician"].map(c_grp["produtos_cons"]).fillna(0).astype(int)
                )
                agg["conversao_pct"] = np.where(
                    agg["consultivos"] > 0,
                    agg["produtos_cons"] / agg["consultivos"] * 100.0,
                    0.0,
                )
    return agg


def calcular_comparacao_tecnicos(
    records: pd.DataFrame,
    tecnico_a: str,
    *,
    modo: ModoComparacao = "media_base",
    tecnico_b: str | None = None,
    consultivo_frame: pd.DataFrame | None = None,
    period_start: pd.Timestamp | None = None,
    period_end: pd.Timestamp | None = None,
) -> ComparacaoTecnicoResultado:
    """Compara um técnico contra outro técnico, a média da Base ou o Top Quartil (P75)."""
    agg = _metricas_individuais_frame(
        records, consultivo_frame, period_start, period_end
    )
    empty_df = pd.DataFrame()
    if agg.empty or tecnico_a not in set(agg["technician"]):
        return ComparacaoTecnicoResultado(
            tecnico_a=tecnico_a,
            referencia_label="Referência indisponível",
            modo=modo,
            base_tecnico_a="Sem base",
            tabela_metricas=empty_df,
            serie_mensal=empty_df,
            radar_normalizado=empty_df,
        )

    row_a = agg.loc[agg["technician"].eq(tecnico_a)].iloc[0]
    base_a = str(row_a["base"] or "Sem base")

    metric_specs = [
        ("Pontos Totais", "points_total", "pts"),
        ("Pontos Prod", "points_prod", "pts"),
        ("Pontos Gpon", "points_gpon", "pts"),
        ("Média Mensal (pts)", "media_mensal", "pts"),
        ("O.S. (Prod)", "os_count", "int"),
        ("Contratos Distintos", "contracts_count", "int"),
        ("Pontos / O.S.", "pts_por_os", "pts"),
        ("Pontos / Contrato", "pts_por_contrato", "pts"),
        ("Consultivos (NetSales)", "consultivos", "int"),
        ("Produtos Vendidos", "produtos_cons", "int"),
        ("Conversão Consultiva (%)", "conversao_pct", "pct"),
    ]

    ref_values: dict[str, float] = {}
    ref_label = ""
    ref_monthly = pd.Series(dtype="float64")

    if modo == "tecnico" and tecnico_b and tecnico_b in set(agg["technician"]):
        row_b = agg.loc[agg["technician"].eq(tecnico_b)].iloc[0]
        ref_label = str(tecnico_b)
        for _, col, _ in metric_specs:
            ref_values[col] = float(row_b[col])
        b_monthly = summarize(
            records[records["technician"].eq(tecnico_b)], "period"
        ).set_index("period")["points_total"]
        ref_monthly = b_monthly
    elif modo == "top_quartil":
        ref_label = "Top Quartil (P75)"
        for _, col, _ in metric_specs:
            ref_values[col] = float(agg[col].quantile(0.75))
        per_tech_m = summarize(records, ["period", "technician"])
        ref_monthly = per_tech_m.groupby("period")["points_total"].quantile(0.75)
    else:
        same_base = agg[agg["base"].eq(base_a)] if base_a != "Sem base" else agg
        if len(same_base) <= 1:
            same_base = agg
            ref_label = "Média da Equipe"
            pool_rec = records
        else:
            ref_label = f"Média Base {base_a}"
            pool_rec = (
                records[records["base"].eq(base_a)]
                if "base" in records.columns
                else records
            )
        for _, col, _ in metric_specs:
            ref_values[col] = float(same_base[col].mean())
        per_tech_m = summarize(pool_rec, ["period", "technician"])
        ref_monthly = per_tech_m.groupby("period")["points_total"].mean()

    rows_comp: list[dict[str, object]] = []
    fortes: list[str] = []
    gaps: list[str] = []
    for label, col, fmt_kind in metric_specs:
        val_a = float(row_a[col])
        val_ref = float(ref_values.get(col, 0.0))
        delta = val_a - val_ref
        delta_pct = (delta / val_ref * 100.0) if val_ref > 0 else np.nan
        rows_comp.append(
            {
                "Indicador": label,
                tecnico_a: round(val_a, 2),
                ref_label: round(val_ref, 2),
                "Delta": round(delta, 2),
                "Delta (%)": round(float(delta_pct), 1)
                if pd.notna(delta_pct)
                else np.nan,
                "_kind": fmt_kind,
            }
        )
        if col in {
            "points_total",
            "media_mensal",
            "pts_por_os",
            "contracts_count",
            "consultivos",
            "conversao_pct",
        } and pd.notna(delta_pct):
            pct_str = f"{delta_pct:+.1f}%".replace(".", ",")
            if delta_pct >= 8.0:
                fortes.append(f"**{label}** {pct_str} acima de {ref_label}")
            elif delta_pct <= -8.0:
                gaps.append(f"**{label}** {pct_str} abaixo de {ref_label}")

    tabela = pd.DataFrame(rows_comp).drop(columns=["_kind"])

    # Série mensal sobreposta
    a_monthly = summarize(
        records[records["technician"].eq(tecnico_a)], "period"
    ).set_index("period")["points_total"]
    all_periods = sorted(set(a_monthly.index).union(set(ref_monthly.index)))
    serie = pd.DataFrame(
        {
            "period": all_periods,
            "Competência": [month_label(p) for p in all_periods],
            tecnico_a: [round(float(a_monthly.get(p, 0.0)), 2) for p in all_periods],
            ref_label: [round(float(ref_monthly.get(p, 0.0)), 2) for p in all_periods],
        }
    )

    # Radar normalizado (0 a 100 pelo máximo da equipe em cada eixo)
    radar_axes = [
        ("Pontos", "points_total"),
        ("Média Mensal", "media_mensal"),
        ("O.S. (Prod)", "os_count"),
        ("Contratos", "contracts_count"),
        ("Pts / O.S.", "pts_por_os"),
        ("Consultivos", "consultivos"),
    ]
    radar_rows: list[dict[str, object]] = []
    for axis_label, col in radar_axes:
        max_col = max(float(agg[col].max()), float(ref_values.get(col, 0.0)), 1e-6)
        radar_rows.append(
            {
                "Eixo": axis_label,
                tecnico_a: round(min(float(row_a[col]) / max_col * 100.0, 100.0), 1),
                ref_label: round(
                    min(float(ref_values.get(col, 0.0)) / max_col * 100.0, 100.0), 1
                ),
            }
        )
    radar_df = pd.DataFrame(radar_rows)

    return ComparacaoTecnicoResultado(
        tecnico_a=tecnico_a,
        referencia_label=ref_label,
        modo=modo,
        base_tecnico_a=base_a,
        tabela_metricas=tabela,
        serie_mensal=serie,
        radar_normalizado=radar_df,
        pontos_fortes=fortes[:4],
        oportunidades=gaps[:4],
    )


@st.cache_data(ttl=900, max_entries=16, show_spinner=False)
def _calcular_comparacao_tecnicos_cached(
    records: pd.DataFrame,
    tecnico_a: str,
    modo: ModoComparacao,
    tecnico_b: str | None,
    consultivo_frame: pd.DataFrame | None,
    period_start: pd.Timestamp | None,
    period_end: pd.Timestamp | None,
) -> ComparacaoTecnicoResultado:
    """Memoiza a comparação 1:1 para não re-agrupar a base a cada interação do fragmento."""
    return calcular_comparacao_tecnicos(
        records,
        tecnico_a,
        modo=modo,
        tecnico_b=tecnico_b,
        consultivo_frame=consultivo_frame,
        period_start=period_start,
        period_end=period_end,
    )


@st.fragment
def render_comparacao_lado_a_lado(
    filtered: pd.DataFrame,
    tecnico_a: str,
    all_names: list[str],
    *,
    consultivo_frame: pd.DataFrame | None = None,
    period_start: pd.Timestamp | None = None,
    period_end: pd.Timestamp | None = None,
) -> None:
    """Renderiza painel interativo de comparação 1:1 (Técnico × Técnico/Base/P75)."""
    render_section_header(
        "Comparação Lado a Lado · Pauta para Feedback 1:1",
        f"Compare {tecnico_a} diretamente contra outro técnico, a média da Base ou o Top Quartil (P75).",
    )
    outros = [n for n in all_names if n != tecnico_a]
    c_modo, c_alvo = st.columns([1.3, 1.4])
    with c_modo:
        modo_label = st.radio(
            "Referência de comparação",
            options=[
                "Média da Base",
                "Top Quartil (P75)",
                "Outro Técnico",
            ],
            horizontal=True,
            key="tech_comp_modo_radio",
        )
    modo_map: dict[str, ModoComparacao] = {
        "Média da Base": "media_base",
        "Top Quartil (P75)": "top_quartil",
        "Outro Técnico": "tecnico",
    }
    modo: ModoComparacao = modo_map[modo_label]
    tecnico_b: str | None = None
    with c_alvo:
        if modo == "tecnico":
            if outros:
                tecnico_b = st.selectbox(
                    "Selecionar 2º técnico",
                    options=outros,
                    key="tech_comp_segundo_tecnico",
                )
            else:
                st.info("Há apenas 1 técnico no recorte atual.")
                modo = "media_base"
        else:
            st.caption(
                "Comparando automaticamente contra o benchmark selecionado no mesmo período."
            )

    res = _calcular_comparacao_tecnicos_cached(
        filtered,
        tecnico_a,
        modo=modo,
        tecnico_b=tecnico_b,
        consultivo_frame=consultivo_frame,
        period_start=period_start,
        period_end=period_end,
    )
    if res.tabela_metricas.empty:
        st.info("Sem dados suficientes para comparação no recorte atual.")
        return

    # Cards de destaque rápido
    tbl_rows = {
        str(row["Indicador"]): row
        for row in res.tabela_metricas.to_dict(orient="records")
    }
    k1, k2, k3, k4 = st.columns(4)
    kpi_specs: tuple[tuple[object, str, str, TemaKPIType], ...] = (
        (k1, "Pontos Totais", "Σ", "azul"),
        (k2, "O.S. (Prod)", "📋", "verde"),
        (k3, "Pontos / O.S.", "⚡", "roxo"),
        (k4, "Consultivos (NetSales)", "🎯", "laranja"),
    )
    for col_box, ind, icon, var_cor in kpi_specs:
        row_ind = tbl_rows.get(ind, {})
        val_a = float(row_ind.get(res.tecnico_a, 0.0) or 0.0)
        val_r = float(row_ind.get(res.referencia_label, 0.0) or 0.0)
        dpct = row_ind.get("Delta (%)")
        dpct_txt = (
            f"{float(dpct):+.1f}%".replace(".", ",")
            if dpct is not None and pd.notna(dpct)
            else "—"
        )
        val_fmt = (
            formatar_numero_br(int(round(val_a)))
            if ind in {"O.S. (Prod)", "Consultivos (NetSales)"}
            else format_points(val_a)
        )
        ref_fmt = (
            formatar_numero_br(int(round(val_r)))
            if ind in {"O.S. (Prod)", "Consultivos (NetSales)"}
            else format_points(val_r)
        )
        render_kpi(
            col_box,
            ind.upper(),
            val_fmt,
            f"vs {res.referencia_label}: {ref_fmt} ({dpct_txt})",
            tema=var_cor,
            icone=icon,
        )

    # Gráficos lado a lado: Evolução mensal sobreposta + Radar normalizado
    g1, g2 = st.columns([1.35, 1.0], gap="medium")
    with g1:
        fig_line = go.Figure()
        fig_line.add_bar(
            x=res.serie_mensal["Competência"],
            y=res.serie_mensal[res.tecnico_a],
            name=res.tecnico_a,
            marker_color=Cores.PRIMARIA,
        )
        fig_line.add_scatter(
            x=res.serie_mensal["Competência"],
            y=res.serie_mensal[res.referencia_label],
            name=res.referencia_label,
            mode="lines+markers",
            line=dict(color=Cores.SECUNDARIA, width=2.8),
            marker=dict(size=7),
        )
        fig_line.update_layout(
            title=dict(
                text=f"Evolução Mensal · {res.tecnico_a} × {res.referencia_label}",
                font=dict(size=14, color=Cores.PRIMARIA),
            ),
            height=330,
            margin=dict(l=18, r=18, t=44, b=28),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family=Fontes.TEXTO, color=Cores.TEXTO),
            legend=dict(
                orientation="h", yanchor="bottom", y=-0.22, x=0.5, xanchor="center"
            ),
            yaxis=dict(gridcolor=Cores.BORDA),
        )
        st.plotly_chart(fig_line, width="stretch")

    with g2:
        eixos = res.radar_normalizado["Eixo"].tolist()
        vals_a = res.radar_normalizado[res.tecnico_a].tolist()
        vals_r = res.radar_normalizado[res.referencia_label].tolist()
        fig_rad = go.Figure()
        fig_rad.add_trace(
            go.Scatterpolar(
                r=vals_a + vals_a[:1],
                theta=eixos + eixos[:1],
                fill="toself",
                name=res.tecnico_a,
                line_color=Cores.PRIMARIA,
                fillcolor="rgba(1, 40, 105, 0.22)",
            )
        )
        fig_rad.add_trace(
            go.Scatterpolar(
                r=vals_r + vals_r[:1],
                theta=eixos + eixos[:1],
                fill="toself",
                name=res.referencia_label,
                line_color=Cores.SECUNDARIA,
                fillcolor="rgba(243, 124, 4, 0.16)",
            )
        )
        fig_rad.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            margin=dict(l=30, r=30, t=42, b=24),
            height=330,
            title=dict(
                text="Perfil Relativo (0–100)",
                font=dict(size=14, color=Cores.PRIMARIA),
            ),
            font=dict(family=Fontes.TEXTO, color=Cores.TEXTO),
            legend=dict(
                orientation="h", yanchor="bottom", y=-0.16, x=0.5, xanchor="center"
            ),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_rad, width="stretch")

    # Pauta automática de 1:1 (Pontos fortes & Oportunidades)
    p1, p2 = st.columns(2, gap="medium")
    with p1:
        with st.container(border=True):
            st.markdown("**Pontos fortes para reconhecer no 1:1**")
            if res.pontos_fortes:
                for item in res.pontos_fortes:
                    st.markdown(f"- {item}")
            else:
                st.caption("Desempenho em linha com a referência em todos os pilares.")
    with p2:
        with st.container(border=True):
            st.markdown("**Gaps prioritários para plano de desenvolvimento**")
            if res.oportunidades:
                for item in res.oportunidades:
                    st.markdown(f"- {item}")
            else:
                st.caption(
                    "Nenhum gap relevante (>8% abaixo da referência) neste recorte."
                )

    st.dataframe(
        res.tabela_metricas,
        width="stretch",
        hide_index=True,
        column_config={
            res.tecnico_a: st.column_config.NumberColumn(format="%.2f"),
            res.referencia_label: st.column_config.NumberColumn(format="%.2f"),
            "Delta": st.column_config.NumberColumn(format="%+.2f"),
            "Delta (%)": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )
