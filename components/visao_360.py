"""Visão 360° Operacional × Comercial (Produção Técnica + Performance Consultiva)."""

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
    formatar_numero_br,
    render_drilldown_tecnico,
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
    GPON,
    PROD,
    ROSTER_STATUS_ORDER,
    clean_code,
    clean_contract,
    format_points,
    is_valid_contract,
    month_label,
    normalize_text,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}

QUADRANTES_360_ORDEM = (
    "Elite 360°",
    "Forte Técnico · Potencial Comercial",
    "Forte Comercial · Potencial Técnico",
    "Atenção Prioritária",
)

CORES_QUADRANTES_360: dict[str, tuple[str, str, str]] = {
    "Elite 360°": ("#047857", "#ECFDF5", "#065F46"),
    "Forte Técnico · Potencial Comercial": ("#012869", "#EFF6FF", "#1E40AF"),
    "Forte Comercial · Potencial Técnico": ("#F37C04", "#FFF7ED", "#C2410C"),
    "Atenção Prioritária": ("#DC2626", "#FEF2F2", "#B91C1C"),
}


@dataclass(frozen=True)
class ResumoVisao360:
    """Consolidação 360° unindo entregas técnicas e performance comercial."""

    por_tecnico: pd.DataFrame
    evolucao_mensal: pd.DataFrame
    por_monitor: pd.DataFrame
    por_base: pd.DataFrame
    por_un: pd.DataFrame
    pontos_totais: float
    os_totais: int
    contratos_totais: int
    consultivos_totais: int
    produtos_totais: int
    conversao_pct: float
    penetracao_pct: float
    contratos_comum: int
    total_tecnicos: int
    elite_count: int
    mediana_pontos: float
    mediana_consultivos: float
    mediana_pontos_os: float
    mediana_conversao: float


def _garantir_periodo(serie: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(serie):
        dt = serie
    else:
        dt = pd.to_datetime(serie, errors="coerce")
    return pd.Series(dt.dt.to_period("M").dt.to_timestamp(), index=serie.index)


def _limpar_contratos_validos(serie: pd.Series) -> pd.Series:
    raw = serie.astype("string")
    unicos = raw.dropna().unique()
    limpos = {v: clean_contract(v) for v in unicos}
    mapped = raw.map(limpos)
    valid_map = {v: is_valid_contract(v) for v in mapped.dropna().unique()}
    mask = mapped.map(valid_map).fillna(False).astype(bool)
    return mapped.where(mask, pd.NA)


def _construir_mapas_cadastro(
    roster_frame: pd.DataFrame | None,
) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """Retorna mapas por technician_key e de login -> technician_key."""
    por_chave: dict[str, dict[str, str]] = {}
    login_para_chave: dict[str, str] = {}
    if roster_frame is None or roster_frame.empty:
        return por_chave, login_para_chave

    for row in roster_frame.itertuples(index=False):
        tech = str(getattr(row, "technician", "") or "").strip()
        key = str(getattr(row, "technician_key", "") or "").strip() or normalize_text(
            tech
        )
        if not key:
            continue
        login = clean_code(getattr(row, "login", "")).upper()
        info = {
            "technician": tech or key,
            "login": login,
            "monitor": str(getattr(row, "monitor", "") or "Sem monitor").strip()
            or "Sem monitor",
            "un": str(getattr(row, "un", "") or "Sem U.N.").strip() or "Sem U.N.",
            "base": str(getattr(row, "base", "") or "Sem base").strip() or "Sem base",
            "status": str(getattr(row, "status", "") or "ATIVO").strip() or "ATIVO",
        }
        por_chave[key] = info
        if login:
            login_para_chave[login] = key
    return por_chave, login_para_chave


def _classificar_quadrante_series(
    eixo_x: pd.Series,
    eixo_y: pd.Series,
    mediana_x: float,
    mediana_y: float,
) -> pd.Series:
    alto_x = eixo_x >= mediana_x
    alto_y = eixo_y >= mediana_y
    return pd.Series(
        np.select(
            [alto_x & alto_y, alto_x & ~alto_y, ~alto_x & alto_y],
            [
                "Elite 360°",
                "Forte Técnico · Potencial Comercial",
                "Forte Comercial · Potencial Técnico",
            ],
            default="Atenção Prioritária",
        ),
        index=eixo_x.index,
        dtype="object",
    )


def _resumir_dimensao_360(por_tecnico: pd.DataFrame, dimensao: str) -> pd.DataFrame:
    colunas = [
        dimensao,
        "Técnicos",
        "Elite 360°",
        "Pontos Totais",
        "O.S. (Prod)",
        "Contratos",
        "Consultivos",
        "Produtos",
        "Conversão (%)",
        "Penetração Consultiva (%)",
        "Score 360° Médio",
    ]
    if por_tecnico.empty or dimensao not in por_tecnico.columns:
        return pd.DataFrame(columns=colunas)

    work = por_tecnico.copy()
    work["_elite"] = work["Quadrante 360°"].eq("Elite 360°").astype(int)
    grouped = cast(Any, work.groupby(dimensao, as_index=False, dropna=False)).agg(
        **{
            "Técnicos": ("Técnico", "nunique"),
            "Elite 360°": ("_elite", "sum"),
            "Pontos Totais": ("Pontos Totais", "sum"),
            "O.S. (Prod)": ("O.S. (Prod)", "sum"),
            "Contratos": ("Contratos", "sum"),
            "Consultivos": ("Consultivos", "sum"),
            "Produtos": ("Produtos", "sum"),
            "Score 360° Médio": ("Score 360°", "mean"),
        }
    )
    grouped["Conversão (%)"] = np.where(
        grouped["Consultivos"] > 0,
        grouped["Produtos"] / grouped["Consultivos"] * 100.0,
        0.0,
    )
    grouped["Penetração Consultiva (%)"] = np.where(
        grouped["Contratos"] > 0,
        grouped["Consultivos"] / grouped["Contratos"] * 100.0,
        0.0,
    )
    grouped = grouped.sort_values(
        ["Score 360° Médio", "Pontos Totais"], ascending=[False, False]
    ).reset_index(drop=True)
    return cast(pd.DataFrame, grouped[colunas])


def _col_consultivo(df: pd.DataFrame, primaria: str, alternativa: str) -> pd.Series:
    if primaria in df.columns:
        return pd.to_numeric(df[primaria], errors="coerce").fillna(0).astype(int)
    if alternativa in df.columns:
        return pd.to_numeric(df[alternativa], errors="coerce").fillna(0).astype(int)
    return pd.Series(0, index=df.index, dtype="int64")


def calcular_visao_360(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
) -> ResumoVisao360:
    """Consolida métricas técnicas (Produção) e comerciais (Consultivo) em visão única."""
    colunas_tec = [
        "Técnico",
        "Situação",
        "Monitor",
        "U.N.",
        "Base",
        "Pontos Prod",
        "Pontos Gpon",
        "Pontos Totais",
        "O.S. (Prod)",
        "Contratos",
        "Pontos / O.S.",
        "Consultivos",
        "Produtos",
        "Mesh",
        "TV Box",
        "Virtua",
        "Conversão (%)",
        "Penetração Consultiva (%)",
        "Contratos em Comum",
        "Score 360°",
        "Quadrante 360°",
    ]
    colunas_mensal = [
        "period",
        "Competência",
        "Pontos Totais",
        "O.S. (Prod)",
        "Contratos",
        "Consultivos",
        "Produtos",
        "Conversão (%)",
        "Penetração Consultiva (%)",
    ]

    prod = production_frame.copy() if production_frame is not None else pd.DataFrame()
    cons = (
        normalizar_coluna_data_consultivo(consultivo_frame)
        if consultivo_frame is not None and not consultivo_frame.empty
        else pd.DataFrame()
    )

    if prod.empty and cons.empty:
        vazio_tec = pd.DataFrame(columns=colunas_tec)
        return ResumoVisao360(
            por_tecnico=vazio_tec,
            evolucao_mensal=pd.DataFrame(columns=colunas_mensal),
            por_monitor=_resumir_dimensao_360(vazio_tec, "Monitor"),
            por_base=_resumir_dimensao_360(vazio_tec, "Base"),
            por_un=_resumir_dimensao_360(vazio_tec, "U.N."),
            pontos_totais=0.0,
            os_totais=0,
            contratos_totais=0,
            consultivos_totais=0,
            produtos_totais=0,
            conversao_pct=0.0,
            penetracao_pct=0.0,
            contratos_comum=0,
            total_tecnicos=0,
            elite_count=0,
            mediana_pontos=0.0,
            mediana_consultivos=0.0,
            mediana_pontos_os=0.0,
            mediana_conversao=0.0,
        )

    mapa_roster, login_para_chave = _construir_mapas_cadastro(roster_frame)

    # 1) Agregação técnica (Produção)
    prod_agg = pd.DataFrame()
    prod_mensal = pd.DataFrame()
    contratos_prod_por_chave: dict[str, set[str]] = {}
    contratos_prod_global: set[str] = set()

    if not prod.empty and "technician" in prod.columns:
        p_work = prod.copy()
        p_work["_key"] = p_work["technician"].astype(str).map(normalize_text)
        p_work = p_work[p_work["_key"].ne("")]
        pts_src = (
            p_work["points"]
            if "points" in p_work.columns
            else pd.Series(0.0, index=p_work.index)
        )
        p_work["_points"] = pd.to_numeric(pts_src, errors="coerce").fillna(0.0)
        sheet_col = (
            p_work["source_sheet"].astype(str)
            if "source_sheet" in p_work.columns
            else pd.Series(PROD, index=p_work.index)
        )
        p_work["_pts_prod"] = p_work["_points"].where(sheet_col.eq(PROD), 0.0)
        p_work["_pts_gpon"] = p_work["_points"].where(sheet_col.eq(GPON), 0.0)
        p_work["_os"] = sheet_col.eq(PROD).astype(int)
        if "contract" in p_work.columns:
            p_work["_contract"] = _limpar_contratos_validos(p_work["contract"])
        else:
            p_work["_contract"] = pd.NA

        fonte_dt = "period" if "period" in p_work.columns else "reference_date"
        if fonte_dt in p_work.columns:
            p_work["_period"] = _garantir_periodo(p_work[fonte_dt])
        else:
            p_work["_period"] = pd.NaT

        # Contratos distintos por técnico e competência (alinhado ao módulo Contratos)
        ct_validos = p_work.dropna(subset=["_contract"])
        if not ct_validos.empty:
            contratos_prod_global = set(ct_validos["_contract"].astype(str).unique())
            for chave, grp in ct_validos.groupby("_key")["_contract"]:
                contratos_prod_por_chave[str(chave)] = set(grp.astype(str).unique())

        prod_agg = cast(Any, p_work.groupby("_key", as_index=False)).agg(
            **{
                "_tech_prod": ("technician", "first"),
                "Pontos Prod": ("_pts_prod", "sum"),
                "Pontos Gpon": ("_pts_gpon", "sum"),
                "O.S. (Prod)": ("_os", "sum"),
                "Contratos": ("_contract", "nunique"),
                "_monitor_prod": (
                    "monitor",
                    "first",
                )
                if "monitor" in p_work.columns
                else ("technician", lambda _: "Sem monitor"),
                "_un_prod": (
                    "un",
                    "first",
                )
                if "un" in p_work.columns
                else ("technician", lambda _: "Sem U.N."),
                "_base_prod": (
                    "base",
                    "first",
                )
                if "base" in p_work.columns
                else ("technician", lambda _: "Sem base"),
                "_status_prod": (
                    "roster_status",
                    "first",
                )
                if "roster_status" in p_work.columns
                else ("technician", lambda _: "Sem cadastro"),
            }
        )
        prod_agg["Pontos Totais"] = prod_agg["Pontos Prod"] + prod_agg["Pontos Gpon"]

        if p_work["_period"].notna().any():
            prod_mensal = cast(
                Any,
                p_work.dropna(subset=["_period"]).groupby("_period", as_index=False),
            ).agg(
                **{
                    "Pontos Totais": ("_points", "sum"),
                    "O.S. (Prod)": ("_os", "sum"),
                    "Contratos": ("_contract", "nunique"),
                }
            )
            prod_mensal = prod_mensal.rename(columns={"_period": "period"})

    # 2) Agregação comercial (Consultivo)
    cons_agg = pd.DataFrame()
    cons_mensal = pd.DataFrame()
    contratos_cons_por_chave: dict[str, set[str]] = {}
    contratos_cons_global: set[str] = set()

    if not cons.empty:
        c_work = cons.copy()
        c_work["_q_cons"] = _col_consultivo(c_work, "Qtde. Cons.", "QTDE_CONSULTIVO")
        c_work["_q_prod"] = _col_consultivo(c_work, "Qtde. Prod.", "QTDE_PRODUTOS")
        c_work["_q_mesh"] = _col_consultivo(c_work, "Qtde. Mesh", "QTDE_MESH")
        c_work["_q_tv"] = _col_consultivo(c_work, "Qtde. TV", "QTDE_TV")
        c_work["_q_virtua"] = _col_consultivo(c_work, "Qtde. Virtua", "QTDE_VIRTUA")

        login_series = (
            c_work["LOGIN NETSALES"].astype(str).map(clean_code).str.upper()
            if "LOGIN NETSALES" in c_work.columns
            else pd.Series("", index=c_work.index)
        )
        nome_col = (
            "Técnico"
            if "Técnico" in c_work.columns
            else ("VENDEDOR" if "VENDEDOR" in c_work.columns else None)
        )
        vendedor_series = (
            c_work["VENDEDOR"].astype(str)
            if "VENDEDOR" in c_work.columns
            else pd.Series("", index=c_work.index)
        )
        nome_raw = (
            c_work[nome_col]
            .astype(str)
            .where(c_work[nome_col].astype(str).str.strip().ne(""), vendedor_series)
            if nome_col is not None
            else vendedor_series
        )

        # Prioridade: login no cadastro -> nome normalizado -> login como chave
        key_by_login = login_series.map(login_para_chave).fillna("")
        key_by_name = nome_raw.map(normalize_text).fillna("")
        c_work["_key"] = key_by_login.where(key_by_login.ne(""), key_by_name)
        c_work["_key"] = c_work["_key"].where(
            c_work["_key"].ne(""), login_series.where(login_series.ne("SEM LOGIN"), "")
        )
        c_work["_nome_cons"] = nome_raw.where(nome_raw.str.strip().ne(""), login_series)
        c_work = c_work[c_work["_key"].ne("")]

        if "CONTRATO" in c_work.columns:
            c_work["_contract"] = _limpar_contratos_validos(c_work["CONTRATO"])
        elif "contract" in c_work.columns:
            c_work["_contract"] = _limpar_contratos_validos(c_work["contract"])
        else:
            c_work["_contract"] = pd.NA

        ct_c_validos = c_work.dropna(subset=["_contract"])
        if not ct_c_validos.empty:
            contratos_cons_global = set(ct_c_validos["_contract"].astype(str).unique())
            for chave, grp in ct_c_validos.groupby("_key")["_contract"]:
                contratos_cons_por_chave[str(chave)] = set(grp.astype(str).unique())

        cons_agg = cast(Any, c_work.groupby("_key", as_index=False)).agg(
            **{
                "_tech_cons": ("_nome_cons", "first"),
                "Consultivos": ("_q_cons", "sum"),
                "Produtos": ("_q_prod", "sum"),
                "Mesh": ("_q_mesh", "sum"),
                "TV Box": ("_q_tv", "sum"),
                "Virtua": ("_q_virtua", "sum"),
                "_monitor_cons": (
                    "Monitor",
                    "first",
                )
                if "Monitor" in c_work.columns
                else ("_nome_cons", lambda _: "Sem monitor"),
                "_un_cons": (
                    "U.N.",
                    "first",
                )
                if "U.N." in c_work.columns
                else ("_nome_cons", lambda _: "Sem U.N."),
                "_base_cons": (
                    "Base",
                    "first",
                )
                if "Base" in c_work.columns
                else ("_nome_cons", lambda _: "Sem base"),
                "_status_cons": (
                    "Situação",
                    "first",
                )
                if "Situação" in c_work.columns
                else ("_nome_cons", lambda _: "Sem cadastro"),
            }
        )

        fonte_c_dt = "period" if "period" in c_work.columns else "DATA"
        if fonte_c_dt in c_work.columns:
            c_work["_period"] = _garantir_periodo(c_work[fonte_c_dt])
            if c_work["_period"].notna().any():
                cons_mensal = cast(
                    Any,
                    c_work.dropna(subset=["_period"]).groupby(
                        "_period", as_index=False
                    ),
                ).agg(Consultivos=("_q_cons", "sum"), Produtos=("_q_prod", "sum"))
                cons_mensal = cons_mensal.rename(columns={"_period": "period"})

    # 3) Junção completa Produção × Consultivo
    if prod_agg.empty and cons_agg.empty:
        vazio_tec = pd.DataFrame(columns=colunas_tec)
        return ResumoVisao360(
            por_tecnico=vazio_tec,
            evolucao_mensal=pd.DataFrame(columns=colunas_mensal),
            por_monitor=_resumir_dimensao_360(vazio_tec, "Monitor"),
            por_base=_resumir_dimensao_360(vazio_tec, "Base"),
            por_un=_resumir_dimensao_360(vazio_tec, "U.N."),
            pontos_totais=0.0,
            os_totais=0,
            contratos_totais=0,
            consultivos_totais=0,
            produtos_totais=0,
            conversao_pct=0.0,
            penetracao_pct=0.0,
            contratos_comum=0,
            total_tecnicos=0,
            elite_count=0,
            mediana_pontos=0.0,
            mediana_consultivos=0.0,
            mediana_pontos_os=0.0,
            mediana_conversao=0.0,
        )

    if prod_agg.empty:
        merged = cons_agg.copy()
    elif cons_agg.empty:
        merged = prod_agg.copy()
    else:
        merged = prod_agg.merge(cons_agg, on="_key", how="outer")

    for col_float in ("Pontos Prod", "Pontos Gpon", "Pontos Totais"):
        if col_float not in merged.columns:
            merged[col_float] = 0.0
        merged[col_float] = pd.to_numeric(merged[col_float], errors="coerce").fillna(
            0.0
        )
    for col_int in (
        "O.S. (Prod)",
        "Contratos",
        "Consultivos",
        "Produtos",
        "Mesh",
        "TV Box",
        "Virtua",
    ):
        if col_int not in merged.columns:
            merged[col_int] = 0
        merged[col_int] = (
            pd.to_numeric(merged[col_int], errors="coerce").fillna(0).astype(int)
        )

    def _pick_meta(
        key: str,
        roster_field: str,
        prod_val: Any,
        cons_val: Any,
        fallback: str,
    ) -> str:
        if key in mapa_roster and mapa_roster[key].get(roster_field):
            return mapa_roster[key][roster_field]
        for candidate in (prod_val, cons_val):
            txt = str(candidate or "").strip()
            if txt and txt not in {
                "nan",
                "None",
                "Não Identificado",
                "Não Identificada",
                "Sem cadastro",
            }:
                return txt
        return fallback

    def _col_vals(col_name: str) -> list[Any]:
        if col_name in merged.columns:
            return merged[col_name].tolist()
        return [None] * len(merged)

    nomes: list[str] = []
    situacoes: list[str] = []
    monitores: list[str] = []
    uns: list[str] = []
    bases: list[str] = []
    comum_list: list[int] = []

    for (
        k_raw,
        tech_p,
        tech_c,
        stat_p,
        stat_c,
        mon_p,
        mon_c,
        un_p,
        un_c,
        base_p,
        base_c,
    ) in zip(
        _col_vals("_key"),
        _col_vals("_tech_prod"),
        _col_vals("_tech_cons"),
        _col_vals("_status_prod"),
        _col_vals("_status_cons"),
        _col_vals("_monitor_prod"),
        _col_vals("_monitor_cons"),
        _col_vals("_un_prod"),
        _col_vals("_un_cons"),
        _col_vals("_base_prod"),
        _col_vals("_base_cons"),
        strict=False,
    ):
        k = str(k_raw or "")
        nomes.append(_pick_meta(k, "technician", tech_p, tech_c, k))
        situacoes.append(_pick_meta(k, "status", stat_p, stat_c, "Não cadastrado"))
        monitores.append(_pick_meta(k, "monitor", mon_p, mon_c, "Sem monitor"))
        uns.append(_pick_meta(k, "un", un_p, un_c, "Sem U.N."))
        bases.append(_pick_meta(k, "base", base_p, base_c, "Sem base"))
        cts_p = contratos_prod_por_chave.get(k, set())
        cts_c = contratos_cons_por_chave.get(k, set())
        comum_list.append(len(cts_p & cts_c))

    merged["Técnico"] = nomes
    merged["Situação"] = situacoes
    merged["Monitor"] = monitores
    merged["U.N."] = uns
    merged["Base"] = bases
    merged["Contratos em Comum"] = comum_list

    merged["Pontos / O.S."] = np.where(
        merged["O.S. (Prod)"] > 0,
        merged["Pontos Totais"] / merged["O.S. (Prod)"],
        0.0,
    )
    merged["Conversão (%)"] = np.where(
        merged["Consultivos"] > 0,
        merged["Produtos"] / merged["Consultivos"] * 100.0,
        0.0,
    )
    merged["Penetração Consultiva (%)"] = np.where(
        merged["Contratos"] > 0,
        merged["Consultivos"] / merged["Contratos"] * 100.0,
        0.0,
    )

    # Score 360° (0 a 100): 50% entrega técnica + 50% resultado comercial
    max_pts = float(merged["Pontos Totais"].max()) if not merged.empty else 0.0
    max_cons = float(merged["Consultivos"].max()) if not merged.empty else 0.0
    max_prods = float(merged["Produtos"].max()) if not merged.empty else 0.0
    norm_tec = merged["Pontos Totais"] / max_pts if max_pts > 0 else 0.0
    norm_cons = merged["Consultivos"] / max_cons if max_cons > 0 else 0.0
    norm_prod_com = merged["Produtos"] / max_prods if max_prods > 0 else 0.0
    norm_com = 0.5 * norm_cons + 0.5 * norm_prod_com
    merged["Score 360°"] = np.round((0.5 * norm_tec + 0.5 * norm_com) * 100.0, 1)

    ativos_tec = merged[merged["Pontos Totais"] > 0]
    ativos_com = merged[merged["Consultivos"] > 0]
    mediana_pontos = (
        float(ativos_tec["Pontos Totais"].median()) if not ativos_tec.empty else 0.0
    )
    mediana_consultivos = (
        float(ativos_com["Consultivos"].median()) if not ativos_com.empty else 0.0
    )
    mediana_pontos_os = (
        float(ativos_tec["Pontos / O.S."].median()) if not ativos_tec.empty else 0.0
    )
    mediana_conversao = (
        float(ativos_com["Conversão (%)"].median()) if not ativos_com.empty else 0.0
    )

    merged["Quadrante 360°"] = _classificar_quadrante_series(
        merged["Pontos Totais"],
        merged["Consultivos"],
        mediana_pontos,
        mediana_consultivos,
    )

    por_tecnico = (
        merged[colunas_tec]
        .sort_values(["Score 360°", "Pontos Totais"], ascending=[False, False])
        .reset_index(drop=True)
    )

    # 4) Evolução mensal combinada
    if prod_mensal.empty and cons_mensal.empty:
        evolucao = pd.DataFrame(columns=colunas_mensal)
    elif prod_mensal.empty:
        evolucao = cons_mensal.copy()
        evolucao["Pontos Totais"] = 0.0
        evolucao["O.S. (Prod)"] = 0
        evolucao["Contratos"] = 0
    elif cons_mensal.empty:
        evolucao = prod_mensal.copy()
        evolucao["Consultivos"] = 0
        evolucao["Produtos"] = 0
    else:
        evolucao = prod_mensal.merge(cons_mensal, on="period", how="outer")

    if not evolucao.empty:
        evolucao["Pontos Totais"] = pd.to_numeric(
            evolucao["Pontos Totais"], errors="coerce"
        ).fillna(0.0)
        for c_int in ("O.S. (Prod)", "Contratos", "Consultivos", "Produtos"):
            evolucao[c_int] = (
                pd.to_numeric(evolucao[c_int], errors="coerce").fillna(0).astype(int)
            )
        evolucao = evolucao.sort_values("period").reset_index(drop=True)
        evolucao["Competência"] = evolucao["period"].map(month_label)
        evolucao["Conversão (%)"] = np.where(
            evolucao["Consultivos"] > 0,
            evolucao["Produtos"] / evolucao["Consultivos"] * 100.0,
            0.0,
        )
        evolucao["Penetração Consultiva (%)"] = np.where(
            evolucao["Contratos"] > 0,
            evolucao["Consultivos"] / evolucao["Contratos"] * 100.0,
            0.0,
        )
        evolucao = evolucao[colunas_mensal]

    pontos_totais = float(por_tecnico["Pontos Totais"].sum())
    os_totais = int(por_tecnico["O.S. (Prod)"].sum())
    contratos_totais = int(por_tecnico["Contratos"].sum())
    consultivos_totais = int(por_tecnico["Consultivos"].sum())
    produtos_totais = int(por_tecnico["Produtos"].sum())
    conversao_pct = (
        (produtos_totais / consultivos_totais * 100.0)
        if consultivos_totais > 0
        else 0.0
    )
    penetracao_pct = (
        (consultivos_totais / contratos_totais * 100.0) if contratos_totais > 0 else 0.0
    )
    contratos_comum = len(contratos_prod_global & contratos_cons_global)
    elite_count = int(por_tecnico["Quadrante 360°"].eq("Elite 360°").sum())

    return ResumoVisao360(
        por_tecnico=por_tecnico,
        evolucao_mensal=evolucao,
        por_monitor=_resumir_dimensao_360(por_tecnico, "Monitor"),
        por_base=_resumir_dimensao_360(por_tecnico, "Base"),
        por_un=_resumir_dimensao_360(por_tecnico, "U.N."),
        pontos_totais=pontos_totais,
        os_totais=os_totais,
        contratos_totais=contratos_totais,
        consultivos_totais=consultivos_totais,
        produtos_totais=produtos_totais,
        conversao_pct=conversao_pct,
        penetracao_pct=penetracao_pct,
        contratos_comum=contratos_comum,
        total_tecnicos=len(por_tecnico),
        elite_count=elite_count,
        mediana_pontos=mediana_pontos,
        mediana_consultivos=mediana_consultivos,
        mediana_pontos_os=mediana_pontos_os,
        mediana_conversao=mediana_conversao,
    )


def resumo_consultivo_tecnico(
    consultivo_frame: pd.DataFrame | None,
    technician: str,
    *,
    login: str = "",
    period_start: pd.Timestamp | None = None,
    period_end: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Extrai resumo consultivo de um técnico específico para o dossiê individual."""
    vazio = {
        "consultivos": 0,
        "produtos": 0,
        "mesh": 0,
        "tv": 0,
        "virtua": 0,
        "conversao_pct": 0.0,
        "registros": 0,
    }
    if consultivo_frame is None or consultivo_frame.empty:
        return vazio

    df = normalizar_coluna_data_consultivo(consultivo_frame)
    if period_start is not None and period_end is not None and "DATA" in df.columns:
        dt = df["DATA"]
        mask_dt = dt.notna() & dt.between(period_start, period_end)
        df = df.loc[mask_dt]
        if df.empty:
            return vazio

    tech_key = normalize_text(technician)
    login_clean = clean_code(login).upper()
    mask = pd.Series(False, index=df.index)
    if login_clean and "LOGIN NETSALES" in df.columns:
        mask = mask | df["LOGIN NETSALES"].astype(str).map(clean_code).str.upper().eq(
            login_clean
        )
    for col in ("Técnico", "VENDEDOR"):
        if col in df.columns:
            mask = mask | df[col].astype(str).map(normalize_text).eq(tech_key)

    rec = df.loc[mask]
    if rec.empty:
        return vazio

    q_cons = int(_col_consultivo(rec, "Qtde. Cons.", "QTDE_CONSULTIVO").sum())
    q_prod = int(_col_consultivo(rec, "Qtde. Prod.", "QTDE_PRODUTOS").sum())
    q_mesh = int(_col_consultivo(rec, "Qtde. Mesh", "QTDE_MESH").sum())
    q_tv = int(_col_consultivo(rec, "Qtde. TV", "QTDE_TV").sum())
    q_vir = int(_col_consultivo(rec, "Qtde. Virtua", "QTDE_VIRTUA").sum())
    return {
        "consultivos": q_cons,
        "produtos": q_prod,
        "mesh": q_mesh,
        "tv": q_tv,
        "virtua": q_vir,
        "conversao_pct": (q_prod / q_cons * 100.0) if q_cons > 0 else 0.0,
        "registros": int(len(rec)),
    }


def _aplicar_layout_360(fig: go.Figure, altura: int = 410) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=12, r=18, t=34, b=16),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=Cores.TEXTO_3, size=11),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        hoverlabel=dict(bgcolor="white", font_color=Cores.TEXTO),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor=Cores.BORDA, zeroline=False)
    return fig


def _grafico_quadrante_360(
    df_tec: pd.DataFrame,
    *,
    col_x: str,
    col_y: str,
    rotulo_x: str,
    rotulo_y: str,
    mediana_x: float,
    mediana_y: float,
) -> go.Figure:
    fig = go.Figure()
    quadrantes_atual = _classificar_quadrante_series(
        df_tec[col_x], df_tec[col_y], mediana_x, mediana_y
    )
    work = df_tec.copy()
    work["_quad_view"] = quadrantes_atual

    for quad in QUADRANTES_360_ORDEM:
        sub = work[work["_quad_view"].eq(quad)]
        if sub.empty:
            continue
        cor_ponto = CORES_QUADRANTES_360[quad][0]
        fig.add_scatter(
            x=sub[col_x],
            y=sub[col_y],
            mode="markers+text" if len(work) <= 20 else "markers",
            name=f"{quad} ({len(sub)})",
            text=sub["Técnico"].str.split().str[0],
            textposition="top center",
            textfont=dict(size=10, color=Cores.TEXTO_2),
            marker=dict(
                size=np.clip(sub["Score 360°"] * 0.24 + 9, 10, 30),
                color=cor_ponto,
                opacity=0.88,
                line=dict(color="#FFFFFF", width=1.5),
            ),
            customdata=np.stack(
                [
                    sub["Técnico"],
                    sub["Monitor"],
                    sub["Base"],
                    sub["Score 360°"],
                    sub["Contratos"],
                    sub["Produtos"],
                ],
                axis=-1,
            ),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Monitor: %{customdata[1]} · Base: %{customdata[2]}<br>"
                f"{rotulo_x}: %{{x:,.2f}}<br>"
                f"{rotulo_y}: %{{y:,.2f}}<br>"
                "Contratos: %{customdata[4]} · Produtos: %{customdata[5]}<br>"
                "Score 360°: <b>%{customdata[3]:.1f}</b><extra></extra>"
            ),
        )

    fig.add_vline(
        x=mediana_x,
        line_dash="dot",
        line_color="#94A3B8",
        annotation_text=f"Mediana: {formatar_numero_br(mediana_x, 1)}",
        annotation_position="top right",
        annotation_font_size=10,
    )
    fig.add_hline(
        y=mediana_y,
        line_dash="dot",
        line_color="#94A3B8",
        annotation_text=f"Mediana: {formatar_numero_br(mediana_y, 1)}",
        annotation_position="bottom right",
        annotation_font_size=10,
    )
    fig.update_xaxes(title=rotulo_x, gridcolor=Cores.BORDA, showgrid=True)
    fig.update_yaxes(title=rotulo_y)
    return _aplicar_layout_360(fig, altura=440)


def _grafico_evolucao_360(evolucao: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_bar(
        x=evolucao["Competência"],
        y=evolucao["Pontos Totais"],
        name="Pontos Totais",
        marker_color=Cores.PRIMARIA,
        opacity=0.88,
        yaxis="y1",
        hovertemplate="<b>%{x}</b><br>Pontos: %{y:,.2f}<extra></extra>",
    )
    fig.add_scatter(
        x=evolucao["Competência"],
        y=evolucao["Consultivos"],
        name="Consultivos",
        mode="lines+markers",
        line=dict(color=Cores.SECUNDARIA, width=2.8),
        marker=dict(size=7),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Consultivos: %{y:,}<extra></extra>",
    )
    fig.add_scatter(
        x=evolucao["Competência"],
        y=evolucao["Produtos"],
        name="Produtos",
        mode="lines+markers",
        line=dict(color="#047857", width=2.2, dash="dot"),
        marker=dict(size=6),
        yaxis="y2",
        hovertemplate="<b>%{x}</b><br>Produtos: %{y:,}<extra></extra>",
    )
    fig.update_layout(
        yaxis=dict(title="Pontos Totais", gridcolor=Cores.BORDA, zeroline=False),
        yaxis2=dict(
            title="Consultivos / Produtos",
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=False,
        ),
    )
    return _aplicar_layout_360(fig, altura=370)


def _estilo_quadrante(valor: object) -> str:
    cores = CORES_QUADRANTES_360.get(str(valor))
    if cores is None:
        return ""
    _, bg, fg = cores
    return f"background-color: {bg}; color: {fg}; font-weight: 700;"


def _filtrar_base_por_periodo_e_cadastro(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Renderiza filtros unificados da Visão 360° aplicados igualmente às duas bases."""
    prod_ok = production_frame.copy() if not production_frame.empty else pd.DataFrame()
    cons_ok = (
        normalizar_coluna_data_consultivo(consultivo_frame)
        if not consultivo_frame.empty
        else pd.DataFrame()
    )

    datas_series: list[pd.Series] = []
    if not prod_ok.empty and "reference_date" in prod_ok.columns:
        datas_series.append(pd.to_datetime(prod_ok["reference_date"], errors="coerce"))
    if not cons_ok.empty and "DATA" in cons_ok.columns:
        datas_series.append(pd.to_datetime(cons_ok["DATA"], errors="coerce"))
    todas_datas = (
        pd.concat(datas_series, ignore_index=True).dropna()
        if datas_series
        else pd.Series(dtype="datetime64[ns]")
    )

    # Opções cadastrais unificadas
    status_set: set[str] = set()
    monitor_set: set[str] = set()
    base_set: set[str] = set()
    un_set: set[str] = set()
    if not prod_ok.empty:
        if "roster_status" in prod_ok.columns:
            status_set.update(prod_ok["roster_status"].dropna().astype(str).unique())
        if "monitor" in prod_ok.columns:
            monitor_set.update(prod_ok["monitor"].dropna().astype(str).unique())
        if "base" in prod_ok.columns:
            base_set.update(prod_ok["base"].dropna().astype(str).unique())
        if "un" in prod_ok.columns:
            un_set.update(prod_ok["un"].dropna().astype(str).unique())
    if not cons_ok.empty:
        if "Situação" in cons_ok.columns:
            status_set.update(cons_ok["Situação"].dropna().astype(str).unique())
        if "Monitor" in cons_ok.columns:
            monitor_set.update(cons_ok["Monitor"].dropna().astype(str).unique())
        if "Base" in cons_ok.columns:
            base_set.update(cons_ok["Base"].dropna().astype(str).unique())
        if "U.N." in cons_ok.columns:
            un_set.update(cons_ok["U.N."].dropna().astype(str).unique())
    if roster_frame is not None and not roster_frame.empty:
        if "status" in roster_frame.columns:
            status_set.update(roster_frame["status"].dropna().astype(str).unique())

    status_opts = [s for s in ROSTER_STATUS_ORDER if s in status_set] + sorted(
        s for s in status_set if s not in ROSTER_STATUS_ORDER
    )
    default_status = ["ATIVO"] if "ATIVO" in status_opts else []
    monitor_opts = sorted(m for m in monitor_set if m.strip())
    base_opts = sorted(b for b in base_set if b.strip())
    un_opts = sorted(u for u in un_set if u.strip())

    with st.container(border=True):
        r1 = st.columns([1.2, 1.2, 1.2, 1.15, 1.15])
        with r1[0]:
            periodo_sel = st.selectbox(
                "Período 360°",
                [
                    "Últimos 3 meses",
                    "Últimos 6 meses",
                    "Últimos 12 meses",
                    "Todo o período",
                ],
                index=2,
                key="v360_periodo",
            )
        with r1[1]:
            sel_status = st.multiselect(
                "Situação",
                status_opts,
                default=default_status,
                placeholder="Todas",
                key="v360_status",
            )
        with r1[2]:
            sel_monitor = st.multiselect(
                "Monitor",
                monitor_opts,
                default=[],
                placeholder="Todos",
                key="v360_monitor",
            )
        with r1[3]:
            sel_base = st.multiselect(
                "Base",
                base_opts,
                default=[],
                placeholder="Todas",
                key="v360_base",
            )
        with r1[4]:
            sel_un = st.multiselect(
                "U.N.",
                un_opts,
                default=[],
                placeholder="Todas",
                key="v360_un",
            )

    cutoff: pd.Timestamp | None = None
    if not todas_datas.empty and periodo_sel.startswith("Últimos"):
        meses = int(periodo_sel.split()[1])
        max_dt = todas_datas.max()
        cutoff = (max_dt.to_period("M") - (meses - 1)).to_timestamp()

    if not prod_ok.empty:
        mask_p = pd.Series(True, index=prod_ok.index)
        if cutoff is not None and "reference_date" in prod_ok.columns:
            mask_p &= (
                pd.to_datetime(prod_ok["reference_date"], errors="coerce") >= cutoff
            )
        if sel_status and "roster_status" in prod_ok.columns:
            mask_p &= prod_ok["roster_status"].isin(sel_status)
        if sel_monitor and "monitor" in prod_ok.columns:
            mask_p &= prod_ok["monitor"].isin(sel_monitor)
        if sel_base and "base" in prod_ok.columns:
            mask_p &= prod_ok["base"].isin(sel_base)
        if sel_un and "un" in prod_ok.columns:
            mask_p &= prod_ok["un"].isin(sel_un)
        prod_ok = prod_ok.loc[mask_p]

    if not cons_ok.empty:
        mask_c = pd.Series(True, index=cons_ok.index)
        if cutoff is not None and "DATA" in cons_ok.columns:
            mask_c &= cons_ok["DATA"] >= cutoff
        if sel_status and "Situação" in cons_ok.columns:
            mask_c &= cons_ok["Situação"].isin(sel_status)
        if sel_monitor and "Monitor" in cons_ok.columns:
            mask_c &= cons_ok["Monitor"].isin(sel_monitor)
        if sel_base and "Base" in cons_ok.columns:
            mask_c &= cons_ok["Base"].isin(sel_base)
        if sel_un and "U.N." in cons_ok.columns:
            mask_c &= cons_ok["U.N."].isin(sel_un)
        cons_ok = cons_ok.loc[mask_c]

    return prod_ok, cons_ok


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _calcular_visao_360_cached(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
) -> ResumoVisao360:
    return calcular_visao_360(production_frame, consultivo_frame, roster_frame)


@st.cache_data(ttl=1800, max_entries=8, show_spinner=False)
def _gerar_pacote_360_xlsx_cached(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None,
) -> bytes:
    from components.pacote_executivo import gerar_pacote_executivo_xlsx

    return gerar_pacote_executivo_xlsx(
        production_frame,
        consultivo_frame,
        roster_frame,
        periodo_label="Recorte ativo Visão 360°",
    )


def render_visao_360(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None = None,
) -> None:
    """Renderiza o módulo executivo Visão 360° Operacional × Comercial."""
    prod_f, cons_f = _filtrar_base_por_periodo_e_cadastro(
        production_frame, consultivo_frame, roster_frame
    )
    resumo = _calcular_visao_360_cached(prod_f, cons_f, roster_frame)

    if resumo.por_tecnico.empty:
        render_insight(
            "Não há registros de Produção ou Consultivo para os filtros selecionados na Visão 360°.",
            tipo="info",
        )
        return

    render_ticker(
        [
            ("Pontos Totais", format_points(resumo.pontos_totais)),
            ("Contratos Atendidos", formatar_numero_br(resumo.contratos_totais)),
            ("Consultivos", formatar_numero_br(resumo.consultivos_totais)),
            ("Produtos Vendidos", formatar_numero_br(resumo.produtos_totais)),
            (
                "Penetração Consultiva",
                f"{resumo.penetracao_pct:.1f}%".replace(".", ","),
            ),
            (
                "Conversão Comercial",
                f"{resumo.conversao_pct:.1f}%".replace(".", ","),
            ),
            (
                "Elite 360°",
                f"{resumo.elite_count} de {resumo.total_tecnicos} técnicos",
            ),
        ],
        label="Destaques 360° Operacional × Comercial",
    )

    k1 = st.columns(4)
    with k1[0]:
        render_kpi_card(
            "PONTOS TOTAIS (PROD + GPON)",
            format_points(resumo.pontos_totais),
            f"{formatar_numero_br(resumo.os_totais)} O.S. · {formatar_numero_br(resumo.contratos_totais)} contratos",
            "⚡",
            "kpi-card--azul",
        )
    with k1[1]:
        render_kpi_card(
            "CONSULTIVOS & PRODUTOS",
            formatar_numero_br(resumo.consultivos_totais),
            f"{formatar_numero_br(resumo.produtos_totais)} produtos ({resumo.conversao_pct:.1f}% conv.)".replace(
                ".", ","
            ),
            "🎯",
            "kpi-card--laranja",
        )
    with k1[2]:
        render_kpi_card(
            "PENETRAÇÃO CONSULTIVA",
            f"{resumo.penetracao_pct:.1f}%".replace(".", ","),
            f"Consultivos ÷ Contratos · {formatar_numero_br(resumo.contratos_comum)} contratos em comum",
            "🔗",
            "kpi-card--verde",
        )
    with k1[3]:
        elite_share = (
            resumo.elite_count / resumo.total_tecnicos * 100.0
            if resumo.total_tecnicos > 0
            else 0.0
        )
        render_kpi_card(
            "TÉCNICOS ELITE 360°",
            f"{resumo.elite_count} / {resumo.total_tecnicos}",
            f"{elite_share:.1f}% acima das medianas técnica e comercial".replace(
                ".", ","
            ),
            "🏆",
            "kpi-card--roxo",
        )

    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

    @st.fragment
    def _render_subsecoes_360() -> None:
        # Renderização sob demanda via segmented_control (evita custo de abas ocultas)
        visao_ativa = (
            st.segmented_control(
                "Seção analítica 360°",
                options=[
                    "🎯 Quadrante 360° & Evolução",
                    "🏢 Consolidado (Monitor · Base · U.N.)",
                    "📋 Matriz 360° & Exportação",
                ],
                default="🎯 Quadrante 360° & Evolução",
                label_visibility="collapsed",
                key="v360_secao_ativa",
            )
            or "🎯 Quadrante 360° & Evolução"
        )

        if visao_ativa == "🎯 Quadrante 360° & Evolução":
            c_eixo, _ = st.columns([1.8, 2.2])
            with c_eixo:
                modo_eixos = st.selectbox(
                    "Eixos do Quadrante Estratégico",
                    [
                        "Pontos Totais × Consultivos",
                        "Pontos / O.S. × Conversão (%)",
                        "Contratos × Produtos",
                    ],
                    key="v360_quadrante_eixos",
                )
            if modo_eixos == "Pontos / O.S. × Conversão (%)":
                cx, cy = "Pontos / O.S.", "Conversão (%)"
                mx, my = resumo.mediana_pontos_os, resumo.mediana_conversao
            elif modo_eixos == "Contratos × Produtos":
                cx, cy = "Contratos", "Produtos"
                at_c = resumo.por_tecnico[resumo.por_tecnico["Contratos"] > 0]
                at_p = resumo.por_tecnico[resumo.por_tecnico["Produtos"] > 0]
                mx = float(at_c["Contratos"].median()) if not at_c.empty else 0.0
                my = float(at_p["Produtos"].median()) if not at_p.empty else 0.0
            else:
                cx, cy = "Pontos Totais", "Consultivos"
                mx, my = resumo.mediana_pontos, resumo.mediana_consultivos

            with st.container(border=True):
                render_section_header(
                    f"Quadrante Estratégico 360° · {modo_eixos}",
                    subtitulo="Tamanho da bolha proporcional ao Score 360° (50% entrega técnica + 50% entrega comercial)",
                    icone="🎯",
                )
                st.plotly_chart(
                    _grafico_quadrante_360(
                        resumo.por_tecnico,
                        col_x=cx,
                        col_y=cy,
                        rotulo_x=cx,
                        rotulo_y=cy,
                        mediana_x=mx,
                        mediana_y=my,
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="v360_chart_quadrante",
                )

            if not resumo.evolucao_mensal.empty:
                with st.container(border=True):
                    render_section_header(
                        "Evolução Mensal Integrada · Produção × Consultivo",
                        subtitulo="Comparativo mensal entre pontuação técnica (barras) e volume comercial (linhas)",
                        icone="📈",
                    )
                    st.plotly_chart(
                        _grafico_evolucao_360(resumo.evolucao_mensal),
                        width="stretch",
                        config=CHART_CONFIG,
                        key="v360_chart_evolucao",
                    )

        elif visao_ativa == "🏢 Consolidado (Monitor · Base · U.N.)":
            dim_sel = (
                st.segmented_control(
                    "Dimensão de agrupamento",
                    options=["Monitor", "Base", "U.N."],
                    default="Monitor",
                    label_visibility="collapsed",
                    key="v360_dimensao_rollup",
                )
                or "Monitor"
            )
            df_dim = (
                resumo.por_monitor
                if dim_sel == "Monitor"
                else (resumo.por_base if dim_sel == "Base" else resumo.por_un)
            )
            if df_dim.empty:
                render_insight(f"Sem dados consolidados para {dim_sel}.", tipo="info")
            else:
                top_dim = df_dim.head(15).sort_values(
                    "Score 360° Médio", ascending=True
                )
                fig_dim = go.Figure()
                fig_dim.add_bar(
                    y=top_dim[dim_sel],
                    x=top_dim["Score 360° Médio"],
                    orientation="h",
                    name="Score 360° Médio",
                    marker_color=Cores.PRIMARIA,
                    text=[f"{v:.1f}" for v in top_dim["Score 360° Médio"]],
                    textposition="outside",
                    hovertemplate=(
                        "<b>%{y}</b><br>Score 360° Médio: %{x:.1f}<extra></extra>"
                    ),
                )
                fig_dim.update_xaxes(range=[0, 115], title="Score 360° Médio (0–100)")
                with st.container(border=True):
                    render_section_header(
                        f"Ranking 360° por {dim_sel}",
                        subtitulo="Índice composto de entrega técnica e performance consultiva",
                        icone="🏢",
                    )
                    st.plotly_chart(
                        _aplicar_layout_360(
                            fig_dim, altura=max(320, min(620, 120 + len(top_dim) * 32))
                        ),
                        width="stretch",
                        config=CHART_CONFIG,
                        key=f"v360_chart_dim_{dim_sel}",
                    )
                st.dataframe(
                    df_dim,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
                        "Conversão (%)": st.column_config.NumberColumn(format="%.1f%%"),
                        "Penetração Consultiva (%)": st.column_config.NumberColumn(
                            format="%.1f%%"
                        ),
                        "Score 360° Médio": st.column_config.ProgressColumn(
                            min_value=0.0, max_value=100.0, format="%.1f"
                        ),
                    },
                )

        else:
            quad_filtro = st.multiselect(
                "Filtrar por Quadrante 360°",
                options=list(QUADRANTES_360_ORDEM),
                default=[],
                placeholder="Todos os quadrantes",
                key="v360_filtro_quadrante",
            )
            df_tabela = resumo.por_tecnico
            if quad_filtro:
                df_tabela = df_tabela[df_tabela["Quadrante 360°"].isin(quad_filtro)]

            st.dataframe(
                df_tabela.style.map(_estilo_quadrante, subset=["Quadrante 360°"]),
                width="stretch",
                hide_index=True,
                column_config={
                    "Pontos Prod": st.column_config.NumberColumn(format="%.2f"),
                    "Pontos Gpon": st.column_config.NumberColumn(format="%.2f"),
                    "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
                    "Pontos / O.S.": st.column_config.NumberColumn(format="%.2f"),
                    "Conversão (%)": st.column_config.NumberColumn(format="%.1f%%"),
                    "Penetração Consultiva (%)": st.column_config.NumberColumn(
                        format="%.1f%%"
                    ),
                    "Score 360°": st.column_config.ProgressColumn(
                        min_value=0.0, max_value=100.0, format="%.1f"
                    ),
                },
            )
            if not df_tabela.empty and "Técnico" in df_tabela.columns:
                render_drilldown_tecnico(
                    df_tabela["Técnico"].tolist(),
                    key_prefix="v360",
                )
            exp_c1, exp_c2 = st.columns(2)
            with exp_c1:
                st.download_button(
                    "Baixar matriz Visão 360° em CSV",
                    data=sanitizar_csv_exportacao(df_tabela),
                    file_name="totale_visao_360_operacional_comercial.csv",
                    mime="text/csv",
                    key="v360_download_csv",
                    use_container_width=True,
                )
            with exp_c2:
                st.download_button(
                    "📊 Baixar Pacote Executivo (.xlsx)",
                    data=_gerar_pacote_360_xlsx_cached(prod_f, cons_f, roster_frame),
                    file_name="totale_pacote_executivo_360.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="v360_download_xlsx",
                    use_container_width=True,
                )

    _render_subsecoes_360()


__all__ = [
    "QUADRANTES_360_ORDEM",
    "ResumoVisao360",
    "calcular_visao_360",
    "render_visao_360",
    "resumo_consultivo_tecnico",
]
