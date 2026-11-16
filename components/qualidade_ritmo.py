"""Qualidade Operacional (Reincidência por Contrato/O.S.) e Ritmo Diário + Projeção."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_drilldown_tecnico,
    render_insight,
    render_kpi_card,
    render_section_header,
    render_ticker,
)
from components.consultivo import sanitizar_csv_exportacao
from production import (
    PROD,
    clean_contract,
    format_points,
    is_valid_contract,
    month_label,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}
DIAS_SEMANA_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


@dataclass(frozen=True)
class ResumoReincidencia:
    """Indicadores de reincidência / retrabalho sobre contratos distintos."""

    janela_dias: int
    contratos_validos: int
    contratos_reincidentes: int
    eventos_reincidencia: int
    taxa_reincidencia_pct: float
    intervalo_medio_dias: float
    mesmo_tecnico_pct: float
    por_tecnico_origem: pd.DataFrame
    por_projeto: pd.DataFrame
    eventos: pd.DataFrame


@dataclass(frozen=True)
class ResumoRitmoDiario:
    """Distribuição por dia da semana e projeção de fechamento da última competência."""

    por_dia_semana: pd.DataFrame
    serie_diaria_ultimo_mes: pd.DataFrame
    competencia_ref: str
    pontos_realizados: float
    pontos_projetados: float
    os_realizadas: int
    os_projetadas: int
    dias_uteis_decorridos: int
    dias_uteis_totais: int
    fator_projecao: float
    melhor_dia_semana: str


def _contar_dias_uteis_mes(ano: int, mes: int, *, ate_dia: int | None = None) -> int:
    """Conta dias úteis no padrão operacional Seg–Sáb."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    limite = min(ate_dia, ultimo_dia) if ate_dia is not None else ultimo_dia
    return sum(1 for d in range(1, limite + 1) if date(ano, mes, d).weekday() < 6)


def calcular_reincidencia_contratos(
    frame: pd.DataFrame,
    *,
    janela_dias: int = 30,
) -> ResumoReincidencia:
    """Identifica contratos com retorno em datas distintas dentro da janela informada."""
    cols_tec = [
        "Técnico Origem",
        "Monitor",
        "Base",
        "Contratos Atendidos",
        "Reincidências Geradas",
        "Taxa Reincidência (%)",
        "Mesmo Técnico (%)",
        "Intervalo Médio (dias)",
    ]
    cols_proj = [
        "Projeto",
        "Contratos Atendidos",
        "Contratos Reincidentes",
        "Eventos",
        "Taxa Reincidência (%)",
    ]
    cols_evt = [
        "Contrato",
        "Data Origem",
        "Data Retorno",
        "Intervalo (dias)",
        "Técnico Origem",
        "Técnico Retorno",
        "Mesmo Técnico",
        "WO Origem",
        "WO Retorno",
        "Projeto",
        "Monitor",
        "Base",
    ]
    vazio = ResumoReincidencia(
        janela_dias=janela_dias,
        contratos_validos=0,
        contratos_reincidentes=0,
        eventos_reincidencia=0,
        taxa_reincidencia_pct=0.0,
        intervalo_medio_dias=0.0,
        mesmo_tecnico_pct=0.0,
        por_tecnico_origem=pd.DataFrame(columns=cols_tec),
        por_projeto=pd.DataFrame(columns=cols_proj),
        eventos=pd.DataFrame(columns=cols_evt),
    )
    if (
        frame.empty
        or "contract" not in frame.columns
        or "reference_date" not in frame.columns
    ):
        return vazio

    raw_ct = frame["contract"].astype("string")
    clean_map = {v: clean_contract(v) for v in raw_ct.dropna().unique()}
    mapped = raw_ct.map(clean_map)
    valid_map = {v: is_valid_contract(v) for v in mapped.dropna().unique()}
    mask_valid = mapped.map(valid_map).fillna(False).astype(bool)
    if not mask_valid.any():
        return vazio

    dates = (
        frame.loc[mask_valid, "reference_date"]
        if pd.api.types.is_datetime64_any_dtype(frame["reference_date"])
        else pd.to_datetime(frame.loc[mask_valid, "reference_date"], errors="coerce")
    )
    work = pd.DataFrame(
        {
            "contract": mapped.loc[mask_valid].astype(str),
            "ref_date": dates.dt.normalize(),
            "technician": frame.loc[mask_valid, "technician"]
            .fillna("Sem técnico")
            .astype(str),
            "wo": (
                frame.loc[mask_valid, "wo"].fillna("Sem WO").astype(str)
                if "wo" in frame.columns
                else "Sem WO"
            ),
            "project": (
                frame.loc[mask_valid, "project"].fillna("Sem projeto").astype(str)
                if "project" in frame.columns
                else "Sem projeto"
            ),
            "monitor": (
                frame.loc[mask_valid, "monitor"].fillna("Sem monitor").astype(str)
                if "monitor" in frame.columns
                else "Sem monitor"
            ),
            "base": (
                frame.loc[mask_valid, "base"].fillna("Sem base").astype(str)
                if "base" in frame.columns
                else "Sem base"
            ),
        },
        index=frame.index[mask_valid],
    ).dropna(subset=["ref_date"])

    if work.empty:
        return vazio

    # Colapsa linhas da mesma visita (ex.: abas Prod e Gpon no mesmo contrato e dia)
    visitas = (
        work.sort_values(["contract", "ref_date", "wo", "technician"])
        .drop_duplicates(subset=["contract", "ref_date"], keep="first")
        .reset_index(drop=True)
    )

    contratos_validos = int(visitas["contract"].nunique())
    grp = visitas.groupby("contract", sort=False)
    visitas["prev_date"] = grp["ref_date"].shift(1)
    visitas["prev_tech"] = grp["technician"].shift(1)
    visitas["prev_wo"] = grp["wo"].shift(1)
    visitas["prev_project"] = grp["project"].shift(1)
    visitas["prev_monitor"] = grp["monitor"].shift(1)
    visitas["prev_base"] = grp["base"].shift(1)
    visitas["intervalo"] = (visitas["ref_date"] - visitas["prev_date"]).dt.days

    reinc = visitas[
        visitas["intervalo"].notna()
        & (visitas["intervalo"] >= 1)
        & (visitas["intervalo"] <= int(janela_dias))
    ].copy()

    if reinc.empty:
        return ResumoReincidencia(
            janela_dias=janela_dias,
            contratos_validos=contratos_validos,
            contratos_reincidentes=0,
            eventos_reincidencia=0,
            taxa_reincidencia_pct=0.0,
            intervalo_medio_dias=0.0,
            mesmo_tecnico_pct=0.0,
            por_tecnico_origem=pd.DataFrame(columns=cols_tec),
            por_projeto=pd.DataFrame(columns=cols_proj),
            eventos=pd.DataFrame(columns=cols_evt),
        )

    reinc["mesmo_tecnico"] = reinc["technician"].eq(reinc["prev_tech"])
    contratos_reincidentes = int(reinc["contract"].nunique())
    eventos_reincidencia = int(len(reinc))
    taxa_pct = (
        contratos_reincidentes / contratos_validos * 100.0
        if contratos_validos > 0
        else 0.0
    )
    intervalo_medio = float(reinc["intervalo"].mean())
    mesmo_tec_pct = float(reinc["mesmo_tecnico"].mean() * 100.0)

    # Ranking por técnico de origem
    ct_por_tec = (
        cast(Any, visitas.groupby("technician", as_index=False))
        .agg(**{"Contratos Atendidos": ("contract", "nunique")})
        .rename(columns={"technician": "Técnico Origem"})
    )
    reinc_por_tec = (
        cast(Any, reinc.groupby("prev_tech", as_index=False))
        .agg(
            **{
                "Monitor": ("prev_monitor", "first"),
                "Base": ("prev_base", "first"),
                "Reincidências Geradas": ("contract", "size"),
                "Mesmo Técnico (%)": (
                    "mesmo_tecnico",
                    lambda s: float(s.mean() * 100.0),
                ),
                "Intervalo Médio (dias)": ("intervalo", "mean"),
            }
        )
        .rename(columns={"prev_tech": "Técnico Origem"})
    )
    por_tec = reinc_por_tec.merge(ct_por_tec, on="Técnico Origem", how="left")
    por_tec["Contratos Atendidos"] = (
        por_tec["Contratos Atendidos"].fillna(0).astype(int)
    )
    por_tec["Taxa Reincidência (%)"] = np.where(
        por_tec["Contratos Atendidos"] > 0,
        por_tec["Reincidências Geradas"] / por_tec["Contratos Atendidos"] * 100.0,
        0.0,
    )
    por_tec = (
        por_tec[cols_tec]
        .sort_values(
            ["Reincidências Geradas", "Taxa Reincidência (%)"], ascending=[False, False]
        )
        .reset_index(drop=True)
    )

    # Por projeto
    ct_por_proj = (
        cast(Any, visitas.groupby("project", as_index=False))
        .agg(**{"Contratos Atendidos": ("contract", "nunique")})
        .rename(columns={"project": "Projeto"})
    )
    reinc_por_proj = (
        cast(Any, reinc.groupby("prev_project", as_index=False))
        .agg(
            **{
                "Contratos Reincidentes": ("contract", "nunique"),
                "Eventos": ("contract", "size"),
            }
        )
        .rename(columns={"prev_project": "Projeto"})
    )
    por_proj = ct_por_proj.merge(reinc_por_proj, on="Projeto", how="left")
    por_proj["Contratos Reincidentes"] = (
        por_proj["Contratos Reincidentes"].fillna(0).astype(int)
    )
    por_proj["Eventos"] = por_proj["Eventos"].fillna(0).astype(int)
    por_proj["Taxa Reincidência (%)"] = np.where(
        por_proj["Contratos Atendidos"] > 0,
        por_proj["Contratos Reincidentes"] / por_proj["Contratos Atendidos"] * 100.0,
        0.0,
    )
    por_proj = (
        por_proj[cols_proj]
        .sort_values(["Taxa Reincidência (%)", "Eventos"], ascending=[False, False])
        .reset_index(drop=True)
    )

    eventos_df = (
        pd.DataFrame(
            {
                "Contrato": reinc["contract"].astype(str),
                "Data Origem": reinc["prev_date"].dt.strftime("%d/%m/%Y"),
                "Data Retorno": reinc["ref_date"].dt.strftime("%d/%m/%Y"),
                "Intervalo (dias)": reinc["intervalo"].astype(int),
                "Técnico Origem": reinc["prev_tech"].astype(str),
                "Técnico Retorno": reinc["technician"].astype(str),
                "Mesmo Técnico": np.where(reinc["mesmo_tecnico"], "Sim", "Não"),
                "WO Origem": reinc["prev_wo"].astype(str),
                "WO Retorno": reinc["wo"].astype(str),
                "Projeto": reinc["prev_project"].astype(str),
                "Monitor": reinc["prev_monitor"].astype(str),
                "Base": reinc["prev_base"].astype(str),
            }
        )
        .sort_values(["Intervalo (dias)", "Contrato"])
        .reset_index(drop=True)
    )

    return ResumoReincidencia(
        janela_dias=janela_dias,
        contratos_validos=contratos_validos,
        contratos_reincidentes=contratos_reincidentes,
        eventos_reincidencia=eventos_reincidencia,
        taxa_reincidencia_pct=taxa_pct,
        intervalo_medio_dias=intervalo_medio,
        mesmo_tecnico_pct=mesmo_tec_pct,
        por_tecnico_origem=por_tec,
        por_projeto=por_proj,
        eventos=eventos_df,
    )


def calcular_ritmo_diario_producao(
    frame: pd.DataFrame,
    *,
    hoje: date | None = None,
) -> ResumoRitmoDiario:
    """Apura ritmo por dia da semana (Seg–Sáb) e projeção de fechamento do último mês."""
    cols_dow = [
        "Dia da Semana",
        "Dias Ativos",
        "Pontos Totais",
        "Média Pontos / Dia",
        "O.S. (Prod)",
        "Média O.S. / Dia",
        "Participação (%)",
    ]
    cols_serie = ["Data", "Data_Exib", "Pontos", "O.S.", "Pontos Acumulados"]
    vazio = ResumoRitmoDiario(
        por_dia_semana=pd.DataFrame(columns=cols_dow),
        serie_diaria_ultimo_mes=pd.DataFrame(columns=cols_serie),
        competencia_ref="Sem dados",
        pontos_realizados=0.0,
        pontos_projetados=0.0,
        os_realizadas=0,
        os_projetadas=0,
        dias_uteis_decorridos=0,
        dias_uteis_totais=0,
        fator_projecao=1.0,
        melhor_dia_semana="—",
    )
    if frame.empty or "reference_date" not in frame.columns:
        return vazio

    dt = (
        frame["reference_date"]
        if pd.api.types.is_datetime64_any_dtype(frame["reference_date"])
        else pd.to_datetime(frame["reference_date"], errors="coerce")
    )
    sheet = (
        frame["source_sheet"].astype(str)
        if "source_sheet" in frame.columns
        else pd.Series(PROD, index=frame.index)
    )
    pts_src = (
        frame["points"]
        if "points" in frame.columns
        else pd.Series(0.0, index=frame.index)
    )
    work = pd.DataFrame(
        {
            "dt": dt.dt.normalize(),
            "points": pd.to_numeric(pts_src, errors="coerce").fillna(0.0),
            "os": sheet.eq(PROD).astype(int),
        },
        index=frame.index,
    ).dropna(subset=["dt"])
    if work.empty:
        return vazio

    # 1) Agregação diária -> média por dia da semana
    diario_all = cast(Any, work.groupby("dt", as_index=False)).agg(
        points=("points", "sum"), os=("os", "sum")
    )
    diario_all["dow"] = diario_all["dt"].dt.weekday
    dow_agg = cast(Any, diario_all.groupby("dow", as_index=False)).agg(
        **{
            "Dias Ativos": ("dt", "nunique"),
            "Pontos Totais": ("points", "sum"),
            "Média Pontos / Dia": ("points", "mean"),
            "O.S. (Prod)": ("os", "sum"),
            "Média O.S. / Dia": ("os", "mean"),
        }
    )
    total_pts_all = float(dow_agg["Pontos Totais"].sum())
    dow_agg["Dia da Semana"] = dow_agg["dow"].map(lambda i: DIAS_SEMANA_PT[int(i)])
    dow_agg["Participação (%)"] = np.where(
        total_pts_all > 0, dow_agg["Pontos Totais"] / total_pts_all * 100.0, 0.0
    )
    dow_agg = dow_agg.sort_values("dow").reset_index(drop=True)
    melhor_dia = (
        str(
            dow_agg.sort_values("Média Pontos / Dia", ascending=False).iloc[0][
                "Dia da Semana"
            ]
        )
        if not dow_agg.empty
        else "—"
    )

    # 2) Série diária e projeção da competência mais recente
    work["period"] = work["dt"].dt.to_period("M")
    ultimo_p = work["period"].max()
    mes_df = work[work["period"].eq(ultimo_p)]
    serie = (
        cast(Any, mes_df.groupby("dt", as_index=False))
        .agg(Pontos=("points", "sum"), **{"O.S.": ("os", "sum")})
        .rename(columns={"dt": "Data"})
        .sort_values("Data")
        .reset_index(drop=True)
    )
    serie["Data_Exib"] = serie["Data"].dt.strftime("%d/%m")
    serie["Pontos Acumulados"] = serie["Pontos"].cumsum()

    ano_ref, mes_ref = int(ultimo_p.year), int(ultimo_p.month)
    dias_uteis_totais = _contar_dias_uteis_mes(ano_ref, mes_ref)
    hoje_ref = hoje or date.today()
    max_data_mes = serie["Data"].max().date()

    if (hoje_ref.year, hoje_ref.month) == (ano_ref, mes_ref):
        dia_corte = max(hoje_ref.day, max_data_mes.day)
        dias_uteis_decorridos = max(
            1, _contar_dias_uteis_mes(ano_ref, mes_ref, ate_dia=dia_corte)
        )
        fator = dias_uteis_totais / dias_uteis_decorridos
    elif (hoje_ref.year, hoje_ref.month) < (ano_ref, mes_ref):
        dias_uteis_decorridos = max(
            1, _contar_dias_uteis_mes(ano_ref, mes_ref, ate_dia=max_data_mes.day)
        )
        fator = dias_uteis_totais / dias_uteis_decorridos
    else:
        # Competência já encerrada: realizado == projetado
        dias_uteis_decorridos = dias_uteis_totais
        fator = 1.0

    pts_real = float(serie["Pontos"].sum())
    os_real = int(serie["O.S."].sum())
    pts_proj = round(pts_real * fator, 2)
    os_proj = int(round(os_real * fator))

    return ResumoRitmoDiario(
        por_dia_semana=dow_agg[cols_dow],
        serie_diaria_ultimo_mes=serie[cols_serie],
        competencia_ref=month_label(ultimo_p.to_timestamp()),
        pontos_realizados=pts_real,
        pontos_projetados=pts_proj,
        os_realizadas=os_real,
        os_projetadas=os_proj,
        dias_uteis_decorridos=dias_uteis_decorridos,
        dias_uteis_totais=dias_uteis_totais,
        fator_projecao=fator,
        melhor_dia_semana=melhor_dia,
    )


def _layout_qr(fig: go.Figure, altura: int = 360) -> go.Figure:
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
def _calcular_reincidencia_cached(
    frame: pd.DataFrame, *, janela_dias: int = 30
) -> ResumoReincidencia:
    return calcular_reincidencia_contratos(frame, janela_dias=janela_dias)


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _calcular_ritmo_cached(frame: pd.DataFrame) -> ResumoRitmoDiario:
    return calcular_ritmo_diario_producao(frame)


def render_qualidade_ritmo(filtered: pd.DataFrame) -> None:
    """Renderiza Qualidade (Reincidência por Contrato/O.S.) e Ritmo Diário + Projeção."""
    if filtered.empty:
        render_insight("Sem registros de produção para o recorte atual.", tipo="info")
        return

    @st.fragment
    def _render_qr_body() -> None:
        visao = (
            st.segmented_control(
                "Submódulo de Qualidade e Ritmo",
                options=["🔁 Reincidência & Qualidade", "📆 Ritmo Diário & Projeção"],
                default="🔁 Reincidência & Qualidade",
                label_visibility="collapsed",
                key="qr_submodulo",
            )
            or "🔁 Reincidência & Qualidade"
        )

        if visao == "🔁 Reincidência & Qualidade":
            c_win, c_note = st.columns([1.2, 2.8])
            with c_win:
                janela = int(
                    st.selectbox(
                        "Janela de reincidência",
                        options=[7, 15, 30, 60],
                        index=2,
                        format_func=lambda d: f"Até {d} dias",
                        key="qr_janela_reinc",
                    )
                )
            with c_note:
                st.caption(
                    "Detecta retornos no mesmo contrato em datas distintas dentro da janela escolhida "
                    "(visitas Prod e Gpon no mesmo dia são consolidadas como atendimento único)."
                )

            res = _calcular_reincidencia_cached(filtered, janela_dias=janela)

            render_ticker(
                [
                    ("Contratos Válidos", formatar_numero_br(res.contratos_validos)),
                    (
                        "Contratos Reincidentes",
                        formatar_numero_br(res.contratos_reincidentes),
                    ),
                    (
                        "Taxa de Reincidência",
                        f"{res.taxa_reincidencia_pct:.1f}%".replace(".", ","),
                    ),
                    (
                        "Eventos de Retorno",
                        formatar_numero_br(res.eventos_reincidencia),
                    ),
                    (
                        "Intervalo Médio",
                        f"{res.intervalo_medio_dias:.1f} dias".replace(".", ","),
                    ),
                ],
                label=f"Qualidade & Reincidência ({janela} dias)",
            )

            k = st.columns(4)
            with k[0]:
                render_kpi_card(
                    "TAXA DE REINCIDÊNCIA",
                    f"{res.taxa_reincidencia_pct:.1f}%".replace(".", ","),
                    f"{res.contratos_reincidentes} de {res.contratos_validos} contratos (≤{janela}d)",
                    "🔁",
                    "kpi-card--vermelho"
                    if res.taxa_reincidencia_pct >= 10
                    else "kpi-card--azul",
                )
            with k[1]:
                render_kpi_card(
                    "EVENTOS DE RETORNO",
                    formatar_numero_br(res.eventos_reincidencia),
                    "Atendimentos subsequentes no mesmo contrato",
                    "📋",
                    "kpi-card--laranja",
                )
            with k[2]:
                render_kpi_card(
                    "INTERVALO MÉDIO",
                    f"{res.intervalo_medio_dias:.1f} dias".replace(".", ","),
                    "Tempo médio entre visita de origem e retorno",
                    "⏱️",
                    "kpi-card--roxo",
                )
            with k[3]:
                render_kpi_card(
                    "RETORNO MESMO TÉCNICO",
                    f"{res.mesmo_tecnico_pct:.1f}%".replace(".", ","),
                    "Proporção resolvida pelo mesmo técnico de origem",
                    "👷",
                    "kpi-card--verde",
                )

            if res.eventos.empty:
                render_insight(
                    f"Excelente! Nenhuma reincidência de contrato identificada na janela de {janela} dias.",
                    tipo="ok",
                )
                return

            g1, g2 = st.columns(2)
            with g1, st.container(border=True):
                render_section_header(
                    "Top Técnicos de Origem por Reincidências",
                    subtitulo="Volume de retornos subsequentes associados ao atendimento anterior",
                    icone="👷",
                )
                top_t = res.por_tecnico_origem.head(12).sort_values(
                    "Reincidências Geradas", ascending=True
                )
                fig_t = go.Figure(
                    go.Bar(
                        y=top_t["Técnico Origem"],
                        x=top_t["Reincidências Geradas"],
                        orientation="h",
                        marker_color=Cores.SECUNDARIA,
                        text=top_t["Reincidências Geradas"],
                        textposition="outside",
                        hovertemplate="<b>%{y}</b><br>Reincidências: %{x}<extra></extra>",
                    )
                )
                max_r = (
                    int(top_t["Reincidências Geradas"].max()) if not top_t.empty else 1
                )
                fig_t.update_xaxes(range=[0, max_r * 1.25])
                st.plotly_chart(
                    _layout_qr(fig_t, altura=360),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="qr_chart_reinc_tec",
                )

            with g2, st.container(border=True):
                render_section_header(
                    "Taxa de Reincidência por Projeto (%)",
                    subtitulo="Percentual de contratos com retorno em cada frente de projeto",
                    icone="🏗️",
                )
                top_p = res.por_projeto.head(12).sort_values(
                    "Taxa Reincidência (%)", ascending=True
                )
                fig_p = go.Figure(
                    go.Bar(
                        y=top_p["Projeto"],
                        x=top_p["Taxa Reincidência (%)"],
                        orientation="h",
                        marker_color=Cores.PRIMARIA,
                        text=[f"{v:.1f}%" for v in top_p["Taxa Reincidência (%)"]],
                        textposition="outside",
                        hovertemplate="<b>%{y}</b><br>Taxa: %{x:.1f}%<extra></extra>",
                    )
                )
                max_p = (
                    float(top_p["Taxa Reincidência (%)"].max())
                    if not top_p.empty
                    else 1.0
                )
                fig_p.update_xaxes(range=[0, max(max_p * 1.25, 5.0)])
                st.plotly_chart(
                    _layout_qr(fig_p, altura=360),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="qr_chart_reinc_proj",
                )

            render_section_header(
                "Detalhamento de Contratos Reincidentes",
                subtitulo=f"{len(res.eventos)} evento(s) registrados na janela de {janela} dias",
                icone="🔎",
            )
            st.dataframe(res.eventos, width="stretch", hide_index=True)
            if "Técnico Origem" in res.eventos.columns:
                render_drilldown_tecnico(
                    res.eventos["Técnico Origem"].tolist(),
                    key_prefix="qr_reinc",
                )
            st.download_button(
                "Baixar auditoria de reincidência em CSV",
                data=sanitizar_csv_exportacao(res.eventos),
                file_name=f"totale_reincidencia_{janela}d.csv",
                mime="text/csv",
                key="qr_download_reinc_csv",
            )

        else:
            ritmo = _calcular_ritmo_cached(filtered)
            if ritmo.por_dia_semana.empty:
                render_insight(
                    "Sem datas diárias válidas para calcular ritmo.", tipo="info"
                )
                return

            render_ticker(
                [
                    ("Competência Ref.", ritmo.competencia_ref),
                    (
                        "Realizado no Mês",
                        f"{format_points(ritmo.pontos_realizados)} pts",
                    ),
                    (
                        "Projeção Fechamento",
                        f"{format_points(ritmo.pontos_projetados)} pts",
                    ),
                    ("O.S. Projetadas", formatar_numero_br(ritmo.os_projetadas)),
                    ("Dia Mais Forte", ritmo.melhor_dia_semana),
                ],
                label="Ritmo Diário & Projeção de Fechamento",
            )

            k = st.columns(4)
            with k[0]:
                render_kpi_card(
                    f"REALIZADO ({ritmo.competencia_ref.upper()})",
                    format_points(ritmo.pontos_realizados),
                    f"{formatar_numero_br(ritmo.os_realizadas)} O.S. (Prod) no mês",
                    "⚡",
                    "kpi-card--azul",
                )
            with k[1]:
                render_kpi_card(
                    "PROJEÇÃO DE PONTOS",
                    format_points(ritmo.pontos_projetados),
                    f"Base Seg–Sáb ({ritmo.dias_uteis_decorridos}/{ritmo.dias_uteis_totais} dias úteis)",
                    "📈",
                    "kpi-card--verde",
                )
            with k[2]:
                render_kpi_card(
                    "PROJEÇÃO DE O.S.",
                    formatar_numero_br(ritmo.os_projetadas),
                    f"Fator de projeção: {ritmo.fator_projecao:.2f}×".replace(".", ","),
                    "📋",
                    "kpi-card--laranja",
                )
            with k[3]:
                render_kpi_card(
                    "DIA MAIS PRODUTIVO",
                    ritmo.melhor_dia_semana,
                    "Maior média de pontos por dia ativo no recorte",
                    "📅",
                    "kpi-card--roxo",
                )

            c1, c2 = st.columns(2)
            with c1, st.container(border=True):
                render_section_header(
                    "Média de Pontos por Dia da Semana",
                    subtitulo="Cadência operacional de Segunda a Sábado no recorte filtrado",
                    icone="📆",
                )
                fig_dow = go.Figure(
                    go.Bar(
                        x=ritmo.por_dia_semana["Dia da Semana"],
                        y=ritmo.por_dia_semana["Média Pontos / Dia"],
                        marker_color=Cores.PRIMARIA,
                        text=[
                            format_points(v)
                            for v in ritmo.por_dia_semana["Média Pontos / Dia"]
                        ],
                        textposition="outside",
                        hovertemplate="<b>%{x}</b><br>Média: %{y:,.2f} pts/dia<extra></extra>",
                    )
                )
                max_d = float(ritmo.por_dia_semana["Média Pontos / Dia"].max())
                fig_dow.update_yaxes(range=[0, max(max_d * 1.22, 1.0)])
                st.plotly_chart(
                    _layout_qr(fig_dow, altura=350),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="qr_chart_dow",
                )

            with c2, st.container(border=True):
                render_section_header(
                    f"Evolução Diária e Acumulada · {ritmo.competencia_ref}",
                    subtitulo="Pontos diários (barras) e curva acumulada no mês de referência",
                    icone="📈",
                )
                fig_dia = go.Figure()
                fig_dia.add_bar(
                    x=ritmo.serie_diaria_ultimo_mes["Data_Exib"],
                    y=ritmo.serie_diaria_ultimo_mes["Pontos"],
                    name="Pontos no dia",
                    marker_color=Cores.PRIMARIA,
                    yaxis="y1",
                )
                fig_dia.add_scatter(
                    x=ritmo.serie_diaria_ultimo_mes["Data_Exib"],
                    y=ritmo.serie_diaria_ultimo_mes["Pontos Acumulados"],
                    name="Acumulado mês",
                    mode="lines+markers",
                    line=dict(color=Cores.SECUNDARIA, width=2.5),
                    yaxis="y2",
                )
                fig_dia.update_layout(
                    yaxis=dict(title="Pontos/dia", gridcolor=Cores.BORDA),
                    yaxis2=dict(
                        title="Acumulado (pts)",
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    ),
                )
                st.plotly_chart(
                    _layout_qr(fig_dia, altura=350),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="qr_chart_diario",
                )

            st.dataframe(
                ritmo.por_dia_semana,
                width="stretch",
                hide_index=True,
                column_config={
                    "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
                    "Média Pontos / Dia": st.column_config.NumberColumn(format="%.2f"),
                    "Média O.S. / Dia": st.column_config.NumberColumn(format="%.1f"),
                    "Participação (%)": st.column_config.NumberColumn(format="%.1f%%"),
                },
            )

    _render_qr_body()


__all__ = [
    "ResumoReincidencia",
    "ResumoRitmoDiario",
    "calcular_reincidencia_contratos",
    "calcular_ritmo_diario_producao",
    "render_qualidade_ritmo",
]
