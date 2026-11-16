"""Scorecard de Supervisão — performance consolidada por Monitor, Base e U.N."""

from __future__ import annotations

from typing import Any, Literal, cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_insight,
    render_kpi_card,
    render_section_header,
    render_ticker,
)
from components.consultivo import (
    normalizar_coluna_data_consultivo,
    sanitizar_csv_exportacao,
)
from production import (
    PROD,
    clean_contract,
    format_points,
    is_valid_contract,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}
DimensaoSupervisao = Literal["Monitor", "Base", "U.N."]

_DIM_MAP: dict[DimensaoSupervisao, tuple[str, tuple[str, ...], str, str]] = {
    "Monitor": ("monitor", ("Monitor", "MONITOR"), "monitor", "Sem monitor"),
    "Base": ("base", ("Base", "BASE"), "base", "Sem base"),
    "U.N.": ("un", ("U.N.", "UN", "U.N"), "un", "Sem U.N."),
}


def _garantir_periodo(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(serie):
        dt = serie
    else:
        dt = pd.to_datetime(serie, errors="coerce")
    return pd.Series(dt.dt.to_period("M").dt.to_timestamp(), index=serie.index)


def _limpar_label(serie: pd.Series, fallback: str) -> pd.Series:
    s = serie.fillna("").astype(str).str.strip()
    return s.where(
        s.ne("") & ~s.isin({"nan", "None", "Não Identificado", "Não Identificada"}),
        fallback,
    )


def calcular_scorecard_supervisao(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    *,
    dimensao: DimensaoSupervisao = "Monitor",
) -> pd.DataFrame:
    """Calcula scorecard executivo por Monitor, Base ou U.N."""
    col_prod, col_cons, col_roster, fallback = _DIM_MAP[dimensao]
    colunas_saida = [
        dimensao,
        "Headcount Ativo",
        "Ativos Produzindo",
        "Cobertura (%)",
        "Pontos Totais",
        "Média / Técnico",
        "Desvio-Padrão",
        "% Faixas 4–5",
        "O.S. (Prod)",
        "Contratos",
        "Consultivos",
        "Produtos",
        "Conversão (%)",
        "Índice Supervisão",
    ]

    if (
        production_frame.empty
        and (consultivo_frame is None or consultivo_frame.empty)
        and (roster_frame is None or roster_frame.empty)
    ):
        return pd.DataFrame(columns=colunas_saida)

    # 1) Headcount ativo por dimensão (span of control)
    hc_df = pd.DataFrame(columns=[dimensao, "Headcount Ativo"])
    if (
        roster_frame is not None
        and not roster_frame.empty
        and col_roster in roster_frame.columns
    ):
        ativos = roster_frame[roster_frame["status"].eq("ATIVO")].copy()
        if not ativos.empty:
            ativos[dimensao] = _limpar_label(ativos[col_roster], fallback)
            hc_df = cast(
                pd.DataFrame,
                cast(Any, ativos.groupby(dimensao, as_index=False)).agg(
                    **{"Headcount Ativo": ("technician_key", "nunique")}
                ),
            )

    # 2) Métricas de produção (Pontos, Média, Desvio-Padrão, % Faixas 4–5, O.S., Contratos)
    prod_df = pd.DataFrame()
    if not production_frame.empty and "technician" in production_frame.columns:
        p = production_frame.copy()
        p[dimensao] = (
            _limpar_label(p[col_prod], fallback) if col_prod in p.columns else fallback
        )
        pts_src = (
            p["points"] if "points" in p.columns else pd.Series(0.0, index=p.index)
        )
        p["_pts"] = pd.to_numeric(pts_src, errors="coerce").fillna(0.0)
        sheet = (
            p["source_sheet"].astype(str)
            if "source_sheet" in p.columns
            else pd.Series(PROD, index=p.index)
        )
        p["_os"] = sheet.eq(PROD).astype(int)

        if "contract" in p.columns:
            raw_ct = p["contract"].astype("string")
            clean_map = {v: clean_contract(v) for v in raw_ct.dropna().unique()}
            mapped_ct = raw_ct.map(clean_map)
            val_map = {v: is_valid_contract(v) for v in mapped_ct.dropna().unique()}
            p["_ct"] = mapped_ct.where(
                mapped_ct.map(val_map).fillna(False).astype(bool), pd.NA
            )
        else:
            p["_ct"] = pd.NA

        fonte_dt = "period" if "period" in p.columns else "reference_date"
        p["_period"] = (
            _garantir_periodo(p[fonte_dt]) if fonte_dt in p.columns else pd.NaT
        )

        # Agregação por dimensão
        base_agg = cast(Any, p.groupby(dimensao, as_index=False)).agg(
            **{
                "Ativos Produzindo": ("technician", "nunique"),
                "Pontos Totais": ("_pts", "sum"),
                "O.S. (Prod)": ("_os", "sum"),
                "Contratos": ("_ct", "nunique"),
            }
        )

        # Dispersão interna por técnico dentro da unidade + % Faixas 4–5 (>=375 pts/mês)
        por_tec_dim = cast(
            pd.DataFrame,
            p.groupby([dimensao, "technician"], as_index=False)["_pts"].sum(),
        )
        disp = cast(Any, por_tec_dim.groupby(dimensao, as_index=False)).agg(
            **{
                "Média / Técnico": ("_pts", "mean"),
                "Desvio-Padrão": (
                    "_pts",
                    lambda s: float(s.std(ddof=0)) if len(s) > 1 else 0.0,
                ),
            }
        )

        por_mes_tec = cast(
            pd.DataFrame,
            p.dropna(subset=["_period"])
            .groupby([dimensao, "technician", "_period"], as_index=False)["_pts"]
            .sum(),
        )
        if not por_mes_tec.empty:
            por_mes_tec["_f45"] = (por_mes_tec["_pts"] >= 375.0).astype(float) * 100.0
            faixas_dim = cast(
                pd.DataFrame,
                cast(Any, por_mes_tec.groupby(dimensao, as_index=False)).agg(
                    **{"% Faixas 4–5": ("_f45", "mean")}
                ),
            )
        else:
            faixas_dim = pd.DataFrame(columns=[dimensao, "% Faixas 4–5"])

        prod_df = base_agg.merge(disp, on=dimensao, how="left").merge(
            faixas_dim, on=dimensao, how="left"
        )

    # 3) Métricas consultivas
    cons_df = pd.DataFrame(columns=[dimensao, "Consultivos", "Produtos"])
    if consultivo_frame is not None and not consultivo_frame.empty:
        c = normalizar_coluna_data_consultivo(consultivo_frame)
        col_cons_efetiva = next((col for col in col_cons if col in c.columns), None)
        c[dimensao] = (
            _limpar_label(c[col_cons_efetiva], fallback)
            if col_cons_efetiva is not None
            else fallback
        )
        c_col = "Qtde. Cons." if "Qtde. Cons." in c.columns else "QTDE_CONSULTIVO"
        p_col = "Qtde. Prod." if "Qtde. Prod." in c.columns else "QTDE_PRODUTOS"
        c_src = c[c_col] if c_col in c.columns else pd.Series(0, index=c.index)
        p_src = c[p_col] if p_col in c.columns else pd.Series(0, index=c.index)
        c["_cons"] = pd.to_numeric(c_src, errors="coerce").fillna(0).astype(int)
        c["_prod"] = pd.to_numeric(p_src, errors="coerce").fillna(0).astype(int)
        cons_df = cast(Any, c.groupby(dimensao, as_index=False)).agg(
            Consultivos=("_cons", "sum"),
            Produtos=("_prod", "sum"),
        )

    # 4) Junção completa
    frames_validos = [df for df in (hc_df, prod_df, cons_df) if not df.empty]
    if not frames_validos:
        return pd.DataFrame(columns=colunas_saida)

    merged = frames_validos[0]
    for outro in frames_validos[1:]:
        merged = merged.merge(outro, on=dimensao, how="outer")

    for col_int in (
        "Headcount Ativo",
        "Ativos Produzindo",
        "O.S. (Prod)",
        "Contratos",
        "Consultivos",
        "Produtos",
    ):
        if col_int not in merged.columns:
            merged[col_int] = 0
        merged[col_int] = (
            pd.to_numeric(merged[col_int], errors="coerce").fillna(0).astype(int)
        )

    for col_flt in (
        "Pontos Totais",
        "Média / Técnico",
        "Desvio-Padrão",
        "% Faixas 4–5",
    ):
        if col_flt not in merged.columns:
            merged[col_flt] = 0.0
        merged[col_flt] = pd.to_numeric(merged[col_flt], errors="coerce").fillna(0.0)

    # Quando não há cadastro para uma dimensão, usa Ativos Produzindo como denominador
    hc_denom = np.where(
        merged["Headcount Ativo"] > 0,
        merged["Headcount Ativo"],
        merged["Ativos Produzindo"],
    )
    merged["Cobertura (%)"] = np.where(
        hc_denom > 0,
        np.minimum(merged["Ativos Produzindo"] / hc_denom * 100.0, 100.0),
        0.0,
    )
    merged["Conversão (%)"] = np.where(
        merged["Consultivos"] > 0,
        merged["Produtos"] / merged["Consultivos"] * 100.0,
        0.0,
    )

    # Índice de Supervisão (0–100): Cobertura 25% + Média/Técnico 30% + % Faixas 4–5 20% + Comercial 25%
    max_media = float(merged["Média / Técnico"].max()) if not merged.empty else 0.0
    max_cons_tec = (
        float((merged["Produtos"] / np.maximum(merged["Ativos Produzindo"], 1)).max())
        if not merged.empty
        else 0.0
    )
    norm_cob = merged["Cobertura (%)"] / 100.0
    norm_media = merged["Média / Técnico"] / max_media if max_media > 0 else 0.0
    norm_f45 = merged["% Faixas 4–5"] / 100.0
    prod_por_tec: pd.Series = merged["Produtos"] / np.maximum(
        merged["Ativos Produzindo"], 1
    )
    norm_com = prod_por_tec / max_cons_tec if max_cons_tec > 0 else 0.0

    merged["Índice Supervisão"] = np.round(
        (0.25 * norm_cob + 0.30 * norm_media + 0.20 * norm_f45 + 0.25 * norm_com)
        * 100.0,
        1,
    )

    return (
        merged[colunas_saida]
        .sort_values(["Índice Supervisão", "Pontos Totais"], ascending=[False, False])
        .reset_index(drop=True)
    )


def _layout_scorecard(fig: go.Figure, altura: int = 380) -> go.Figure:
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
def _calcular_scorecard_cached(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    *,
    dimensao: DimensaoSupervisao = "Monitor",
) -> pd.DataFrame:
    return calcular_scorecard_supervisao(
        production_frame,
        consultivo_frame,
        roster_frame,
        dimensao=dimensao,
    )


def render_scorecard_supervisao(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
) -> None:
    """Renderiza o Scorecard Executivo de Supervisão por Monitor, Base e U.N."""

    @st.fragment
    def _render_scorecard_body() -> None:
        dimensao = cast(
            DimensaoSupervisao,
            st.segmented_control(
                "Visão hierárquica",
                options=["Monitor", "Base", "U.N."],
                default="Monitor",
                label_visibility="collapsed",
                key="scorecard_dimensao",
            )
            or "Monitor",
        )

        scorecard = _calcular_scorecard_cached(
            production_frame,
            consultivo_frame,
            roster_frame,
            dimensao=dimensao,
        )
        if scorecard.empty:
            render_insight(
                f"Não há dados suficientes para compor o Scorecard por {dimensao} neste recorte.",
                tipo="info",
            )
            return

        lider = scorecard.iloc[0]
        total_hc = int(scorecard["Headcount Ativo"].sum())
        total_prod_tec = int(scorecard["Ativos Produzindo"].sum())
        cobertura_geral = (total_prod_tec / total_hc * 100.0) if total_hc > 0 else 0.0
        media_f45 = float(scorecard["% Faixas 4–5"].mean())
        media_span = float(scorecard["Headcount Ativo"].mean())

        render_ticker(
            [
                (f"Total de {dimensao}s", formatar_numero_br(len(scorecard))),
                (
                    "Líder no Índice",
                    f"{lider[dimensao]} · {lider['Índice Supervisão']:.1f} pts",
                ),
                (
                    "Span Médio",
                    f"{media_span:.1f} técnicos/{dimensao.lower()}".replace(".", ","),
                ),
                ("Cobertura Ativa", f"{cobertura_geral:.1f}%".replace(".", ",")),
                ("Média Faixas 4–5", f"{media_f45:.1f}%".replace(".", ",")),
            ],
            label=f"Scorecard de Supervisão por {dimensao}",
        )

        k = st.columns(4)
        with k[0]:
            render_kpi_card(
                f"{dimensao.upper()} LÍDER",
                str(lider[dimensao])[:22],
                f"Índice {lider['Índice Supervisão']:.1f} · {format_points(lider['Pontos Totais'])} pts",
                "🏆",
                "kpi-card--azul",
            )
        with k[1]:
            render_kpi_card(
                "SPAN OF CONTROL MÉDIO",
                f"{media_span:.1f}".replace(".", ","),
                f"{total_hc} ativos cadastrados em {len(scorecard)} {dimensao.lower()}(s)",
                "👥",
                "kpi-card--roxo",
            )
        with k[2]:
            render_kpi_card(
                "COBERTURA PRODUTIVA",
                f"{cobertura_geral:.1f}%".replace(".", ","),
                f"{total_prod_tec} de {total_hc} ativos com produção",
                "✓",
                "kpi-card--verde",
            )
        with k[3]:
            render_kpi_card(
                "MÉDIA FAIXAS 4–5 (≥375 PTS)",
                f"{media_f45:.1f}%".replace(".", ","),
                "Participação média nos patamares de excelência",
                "⚡",
                "kpi-card--laranja",
            )

        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)

        c1, c2 = st.columns([1.2, 1.0])
        top = scorecard.head(15).sort_values("Índice Supervisão", ascending=True)
        with c1, st.container(border=True):
            render_section_header(
                f"Ranking Composto · Índice de Supervisão por {dimensao}",
                subtitulo="Composição: Cobertura (25%) · Média/Técnico (30%) · % Faixas 4–5 (20%) · Comercial (25%)",
                icone="🏅",
            )
            fig_idx = go.Figure(
                go.Bar(
                    y=top[dimensao],
                    x=top["Índice Supervisão"],
                    orientation="h",
                    marker_color=Cores.PRIMARIA,
                    text=[f"{v:.1f}" for v in top["Índice Supervisão"]],
                    textposition="outside",
                    hovertemplate=("<b>%{y}</b><br>Índice: %{x:.1f}<extra></extra>"),
                )
            )
            fig_idx.update_xaxes(range=[0, 115], title="Índice Supervisão (0–100)")
            st.plotly_chart(
                _layout_scorecard(
                    fig_idx, altura=max(320, min(560, 120 + len(top) * 32))
                ),
                width="stretch",
                config=CHART_CONFIG,
                key=f"scorecard_chart_idx_{dimensao}",
            )

        with c2, st.container(border=True):
            render_section_header(
                f"Média × Dispersão Interna ({dimensao})",
                subtitulo="Menor desvio-padrão com maior média indica equipe homogênea e previsível",
                icone="🎯",
            )
            fig_disp = go.Figure(
                go.Scatter(
                    x=scorecard["Média / Técnico"],
                    y=scorecard["Desvio-Padrão"],
                    mode="markers+text" if len(scorecard) <= 15 else "markers",
                    text=scorecard[dimensao].astype(str).str.split().str[0],
                    textposition="top center",
                    textfont=dict(size=10, color=Cores.TEXTO_2),
                    marker=dict(
                        size=np.clip(scorecard["Ativos Produzindo"] * 2.5 + 10, 11, 34),
                        color=scorecard["% Faixas 4–5"],
                        colorscale=[
                            [0.0, "#F37C04"],
                            [0.5, "#3B82F6"],
                            [1.0, "#047857"],
                        ],
                        showscale=True,
                        colorbar=dict(title="% F4–5"),
                        line=dict(color="#FFFFFF", width=1.5),
                    ),
                    customdata=np.stack(
                        [
                            scorecard[dimensao],
                            scorecard["Headcount Ativo"],
                            scorecard["Cobertura (%)"],
                            scorecard["% Faixas 4–5"],
                        ],
                        axis=-1,
                    ),
                    hovertemplate=(
                        "<b>%{customdata[0]}</b><br>"
                        "Média/Técnico: %{x:,.2f} pts<br>"
                        "Desvio-Padrão: %{y:,.2f} pts<br>"
                        "Headcount: %{customdata[1]} · Cobertura: %{customdata[2]:.1f}%<br>"
                        "Faixas 4–5: %{customdata[3]:.1f}%<extra></extra>"
                    ),
                )
            )
            fig_disp.update_xaxes(
                title="Média de Pontos / Técnico", showgrid=True, gridcolor=Cores.BORDA
            )
            fig_disp.update_yaxes(title="Desvio-Padrão Interno (pts)")
            st.plotly_chart(
                _layout_scorecard(fig_disp, altura=360),
                width="stretch",
                config=CHART_CONFIG,
                key=f"scorecard_chart_disp_{dimensao}",
            )

        render_section_header(
            f"Scorecard Detalhado por {dimensao}",
            subtitulo="Indicadores integrados de headcount, produtividade técnica, qualidade de faixas e conversão consultiva",
            icone="📋",
        )
        st.dataframe(
            scorecard,
            width="stretch",
            hide_index=True,
            column_config={
                "Cobertura (%)": st.column_config.NumberColumn(format="%.1f%%"),
                "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
                "Média / Técnico": st.column_config.NumberColumn(format="%.2f"),
                "Desvio-Padrão": st.column_config.NumberColumn(format="%.2f"),
                "% Faixas 4–5": st.column_config.NumberColumn(format="%.1f%%"),
                "Conversão (%)": st.column_config.NumberColumn(format="%.1f%%"),
                "Índice Supervisão": st.column_config.ProgressColumn(
                    min_value=0.0, max_value=100.0, format="%.1f"
                ),
            },
        )
        st.download_button(
            f"Baixar Scorecard por {dimensao} em CSV",
            data=sanitizar_csv_exportacao(scorecard),
            file_name=f"totale_scorecard_{dimensao.lower().replace('.', '')}.csv",
            mime="text/csv",
            key=f"scorecard_download_{dimensao}",
        )

    _render_scorecard_body()


__all__ = [
    "DimensaoSupervisao",
    "calcular_scorecard_supervisao",
    "render_scorecard_supervisao",
]
