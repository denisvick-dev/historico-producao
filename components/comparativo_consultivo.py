"""Comparativo interanual 2025 x 2026 de Consultivos e Mix de Produtos."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import html
from typing import Any, Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    TemaKPIType,
    TipoInsightType,
    TipoTrendType,
    formatar_delta_decimal_br,
    formatar_delta_inteiro_br,
    formatar_numero_br,
    formatar_variacao_pct_br,
    injetar_css,
    render_delta_card,
    render_insight,
    render_kpi,
    render_section_header,
    render_ticker,
)
from components.consultivo import (
    CONFIG_CONSULTIVO,
    formatar_data_br_consultivo,
    sanitizar_csv_exportacao,
)
from components.painel_quantidades import CHART_CONFIG
from production import (
    DEFAULT_CONSULTIVO_FOLDER_ID,
    ROSTER_ACTIVE_TAB,
    clean_code,
    converter_data_consultivo_br,
    normalize_text,
    process_consultivo_upload,
    save_consultivo_records,
)

ModoMesesConsultivo = Literal["equivalente", "ano_completo", "personalizado"]
EscopoEquipeConsultivo = Literal["todos", "ativos", "mesma_equipe"]

MESES_CALENDARIO: tuple[tuple[int, str, str], ...] = (
    (1, "Jan", "Janeiro"),
    (2, "Fev", "Fevereiro"),
    (3, "Mar", "Março"),
    (4, "Abr", "Abril"),
    (5, "Mai", "Maio"),
    (6, "Jun", "Junho"),
    (7, "Jul", "Julho"),
    (8, "Ago", "Agosto"),
    (9, "Set", "Setembro"),
    (10, "Out", "Outubro"),
    (11, "Nov", "Novembro"),
    (12, "Dez", "Dezembro"),
)

_MAPA_MES_ABREV = {num: abrev for num, abrev, _ in MESES_CALENDARIO}

_COR_2025_CONS = "#64748B"
_COR_2026_CONS = "#012869"
_COR_2025_PROD = "#94A3B8"
_COR_2026_PROD = "#F37C04"
_COR_MESH = "#16A34A"
_COR_TV = "#7C3AED"
_COR_VIRTUA = "#0EA5E9"

REGRA_COMPARATIVO_CONSULTIVO = (
    "Consultivos apurados pela regra oficial de tabulação (1 por TV ou Internet, "
    "2 em vendas combinadas TV + Internet) · Produtos apurados pelos códigos seriais/O.S. "
    "registrados em OBSERVAÇÃO (Mesh + TV Box + Virtua) · Datas em padrão DD/MM/AAAA."
)


@dataclass(frozen=True)
class ResumoComparativoConsultivo:
    """Estrutura auditável do comparativo 2025 x 2026 de Consultivos."""

    ano_base: int
    ano_comp: int
    modo_solicitado: ModoMesesConsultivo
    modo_efetivo: ModoMesesConsultivo
    fallback_sem_intersecao: bool
    escopo_equipe: EscopoEquipeConsultivo
    meses_disponiveis_base: list[int]
    meses_disponiveis_comp: list[int]
    meses_considerados: list[int]
    data_min_base: str
    data_max_base: str
    data_min_comp: str
    data_max_comp: str
    consultivos_base: int
    consultivos_comp: int
    delta_consultivos: int
    pct_consultivos: float | None
    produtos_base: int
    produtos_comp: int
    delta_produtos: int
    pct_produtos: float | None
    mesh_base: int
    mesh_comp: int
    delta_mesh: int
    pct_mesh: float | None
    tv_base: int
    tv_comp: int
    delta_tv: int
    pct_tv: float | None
    virtua_base: int
    virtua_comp: int
    delta_virtua: int
    pct_virtua: float | None
    conversao_base: float
    conversao_comp: float
    delta_conversao: float
    pct_conversao: float | None
    media_mensal_cons_base: float
    media_mensal_cons_comp: float
    pct_media_cons: float | None
    media_mensal_prod_base: float
    media_mensal_prod_comp: float
    pct_media_prod: float | None
    meses_ativos_base: int
    meses_ativos_comp: int
    equipes_produtivas_base: int
    equipes_produtivas_comp: int
    equipes_comuns: int
    cons_por_equipe_base: float
    cons_por_equipe_comp: float
    prod_por_equipe_base: float
    prod_por_equipe_comp: float
    taxa_meta_tecnico_base: float
    taxa_meta_tecnico_comp: float
    mensal: pd.DataFrame
    mix_produtos: pd.DataFrame
    por_tipo_servico: pd.DataFrame
    por_base: pd.DataFrame
    por_monitor: pd.DataFrame
    por_un: pd.DataFrame
    por_vendedor: pd.DataFrame

    @property
    def rotulo_recorte_meses(self) -> str:
        return _formatar_lista_meses(self.meses_considerados)


def _variacao_pct(atual: float | int, base: float | int) -> float | None:
    base_f = float(base)
    atual_f = float(atual)
    if base_f == 0.0:
        return None
    return ((atual_f - base_f) / base_f) * 100.0


def _formatar_pct_br(valor: float | None, *, com_sinal: bool = True) -> str:
    if valor is None or pd.isna(valor):
        return "Novo"
    sinal = "+" if com_sinal and valor > 0 else ""
    return f"{sinal}{valor:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")


def _formatar_decimal_br(
    valor: float, casas: int = 2, *, com_sinal: bool = False
) -> str:
    if pd.isna(valor):
        return "—"
    sinal = "+" if com_sinal and valor > 0 else ""
    return (
        f"{sinal}{valor:,.{casas}f}".replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def _formatar_lista_meses(meses: list[int]) -> str:
    if not meses:
        return "Nenhum mês"
    ordenados = sorted(set(meses))
    if ordenados == list(range(ordenados[0], ordenados[-1] + 1)) and len(ordenados) > 2:
        return f"{_MAPA_MES_ABREV[ordenados[0]]} a {_MAPA_MES_ABREV[ordenados[-1]]} ({len(ordenados)} meses)"
    nomes = [_MAPA_MES_ABREV[m] for m in ordenados if m in _MAPA_MES_ABREV]
    return ", ".join(nomes)


def _limpar_dimensao(serie: pd.Series, padrao: str) -> pd.Series:
    limpa = serie.fillna("").astype(str).str.strip()
    invalidos = limpa.str.lower().isin(
        {"", "nan", "none", "null", "<na>", "não identificado", "nao identificado"}
    )
    return limpa.mask(invalidos, padrao)


def _preparar_base_consultivo_comparativa(
    consultivo_frame: pd.DataFrame,
    roster: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Normaliza colunas, datas DD/MM/AAAA e chaves de equipe sem alterar o DataFrame original."""
    colunas_saida = [
        "_dt",
        "year",
        "month",
        "period",
        "_seller_key",
        "login",
        "seller",
        "monitor",
        "base",
        "un",
        "roster_status",
        "tipo_servico",
        "qtde_cons",
        "qtde_prod",
        "qtde_mesh",
        "qtde_tv",
        "qtde_virtua",
    ]
    if consultivo_frame is None or consultivo_frame.empty:
        return pd.DataFrame(columns=colunas_saida)

    work = consultivo_frame.copy()

    # Normalização estrita de datas em padrão brasileiro DD/MM/AAAA (sem inversão MM/DD).
    if "DATA" in work.columns:
        datas = converter_data_consultivo_br(work["DATA"])
    elif "reference_date" in work.columns:
        datas = converter_data_consultivo_br(work["reference_date"])
    else:
        return pd.DataFrame(columns=colunas_saida)

    work["_dt"] = datas
    work = work[work["_dt"].notna()].copy()
    if work.empty:
        return pd.DataFrame(columns=colunas_saida)

    def _col_int(opcoes: tuple[str, ...]) -> pd.Series:
        for c in opcoes:
            if c in work.columns:
                return pd.to_numeric(work[c], errors="coerce").fillna(0).astype(int)
        return pd.Series(0, index=work.index, dtype="int64")

    work["qtde_cons"] = _col_int(("Qtde. Cons.", "QTDE_CONSULTIVO", "qtde_consultivo"))
    work["qtde_prod"] = _col_int(("Qtde. Prod.", "QTDE_PRODUTOS", "qtde_produtos"))
    work["qtde_mesh"] = _col_int(("Qtde. Mesh", "QTDE_MESH", "qtde_mesh"))
    work["qtde_tv"] = _col_int(("Qtde. TV", "QTDE_TV", "qtde_tv"))
    work["qtde_virtua"] = _col_int(("Qtde. Virtua", "QTDE_VIRTUA", "qtde_virtua"))

    login_raw = (
        work["LOGIN NETSALES"]
        if "LOGIN NETSALES" in work.columns
        else (
            work["login_netsales"]
            if "login_netsales" in work.columns
            else pd.Series("", index=work.index)
        )
    )
    login_clean = login_raw.fillna("").map(lambda v: clean_code(v).upper())
    login_clean = login_clean.mask(login_clean.isin({"", "SEMLOGIN", "SEM LOGIN"}), "")

    seller_raw = (
        work["Técnico"].where(
            work["Técnico"].fillna("").astype(str).str.strip().ne(""),
            work.get("VENDEDOR", ""),
        )
        if "Técnico" in work.columns
        else (
            work["VENDEDOR"]
            if "VENDEDOR" in work.columns
            else work.get("seller", pd.Series("", index=work.index))
        )
    )
    seller_clean = _limpar_dimensao(pd.Series(seller_raw, index=work.index), "")

    # Enriquecimento opcional com lista_ativos caso o DataFrame venha cru em testes.
    if roster is not None and not roster.empty:
        r_copy = roster.copy()
        if "source_tab" in r_copy.columns:
            r_copy["_prio"] = (
                r_copy["source_tab"].astype(str).ne(ROSTER_ACTIVE_TAB)
            ).astype(int)
            r_copy = r_copy.sort_values("_prio")
        r_copy["_lg"] = r_copy.get("login", pd.Series("", index=r_copy.index)).map(
            lambda v: clean_code(v).upper()
        )
        r_copy["_nm"] = r_copy.get("technician", pd.Series("", index=r_copy.index)).map(
            normalize_text
        )
        by_lg = r_copy[r_copy["_lg"].ne("")].drop_duplicates("_lg", keep="first")
        by_nm = r_copy[r_copy["_nm"].ne("")].drop_duplicates("_nm", keep="first")

        map_name_lg = dict(
            zip(by_lg["_lg"], by_lg["technician"].astype(str), strict=False)
        )
        seller_clean = seller_clean.mask(
            seller_clean.eq("") & login_clean.ne(""),
            login_clean.map(map_name_lg).fillna(""),
        )

        for dest_col, src_Candidates, r_col in (
            ("Monitor", ("Monitor", "monitor"), "monitor"),
            ("Base", ("Base", "base"), "base"),
            ("U.N.", ("U.N.", "un"), "un"),
            ("Situação", ("Situação", "roster_status", "status"), "status"),
        ):
            if (
                not any(c in work.columns for c in src_Candidates)
                and r_col in r_copy.columns
            ):
                m_lg = dict(zip(by_lg["_lg"], by_lg[r_col].astype(str), strict=False))
                m_nm = dict(zip(by_nm["_nm"], by_nm[r_col].astype(str), strict=False))
                val_lg = login_clean.map(m_lg)
                val_nm = seller_clean.map(normalize_text).map(m_nm)
                work[dest_col] = val_lg.where(val_lg.notna() & val_lg.ne(""), val_nm)

    seller_final = seller_clean.mask(
        seller_clean.eq(""),
        login_clean.where(login_clean.ne(""), "Não Identificado"),
    )
    name_norm = seller_final.map(normalize_text)
    full_name_mask = (
        login_clean.ne("")
        & name_norm.ne("")
        & seller_final.str.strip().str.contains(" ", regex=False)
    )
    login_alias: dict[str, str] = {}
    if full_name_mask.any():
        canonical_login_by_name = (
            pd.DataFrame(
                {
                    "_dt": work.loc[full_name_mask, "_dt"],
                    "_nm": name_norm.loc[full_name_mask],
                    "_lg": login_clean.loc[full_name_mask],
                }
            )
            .sort_values("_dt")
            .groupby("_nm")["_lg"]
            .last()
            .to_dict()
        )
        for nm_val, lg_val in zip(
            name_norm.loc[full_name_mask], login_clean.loc[full_name_mask], strict=False
        ):
            canon_lg = canonical_login_by_name.get(nm_val, lg_val)
            if canon_lg != lg_val:
                login_alias[lg_val] = canon_lg
    effective_login = login_clean.replace(login_alias) if login_alias else login_clean
    seller_key = effective_login.where(effective_login.ne(""), name_norm)
    work = work[seller_key.ne("")].copy()
    if work.empty:
        return pd.DataFrame(columns=colunas_saida)

    work["_seller_key"] = seller_key.loc[work.index]
    work["login"] = effective_login.loc[work.index].replace({"": "SEM LOGIN"})
    work["seller"] = seller_final.loc[work.index]

    def _pick_dim(candidates: tuple[str, ...], default: str) -> pd.Series:
        for col in candidates:
            if col in work.columns:
                return _limpar_dimensao(work[col], default)
        return pd.Series(default, index=work.index, dtype="object")

    work["monitor"] = _pick_dim(("Monitor", "monitor"), "Sem monitor")
    work["base"] = _pick_dim(("Base", "base"), "Sem base")
    work["un"] = _pick_dim(("U.N.", "un"), "Sem U.N.")
    work["roster_status"] = _pick_dim(
        ("Situação", "roster_status", "status"), "NÃO CADASTRADO"
    ).str.upper()
    work["tipo_servico"] = _pick_dim(("TIPO SERVIÇO", "tipo_servico"), "Sem Tipo")

    work["year"] = work["_dt"].dt.year.astype(int)
    work["month"] = work["_dt"].dt.month.astype(int)
    work["period"] = work["_dt"].dt.to_period("M").dt.to_timestamp()
    return work[colunas_saida].copy()


def _agrupar_dimensao_consultivo(
    df_escopo: pd.DataFrame,
    coluna: str,
    rotulo: str,
    ano_base: int,
    ano_comp: int,
) -> pd.DataFrame:
    colunas = [
        rotulo,
        f"Cons. {ano_base}",
        f"Cons. {ano_comp}",
        "Δ Cons.",
        "Var. Cons. (%)",
        f"Prod. {ano_base}",
        f"Prod. {ano_comp}",
        "Δ Prod.",
        "Var. Prod. (%)",
        f"Mesh {ano_comp}",
        f"TV Box {ano_comp}",
        f"Virtua {ano_comp}",
        f"Conv. {ano_base}",
        f"Conv. {ano_comp}",
        f"Equipes {ano_base}",
        f"Equipes {ano_comp}",
    ]
    if df_escopo.empty:
        return pd.DataFrame(columns=colunas)

    def _agg_ano(sub: pd.DataFrame) -> pd.DataFrame:
        if sub.empty:
            return pd.DataFrame(
                columns=[
                    coluna,
                    "cons",
                    "prod",
                    "mesh",
                    "tv",
                    "virtua",
                    "equipes",
                ]
            )
        eq_prod = (
            sub.loc[sub["qtde_cons"] > 0]
            .groupby(coluna)["_seller_key"]
            .nunique()
            .rename("equipes")
        )
        tot = (
            sub.groupby(coluna, as_index=False)
            .agg(
                cons=("qtde_cons", "sum"),
                prod=("qtde_prod", "sum"),
                mesh=("qtde_mesh", "sum"),
                tv=("qtde_tv", "sum"),
                virtua=("qtde_virtua", "sum"),
            )
            .merge(eq_prod, on=coluna, how="left")
        )
        tot["equipes"] = tot["equipes"].fillna(0).astype(int)
        return tot

    b = _agg_ano(df_escopo[df_escopo["year"] == ano_base]).rename(
        columns={
            "cons": "cons_b",
            "prod": "prod_b",
            "mesh": "mesh_b",
            "tv": "tv_b",
            "virtua": "virtua_b",
            "equipes": "eq_b",
        }
    )
    c = _agg_ano(df_escopo[df_escopo["year"] == ano_comp]).rename(
        columns={
            "cons": "cons_c",
            "prod": "prod_c",
            "mesh": "mesh_c",
            "tv": "tv_c",
            "virtua": "virtua_c",
            "equipes": "eq_c",
        }
    )
    merged = b.merge(c, on=coluna, how="outer")
    for num_col in (
        "cons_b",
        "prod_b",
        "mesh_b",
        "tv_b",
        "virtua_b",
        "eq_b",
        "cons_c",
        "prod_c",
        "mesh_c",
        "tv_c",
        "virtua_c",
        "eq_c",
    ):
        merged[num_col] = (
            pd.to_numeric(merged[num_col], errors="coerce").fillna(0).astype(int)
        )

    merged = merged[
        (merged["cons_b"] + merged["cons_c"] + merged["prod_b"] + merged["prod_c"]) > 0
    ].copy()
    if merged.empty:
        return pd.DataFrame(columns=colunas)

    merged["Δ Cons."] = merged["cons_c"] - merged["cons_b"]
    merged["Var. Cons. (%)"] = [
        _variacao_pct(ac, ab)
        for ac, ab in zip(merged["cons_c"], merged["cons_b"], strict=False)
    ]
    merged["Δ Prod."] = merged["prod_c"] - merged["prod_b"]
    merged["Var. Prod. (%)"] = [
        _variacao_pct(oc, ob)
        for oc, ob in zip(merged["prod_c"], merged["prod_b"], strict=False)
    ]
    merged[f"Conv. {ano_base}"] = [
        round(pb / cb, 2) if cb > 0 else 0.0
        for pb, cb in zip(merged["prod_b"], merged["cons_b"], strict=False)
    ]
    merged[f"Conv. {ano_comp}"] = [
        round(pc / cc, 2) if cc > 0 else 0.0
        for pc, cc in zip(merged["prod_c"], merged["cons_c"], strict=False)
    ]
    merged = merged.rename(
        columns={
            coluna: rotulo,
            "cons_b": f"Cons. {ano_base}",
            "cons_c": f"Cons. {ano_comp}",
            "prod_b": f"Prod. {ano_base}",
            "prod_c": f"Prod. {ano_comp}",
            "mesh_c": f"Mesh {ano_comp}",
            "tv_c": f"TV Box {ano_comp}",
            "virtua_c": f"Virtua {ano_comp}",
            "eq_b": f"Equipes {ano_base}",
            "eq_c": f"Equipes {ano_comp}",
        }
    )
    return merged.sort_values(
        by=[f"Cons. {ano_comp}", f"Prod. {ano_comp}", f"Cons. {ano_base}", rotulo],
        ascending=[False, False, False, True],
    )[colunas].reset_index(drop=True)


def _agrupar_por_vendedor_consultivo(
    df_escopo: pd.DataFrame,
    ano_base: int,
    ano_comp: int,
) -> pd.DataFrame:
    colunas = [
        "Técnico / Vendedor",
        "Login",
        "Situação",
        "Base",
        "Monitor",
        f"Cons. {ano_base}",
        f"Cons. {ano_comp}",
        "Δ Cons.",
        "Var. Cons. (%)",
        f"Prod. {ano_base}",
        f"Prod. {ano_comp}",
        "Δ Prod.",
        "Var. Prod. (%)",
        "Δ Mesh",
        "Δ TV Box",
        "Δ Virtua",
        f"Conv. {ano_base}",
        f"Conv. {ano_comp}",
    ]
    if df_escopo.empty:
        return pd.DataFrame(columns=colunas)

    meta_rows = (
        df_escopo.sort_values("_dt")
        .groupby("_seller_key", as_index=False)
        .last()[["_seller_key", "seller", "login", "roster_status", "base", "monitor"]]
    )

    def _agg_vend(sub: pd.DataFrame) -> pd.DataFrame:
        if sub.empty:
            return pd.DataFrame(
                columns=["_seller_key", "cons", "prod", "mesh", "tv", "virtua"]
            )
        return sub.groupby("_seller_key", as_index=False).agg(
            cons=("qtde_cons", "sum"),
            prod=("qtde_prod", "sum"),
            mesh=("qtde_mesh", "sum"),
            tv=("qtde_tv", "sum"),
            virtua=("qtde_virtua", "sum"),
        )

    b = _agg_vend(df_escopo[df_escopo["year"] == ano_base]).rename(
        columns={
            "cons": "cons_b",
            "prod": "prod_b",
            "mesh": "mesh_b",
            "tv": "tv_b",
            "virtua": "virtua_b",
        }
    )
    c = _agg_vend(df_escopo[df_escopo["year"] == ano_comp]).rename(
        columns={
            "cons": "cons_c",
            "prod": "prod_c",
            "mesh": "mesh_c",
            "tv": "tv_c",
            "virtua": "virtua_c",
        }
    )
    merged = meta_rows.merge(b, on="_seller_key", how="left").merge(
        c, on="_seller_key", how="left"
    )
    for num_col in (
        "cons_b",
        "prod_b",
        "mesh_b",
        "tv_b",
        "virtua_b",
        "cons_c",
        "prod_c",
        "mesh_c",
        "tv_c",
        "virtua_c",
    ):
        merged[num_col] = (
            pd.to_numeric(merged[num_col], errors="coerce").fillna(0).astype(int)
        )

    merged = merged[
        (merged["cons_b"] + merged["cons_c"] + merged["prod_b"] + merged["prod_c"]) > 0
    ].copy()
    if merged.empty:
        return pd.DataFrame(columns=colunas)

    merged["Δ Cons."] = merged["cons_c"] - merged["cons_b"]
    merged["Var. Cons. (%)"] = [
        _variacao_pct(ac, ab)
        for ac, ab in zip(merged["cons_c"], merged["cons_b"], strict=False)
    ]
    merged["Δ Prod."] = merged["prod_c"] - merged["prod_b"]
    merged["Var. Prod. (%)"] = [
        _variacao_pct(pc, pb)
        for pc, pb in zip(merged["prod_c"], merged["prod_b"], strict=False)
    ]
    merged["Δ Mesh"] = merged["mesh_c"] - merged["mesh_b"]
    merged["Δ TV Box"] = merged["tv_c"] - merged["tv_b"]
    merged["Δ Virtua"] = merged["virtua_c"] - merged["virtua_b"]
    merged[f"Conv. {ano_base}"] = [
        round(pb / cb, 2) if cb > 0 else 0.0
        for pb, cb in zip(merged["prod_b"], merged["cons_b"], strict=False)
    ]
    merged[f"Conv. {ano_comp}"] = [
        round(pc / cc, 2) if cc > 0 else 0.0
        for pc, cc in zip(merged["prod_c"], merged["cons_c"], strict=False)
    ]
    merged = merged.rename(
        columns={
            "seller": "Técnico / Vendedor",
            "login": "Login",
            "roster_status": "Situação",
            "base": "Base",
            "monitor": "Monitor",
            "cons_b": f"Cons. {ano_base}",
            "cons_c": f"Cons. {ano_comp}",
            "prod_b": f"Prod. {ano_base}",
            "prod_c": f"Prod. {ano_comp}",
        }
    )
    return merged.sort_values(
        by=[
            f"Cons. {ano_comp}",
            f"Prod. {ano_comp}",
            f"Cons. {ano_base}",
            "Técnico / Vendedor",
        ],
        ascending=[False, False, False, True],
    )[colunas].reset_index(drop=True)


def _calcular_taxa_meta_tecnico(sub: pd.DataFrame) -> float:
    """Percentual de competências individuais produtivas com ≥ meta_mensal_produtos_tecnico."""
    if sub.empty:
        return 0.0
    prod_rows = sub[sub["qtde_cons"] > 0]
    if prod_rows.empty:
        return 0.0
    mensal_vend = prod_rows.groupby(["month", "_seller_key"], as_index=False)[
        "qtde_prod"
    ].sum()
    if mensal_vend.empty:
        return 0.0
    batidas = int(
        (
            mensal_vend["qtde_prod"] >= CONFIG_CONSULTIVO.meta_mensal_produtos_tecnico
        ).sum()
    )
    return (batidas / len(mensal_vend)) * 100.0


def calcular_comparativo_consultivo(
    consultivo_frame: pd.DataFrame,
    *,
    roster: pd.DataFrame | None = None,
    ano_base: int = 2025,
    ano_comp: int = 2026,
    modo_meses: ModoMesesConsultivo = "equivalente",
    meses_personalizados: list[int] | None = None,
    escopo_equipe: EscopoEquipeConsultivo = "todos",
    bases: list[str] | None = None,
    monitores: list[str] | None = None,
    uns: list[str] | None = None,
) -> ResumoComparativoConsultivo:
    """Calcula a análise interanual completa de Consultivos e Mix de Produtos."""
    base_df = _preparar_base_consultivo_comparativa(consultivo_frame, roster=roster)
    base_df = base_df[base_df["year"].isin([ano_base, ano_comp])].copy()

    if bases:
        base_df = base_df[base_df["base"].isin(bases)]
    if monitores:
        base_df = base_df[base_df["monitor"].isin(monitores)]
    if uns:
        base_df = base_df[base_df["un"].isin(uns)]

    if escopo_equipe == "ativos":
        base_df = base_df[base_df["roster_status"] == "ATIVO"]

    prod_valid = base_df[base_df["qtde_cons"] > 0]
    meses_disp_base = sorted(
        prod_valid.loc[prod_valid["year"] == ano_base, "month"].unique().tolist()
    )
    meses_disp_comp = sorted(
        prod_valid.loc[prod_valid["year"] == ano_comp, "month"].unique().tolist()
    )

    modo_efetivo: ModoMesesConsultivo = modo_meses
    fallback_sem_intersecao = False

    if modo_meses == "equivalente":
        intersecao = sorted(set(meses_disp_base) & set(meses_disp_comp))
        if intersecao:
            meses_considerados = intersecao
        else:
            fallback_sem_intersecao = bool(meses_disp_base or meses_disp_comp)
            modo_efetivo = "ano_completo"
            meses_considerados = list(range(1, 13))
    elif modo_meses == "personalizado":
        escolhidos = sorted(
            {int(m) for m in (meses_personalizados or []) if 1 <= int(m) <= 12}
        )
        meses_considerados = escolhidos or list(range(1, 13))
    else:
        meses_considerados = list(range(1, 13))

    if escopo_equipe == "mesma_equipe":
        df_janela = base_df[
            base_df["month"].isin(meses_considerados) & (base_df["qtde_cons"] > 0)
        ]
        eq_b = set(df_janela.loc[df_janela["year"] == ano_base, "_seller_key"].unique())
        eq_c = set(df_janela.loc[df_janela["year"] == ano_comp, "_seller_key"].unique())
        comuns_filtro = eq_b & eq_c
        base_df = base_df[base_df["_seller_key"].isin(comuns_filtro)].copy()
        prod_valid = base_df[base_df["qtde_cons"] > 0]
        meses_disp_base = sorted(
            prod_valid.loc[prod_valid["year"] == ano_base, "month"].unique().tolist()
        )
        meses_disp_comp = sorted(
            prod_valid.loc[prod_valid["year"] == ano_comp, "month"].unique().tolist()
        )

    # Série mensal completa Jan..Dez para visualização sazonal.
    grade = pd.DataFrame(
        [(num, abrev, nome) for num, abrev, nome in MESES_CALENDARIO],
        columns=["month", "mes_abrev", "mes_nome"],
    )

    def _serie_mensal_ano(ano: int, sufixo: str) -> pd.DataFrame:
        sub = base_df[base_df["year"] == ano]
        if sub.empty:
            return pd.DataFrame(
                {
                    "month": grade["month"],
                    f"consultivos_{sufixo}": 0,
                    f"produtos_{sufixo}": 0,
                    f"mesh_{sufixo}": 0,
                    f"tv_{sufixo}": 0,
                    f"virtua_{sufixo}": 0,
                    f"equipes_{sufixo}": 0,
                }
            )
        eq_m = (
            sub.loc[sub["qtde_cons"] > 0]
            .groupby("month")["_seller_key"]
            .nunique()
            .rename(f"equipes_{sufixo}")
        )
        agg = (
            sub.groupby("month", as_index=False)
            .agg(
                **{
                    f"consultivos_{sufixo}": ("qtde_cons", "sum"),
                    f"produtos_{sufixo}": ("qtde_prod", "sum"),
                    f"mesh_{sufixo}": ("qtde_mesh", "sum"),
                    f"tv_{sufixo}": ("qtde_tv", "sum"),
                    f"virtua_{sufixo}": ("qtde_virtua", "sum"),
                }
            )
            .merge(eq_m, on="month", how="left")
        )
        agg[f"equipes_{sufixo}"] = agg[f"equipes_{sufixo}"].fillna(0).astype(int)
        return grade[["month"]].merge(agg, on="month", how="left").fillna(0)

    m_base = _serie_mensal_ano(ano_base, "base")
    m_comp = _serie_mensal_ano(ano_comp, "comp")
    mensal = grade.merge(m_base, on="month").merge(m_comp, on="month")
    for int_col in (
        "consultivos_base",
        "produtos_base",
        "mesh_base",
        "tv_base",
        "virtua_base",
        "equipes_base",
        "consultivos_comp",
        "produtos_comp",
        "mesh_comp",
        "tv_comp",
        "virtua_comp",
        "equipes_comp",
    ):
        mensal[int_col] = mensal[int_col].astype(int)

    mensal["em_escopo"] = mensal["month"].isin(meses_considerados)
    mensal["delta_consultivos"] = (
        mensal["consultivos_comp"] - mensal["consultivos_base"]
    )
    mensal["pct_consultivos"] = [
        _variacao_pct(cc, cb)
        for cc, cb in zip(
            mensal["consultivos_comp"], mensal["consultivos_base"], strict=False
        )
    ]
    mensal["delta_produtos"] = mensal["produtos_comp"] - mensal["produtos_base"]
    mensal["pct_produtos"] = [
        _variacao_pct(pc, pb)
        for pc, pb in zip(
            mensal["produtos_comp"], mensal["produtos_base"], strict=False
        )
    ]
    mensal["conversao_base"] = [
        round(pb / cb, 2) if cb > 0 else 0.0
        for pb, cb in zip(
            mensal["produtos_base"], mensal["consultivos_base"], strict=False
        )
    ]
    mensal["conversao_comp"] = [
        round(pc / cc, 2) if cc > 0 else 0.0
        for pc, cc in zip(
            mensal["produtos_comp"], mensal["consultivos_comp"], strict=False
        )
    ]
    mensal["acum_consultivos_base"] = (
        mensal["consultivos_base"].where(mensal["em_escopo"], 0).cumsum()
    )
    mensal["acum_consultivos_comp"] = (
        mensal["consultivos_comp"].where(mensal["em_escopo"], 0).cumsum()
    )
    mensal["acum_produtos_base"] = (
        mensal["produtos_base"].where(mensal["em_escopo"], 0).cumsum()
    )
    mensal["acum_produtos_comp"] = (
        mensal["produtos_comp"].where(mensal["em_escopo"], 0).cumsum()
    )

    # Recorte efetivo para KPIs e rankings.
    df_escopo = base_df[base_df["month"].isin(meses_considerados)].copy()
    sub_b = df_escopo[df_escopo["year"] == ano_base]
    sub_c = df_escopo[df_escopo["year"] == ano_comp]

    def _min_max_br(sub: pd.DataFrame) -> tuple[str, str]:
        if sub.empty:
            return "—", "—"
        return (
            formatar_data_br_consultivo(sub["_dt"].min()),
            formatar_data_br_consultivo(sub["_dt"].max()),
        )

    dmin_b, dmax_b = _min_max_br(sub_b)
    dmin_c, dmax_c = _min_max_br(sub_c)

    cons_b = int(sub_b["qtde_cons"].sum())
    cons_c = int(sub_c["qtde_cons"].sum())
    delta_cons = cons_c - cons_b
    pct_cons = _variacao_pct(cons_c, cons_b)

    prod_b = int(sub_b["qtde_prod"].sum())
    prod_c = int(sub_c["qtde_prod"].sum())
    delta_prod = prod_c - prod_b
    pct_prod = _variacao_pct(prod_c, prod_b)

    mesh_b = int(sub_b["qtde_mesh"].sum())
    mesh_c = int(sub_c["qtde_mesh"].sum())
    delta_mesh = mesh_c - mesh_b
    pct_mesh = _variacao_pct(mesh_c, mesh_b)

    tv_b = int(sub_b["qtde_tv"].sum())
    tv_c = int(sub_c["qtde_tv"].sum())
    delta_tv = tv_c - tv_b
    pct_tv = _variacao_pct(tv_c, tv_b)

    vir_b = int(sub_b["qtde_virtua"].sum())
    vir_c = int(sub_c["qtde_virtua"].sum())
    delta_vir = vir_c - vir_b
    pct_vir = _variacao_pct(vir_c, vir_b)

    conv_b = round(prod_b / cons_b, 2) if cons_b > 0 else 0.0
    conv_c = round(prod_c / cons_c, 2) if cons_c > 0 else 0.0
    delta_conv = round(conv_c - conv_b, 2)
    pct_conv = _variacao_pct(conv_c, conv_b)

    mensal_esc = mensal[mensal["em_escopo"]]
    meses_at_b = int((mensal_esc["consultivos_base"] > 0).sum())
    meses_at_c = int((mensal_esc["consultivos_comp"] > 0).sum())
    media_cons_b = round(cons_b / meses_at_b, 1) if meses_at_b > 0 else 0.0
    media_cons_c = round(cons_c / meses_at_c, 1) if meses_at_c > 0 else 0.0
    pct_media_cons = _variacao_pct(media_cons_c, media_cons_b)

    media_prod_b = round(prod_b / meses_at_b, 1) if meses_at_b > 0 else 0.0
    media_prod_c = round(prod_c / meses_at_c, 1) if meses_at_c > 0 else 0.0
    pct_media_prod = _variacao_pct(media_prod_c, media_prod_b)

    eq_set_b = set(sub_b.loc[sub_b["qtde_cons"] > 0, "_seller_key"].unique())
    eq_set_c = set(sub_c.loc[sub_c["qtde_cons"] > 0, "_seller_key"].unique())
    eq_b_n = len(eq_set_b)
    eq_c_n = len(eq_set_c)
    eq_comuns = len(eq_set_b & eq_set_c)

    cons_eq_b = round(cons_b / eq_b_n, 1) if eq_b_n > 0 else 0.0
    cons_eq_c = round(cons_c / eq_c_n, 1) if eq_c_n > 0 else 0.0
    prod_eq_b = round(prod_b / eq_b_n, 1) if eq_b_n > 0 else 0.0
    prod_eq_c = round(prod_c / eq_c_n, 1) if eq_c_n > 0 else 0.0

    taxa_meta_b = round(_calcular_taxa_meta_tecnico(sub_b), 1)
    taxa_meta_c = round(_calcular_taxa_meta_tecnico(sub_c), 1)

    # Tabela comparativa de Mix de Produtos (Mesh, TV Box, Virtua).
    linhas_mix: list[dict[str, Any]] = []
    for nome_prod, vb, vc in (
        ("Mesh", mesh_b, mesh_c),
        ("TV Box", tv_b, tv_c),
        ("Virtua", vir_b, vir_c),
    ):
        sh_b = (vb / prod_b * 100.0) if prod_b > 0 else 0.0
        sh_c = (vc / prod_c * 100.0) if prod_c > 0 else 0.0
        linhas_mix.append(
            {
                "Produto": nome_prod,
                f"Qtde {ano_base}": vb,
                f"Share {ano_base} (%)": round(sh_b, 1),
                f"Qtde {ano_comp}": vc,
                f"Share {ano_comp} (%)": round(sh_c, 1),
                "Δ Qtde": vc - vb,
                "Var. (%)": _variacao_pct(vc, vb),
                "Δ Share (p.p.)": round(sh_c - sh_b, 1),
            }
        )
    mix_df = pd.DataFrame(linhas_mix)

    por_servico = _agrupar_dimensao_consultivo(
        df_escopo[df_escopo["tipo_servico"].ne("Sem Tipo")],
        "tipo_servico",
        "Tipo de Serviço / Plano",
        ano_base,
        ano_comp,
    )
    por_base = _agrupar_dimensao_consultivo(
        df_escopo, "base", "Base", ano_base, ano_comp
    )
    por_monitor = _agrupar_dimensao_consultivo(
        df_escopo, "monitor", "Monitor", ano_base, ano_comp
    )
    por_un = _agrupar_dimensao_consultivo(df_escopo, "un", "U.N.", ano_base, ano_comp)
    por_vendedor = _agrupar_por_vendedor_consultivo(df_escopo, ano_base, ano_comp)

    return ResumoComparativoConsultivo(
        ano_base=ano_base,
        ano_comp=ano_comp,
        modo_solicitado=modo_meses,
        modo_efetivo=modo_efetivo,
        fallback_sem_intersecao=fallback_sem_intersecao,
        escopo_equipe=escopo_equipe,
        meses_disponiveis_base=meses_disp_base,
        meses_disponiveis_comp=meses_disp_comp,
        meses_considerados=meses_considerados,
        data_min_base=dmin_b,
        data_max_base=dmax_b,
        data_min_comp=dmin_c,
        data_max_comp=dmax_c,
        consultivos_base=cons_b,
        consultivos_comp=cons_c,
        delta_consultivos=delta_cons,
        pct_consultivos=pct_cons,
        produtos_base=prod_b,
        produtos_comp=prod_c,
        delta_produtos=delta_prod,
        pct_produtos=pct_prod,
        mesh_base=mesh_b,
        mesh_comp=mesh_c,
        delta_mesh=delta_mesh,
        pct_mesh=pct_mesh,
        tv_base=tv_b,
        tv_comp=tv_c,
        delta_tv=delta_tv,
        pct_tv=pct_tv,
        virtua_base=vir_b,
        virtua_comp=vir_c,
        delta_virtua=delta_vir,
        pct_virtua=pct_vir,
        conversao_base=conv_b,
        conversao_comp=conv_c,
        delta_conversao=delta_conv,
        pct_conversao=pct_conv,
        media_mensal_cons_base=media_cons_b,
        media_mensal_cons_comp=media_cons_c,
        pct_media_cons=pct_media_cons,
        media_mensal_prod_base=media_prod_b,
        media_mensal_prod_comp=media_prod_c,
        pct_media_prod=pct_media_prod,
        meses_ativos_base=meses_at_b,
        meses_ativos_comp=meses_at_c,
        equipes_produtivas_base=eq_b_n,
        equipes_produtivas_comp=eq_c_n,
        equipes_comuns=eq_comuns,
        cons_por_equipe_base=cons_eq_b,
        cons_por_equipe_comp=cons_eq_c,
        prod_por_equipe_base=prod_eq_b,
        prod_por_equipe_comp=prod_eq_c,
        taxa_meta_tecnico_base=taxa_meta_b,
        taxa_meta_tecnico_comp=taxa_meta_c,
        mensal=mensal,
        mix_produtos=mix_df,
        por_tipo_servico=por_servico,
        por_base=por_base,
        por_monitor=por_monitor,
        por_un=por_un,
        por_vendedor=por_vendedor,
    )


def _injetar_css_comparativo_consultivo() -> None:
    injetar_css(
        """
        .comp-cons-hero {
            position: relative;
            overflow: hidden;
            background: linear-gradient(135deg, #061A40 0%, #012869 52%, #0F4C81 100%);
            border-radius: 18px;
            padding: 1.45rem 1.7rem;
            color: #FFFFFF;
            box-shadow: 0 16px 36px rgba(1, 40, 105, 0.18);
            border: 1px solid rgba(255, 255, 255, 0.12);
            margin-bottom: 1rem;
        }
        .comp-cons-hero::after {
            content: "";
            position: absolute;
            right: -60px;
            top: -60px;
            width: 230px;
            height: 230px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(243, 124, 4, 0.30) 0%, rgba(243, 124, 4, 0) 70%);
            pointer-events: none;
        }
        .comp-cons-hero-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            flex-wrap: wrap;
            margin-bottom: 0.45rem;
        }
        .comp-cons-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.42rem;
            padding: 0.28rem 0.74rem;
            border-radius: 999px;
            background: rgba(243, 124, 4, 0.22);
            border: 1px solid rgba(251, 146, 60, 0.44);
            color: #FFEDD5;
            font-size: 0.69rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .comp-cons-scope-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.28rem 0.75rem;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.11);
            border: 1px solid rgba(255, 255, 255, 0.18);
            color: #E2E8F0;
            font-size: 0.74rem;
            font-weight: 600;
        }
        .comp-cons-hero h2 {
            color: #FFFFFF !important;
            font-size: 1.5rem !important;
            font-weight: 800 !important;
            letter-spacing: -0.025em !important;
            margin: 0 0 0.28rem 0 !important;
        }
        .comp-cons-hero p {
            color: rgba(226, 232, 240, 0.92) !important;
            font-size: 0.89rem !important;
            line-height: 1.48 !important;
            margin: 0 !important;
            max-width: 860px;
        }
        .comp-cons-note {
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-left: 4px solid #012869;
            border-radius: 10px;
            padding: 0.65rem 0.95rem;
            font-size: 0.8rem;
            color: #334155;
            margin: 0.4rem 0 0.95rem;
        }
        .comp-cons-note strong {
            color: #012869;
        }
        """
    )


def _layout_base_plotly(fig: go.Figure, *, altura: int = 360) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin={"l": 16, "r": 18, "t": 34, "b": 24},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font={"family": Fontes.TEXTO, "size": 12, "color": Cores.TEXTO},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "title_text": "",
        },
        hoverlabel={"bgcolor": "#0F172A", "font": {"color": "#FFFFFF", "size": 12}},
    )
    fig.update_xaxes(showgrid=False, linecolor="#E2E8F0")
    fig.update_yaxes(gridcolor="#EEF2F7", zeroline=False)
    return fig


def _grafico_mensal_consultivo(
    mensal: pd.DataFrame,
    *,
    col_base: str,
    col_comp: str,
    ano_base: int,
    ano_comp: int,
    cor_base: str,
    cor_comp: str,
    unidade: str,
) -> go.Figure:
    opacidades = [1.0 if bool(esc) else 0.30 for esc in mensal["em_escopo"]]
    textos_comp: list[str] = []
    hovers_pct_comp: list[str] = []
    for vb_raw, vc_raw in zip(mensal[col_base], mensal[col_comp], strict=False):
        vb_i = int(vb_raw)
        vc_i = int(vc_raw)
        pct_mes = _variacao_pct(vc_i, vb_i)
        pct_txt = formatar_variacao_pct_br(pct_mes, atual=vc_i, base=vb_i)
        hovers_pct_comp.append(pct_txt)
        if vc_i <= 0:
            textos_comp.append("")
        elif pct_mes is not None:
            textos_comp.append(f"{formatar_numero_br(vc_i)}<br><b>({pct_txt})</b>")
        else:
            textos_comp.append(formatar_numero_br(vc_i))

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name=str(ano_base),
            x=mensal["mes_abrev"],
            y=mensal[col_base],
            marker={"color": cor_base, "opacity": opacidades},
            text=[
                formatar_numero_br(int(v)) if int(v) > 0 else ""
                for v in mensal[col_base]
            ],
            textposition="outside",
            cliponaxis=False,
            hovertemplate=f"<b>%{{x}}/{ano_base}</b><br>{unidade}: %{{y:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name=str(ano_comp),
            x=mensal["mes_abrev"],
            y=mensal[col_comp],
            marker={"color": cor_comp, "opacity": opacidades},
            customdata=hovers_pct_comp,
            text=textos_comp,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                f"<b>%{{x}}/{ano_comp}</b><br>{unidade}: %{{y:,.0f}}"
                f"<br><b>Variação vs {ano_base}: %{{customdata}}</b><extra></extra>"
            ),
        )
    )
    fig.update_layout(barmode="group", bargap=0.22, bargroupgap=0.10)
    ymax = max(float(mensal[col_base].max()), float(mensal[col_comp].max()), 1.0)
    fig.update_yaxes(range=[0, ymax * 1.28], title_text=unidade)
    return _layout_base_plotly(fig, altura=355)


def _grafico_acumulado_consultivo(
    mensal: pd.DataFrame,
    *,
    metrica: Literal["consultivos", "produtos"],
    ano_base: int,
    ano_comp: int,
) -> go.Figure:
    esc = mensal[mensal["em_escopo"]].copy()
    if esc.empty:
        esc = mensal.copy()

    col_b = f"acum_{metrica}_base"
    col_c = f"acum_{metrica}_comp"
    cor_c = _COR_2026_CONS if metrica == "consultivos" else _COR_2026_PROD
    fill_c = (
        "rgba(1, 40, 105, 0.08)"
        if metrica == "consultivos"
        else "rgba(243, 124, 4, 0.10)"
    )
    rotulo = (
        "Consultivos acumulados" if metrica == "consultivos" else "Produtos acumulados"
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            name=f"Acumulado {ano_base}",
            x=esc["mes_abrev"],
            y=esc[col_b],
            mode="lines+markers",
            line={"color": "#64748B", "width": 2.6, "dash": "dot"},
            marker={"size": 7, "color": "#64748B"},
            hovertemplate=f"<b>Até %{{x}}/{ano_base}</b><br>{rotulo}: %{{y:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            name=f"Acumulado {ano_comp}",
            x=esc["mes_abrev"],
            y=esc[col_c],
            mode="lines+markers",
            line={"color": cor_c, "width": 3.2},
            marker={"size": 8, "color": cor_c},
            fill="tozeroy",
            fillcolor=fill_c,
            hovertemplate=f"<b>Até %{{x}}/{ano_comp}</b><br>{rotulo}: %{{y:,.0f}}<extra></extra>",
        )
    )
    fig.update_yaxes(title_text=rotulo)
    return _layout_base_plotly(fig, altura=335)


def _grafico_conversao_mensal(
    mensal: pd.DataFrame, ano_base: int, ano_comp: int
) -> go.Figure:
    fig = go.Figure()
    y_b = [
        float(v) if int(c) > 0 else None
        for v, c in zip(
            mensal["conversao_base"], mensal["consultivos_base"], strict=False
        )
    ]
    y_c = [
        float(v) if int(c) > 0 else None
        for v, c in zip(
            mensal["conversao_comp"], mensal["consultivos_comp"], strict=False
        )
    ]
    fig.add_trace(
        go.Scatter(
            name=f"Prod./Cons. ({ano_base})",
            x=mensal["mes_abrev"],
            y=y_b,
            mode="lines+markers",
            connectgaps=False,
            line={"color": "#64748B", "width": 2.4, "dash": "dash"},
            marker={"size": 7, "color": "#64748B"},
            hovertemplate=f"<b>%{{x}}/{ano_base}</b><br>Produtos / Consultivo: %{{y:.2f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            name=f"Prod./Cons. ({ano_comp})",
            x=mensal["mes_abrev"],
            y=y_c,
            mode="lines+markers",
            connectgaps=False,
            line={"color": "#7C3AED", "width": 3.0},
            marker={"size": 8, "color": "#7C3AED"},
            hovertemplate=f"<b>%{{x}}/{ano_comp}</b><br>Produtos / Consultivo: %{{y:.2f}}<extra></extra>",
        )
    )
    fig.add_hline(
        y=1.0,
        line_dash="dot",
        line_color="#CBD5E1",
        annotation_text="1,0 prod./consultivo",
        annotation_position="bottom right",
    )
    fig.update_yaxes(title_text="Produtos / Consultivo")
    return _layout_base_plotly(fig, altura=335)


def _grafico_mix_produtos(
    mix_df: pd.DataFrame, ano_base: int, ano_comp: int
) -> tuple[go.Figure, go.Figure]:
    col_qb = f"Qtde {ano_base}"
    col_qc = f"Qtde {ano_comp}"
    col_sb = f"Share {ano_base} (%)"
    col_sc = f"Share {ano_comp} (%)"

    fig_vol = go.Figure()
    fig_vol.add_trace(
        go.Bar(
            name=str(ano_base),
            x=mix_df["Produto"],
            y=mix_df[col_qb],
            marker={"color": "#94A3B8"},
            text=[formatar_numero_br(int(v)) for v in mix_df[col_qb]],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig_vol.add_trace(
        go.Bar(
            name=str(ano_comp),
            x=mix_df["Produto"],
            y=mix_df[col_qc],
            marker={"color": [_COR_MESH, _COR_TV, _COR_VIRTUA]},
            text=[formatar_numero_br(int(v)) for v in mix_df[col_qc]],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig_vol.update_layout(barmode="group", bargap=0.28)
    ymax = max(float(mix_df[col_qb].max()), float(mix_df[col_qc].max()), 1.0)
    fig_vol.update_yaxes(range=[0, ymax * 1.24], title_text="Quantidade de Produtos")
    _layout_base_plotly(fig_vol, altura=340)

    fig_share = go.Figure()
    for prod_nome, cor in (
        ("Mesh", _COR_MESH),
        ("TV Box", _COR_TV),
        ("Virtua", _COR_VIRTUA),
    ):
        row = mix_df[mix_df["Produto"] == prod_nome]
        vb = float(row[col_sb].iloc[0]) if not row.empty else 0.0
        vc = float(row[col_sc].iloc[0]) if not row.empty else 0.0
        fig_share.add_trace(
            go.Bar(
                name=prod_nome,
                x=[str(ano_base), str(ano_comp)],
                y=[vb, vc],
                marker={"color": cor},
                text=[
                    f"{vb:.1f}%".replace(".", ",") if vb >= 5 else "",
                    f"{vc:.1f}%".replace(".", ",") if vc >= 5 else "",
                ],
                textposition="inside",
                insidetextanchor="middle",
                textfont={"color": "#FFFFFF", "weight": 700},
                hovertemplate=f"<b>{prod_nome} (%{{x}})</b><br>Participação: %{{y:.1f}}%<extra></extra>",
            )
        )
    fig_share.update_layout(barmode="stack", bargap=0.42)
    fig_share.update_yaxes(range=[0, 105], title_text="Participação no Mix (%)")
    _layout_base_plotly(fig_share, altura=340)
    return fig_vol, fig_share


def _grafico_dumbbell_consultivo(
    tabela: pd.DataFrame,
    *,
    rotulo: str,
    metrica_prefixo: str,
    ano_base: int,
    ano_comp: int,
    cor_comp: str,
    limite: int = 12,
) -> go.Figure:
    fig = go.Figure()
    if tabela.empty:
        return _layout_base_plotly(fig, altura=320)

    col_b = f"{metrica_prefixo} {ano_base}"
    col_c = f"{metrica_prefixo} {ano_comp}"
    top = tabela.head(limite).iloc[::-1].copy()

    for _, row in top.iterrows():
        fig_x = [row[col_b], row[col_c]]
        fig.add_trace(
            go.Scatter(
                x=fig_x,
                y=[row[rotulo], row[rotulo]],
                mode="lines",
                line={
                    "color": "#CBD5E1"
                    if row[col_c] >= row[col_b]
                    else "rgba(220, 38, 38, 0.38)",
                    "width": 3,
                },
                showlegend=False,
                hoverinfo="skip",
            )
        )

    fig.add_trace(
        go.Scatter(
            name=str(ano_base),
            x=top[col_b],
            y=top[rotulo],
            mode="markers",
            marker={
                "size": 10,
                "color": "#64748B",
                "line": {"width": 1.5, "color": "#FFFFFF"},
            },
            hovertemplate=f"<b>%{{y}}</b><br>{metrica_prefixo} {ano_base}: %{{x:,.0f}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            name=str(ano_comp),
            x=top[col_c],
            y=top[rotulo],
            mode="markers",
            marker={
                "size": 12,
                "color": cor_comp,
                "line": {"width": 1.5, "color": "#FFFFFF"},
            },
            hovertemplate=f"<b>%{{y}}</b><br>{metrica_prefixo} {ano_comp}: %{{x:,.0f}}<extra></extra>",
        )
    )
    fig.update_xaxes(showgrid=True, gridcolor="#EEF2F7", title_text=metrica_prefixo)
    fig.update_yaxes(showgrid=False)
    return _layout_base_plotly(fig, altura=max(300, 44 * len(top) + 70))


def _grafico_quadrante_vendedores(
    por_vendedor: pd.DataFrame, ano_base: int, ano_comp: int
) -> go.Figure:
    fig = go.Figure()
    if por_vendedor.empty:
        return _layout_base_plotly(fig, altura=360)

    cores = [
        "#16A34A"
        if (dc >= 0 and dp >= 0)
        else ("#DC2626" if (dc < 0 and dp < 0) else "#F37C04")
        for dc, dp in zip(
            por_vendedor["Δ Cons."], por_vendedor["Δ Prod."], strict=False
        )
    ]
    fig.add_hline(y=0, line_dash="dash", line_color="#CBD5E1")
    fig.add_vline(x=0, line_dash="dash", line_color="#CBD5E1")
    fig.add_trace(
        go.Scatter(
            x=por_vendedor["Δ Cons."],
            y=por_vendedor["Δ Prod."],
            mode="markers",
            text=por_vendedor["Técnico / Vendedor"],
            customdata=por_vendedor[
                [
                    f"Cons. {ano_base}",
                    f"Cons. {ano_comp}",
                    f"Prod. {ano_base}",
                    f"Prod. {ano_comp}",
                ]
            ].to_numpy(),
            marker={
                "size": 11,
                "color": cores,
                "opacity": 0.88,
                "line": {"width": 1.2, "color": "#FFFFFF"},
            },
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Consultivos: %{customdata[0]:,.0f} → %{customdata[1]:,.0f} (Δ %{x:+,.0f})<br>"
                "Produtos: %{customdata[2]:,.0f} → %{customdata[3]:,.0f} (Δ %{y:+,.0f})<extra></extra>"
            ),
            showlegend=False,
        )
    )
    fig.update_xaxes(
        title_text=f"Δ Consultivos ({ano_comp} − {ano_base})",
        showgrid=True,
        gridcolor="#EEF2F7",
    )
    fig.update_yaxes(
        title_text=f"Δ Produtos ({ano_comp} − {ano_base})",
        showgrid=True,
        gridcolor="#EEF2F7",
    )
    return _layout_base_plotly(fig, altura=360)


def _estilizar_tabela(
    tabela: pd.DataFrame,
    *,
    colunas_inteiras: list[str],
    colunas_delta: list[str],
    colunas_pct: list[str],
    colunas_decimais: list[str] | None = None,
) -> Any:
    colunas_decimais = colunas_decimais or []
    formatos: dict[str, Any] = {}
    for col in colunas_inteiras:
        if col in tabela.columns:
            formatos[col] = lambda v: "—" if pd.isna(v) else formatar_numero_br(int(v))
    for col in colunas_delta:
        if col in tabela.columns:
            formatos[col] = lambda v: (
                "—"
                if pd.isna(v)
                else (
                    f"+{formatar_numero_br(int(v))}"
                    if int(v) > 0
                    else formatar_numero_br(int(v))
                )
            )
    for col in colunas_pct:
        if col in tabela.columns:
            formatos[col] = lambda v: _formatar_pct_br(None if pd.isna(v) else float(v))
    for col in colunas_decimais:
        if col in tabela.columns:
            formatos[col] = lambda v: (
                "—" if pd.isna(v) else _formatar_decimal_br(float(v), 2)
            )

    def _cor_delta(val: Any) -> str:
        if val is None or pd.isna(val):
            return "color: #64748B;"
        try:
            num = float(val)
        except (TypeError, ValueError):
            return ""
        if num > 0:
            return "color: #15803D; font-weight: 700; background-color: rgba(22, 163, 74, 0.08);"
        if num < 0:
            return "color: #B91C1C; font-weight: 700; background-color: rgba(220, 38, 38, 0.08);"
        return "color: #475569;"

    styler = tabela.style.format(formatos)
    alvo = [c for c in [*colunas_delta, *colunas_pct] if c in tabela.columns]
    if alvo and tabela.size <= 5000:
        styler = styler.map(_cor_delta, subset=pd.Index(alvo))
    return styler


def _tema_variacao(delta: float | int, neutro: TemaKPIType = "azul") -> TemaKPIType:
    if float(delta) > 0:
        return "verde"
    if float(delta) < 0:
        return "vermelho"
    return neutro


def _trend_variacao(delta: float | int) -> TipoTrendType:
    if float(delta) > 0:
        return "up"
    if float(delta) < 0:
        return "down"
    return "neutral"


def _sintese_executiva_consultivo(
    resumo: ResumoComparativoConsultivo,
) -> tuple[str, TipoInsightType]:
    b, c = resumo.ano_base, resumo.ano_comp
    if resumo.consultivos_base == 0 and resumo.consultivos_comp > 0:
        return (
            f"Em <b>{c}</b> foram registrados <b>{formatar_numero_br(resumo.consultivos_comp)} consultivos</b> e "
            f"<b>{formatar_numero_br(resumo.produtos_comp)} produtos</b> "
            f"(conversão de <b>{_formatar_decimal_br(resumo.conversao_comp)} prod./cons.</b>). "
            f"Ainda não há histórico de <b>{b}</b> importado na base — adicione os arquivos de {b} na pasta "
            f"<i>Histórico Consultivo</i> do Google Drive ou importe um CSV/XLSX complementar abaixo para ativar a variação interanual.",
            "info",
        )
    if resumo.consultivos_comp == 0 and resumo.consultivos_base > 0:
        return (
            f"A base possui <b>{formatar_numero_br(resumo.consultivos_base)} consultivos</b> em <b>{b}</b>, "
            f"mas nenhum registro em <b>{c}</b> para os filtros selecionados.",
            "alerta",
        )

    acao_cons = "cresceram" if resumo.delta_consultivos >= 0 else "recuaram"
    acao_prod = "avançaram" if resumo.delta_produtos >= 0 else "retraíram"
    tipo: TipoInsightType = (
        "ok"
        if resumo.delta_consultivos >= 0 and resumo.delta_produtos >= 0
        else (
            "critico"
            if resumo.delta_consultivos < 0 and resumo.delta_produtos < 0
            else "alerta"
        )
    )

    # Identifica o produto líder de crescimento no mix.
    lider_txt = ""
    if not resumo.mix_produtos.empty:
        top_mix = resumo.mix_produtos.sort_values("Δ Qtde", ascending=False).iloc[0]
        lider_txt = (
            f" Destaque no mix para <b>{html.escape(str(top_mix['Produto']))}</b> "
            f"(Δ {int(top_mix['Δ Qtde']):+d} itens · "
            f"{_formatar_decimal_br(float(top_mix['Δ Share (p.p.)']), 1, com_sinal=True)} p.p. de share).".replace(
                ",", "."
            )
        )

    return (
        f"No recorte comparativo selecionado, os <b>consultivos {acao_cons} {_formatar_pct_br(resumo.pct_consultivos)}</b> "
        f"(<b>{formatar_numero_br(resumo.consultivos_base)}</b> em {b} → <b>{formatar_numero_br(resumo.consultivos_comp)}</b> em {c}), "
        f"enquanto o volume de <b>produtos {acao_prod} {_formatar_pct_br(resumo.pct_produtos)}</b> "
        f"(<b>{formatar_numero_br(resumo.produtos_base)}</b> → <b>{formatar_numero_br(resumo.produtos_comp)}</b>), "
        f"levando a conversão para <b>{_formatar_decimal_br(resumo.conversao_comp)} produtos/consultivo</b>."
        f"{lider_txt}",
        tipo,
    )


def render_comparativo_consultivo(
    consultivo_frame: pd.DataFrame,
    roster: pd.DataFrame | None = None,
    *,
    consultivo_folder_id: str = DEFAULT_CONSULTIVO_FOLDER_ID,
    drive_configured: bool = False,
    on_sync_consultivo: Callable[[], None] | None = None,
    sync_issues: list[str] | None = None,
    on_abrir_painel_consultivo: Callable[[], None] | None = None,
    on_abrir_comparativo_contratos: Callable[[], None] | None = None,
    on_dados_importados: Callable[[], None] | None = None,
) -> None:
    """Renderiza o painel executivo 2025 x 2026 de Consultivos e Mix de Produtos."""
    _injetar_css_comparativo_consultivo()

    mostrar_sync_drive = bool(on_sync_consultivo is not None and drive_configured)
    # Barra superior de atalhos cruzados sem mutar chaves após instanciação.
    if (
        on_abrir_painel_consultivo is not None
        or on_abrir_comparativo_contratos is not None
        or mostrar_sync_drive
    ):
        nav_cols = st.columns([1.25, 1.4, 1.35, 1.0])
        with nav_cols[0]:
            if on_abrir_painel_consultivo is not None:
                st.button(
                    "Painel Operacional Consultivo",
                    key="comp_cons_ir_painel",
                    icon=":material/support_agent:",
                    on_click=on_abrir_painel_consultivo,
                )
        with nav_cols[1]:
            if on_abrir_comparativo_contratos is not None:
                st.button(
                    "Comparativo Contratos & O.S.",
                    key="comp_cons_ir_contratos",
                    icon=":material/compare_arrows:",
                    on_click=on_abrir_comparativo_contratos,
                )
        with nav_cols[2]:
            if mostrar_sync_drive and on_sync_consultivo is not None:
                if st.button(
                    "🔄 Sincronizar Drive (Consultivo)",
                    key="comp_cons_btn_sync_drive",
                    help=f"Sincroniza a pasta {consultivo_folder_id} do Google Drive.",
                ):
                    on_sync_consultivo()

    if sync_issues:
        with st.expander(
            f"Avisos da última sincronização do Consultivo ({len(sync_issues)})",
            expanded=False,
        ):
            for item in sync_issues[:20]:
                st.caption(f"• {item}")

    prep = _preparar_base_consultivo_comparativa(consultivo_frame, roster=roster)
    anos_presentes = sorted(prep["year"].unique().tolist()) if not prep.empty else []
    ano_base, ano_comp = 2025, 2026

    bases_disp = (
        sorted(b for b in prep["base"].unique().tolist() if b and b != "Sem base")
        if not prep.empty
        else []
    )
    monitores_disp = (
        sorted(m for m in prep["monitor"].unique().tolist() if m and m != "Sem monitor")
        if not prep.empty
        else []
    )
    uns_disp = (
        sorted(u for u in prep["un"].unique().tolist() if u and u != "Sem U.N.")
        if not prep.empty
        else []
    )

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([1.35, 1.35, 1.0, 1.0, 1.0])
        with c1:
            opcoes_modo: dict[ModoMesesConsultivo, str] = {
                "equivalente": "Mesmos meses (Equivalente)",
                "ano_completo": "Ano completo disponível (Jan–Dez)",
                "personalizado": "Seleção manual de meses",
            }
            modo_sel = st.selectbox(
                "Recorte temporal",
                options=list(opcoes_modo.keys()),
                format_func=lambda k: opcoes_modo[k],
                key="comp_cons_modo_meses",
                help=(
                    "Mesmos meses compara apenas os meses com tabulação consultiva registrada "
                    "nos dois anos, evitando distorção por ano em andamento."
                ),
            )
        with c2:
            opcoes_equipe: dict[EscopoEquipeConsultivo, str] = {
                "todos": "Operação completa (todos)",
                "ativos": "Quadro ativo atual (ATIVO)",
                "mesma_equipe": "Mesma equipe (2025 e 2026)",
            }
            escopo_equipe = st.selectbox(
                "Escopo de equipes",
                options=list(opcoes_equipe.keys()),
                format_func=lambda k: opcoes_equipe[k],
                key="comp_cons_escopo_equipe",
                help=(
                    "'Operação completa' preserva vendas históricas de 2025 mesmo de quem hoje está DESLIGADO; "
                    "'Mesma equipe' isola apenas quem vendeu nos dois anos."
                ),
            )
        with c3:
            bases_sel = st.multiselect(
                "Base (lista_ativos)",
                options=bases_disp,
                default=[],
                placeholder="Todas",
                key="comp_cons_bases",
            )
        with c4:
            monitores_sel = st.multiselect(
                "Monitor",
                options=monitores_disp,
                default=[],
                placeholder="Todos",
                key="comp_cons_monitores",
            )
        with c5:
            uns_sel = st.multiselect(
                "U.N.",
                options=uns_disp,
                default=[],
                placeholder="Todas",
                key="comp_cons_uns",
            )

        meses_custom: list[int] | None = None
        if modo_sel == "personalizado":
            mapa_nome_mes = {num: abrev for num, abrev, _ in MESES_CALENDARIO}
            padrao_meses = sorted(
                set(prep.loc[prep["year"] == ano_base, "month"].unique().tolist())
                | set(prep.loc[prep["year"] == ano_comp, "month"].unique().tolist())
            ) or list(range(1, 13))
            meses_custom = st.multiselect(
                "Meses considerados na comparação",
                options=[num for num, _, _ in MESES_CALENDARIO],
                default=padrao_meses,
                format_func=lambda m: mapa_nome_mes.get(m, str(m)),
                key="comp_cons_meses_custom",
            )

    resumo = calcular_comparativo_consultivo(
        consultivo_frame,
        roster=roster,
        ano_base=ano_base,
        ano_comp=ano_comp,
        modo_meses=modo_sel,
        meses_personalizados=meses_custom,
        escopo_equipe=escopo_equipe,
        bases=bases_sel or None,
        monitores=monitores_sel or None,
        uns=uns_sel or None,
    )

    # Upload complementar opcional (útil para carregar base histórica 2025 em CSV/XLSX na hora).
    expandir_upload = not resumo.meses_disponiveis_base
    with st.expander(
        "📂 Importar arquivo complementar de Histórico Consultivo (CSV / XLSX — ex.: base 2025)",
        expanded=False,
    ):
        st.caption(
            f"Sincronização principal via Google Drive (pasta `{consultivo_folder_id}`, com leitura "
            "automática de subpastas `2025/` e `2026/`). Use o envio abaixo se desejar carregar "
            "imediatamente uma exportação CSV/XLSX adicional de tabulação consultiva."
        )
        up_cols = st.columns([2.6, 1.0])
        with up_cols[0]:
            arq_up = st.file_uploader(
                "Arquivo de tabulação consultiva (.csv, .xlsx, .xls)",
                type=["csv", "xlsx", "xls"],
                key="comp_cons_upload_file",
                label_visibility="collapsed",
            )
        with up_cols[1]:
            if (
                st.button(
                    "Importar arquivo",
                    key="comp_cons_btn_importar",
                    type="primary",
                    width="stretch",
                    disabled=arq_up is None,
                )
                and arq_up is not None
            ):
                try:
                    novos_regs, avisos = process_consultivo_upload(
                        arq_up.name, arq_up.getvalue()
                    )
                    salvos = save_consultivo_records(novos_regs, is_demo=False)
                    if on_dados_importados is not None:
                        on_dados_importados()
                    st.success(
                        f"Arquivo '{arq_up.name}' importado com sucesso ({salvos} registros processados)."
                    )
                    if avisos:
                        st.warning(" · ".join(avisos[:5]))
                    st.rerun()
                except ValueError as erro_up:
                    st.error(f"Não foi possível importar '{arq_up.name}': {erro_up}")
    del expandir_upload

    if prep.empty or not any(a in anos_presentes for a in (ano_base, ano_comp)):
        render_insight(
            "Não há registros de Consultivo em 2025 ou 2026 carregados no momento. "
            "Use 'Atualizar dados' na barra lateral ou importe um arquivo acima.",
            tipo="alerta",
        )
        return

    escopo_meses_txt = _formatar_lista_meses(resumo.meses_considerados)
    modo_badge_map: dict[ModoMesesConsultivo, str] = {
        "equivalente": "Comparação Equivalente (Mesmos Meses)",
        "ano_completo": "Ano Completo Disponível",
        "personalizado": "Meses Selecionados",
    }
    st.markdown(
        f"""
        <div class="comp-cons-hero">
            <div class="comp-cons-hero-top">
                <span class="comp-cons-badge">📊 TOTALE · INTELIGÊNCIA INTERANUAL · Consultivos {ano_base} × {ano_comp}</span>
                <span class="comp-cons-scope-pill">🗓️ {html.escape(modo_badge_map[resumo.modo_efetivo])} · {html.escape(escopo_meses_txt)}</span>
            </div>
            <h2>Comparativo Interanual {ano_base} × {ano_comp} · Performance Consultiva &amp; Mix</h2>
            <p>
                Evolução comparativa de atendimentos consultivos, produtos comercializados
                (<b>Mesh</b>, <b>TV Box</b> e <b>Virtua</b>), taxa de conversão por atendimento e
                atingimento de metas mensais por Base, Monitor e Técnico.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if resumo.fallback_sem_intersecao:
        render_insight(
            f"<b>Cobertura parcial entre {ano_base} e {ano_comp}:</b> "
            f"{ano_base} possui registros em <b>{_formatar_lista_meses(resumo.meses_disponiveis_base)}</b> "
            f"e {ano_comp} em <b>{_formatar_lista_meses(resumo.meses_disponiveis_comp)}</b>. "
            "Como ainda não há meses equivalentes sobrepostos nos dois anos, o painel exibiu todos os meses "
            "disponíveis e destacou a <b>Média Mensal Ativa</b> para leitura justa.",
            tipo="info",
            titulo="Cobertura interanual",
        )

    texto_diag, tipo_diag = _sintese_executiva_consultivo(resumo)
    render_insight(texto_diag, tipo=tipo_diag, titulo="Síntese executiva")

    janela_b_txt = (
        f"{resumo.data_min_base} a {resumo.data_max_base}"
        if resumo.data_min_base != "—"
        else "Sem registros"
    )
    janela_c_txt = (
        f"{resumo.data_min_comp} a {resumo.data_max_comp}"
        if resumo.data_min_comp != "—"
        else "Sem registros"
    )
    render_ticker(
        [
            (f"Período {ano_base}", janela_b_txt),
            (f"Período {ano_comp}", janela_c_txt),
            (
                "Equipes produtivas",
                f"{resumo.equipes_produtivas_base} ({ano_base}) · {resumo.equipes_produtivas_comp} ({ano_comp})",
            ),
            ("Equipes nos 2 anos", formatar_numero_br(resumo.equipes_comuns)),
            (
                f"Meta ≥{CONFIG_CONSULTIVO.meta_mensal_produtos_tecnico} prod./mês",
                f"{_formatar_decimal_br(resumo.taxa_meta_tecnico_base, 1)}% → {_formatar_decimal_br(resumo.taxa_meta_tecnico_comp, 1)}%",
            ),
        ]
    )

    st.markdown(
        f'<div class="comp-cons-note"><strong>Critério oficial unificado:</strong> {html.escape(REGRA_COMPARATIVO_CONSULTIVO)}</div>',
        unsafe_allow_html=True,
    )

    # Seção dedicada de Cards de Saldo / Delta (Δ): Consultivos, Produtos, Conversão e Mix Comercial.
    render_section_header(
        f"Cards de Delta (Δ) · Consultivo {ano_comp} vs {ano_base}",
        subtitulo="Variação líquida absoluta e destaque percentual em Consultivos, Produtos comercializados e Mix (Mesh, TV Box e Virtua)",
        icone="Δ",
        badge=resumo.rotulo_recorte_meses,
        badge_tipo="info",
    )

    diff_mc = resumo.media_mensal_cons_comp - resumo.media_mensal_cons_base
    diff_mp = resumo.media_mensal_prod_comp - resumo.media_mensal_prod_base
    diff_eq = resumo.equipes_produtivas_comp - resumo.equipes_produtivas_base
    pct_eq = _variacao_pct(
        resumo.equipes_produtivas_comp, resumo.equipes_produtivas_base
    )

    d_cons_top = st.columns(3)
    render_delta_card(
        d_cons_top[0],
        "Δ Total de Consultivos",
        formatar_delta_inteiro_br(resumo.delta_consultivos, "cons."),
        valor_base=formatar_numero_br(resumo.consultivos_base),
        valor_atual=formatar_numero_br(resumo.consultivos_comp),
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_consultivos,
            atual=resumo.consultivos_comp,
            base=resumo.consultivos_base,
        ),
        direcao=_trend_variacao(resumo.delta_consultivos),
        icone="📋",
        detalhe=f"Média ativa: {formatar_delta_decimal_br(diff_mc, 1, 'cons./mês')}",
        detalhe_pct=(
            f"Média: {formatar_variacao_pct_br(resumo.pct_media_cons, atual=resumo.media_mensal_cons_comp, base=resumo.media_mensal_cons_base)}"
        ),
        detalhe_pct_direcao=_trend_variacao(diff_mc),
        num_base=resumo.consultivos_base,
        num_atual=resumo.consultivos_comp,
    )
    render_delta_card(
        d_cons_top[1],
        "Δ Total de Produtos",
        formatar_delta_inteiro_br(resumo.delta_produtos, "prod."),
        valor_base=formatar_numero_br(resumo.produtos_base),
        valor_atual=formatar_numero_br(resumo.produtos_comp),
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_produtos,
            atual=resumo.produtos_comp,
            base=resumo.produtos_base,
        ),
        direcao=_trend_variacao(resumo.delta_produtos),
        icone="📦",
        detalhe=f"Média ativa: {formatar_delta_decimal_br(diff_mp, 1, 'prod./mês')}",
        detalhe_pct=(
            f"Média: {formatar_variacao_pct_br(resumo.pct_media_prod, atual=resumo.media_mensal_prod_comp, base=resumo.media_mensal_prod_base)}"
        ),
        detalhe_pct_direcao=_trend_variacao(diff_mp),
        num_base=resumo.produtos_base,
        num_atual=resumo.produtos_comp,
    )
    render_delta_card(
        d_cons_top[2],
        "Δ Conversão Prod./Cons.",
        formatar_delta_decimal_br(resumo.delta_conversao, 2, "x"),
        valor_base=f"{_formatar_decimal_br(resumo.conversao_base, 2)}x",
        valor_atual=f"{_formatar_decimal_br(resumo.conversao_comp, 2)}x",
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_conversao,
            atual=resumo.conversao_comp,
            base=resumo.conversao_base,
        ),
        direcao=_trend_variacao(resumo.delta_conversao),
        icone="🎯",
        detalhe=f"Equipes produtivas: {formatar_delta_inteiro_br(diff_eq, 'eq.')}",
        detalhe_pct=(
            f"Equipes: {formatar_variacao_pct_br(pct_eq, atual=resumo.equipes_produtivas_comp, base=resumo.equipes_produtivas_base)}"
        ),
        detalhe_pct_direcao=_trend_variacao(diff_eq),
        num_base=resumo.conversao_base,
        num_atual=resumo.conversao_comp,
    )

    st.markdown("<div style='height:0.45rem'></div>", unsafe_allow_html=True)

    def _info_share_mix(vol_b: int, vol_c: int) -> tuple[str, str, TipoTrendType]:
        sh_b = (
            (vol_b / resumo.produtos_base * 100.0) if resumo.produtos_base > 0 else 0.0
        )
        sh_c = (
            (vol_c / resumo.produtos_comp * 100.0) if resumo.produtos_comp > 0 else 0.0
        )
        diff_pp = sh_c - sh_b
        return (
            f"Mix {ano_comp}: {_formatar_decimal_br(sh_c, 1)}%",
            f"Δ Mix: {formatar_delta_decimal_br(diff_pp, 1, 'p.p.')}",
            _trend_variacao(diff_pp),
        )

    det_mesh, pp_mesh, dir_pp_mesh = _info_share_mix(resumo.mesh_base, resumo.mesh_comp)
    det_tv, pp_tv, dir_pp_tv = _info_share_mix(resumo.tv_base, resumo.tv_comp)
    det_virt, pp_virt, dir_pp_virt = _info_share_mix(
        resumo.virtua_base, resumo.virtua_comp
    )

    d_cons_mix = st.columns(3)
    render_delta_card(
        d_cons_mix[0],
        "Δ Mesh",
        formatar_delta_inteiro_br(resumo.delta_mesh, "un."),
        valor_base=formatar_numero_br(resumo.mesh_base),
        valor_atual=formatar_numero_br(resumo.mesh_comp),
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_mesh,
            atual=resumo.mesh_comp,
            base=resumo.mesh_base,
        ),
        direcao=_trend_variacao(resumo.delta_mesh),
        icone="📶",
        detalhe=det_mesh,
        detalhe_pct=pp_mesh,
        detalhe_pct_direcao=dir_pp_mesh,
        num_base=resumo.mesh_base,
        num_atual=resumo.mesh_comp,
    )
    render_delta_card(
        d_cons_mix[1],
        "Δ TV Box",
        formatar_delta_inteiro_br(resumo.delta_tv, "un."),
        valor_base=formatar_numero_br(resumo.tv_base),
        valor_atual=formatar_numero_br(resumo.tv_comp),
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_tv,
            atual=resumo.tv_comp,
            base=resumo.tv_base,
        ),
        direcao=_trend_variacao(resumo.delta_tv),
        icone="📺",
        detalhe=det_tv,
        detalhe_pct=pp_tv,
        detalhe_pct_direcao=dir_pp_tv,
        num_base=resumo.tv_base,
        num_atual=resumo.tv_comp,
    )
    render_delta_card(
        d_cons_mix[2],
        "Δ Virtua",
        formatar_delta_inteiro_br(resumo.delta_virtua, "un."),
        valor_base=formatar_numero_br(resumo.virtua_base),
        valor_atual=formatar_numero_br(resumo.virtua_comp),
        rotulo_base=str(ano_base),
        rotulo_atual=str(ano_comp),
        variacao_pct=formatar_variacao_pct_br(
            resumo.pct_virtua,
            atual=resumo.virtua_comp,
            base=resumo.virtua_base,
        ),
        direcao=_trend_variacao(resumo.delta_virtua),
        icone="🌐",
        detalhe=det_virt,
        detalhe_pct=pp_virt,
        detalhe_pct_direcao=dir_pp_virt,
        num_base=resumo.virtua_base,
        num_atual=resumo.virtua_comp,
    )

    st.markdown("<div style='height:0.65rem'></div>", unsafe_allow_html=True)

    # Linha 1 de KPIs: Consultivos, Produtos e Conversão.
    k_row1 = st.columns(3)
    render_kpi(
        k_row1[0],
        f"Total Consultivos ({ano_comp} vs {ano_base})",
        formatar_numero_br(resumo.consultivos_comp),
        sub=(
            f"Base {ano_base}: {formatar_numero_br(resumo.consultivos_base)} · "
            f"Δ {formatar_delta_inteiro_br(resumo.delta_consultivos)}"
        ),
        icone="📋",
        tema=_tema_variacao(resumo.delta_consultivos, "azul"),
        delta=_formatar_pct_br(resumo.pct_consultivos),
        delta_tipo=_trend_variacao(resumo.delta_consultivos),
    )
    render_kpi(
        k_row1[1],
        f"Total Produtos ({ano_comp} vs {ano_base})",
        formatar_numero_br(resumo.produtos_comp),
        sub=(
            f"Base {ano_base}: {formatar_numero_br(resumo.produtos_base)} · "
            f"Δ {formatar_delta_inteiro_br(resumo.delta_produtos)}"
        ),
        icone="📦",
        tema=_tema_variacao(resumo.delta_produtos, "laranja"),
        delta=_formatar_pct_br(resumo.pct_produtos),
        delta_tipo=_trend_variacao(resumo.delta_produtos),
    )
    render_kpi(
        k_row1[2],
        f"Conversão Prod./Cons. ({ano_comp})",
        f"{_formatar_decimal_br(resumo.conversao_comp, 2)}x",
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.conversao_base, 2)}x · "
            f"Δ {_formatar_decimal_br(resumo.delta_conversao, 2, com_sinal=True)}"
        ),
        icone="🎯",
        tema="roxo",
        delta=_formatar_pct_br(resumo.pct_conversao),
        delta_tipo=_trend_variacao(resumo.delta_conversao),
    )

    st.markdown("<div style='height:0.55rem'></div>", unsafe_allow_html=True)

    # Linha 2 de KPIs: Médias Mensais Ativas e Produtividade / Meta por Equipe.
    k_row2 = st.columns(3)
    render_kpi(
        k_row2[0],
        f"Média Mensal · Consultivos ({ano_comp})",
        _formatar_decimal_br(resumo.media_mensal_cons_comp, 1),
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.media_mensal_cons_base, 1)}/mês "
            f"({resumo.meses_ativos_base}→{resumo.meses_ativos_comp}m)"
        ),
        icone="📆",
        tema=_tema_variacao(diff_mc, "azul"),
        delta=_formatar_pct_br(resumo.pct_media_cons),
        delta_tipo=_trend_variacao(diff_mc),
    )
    render_kpi(
        k_row2[1],
        f"Média Mensal · Produtos ({ano_comp})",
        _formatar_decimal_br(resumo.media_mensal_prod_comp, 1),
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.media_mensal_prod_base, 1)}/mês "
            f"({resumo.meses_ativos_base}→{resumo.meses_ativos_comp}m)"
        ),
        icone="⚡",
        tema=_tema_variacao(diff_mp, "laranja"),
        delta=_formatar_pct_br(resumo.pct_media_prod),
        delta_tipo=_trend_variacao(diff_mp),
    )
    render_kpi(
        k_row2[2],
        f"Volume / Equipe Produtiva ({ano_comp})",
        f"{_formatar_decimal_br(resumo.cons_por_equipe_comp, 1)} cons · {_formatar_decimal_br(resumo.prod_por_equipe_comp, 1)} prod",
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.cons_por_equipe_base, 1)} cons · "
            f"{_formatar_decimal_br(resumo.prod_por_equipe_base, 1)} prod "
            f"({resumo.equipes_produtivas_base}→{resumo.equipes_produtivas_comp} eq.)"
        ),
        icone="👷",
        tema="gradiente",
    )

    st.markdown("<div style='height:0.65rem'></div>", unsafe_allow_html=True)

    aba_mensal, aba_mix, aba_dimensoes, aba_vendedores = st.tabs(
        [
            "📈 Evolução Mensal (Jan–Dez)",
            "📦 Mix de Produtos & Planos",
            "🏗️ Bases, Monitores e U.N.",
            "👷 Comparativo por Técnico",
        ]
    )

    with aba_mensal:
        gm1, gm2 = st.columns(2)
        with gm1:
            with st.container(border=True):
                render_section_header(
                    f"Consultivos por mês · {ano_base} x {ano_comp}",
                    subtitulo="Barras sólidas indicam os meses dentro do recorte comparativo ativo",
                    icone="📋",
                )
                st.plotly_chart(
                    _grafico_mensal_consultivo(
                        resumo.mensal,
                        col_base="consultivos_base",
                        col_comp="consultivos_comp",
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                        cor_base=_COR_2025_CONS,
                        cor_comp=_COR_2026_CONS,
                        unidade="Consultivos",
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_mensal_cons",
                )
        with gm2:
            with st.container(border=True):
                render_section_header(
                    f"Produtos comercializados por mês · {ano_base} x {ano_comp}",
                    subtitulo="Soma mensal de Mesh + TV Box + Virtua em cada competência",
                    icone="📦",
                )
                st.plotly_chart(
                    _grafico_mensal_consultivo(
                        resumo.mensal,
                        col_base="produtos_base",
                        col_comp="produtos_comp",
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                        cor_base=_COR_2025_PROD,
                        cor_comp=_COR_2026_PROD,
                        unidade="Produtos",
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_mensal_prod",
                )

        gm3, gm4 = st.columns([1.15, 1.0])
        with gm3:
            with st.container(border=True):
                acc_hdr = st.columns([1.5, 1.0])
                with acc_hdr[0]:
                    render_section_header(
                        f"Ritmo acumulado no recorte · {ano_base} x {ano_comp}",
                        subtitulo="Trajetória acumulada mês a mês nos meses considerados",
                        icone="🚀",
                    )
                with acc_hdr[1]:
                    m_acum = st.radio(
                        "Indicador acumulado consultivo",
                        options=["consultivos", "produtos"],
                        format_func=lambda m: (
                            "Consultivos" if m == "consultivos" else "Produtos"
                        ),
                        horizontal=True,
                        key="comp_cons_acum_metrica",
                        label_visibility="collapsed",
                    )
                m_acum_lit: Literal["consultivos", "produtos"] = (
                    "produtos" if m_acum == "produtos" else "consultivos"
                )
                st.plotly_chart(
                    _grafico_acumulado_consultivo(
                        resumo.mensal,
                        metrica=m_acum_lit,
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_acum",
                )
        with gm4:
            with st.container(border=True):
                render_section_header(
                    f"Conversão Produtos / Consultivo · {ano_base} x {ano_comp}",
                    subtitulo="Densidade média de produtos instalados por atendimento consultivo",
                    icone="🎯",
                )
                st.plotly_chart(
                    _grafico_conversao_mensal(resumo.mensal, ano_base, ano_comp),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_conv",
                )

        with st.container(border=True):
            render_section_header(
                f"Matriz mensal detalhada · {ano_base} x {ano_comp}",
                subtitulo="Comparação mês a mês de Consultivos, Produtos, Mix e Conversão",
                icone="📊",
            )
            tab_mensal = resumo.mensal[
                [
                    "mes_nome",
                    "em_escopo",
                    "consultivos_base",
                    "consultivos_comp",
                    "delta_consultivos",
                    "pct_consultivos",
                    "produtos_base",
                    "produtos_comp",
                    "delta_produtos",
                    "pct_produtos",
                    "conversao_base",
                    "conversao_comp",
                    "equipes_base",
                    "equipes_comp",
                ]
            ].copy()
            tab_mensal["em_escopo"] = tab_mensal["em_escopo"].map(
                lambda ok: "Sim" if bool(ok) else "Fora do recorte"
            )
            tab_mensal = tab_mensal.rename(
                columns={
                    "mes_nome": "Mês",
                    "em_escopo": "No recorte",
                    "consultivos_base": f"Cons. {ano_base}",
                    "consultivos_comp": f"Cons. {ano_comp}",
                    "delta_consultivos": "Δ Cons.",
                    "pct_consultivos": "Var. Cons. (%)",
                    "produtos_base": f"Prod. {ano_base}",
                    "produtos_comp": f"Prod. {ano_comp}",
                    "delta_produtos": "Δ Prod.",
                    "pct_produtos": "Var. Prod. (%)",
                    "conversao_base": f"Conv. {ano_base}",
                    "conversao_comp": f"Conv. {ano_comp}",
                    "equipes_base": f"Equipes {ano_base}",
                    "equipes_comp": f"Equipes {ano_comp}",
                }
            )
            st.dataframe(
                _estilizar_tabela(
                    tab_mensal,
                    colunas_inteiras=[
                        f"Cons. {ano_base}",
                        f"Cons. {ano_comp}",
                        f"Prod. {ano_base}",
                        f"Prod. {ano_comp}",
                        f"Equipes {ano_base}",
                        f"Equipes {ano_comp}",
                    ],
                    colunas_delta=["Δ Cons.", "Δ Prod."],
                    colunas_pct=["Var. Cons. (%)", "Var. Prod. (%)"],
                    colunas_decimais=[f"Conv. {ano_base}", f"Conv. {ano_comp}"],
                ),
                width="stretch",
                hide_index=True,
            )
            st.download_button(
                "📥 Baixar comparativo mensal de Consultivos (CSV)",
                data=sanitizar_csv_exportacao(tab_mensal),
                file_name=f"comparativo_consultivo_mensal_{ano_base}_{ano_comp}_{date.today().strftime('%d_%m_%Y')}.csv",
                mime="text/csv",
                key="comp_cons_dl_mensal",
            )

    with aba_mix:
        fig_mix_vol, fig_mix_sh = _grafico_mix_produtos(
            resumo.mix_produtos, ano_base, ano_comp
        )
        mx1, mx2 = st.columns([1.15, 1.0])
        with mx1:
            with st.container(border=True):
                render_section_header(
                    f"Volume por família de produto · {ano_base} x {ano_comp}",
                    subtitulo="Evolução absoluta de Mesh, TV Box e Virtua no recorte",
                    icone="📦",
                )
                st.plotly_chart(
                    fig_mix_vol,
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_mix_vol",
                )
        with mx2:
            with st.container(border=True):
                render_section_header(
                    f"Mudança de Share no portfólio · {ano_base} x {ano_comp}",
                    subtitulo="Participação percentual (%) de cada linha no total de produtos",
                    icone="🥧",
                )
                st.plotly_chart(
                    fig_mix_sh,
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_mix_share",
                )

        with st.container(border=True):
            render_section_header(
                f"Resumo do Mix (Mesh, TV Box e Virtua) · {ano_base} x {ano_comp}",
                subtitulo="Variação de quantidade e deslocamento em pontos percentuais (p.p.)",
                icone="📶",
            )
            st.dataframe(
                _estilizar_tabela(
                    resumo.mix_produtos,
                    colunas_inteiras=[f"Qtde {ano_base}", f"Qtde {ano_comp}"],
                    colunas_delta=["Δ Qtde"],
                    colunas_pct=["Var. (%)"],
                    colunas_decimais=[
                        f"Share {ano_base} (%)",
                        f"Share {ano_comp} (%)",
                        "Δ Share (p.p.)",
                    ],
                ),
                width="stretch",
                hide_index=True,
            )

        with st.container(border=True):
            render_section_header(
                f"Comparativo por Tipo de Serviço / Plano · {ano_base} x {ano_comp}",
                subtitulo="Ofertas individuais e combinadas (TV + Fibra + Serviços Avançados)",
                icone="📑",
            )
            if resumo.por_tipo_servico.empty:
                st.info("Não há planos classificados para o filtro atual.")
            else:
                st.dataframe(
                    _estilizar_tabela(
                        resumo.por_tipo_servico,
                        colunas_inteiras=[
                            f"Cons. {ano_base}",
                            f"Cons. {ano_comp}",
                            f"Prod. {ano_base}",
                            f"Prod. {ano_comp}",
                            f"Mesh {ano_comp}",
                            f"TV Box {ano_comp}",
                            f"Virtua {ano_comp}",
                            f"Equipes {ano_base}",
                            f"Equipes {ano_comp}",
                        ],
                        colunas_delta=["Δ Cons.", "Δ Prod."],
                        colunas_pct=["Var. Cons. (%)", "Var. Prod. (%)"],
                        colunas_decimais=[f"Conv. {ano_base}", f"Conv. {ano_comp}"],
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    "📥 Baixar mix e tipos de serviço (CSV)",
                    data=sanitizar_csv_exportacao(resumo.por_tipo_servico),
                    file_name=f"comparativo_consultivo_planos_{ano_base}_{ano_comp}_{date.today().strftime('%d_%m_%Y')}.csv",
                    mime="text/csv",
                    key="comp_cons_dl_planos",
                )

    with aba_dimensoes:
        d_ctrl1, d_ctrl2 = st.columns([1.2, 1.2])
        with d_ctrl1:
            dim_escolhida = st.radio(
                "Agrupar comparativo por",
                options=["Monitor", "Base", "U.N."],
                horizontal=True,
                key="comp_cons_dim_radio",
            )
        with d_ctrl2:
            met_dim = st.radio(
                "Métrica em destaque no gráfico",
                options=["Cons.", "Prod."],
                format_func=lambda m: "Consultivos" if m == "Cons." else "Produtos",
                horizontal=True,
                key="comp_cons_dim_metrica",
            )

        tabela_dim = (
            resumo.por_monitor
            if dim_escolhida == "Monitor"
            else (resumo.por_base if dim_escolhida == "Base" else resumo.por_un)
        )
        if tabela_dim.empty:
            st.info(f"Não há dados por {dim_escolhida} para os filtros atuais.")
        else:
            with st.container(border=True):
                render_section_header(
                    f"Deslocamento {ano_base} → {ano_comp} por {dim_escolhida}",
                    subtitulo="Comparação direta de patamar entre o ano-base e o ano atual",
                    icone="🏗️",
                )
                st.plotly_chart(
                    _grafico_dumbbell_consultivo(
                        tabela_dim,
                        rotulo=dim_escolhida,
                        metrica_prefixo=met_dim,
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                        cor_comp=_COR_2026_CONS
                        if met_dim == "Cons."
                        else _COR_2026_PROD,
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_dumbbell",
                )

            with st.container(border=True):
                render_section_header(
                    f"Tabela comparativa por {dim_escolhida}",
                    subtitulo="Volumes, variação percentual, mix 2026 e conversão",
                    icone="📋",
                )
                st.dataframe(
                    _estilizar_tabela(
                        tabela_dim,
                        colunas_inteiras=[
                            f"Cons. {ano_base}",
                            f"Cons. {ano_comp}",
                            f"Prod. {ano_base}",
                            f"Prod. {ano_comp}",
                            f"Mesh {ano_comp}",
                            f"TV Box {ano_comp}",
                            f"Virtua {ano_comp}",
                            f"Equipes {ano_base}",
                            f"Equipes {ano_comp}",
                        ],
                        colunas_delta=["Δ Cons.", "Δ Prod."],
                        colunas_pct=["Var. Cons. (%)", "Var. Prod. (%)"],
                        colunas_decimais=[f"Conv. {ano_base}", f"Conv. {ano_comp}"],
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    f"📥 Baixar comparativo por {dim_escolhida} (CSV)",
                    data=sanitizar_csv_exportacao(tabela_dim),
                    file_name=f"comparativo_consultivo_{dim_escolhida.lower().replace('.', '')}_{ano_base}_{ano_comp}_{date.today().strftime('%d_%m_%Y')}.csv",
                    mime="text/csv",
                    key="comp_cons_dl_dim",
                )

    with aba_vendedores:
        if resumo.por_vendedor.empty:
            st.info("Não há colaboradores com consultivos para os filtros atuais.")
        else:
            with st.container(border=True):
                render_section_header(
                    f"Mapa de evolução por técnico / vendedor ({ano_comp} − {ano_base})",
                    subtitulo="Quadrante superior direito destaca expansão simultânea em Consultivos e Produtos",
                    icone="🧭",
                )
                st.plotly_chart(
                    _grafico_quadrante_vendedores(
                        resumo.por_vendedor, ano_base, ano_comp
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_cons_chart_quadrante",
                )

            with st.container(border=True):
                busca_v = st.text_input(
                    "Filtrar colaborador por nome, login, base ou monitor",
                    value="",
                    placeholder="Ex.: André, Z6400, NET-ABCDM...",
                    key="comp_cons_busca_vendedor",
                )
                tab_vend = resumo.por_vendedor.copy()
                if busca_v.strip():
                    termo = busca_v.strip().lower()
                    mask_v = (
                        tab_vend["Técnico / Vendedor"]
                        .str.lower()
                        .str.contains(termo, na=False)
                        | tab_vend["Login"].str.lower().str.contains(termo, na=False)
                        | tab_vend["Base"].str.lower().str.contains(termo, na=False)
                        | tab_vend["Monitor"].str.lower().str.contains(termo, na=False)
                    )
                    tab_vend = tab_vend[mask_v].copy()

                st.dataframe(
                    _estilizar_tabela(
                        tab_vend,
                        colunas_inteiras=[
                            f"Cons. {ano_base}",
                            f"Cons. {ano_comp}",
                            f"Prod. {ano_base}",
                            f"Prod. {ano_comp}",
                        ],
                        colunas_delta=[
                            "Δ Cons.",
                            "Δ Prod.",
                            "Δ Mesh",
                            "Δ TV Box",
                            "Δ Virtua",
                        ],
                        colunas_pct=["Var. Cons. (%)", "Var. Prod. (%)"],
                        colunas_decimais=[f"Conv. {ano_base}", f"Conv. {ano_comp}"],
                    ),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    "📥 Baixar comparativo por técnico / vendedor (CSV)",
                    data=sanitizar_csv_exportacao(tab_vend),
                    file_name=f"comparativo_consultivo_tecnicos_{ano_base}_{ano_comp}_{date.today().strftime('%d_%m_%Y')}.csv",
                    mime="text/csv",
                    key="comp_cons_dl_vendedores",
                )


__all__ = [
    "REGRA_COMPARATIVO_CONSULTIVO",
    "ResumoComparativoConsultivo",
    "calcular_comparativo_consultivo",
    "render_comparativo_consultivo",
]
