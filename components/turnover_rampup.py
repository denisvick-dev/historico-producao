"""Turnover, Capacidade Produtiva Perdida e Curva de Ramp-up de Técnicos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    converter_data_br,
    formatar_numero_br,
    render_drilldown_tecnico,
    render_insight,
    render_kpi_card,
    render_section_header,
    render_ticker,
)
from components.consultivo import sanitizar_csv_exportacao
from production import format_points, month_label, normalize_text, summarize

CHART_CONFIG = {"displayModeBar": False, "responsive": True}


@dataclass(frozen=True)
class ResumoTurnover:
    """Indicadores de desligamentos, motivos e perda de capacidade produtiva."""

    total_ativos: int
    total_desligados: int
    taxa_turnover_pct: float
    capacidade_perdida_mensal: float
    motivo_principal: str
    evolucao_mensal: pd.DataFrame
    por_motivo: pd.DataFrame
    por_base: pd.DataFrame
    detalhado: pd.DataFrame


@dataclass(frozen=True)
class ResumoRampup:
    """Curva de maturação de novos técnicos por mês de casa vs. meta de 300 pts."""

    meta_pontos: float
    curva_maturacao: pd.DataFrame
    tecnicos_em_rampup: pd.DataFrame
    media_mes_1: float
    media_mes_3: float
    media_maduros: float
    pct_atinge_meta_mes_3: float


def _parse_data_desligamento(serie: pd.Series) -> pd.Series:
    parsed = converter_data_br(serie)
    missing = parsed.isna() & serie.notna()
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(
            serie.loc[missing], errors="coerce", format="mixed"
        )
    return parsed


def calcular_turnover(
    roster_frame: pd.DataFrame | None,
    production_frame: pd.DataFrame | None = None,
) -> ResumoTurnover:
    """Calcula taxa de turnover, motivos de desligamento e capacidade produtiva perdida."""
    cols_ev = ["period", "Competência", "Desligamentos", "Capacidade Perdida (pts/mês)"]
    cols_mot = [
        "Motivo",
        "Desligamentos",
        "Participação (%)",
        "Capacidade Perdida (pts/mês)",
    ]
    cols_base = [
        "Base",
        "Ativos",
        "Desligados",
        "Taxa Turnover (%)",
        "Capacidade Perdida (pts/mês)",
    ]
    cols_det = [
        "Técnico",
        "RE",
        "Monitor",
        "Base",
        "U.N.",
        "Data Desligamento",
        "Motivo",
        "Meses Ativos Hist.",
        "Média Mensal Hist. (pts)",
        "Pontos Totais Hist.",
    ]

    if roster_frame is None or roster_frame.empty:
        return ResumoTurnover(
            total_ativos=0,
            total_desligados=0,
            taxa_turnover_pct=0.0,
            capacidade_perdida_mensal=0.0,
            motivo_principal="—",
            evolucao_mensal=pd.DataFrame(columns=cols_ev),
            por_motivo=pd.DataFrame(columns=cols_mot),
            por_base=pd.DataFrame(columns=cols_base),
            detalhado=pd.DataFrame(columns=cols_det),
        )

    roster = roster_frame.copy()
    status_s = (
        roster.get("status", pd.Series("", index=roster.index)).astype(str).str.upper()
    )
    ativos_df = roster[status_s.eq("ATIVO")]
    deslig_df = roster[status_s.eq("DESLIGADO")].copy()

    total_ativos = int(len(ativos_df))
    total_desligados = int(len(deslig_df))
    base_total = total_ativos + total_desligados
    taxa_turnover = (total_desligados / base_total * 100.0) if base_total > 0 else 0.0

    # Histórico de produção por técnico (para estimar capacidade produtiva perdida)
    hist_map: dict[str, tuple[int, float, float]] = {}
    if (
        production_frame is not None
        and not production_frame.empty
        and "technician" in production_frame.columns
    ):
        p = production_frame.copy()
        col_dt = "period" if "period" in p.columns else "reference_date"
        if col_dt in p.columns:
            p["period"] = (
                p[col_dt].dt.to_period("M").dt.to_timestamp()
                if pd.api.types.is_datetime64_any_dtype(p[col_dt])
                else pd.to_datetime(p[col_dt], errors="coerce")
                .dt.to_period("M")
                .dt.to_timestamp()
            )
            mensal_p = summarize(p.dropna(subset=["period"]), ["technician", "period"])
            if not mensal_p.empty:
                mensal_p["tech_key"] = (
                    mensal_p["technician"].astype(str).map(normalize_text)
                )
                res_hist = cast(Any, mensal_p.groupby("tech_key", as_index=False)).agg(
                    meses=("period", "nunique"),
                    media=("points_total", "mean"),
                    total=("points_total", "sum"),
                )
                for row in res_hist.itertuples(index=False):
                    hist_map[str(row.tech_key)] = (
                        int(row.meses),
                        float(row.media),
                        float(row.total),
                    )

    if deslig_df.empty:
        base_ativos = (
            cast(Any, ativos_df.groupby("base", as_index=False))
            .agg(Ativos=("technician_key", "nunique"))
            .rename(columns={"base": "Base"})
            if not ativos_df.empty and "base" in ativos_df.columns
            else pd.DataFrame(columns=["Base", "Ativos"])
        )
        if not base_ativos.empty:
            base_ativos["Desligados"] = 0
            base_ativos["Taxa Turnover (%)"] = 0.0
            base_ativos["Capacidade Perdida (pts/mês)"] = 0.0
            base_ativos = base_ativos[cols_base]
        else:
            base_ativos = pd.DataFrame(columns=cols_base)
        return ResumoTurnover(
            total_ativos=total_ativos,
            total_desligados=0,
            taxa_turnover_pct=0.0,
            capacidade_perdida_mensal=0.0,
            motivo_principal="Sem desligamentos",
            evolucao_mensal=pd.DataFrame(columns=cols_ev),
            por_motivo=pd.DataFrame(columns=cols_mot),
            por_base=base_ativos,
            detalhado=pd.DataFrame(columns=cols_det),
        )

    deslig_df["_key"] = (
        deslig_df["technician_key"].astype(str).map(normalize_text)
        if "technician_key" in deslig_df.columns
        else deslig_df["technician"].astype(str).map(normalize_text)
    )
    deslig_df["_dt_term"] = _parse_data_desligamento(
        deslig_df.get("termination_date", pd.Series("", index=deslig_df.index))
    )
    deslig_df["_motivo"] = (
        deslig_df.get("termination_reason", pd.Series("", index=deslig_df.index))
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", "Não informado")
    )
    deslig_df["_meses_hist"] = [
        hist_map.get(k, (0, 0.0, 0.0))[0] for k in deslig_df["_key"]
    ]
    deslig_df["_media_hist"] = [
        hist_map.get(k, (0, 0.0, 0.0))[1] for k in deslig_df["_key"]
    ]
    deslig_df["_total_hist"] = [
        hist_map.get(k, (0, 0.0, 0.0))[2] for k in deslig_df["_key"]
    ]

    capacidade_perdida = float(deslig_df["_media_hist"].sum())

    # Evolução mensal de desligamentos
    com_data = deslig_df.dropna(subset=["_dt_term"]).copy()
    if not com_data.empty:
        com_data["period"] = com_data["_dt_term"].dt.to_period("M").dt.to_timestamp()
        evol = (
            cast(Any, com_data.groupby("period", as_index=False))
            .agg(
                **{
                    "Desligamentos": ("_key", "size"),
                    "Capacidade Perdida (pts/mês)": ("_media_hist", "sum"),
                }
            )
            .sort_values("period")
            .reset_index(drop=True)
        )
        evol["Competência"] = evol["period"].map(month_label)
        evol = evol[cols_ev]
    else:
        evol = pd.DataFrame(columns=cols_ev)

    # Pareto por motivo
    por_mot = (
        cast(Any, deslig_df.groupby("_motivo", as_index=False))
        .agg(
            **{
                "Desligamentos": ("_key", "size"),
                "Capacidade Perdida (pts/mês)": ("_media_hist", "sum"),
            }
        )
        .rename(columns={"_motivo": "Motivo"})
        .sort_values(
            ["Desligamentos", "Capacidade Perdida (pts/mês)"], ascending=[False, False]
        )
        .reset_index(drop=True)
    )
    por_mot["Participação (%)"] = (
        por_mot["Desligamentos"] / max(total_desligados, 1) * 100.0
    )
    por_mot = por_mot[cols_mot]
    motivo_principal = str(por_mot.iloc[0]["Motivo"]) if not por_mot.empty else "—"

    # Turnover por Base
    at_base = (
        cast(Any, ativos_df.groupby("base", as_index=False))
        .agg(Ativos=("technician_key", "nunique"))
        .rename(columns={"base": "Base"})
        if not ativos_df.empty and "base" in ativos_df.columns
        else pd.DataFrame(columns=["Base", "Ativos"])
    )
    des_base = (
        cast(Any, deslig_df.groupby("base", as_index=False))
        .agg(
            **{
                "Desligados": ("_key", "size"),
                "Capacidade Perdida (pts/mês)": ("_media_hist", "sum"),
            }
        )
        .rename(columns={"base": "Base"})
    )
    por_base = at_base.merge(des_base, on="Base", how="outer")
    por_base["Ativos"] = (
        pd.to_numeric(por_base["Ativos"], errors="coerce").fillna(0).astype(int)
    )
    por_base["Desligados"] = (
        pd.to_numeric(por_base["Desligados"], errors="coerce").fillna(0).astype(int)
    )
    por_base["Capacidade Perdida (pts/mês)"] = pd.to_numeric(
        por_base["Capacidade Perdida (pts/mês)"], errors="coerce"
    ).fillna(0.0)
    denom_b = por_base["Ativos"] + por_base["Desligados"]
    por_base["Taxa Turnover (%)"] = np.where(
        denom_b > 0, por_base["Desligados"] / denom_b * 100.0, 0.0
    )
    por_base = (
        por_base[cols_base]
        .sort_values(["Taxa Turnover (%)", "Desligados"], ascending=[False, False])
        .reset_index(drop=True)
    )

    col_nome_desl = (
        "technician"
        if "technician" in deslig_df.columns
        else (
            "technician_name"
            if "technician_name" in deslig_df.columns
            else "technician_key"
        )
    )
    detalhado = (
        pd.DataFrame(
            {
                "Técnico": deslig_df[col_nome_desl].astype(str),
                "RE": deslig_df.get("re_code", pd.Series("", index=deslig_df.index))
                .fillna("")
                .astype(str),
                "Monitor": deslig_df.get(
                    "monitor", pd.Series("Sem monitor", index=deslig_df.index)
                )
                .fillna("Sem monitor")
                .astype(str),
                "Base": deslig_df.get(
                    "base", pd.Series("Sem base", index=deslig_df.index)
                )
                .fillna("Sem base")
                .astype(str),
                "U.N.": deslig_df.get(
                    "un", pd.Series("Sem U.N.", index=deslig_df.index)
                )
                .fillna("Sem U.N.")
                .astype(str),
                "Data Desligamento": deslig_df["_dt_term"]
                .dt.strftime("%d/%m/%Y")
                .fillna("Não informada"),
                "Motivo": deslig_df["_motivo"],
                "Meses Ativos Hist.": deslig_df["_meses_hist"].astype(int),
                "Média Mensal Hist. (pts)": deslig_df["_media_hist"].round(2),
                "Pontos Totais Hist.": deslig_df["_total_hist"].round(2),
            }
        )
        .sort_values(["Média Mensal Hist. (pts)", "Técnico"], ascending=[False, True])
        .reset_index(drop=True)
    )

    return ResumoTurnover(
        total_ativos=total_ativos,
        total_desligados=total_desligados,
        taxa_turnover_pct=taxa_turnover,
        capacidade_perdida_mensal=capacidade_perdida,
        motivo_principal=motivo_principal,
        evolucao_mensal=evol,
        por_motivo=por_mot,
        por_base=por_base,
        detalhado=detalhado,
    )


def calcular_curva_rampup(
    production_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None = None,
    *,
    meta_pontos: float = 300.0,
) -> ResumoRampup:
    """Calcula a curva de ramp-up por mês de casa (Mês 1..6+) vs. meta operacional."""
    cols_curva = [
        "Estágio",
        "Observações",
        "Média Pontos",
        "Mediana Pontos",
        "% Atinge Meta",
    ]
    cols_recentes = [
        "Técnico",
        "Monitor",
        "Base",
        "Primeiro Mês",
        "Meses de Casa",
        "Pontos Último Mês",
        "Média Ramp-up",
        "Status vs Meta",
    ]
    vazio = ResumoRampup(
        meta_pontos=meta_pontos,
        curva_maturacao=pd.DataFrame(columns=cols_curva),
        tecnicos_em_rampup=pd.DataFrame(columns=cols_recentes),
        media_mes_1=0.0,
        media_mes_3=0.0,
        media_maduros=0.0,
        pct_atinge_meta_mes_3=0.0,
    )
    if production_frame.empty or "technician" not in production_frame.columns:
        return vazio

    work = production_frame.copy()
    col_dt = "period" if "period" in work.columns else "reference_date"
    if col_dt not in work.columns:
        return vazio

    work["period"] = (
        work[col_dt].dt.to_period("M").dt.to_timestamp()
        if pd.api.types.is_datetime64_any_dtype(work[col_dt])
        else pd.to_datetime(work[col_dt], errors="coerce")
        .dt.to_period("M")
        .dt.to_timestamp()
    )
    work = work.dropna(subset=["period"])
    if work.empty:
        return vazio

    mensal = summarize(work, ["technician", "period"]).sort_values(
        ["technician", "period"]
    )
    if mensal.empty:
        return vazio

    # Mês de entrada (primeiro mês com produção de cada técnico)
    primeiro = mensal.groupby("technician")["period"].transform("min")
    mes_casa = (
        (mensal["period"].dt.year - primeiro.dt.year) * 12
        + (mensal["period"].dt.month - primeiro.dt.month)
        + 1
    ).astype(int)
    mensal["mes_casa"] = mes_casa
    mensal["estagio_ord"] = np.minimum(mes_casa, 6)
    mensal["Estágio"] = np.where(
        mes_casa >= 6,
        "Mês 6+ (Maduro)",
        "Mês " + mes_casa.astype(str),
    )
    mensal["_bateu_meta"] = (mensal["points_total"] >= meta_pontos).astype(
        float
    ) * 100.0

    curva = (
        cast(Any, mensal.groupby(["estagio_ord", "Estágio"], as_index=False))
        .agg(
            **{
                "Observações": ("technician", "size"),
                "Média Pontos": ("points_total", "mean"),
                "Mediana Pontos": ("points_total", "median"),
                "% Atinge Meta": ("_bateu_meta", "mean"),
            }
        )
        .sort_values("estagio_ord")
        .reset_index(drop=True)
    )

    def _val_estagio(ord_val: int, col: str) -> float:
        sub = curva[curva["estagio_ord"].eq(ord_val)]
        return float(sub.iloc[0][col]) if not sub.empty else 0.0

    media_m1 = _val_estagio(1, "Média Pontos")
    media_m3 = _val_estagio(3, "Média Pontos")
    media_mad = _val_estagio(6, "Média Pontos")
    pct_m3 = _val_estagio(3, "% Atinge Meta")

    # Técnicos atualmente em ramp-up (iniciaram nos últimos 3 meses em relação à última competência da base)
    ultima_global = mensal["period"].max()
    corte_ramp = ultima_global - pd.DateOffset(months=3)
    meta_por_tec: dict[str, tuple[str, str]] = {}
    if "monitor" in work.columns and "base" in work.columns:
        for row in work.drop_duplicates("technician").itertuples(index=False):
            meta_por_tec[str(row.technician)] = (
                str(getattr(row, "monitor", "Sem monitor") or "Sem monitor"),
                str(getattr(row, "base", "Sem base") or "Sem base"),
            )
    if roster_frame is not None and not roster_frame.empty:
        for row in roster_frame.itertuples(index=False):
            meta_por_tec[str(getattr(row, "technician", ""))] = (
                str(getattr(row, "monitor", "Sem monitor") or "Sem monitor"),
                str(getattr(row, "base", "Sem base") or "Sem base"),
            )

    resumo_tec = cast(Any, mensal.groupby("technician", as_index=False)).agg(
        primeiro_mes=("period", "min"),
        ultimo_mes=("period", "max"),
        meses_casa=("mes_casa", "max"),
        media_ramp=("points_total", "mean"),
    )
    ultimos_pts = (
        mensal.sort_values("period")
        .drop_duplicates("technician", keep="last")
        .set_index("technician")["points_total"]
    )
    em_ramp = resumo_tec[resumo_tec["primeiro_mes"] > corte_ramp].copy()
    if em_ramp.empty:
        # Fallback: mostra os técnicos com menos meses de casa (<= 4) se base toda for antiga
        em_ramp = resumo_tec[resumo_tec["meses_casa"] <= 4].copy()

    if not em_ramp.empty:
        em_ramp["Pontos Último Mês"] = (
            em_ramp["technician"].map(ultimos_pts).fillna(0.0).round(2)
        )
        em_ramp["Monitor"] = [
            meta_por_tec.get(str(t), ("Sem monitor", "Sem base"))[0]
            for t in em_ramp["technician"]
        ]
        em_ramp["Base"] = [
            meta_por_tec.get(str(t), ("Sem monitor", "Sem base"))[1]
            for t in em_ramp["technician"]
        ]
        em_ramp["Primeiro Mês"] = em_ramp["primeiro_mes"].map(month_label)
        em_ramp["Status vs Meta"] = np.where(
            em_ramp["Pontos Último Mês"] >= meta_pontos,
            "Na meta",
            "Em maturação",
        )
        em_ramp = (
            em_ramp.rename(
                columns={
                    "technician": "Técnico",
                    "meses_casa": "Meses de Casa",
                    "media_ramp": "Média Ramp-up",
                }
            )[cols_recentes]
            .sort_values(
                ["Meses de Casa", "Pontos Último Mês"], ascending=[True, False]
            )
            .reset_index(drop=True)
        )
    else:
        em_ramp = pd.DataFrame(columns=cols_recentes)

    return ResumoRampup(
        meta_pontos=meta_pontos,
        curva_maturacao=curva[cols_curva],
        tecnicos_em_rampup=em_ramp,
        media_mes_1=media_m1,
        media_mes_3=media_m3,
        media_maduros=media_mad,
        pct_atinge_meta_mes_3=pct_m3,
    )


def _layout_tr(fig: go.Figure, altura: int = 360) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=10, r=18, t=26, b=14),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=Cores.TEXTO_3, size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white", font_color=Cores.TEXTO),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor=Cores.BORDA, zeroline=False)
    return fig


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _calcular_turnover_cached(
    roster_frame: pd.DataFrame | None,
    production_frame: pd.DataFrame | None = None,
) -> ResumoTurnover:
    return calcular_turnover(roster_frame, production_frame)


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _calcular_rampup_cached(
    production_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None = None,
    *,
    meta_pontos: float = 300.0,
) -> ResumoRampup:
    return calcular_curva_rampup(
        production_frame, roster_frame, meta_pontos=meta_pontos
    )


def render_turnover_rampup(
    production_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None = None,
) -> None:
    """Renderiza o módulo de Turnover, Capacidade Perdida e Curva de Ramp-up."""

    @st.fragment
    def _render_tr_body() -> None:
        visao = (
            st.segmented_control(
                "Submódulo de Turnover e Ramp-up",
                options=["📉 Turnover & Capacidade Perdida", "🚀 Curva de Ramp-up"],
                default="📉 Turnover & Capacidade Perdida",
                label_visibility="collapsed",
                key="tr_submodulo",
            )
            or "📉 Turnover & Capacidade Perdida"
        )

        if visao == "📉 Turnover & Capacidade Perdida":
            turn = _calcular_turnover_cached(roster_frame, production_frame)
            if turn.total_ativos == 0 and turn.total_desligados == 0:
                render_insight(
                    "Sem registros cadastrais (lista_ativos / desligados) para apurar Turnover.",
                    tipo="info",
                )
                return

            render_ticker(
                [
                    ("Ativos", formatar_numero_br(turn.total_ativos)),
                    ("Desligados", formatar_numero_br(turn.total_desligados)),
                    (
                        "Taxa Turnover",
                        f"{turn.taxa_turnover_pct:.1f}%".replace(".", ","),
                    ),
                    (
                        "Capacidade Perdida",
                        f"{format_points(turn.capacidade_perdida_mensal)} pts/mês",
                    ),
                    ("Principal Motivo", turn.motivo_principal),
                ],
                label="Turnover & Impacto Operacional",
            )

            k = st.columns(4)
            with k[0]:
                render_kpi_card(
                    "TAXA DE TURNOVER",
                    f"{turn.taxa_turnover_pct:.1f}%".replace(".", ","),
                    f"{turn.total_desligados} desligado(s) sobre {turn.total_ativos + turn.total_desligados} cadastrados",
                    "📉",
                    "kpi-card--vermelho"
                    if turn.taxa_turnover_pct >= 15
                    else "kpi-card--azul",
                )
            with k[1]:
                render_kpi_card(
                    "CAPACIDADE PERDIDA / MÊS",
                    f"{format_points(turn.capacidade_perdida_mensal)} pts",
                    "Soma da média mensal histórica dos desligados",
                    "⚡",
                    "kpi-card--laranja",
                )
            with k[2]:
                render_kpi_card(
                    "COLABORADORES DESLIGADOS",
                    formatar_numero_br(turn.total_desligados),
                    f"Base ativa atual: {formatar_numero_br(turn.total_ativos)}",
                    "👥",
                    "kpi-card--roxo",
                )
            with k[3]:
                render_kpi_card(
                    "PRINCIPAL MOTIVO",
                    turn.motivo_principal[:24],
                    "Motivo com maior incidência na aba desligados",
                    "📌",
                    "kpi-card--verde",
                )

            c1, c2 = st.columns(2)
            with c1, st.container(border=True):
                render_section_header(
                    "Pareto de Motivos de Desligamento",
                    subtitulo="Volume de desligamentos por motivo cadastrado",
                    icone="📊",
                )
                if not turn.por_motivo.empty:
                    m_plot = turn.por_motivo.sort_values(
                        "Desligamentos", ascending=True
                    )
                    fig_m = go.Figure(
                        go.Bar(
                            y=m_plot["Motivo"],
                            x=m_plot["Desligamentos"],
                            orientation="h",
                            marker_color=Cores.SECUNDARIA,
                            text=[
                                f"{int(d)} ({p:.1f}%)"
                                for d, p in zip(
                                    m_plot["Desligamentos"],
                                    m_plot["Participação (%)"],
                                    strict=False,
                                )
                            ],
                            textposition="outside",
                        )
                    )
                    max_m = (
                        int(m_plot["Desligamentos"].max()) if not m_plot.empty else 1
                    )
                    fig_m.update_xaxes(range=[0, max_m * 1.35])
                    st.plotly_chart(
                        _layout_tr(fig_m, altura=330),
                        width="stretch",
                        config=CHART_CONFIG,
                        key="tr_chart_motivos",
                    )
                else:
                    render_insight("Sem desligamentos registrados.", tipo="info")

            with c2, st.container(border=True):
                render_section_header(
                    "Taxa de Turnover por Base (%)",
                    subtitulo="Comparativo de rotatividade entre bases operacionais",
                    icone="🏢",
                )
                if not turn.por_base.empty:
                    b_plot = turn.por_base.sort_values(
                        "Taxa Turnover (%)", ascending=True
                    )
                    fig_b = go.Figure(
                        go.Bar(
                            y=b_plot["Base"],
                            x=b_plot["Taxa Turnover (%)"],
                            orientation="h",
                            marker_color=Cores.PRIMARIA,
                            text=[f"{v:.1f}%" for v in b_plot["Taxa Turnover (%)"]],
                            textposition="outside",
                        )
                    )
                    max_b = (
                        float(b_plot["Taxa Turnover (%)"].max())
                        if not b_plot.empty
                        else 1.0
                    )
                    fig_b.update_xaxes(range=[0, max(max_b * 1.3, 10.0)])
                    st.plotly_chart(
                        _layout_tr(fig_b, altura=330),
                        width="stretch",
                        config=CHART_CONFIG,
                        key="tr_chart_base",
                    )

            if not turn.evolucao_mensal.empty:
                with st.container(border=True):
                    render_section_header(
                        "Linha do Tempo de Desligamentos & Capacidade Perdida",
                        subtitulo="Evolução mensal pela data de desligamento registrada",
                        icone="📅",
                    )
                    fig_ev = go.Figure()
                    fig_ev.add_bar(
                        x=turn.evolucao_mensal["Competência"],
                        y=turn.evolucao_mensal["Desligamentos"],
                        name="Desligamentos",
                        marker_color="#DC2626",
                        yaxis="y1",
                    )
                    fig_ev.add_scatter(
                        x=turn.evolucao_mensal["Competência"],
                        y=turn.evolucao_mensal["Capacidade Perdida (pts/mês)"],
                        name="Capacidade Perdida (pts/mês)",
                        mode="lines+markers",
                        line=dict(color=Cores.PRIMARIA, width=2.5),
                        yaxis="y2",
                    )
                    fig_ev.update_layout(
                        yaxis=dict(title="Desligamentos", gridcolor=Cores.BORDA),
                        yaxis2=dict(
                            title="Capacidade Perdida (pts/mês)",
                            overlaying="y",
                            side="right",
                            showgrid=False,
                        ),
                    )
                    st.plotly_chart(
                        _layout_tr(fig_ev, altura=320),
                        width="stretch",
                        config=CHART_CONFIG,
                        key="tr_chart_evol",
                    )

            if not turn.detalhado.empty:
                render_section_header(
                    "Detalhamento de Colaboradores Desligados",
                    subtitulo="Impacto histórico individual na capacidade operacional",
                    icone="📋",
                )
                st.dataframe(
                    turn.detalhado,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Média Mensal Hist. (pts)": st.column_config.NumberColumn(
                            format="%.2f"
                        ),
                        "Pontos Totais Hist.": st.column_config.NumberColumn(
                            format="%.2f"
                        ),
                    },
                )
                if "Técnico" in turn.detalhado.columns:
                    render_drilldown_tecnico(
                        turn.detalhado["Técnico"].tolist(),
                        key_prefix="tr_turn",
                    )
                st.download_button(
                    "Baixar relatório de Turnover em CSV",
                    data=sanitizar_csv_exportacao(turn.detalhado),
                    file_name="totale_turnover_capacidade_perdida.csv",
                    mime="text/csv",
                    key="tr_download_turnover_csv",
                )

        else:
            meta_pts = float(
                st.slider(
                    "Meta de maturação operacional (pontos/mês)",
                    min_value=200,
                    max_value=450,
                    value=300,
                    step=25,
                    key="tr_meta_rampup",
                )
            )
            ramp = _calcular_rampup_cached(
                production_frame, roster_frame, meta_pontos=meta_pts
            )
            if ramp.curva_maturacao.empty:
                render_insight(
                    "Sem histórico de produção suficiente para montar a Curva de Ramp-up.",
                    tipo="info",
                )
                return

            k = st.columns(4)
            with k[0]:
                render_kpi_card(
                    "MÉDIA NO MÊS 1",
                    f"{format_points(ramp.media_mes_1)} pts",
                    "Primeira competência com produção do técnico",
                    "🌱",
                    "kpi-card--laranja",
                )
            with k[1]:
                render_kpi_card(
                    "MÉDIA NO MÊS 3",
                    f"{format_points(ramp.media_mes_3)} pts",
                    f"{ramp.pct_atinge_meta_mes_3:.1f}% atingem a meta de {int(meta_pts)} pts".replace(
                        ".", ","
                    ),
                    "🚀",
                    "kpi-card--azul",
                )
            with k[2]:
                render_kpi_card(
                    "MÉDIA MADUROS (MÊS 6+)",
                    f"{format_points(ramp.media_maduros)} pts",
                    "Patamar consolidado da operação madura",
                    "🏆",
                    "kpi-card--verde",
                )
            with k[3]:
                render_kpi_card(
                    "TÉCNICOS EM RAMP-UP",
                    formatar_numero_br(len(ramp.tecnicos_em_rampup)),
                    "Colaboradores em janela inicial de maturação",
                    "👷",
                    "kpi-card--roxo",
                )

            with st.container(border=True):
                render_section_header(
                    "Curva de Maturação Operacional (Mês 1 a Mês 6+)",
                    subtitulo=f"Evolução da média e mediana de pontos por mês de casa frente à meta de {int(meta_pts)} pontos",
                    icone="📈",
                )
                fig_r = go.Figure()
                fig_r.add_bar(
                    x=ramp.curva_maturacao["Estágio"],
                    y=ramp.curva_maturacao["Média Pontos"],
                    name="Média de Pontos",
                    marker_color=Cores.PRIMARIA,
                    text=[
                        format_points(v) for v in ramp.curva_maturacao["Média Pontos"]
                    ],
                    textposition="outside",
                )
                fig_r.add_scatter(
                    x=ramp.curva_maturacao["Estágio"],
                    y=ramp.curva_maturacao["Mediana Pontos"],
                    name="Mediana",
                    mode="lines+markers",
                    line=dict(color=Cores.SECUNDARIA, width=2.5),
                )
                fig_r.add_hline(
                    y=meta_pts,
                    line_dash="dot",
                    line_color="#047857",
                    annotation_text=f"Meta {int(meta_pts)} pts",
                    annotation_position="top right",
                )
                max_y = max(float(ramp.curva_maturacao["Média Pontos"].max()), meta_pts)
                fig_r.update_yaxes(range=[0, max_y * 1.25], title="Pontos / Mês")
                st.plotly_chart(
                    _layout_tr(fig_r, altura=370),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="tr_chart_rampup",
                )

            if not ramp.tecnicos_em_rampup.empty:
                render_section_header(
                    "Acompanhamento de Técnicos em Ramp-up",
                    subtitulo="Colaboradores recentes com comparativo direto contra a meta operacional",
                    icone="👷",
                )
                st.dataframe(
                    ramp.tecnicos_em_rampup,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Pontos Último Mês": st.column_config.NumberColumn(
                            format="%.2f"
                        ),
                        "Média Ramp-up": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
                if "Técnico" in ramp.tecnicos_em_rampup.columns:
                    render_drilldown_tecnico(
                        ramp.tecnicos_em_rampup["Técnico"].tolist(),
                        key_prefix="tr_ramp",
                    )
                st.download_button(
                    "Baixar acompanhamento de Ramp-up em CSV",
                    data=sanitizar_csv_exportacao(ramp.tecnicos_em_rampup),
                    file_name="totale_curva_rampup.csv",
                    mime="text/csv",
                    key="tr_download_rampup_csv",
                )

    _render_tr_body()


__all__ = [
    "ResumoRampup",
    "ResumoTurnover",
    "calcular_curva_rampup",
    "calcular_turnover",
    "render_turnover_rampup",
]
