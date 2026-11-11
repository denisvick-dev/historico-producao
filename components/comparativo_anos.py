"""Análise comparativa interanual (2025 x 2026) de Contratos e O.S. (Prod).

Cruza a evolução histórica de **Contratos** e **Ordens de Serviço (O.S.)** entre dois
anos (padrão **2025 x 2026**), preservando integralmente as regras oficiais do painel:

- **Contratos**: identificadores válidos distintos de ``contract`` por
  ``(technician, period)`` considerando todas as abas importadas (``Prod`` + ``Gpon``).
- **O.S. (Prod)**: cada linha válida da aba ``Prod`` com técnico e competência
  equivale a ``1`` O.S.
- **Relação O.S. / Contrato (Giro)**: ``O.S. (Prod) ÷ Contratos``, medindo a
  densidade média de atendimentos/ordens por contrato em cada período.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler

from components.componentes import (
    Cores,
    Fontes,
    TemaKPIType,
    TipoInsightType,
    TipoTrendType,
    formatar_numero_br,
    injetar_css,
    render_insight,
    render_kpi,
    render_section_header,
    render_ticker,
)
from components.painel_quantidades import (
    AZUL_TOTALE,
    CHART_CONFIG,
    LARANJA_TOTALE,
    csv_download,
)
from production import (
    GPON,
    MONTHS_SHORT,
    PROD,
    clean_contract,
    format_points,
    is_valid_contract,
)

ModoMesesComparativo = Literal["equivalente", "ano_completo", "personalizado"]
EscopoEquipeComparativo = Literal["todos", "ativos", "mesma_equipe"]

MESES_NOMES: tuple[str, ...] = (
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
)

REGRA_COMPARATIVO_ANOS = (
    "Contratos somam contratos distintos válidos por técnico e competência (Prod + Gpon). "
    "O.S. somam as linhas válidas da aba Prod (1 linha Prod = 1 O.S.). "
    "No modo 'Mesmos meses', apenas os meses presentes nos dois anos entram nos totais "
    "acumulados, evitando distorção por ano em andamento."
)

_COR_2025_CONTRATOS = "#94A3B8"
_COR_2026_CONTRATOS = AZUL_TOTALE
_COR_2025_OS = "#FDBA74"
_COR_2026_OS = LARANJA_TOTALE
_VERDE = "#047857"
_VERMELHO = "#DC2626"
_ROXO = "#6D28D9"

_CSS_COMPARATIVO = """
.comp-hero {
    position: relative;
    overflow: hidden;
    padding: 1.35rem 1.5rem 1.25rem;
    margin-bottom: 1rem;
    border-radius: 16px;
    background: linear-gradient(128deg, #041329 0%, #012869 56%, #0D3D8A 100%);
    border: 1px solid rgba(255, 255, 255, 0.14);
    box-shadow: 0 12px 30px rgba(1, 40, 105, 0.16);
    color: #F8FAFC;
}
.comp-hero::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 4px;
    background: linear-gradient(90deg, #F37C04 0%, #FDBA74 52%, #38BDF8 100%);
}
.comp-hero::after {
    content: "";
    position: absolute;
    right: -60px;
    top: -70px;
    width: 220px;
    height: 220px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(243, 124, 4, 0.22), transparent 68%);
    pointer-events: none;
}
.comp-hero-top {
    position: relative;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
}
.comp-hero-eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: rgba(243, 124, 4, 0.18);
    border: 1px solid rgba(253, 186, 116, 0.36);
    color: #FDBA74;
    font-size: 10.5px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.comp-hero h2 {
    margin: 0.45rem 0 0.25rem !important;
    color: #FFFFFF !important;
    font-size: 1.55rem !important;
    font-weight: 820 !important;
    letter-spacing: -0.03em !important;
}
.comp-hero p {
    margin: 0 !important;
    color: #CBD5E1 !important;
    font-size: 13px !important;
    max-width: 760px;
    line-height: 1.48;
}
.comp-pills {
    position: relative;
    z-index: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 0.95rem;
}
.comp-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 11px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.09);
    border: 1px solid rgba(255, 255, 255, 0.16);
    color: #F1F5F9;
    font-size: 11.5px;
    font-weight: 650;
}
.comp-pill strong {
    color: #FDBA74;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
}
.comp-rule-note {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-left: 4px solid #012869;
    border-radius: 10px;
    padding: 0.68rem 0.95rem;
    font-size: 12px;
    color: #334155;
    margin: 0.35rem 0 0.9rem;
}
"""


@dataclass(frozen=True)
class ResumoComparativoAnos:
    """Estrutura imutável com todos os indicadores do comparativo interanual."""

    ano_base: int
    ano_comp: int
    modo_solicitado: ModoMesesComparativo
    modo_efetivo: ModoMesesComparativo
    fallback_sem_intersecao: bool
    escopo_equipe: EscopoEquipeComparativo
    meses_disponiveis_base: list[int]
    meses_disponiveis_comp: list[int]
    meses_intersecao: list[int]
    meses_considerados: list[int]
    rotulo_recorte_meses: str
    contratos_base: int
    contratos_comp: int
    delta_contratos: int
    pct_contratos: float | None
    os_base: int
    os_comp: int
    delta_os: int
    pct_os: float | None
    os_por_contrato_base: float
    os_por_contrato_comp: float
    delta_os_por_contrato: float
    pct_os_por_contrato: float | None
    meses_ativos_contratos_base: int
    meses_ativos_contratos_comp: int
    media_mensal_contratos_base: float
    media_mensal_contratos_comp: float
    pct_media_contratos: float | None
    meses_ativos_os_base: int
    meses_ativos_os_comp: int
    media_mensal_os_base: float
    media_mensal_os_comp: float
    pct_media_os: float | None
    tecnicos_ativos_base: int
    tecnicos_ativos_comp: int
    tecnicos_comuns: int
    contratos_por_tecnico_base: float
    contratos_por_tecnico_comp: float
    os_por_tecnico_base: float
    os_por_tecnico_comp: float
    pontos_prod_base: float
    pontos_prod_comp: float
    pontos_totais_base: float
    pontos_totais_comp: float
    sem_contrato_registros: int
    linhas_incompletas: int
    mensal: pd.DataFrame
    tabela_mensal: pd.DataFrame
    por_projeto: pd.DataFrame
    por_base: pd.DataFrame
    por_monitor: pd.DataFrame
    por_tecnico: pd.DataFrame


def _parse_datas_seguras(serie: pd.Series) -> pd.Series:
    """Converte série de datas preservando ISO YYYY-MM-DD e formato brasileiro DD/MM/YYYY."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")

    texto = serie.astype("string").str.strip()
    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
    formatos = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%y",
    )
    for fmt in formatos:
        faltantes = resultado.isna() & texto.notna() & texto.ne("")
        if not faltantes.any():
            break
        convertido = pd.to_datetime(texto.loc[faltantes], format=fmt, errors="coerce")
        validos = convertido.notna()
        if validos.any():
            idx_ok = convertido.index[validos]
            resultado.loc[idx_ok] = convertido.loc[idx_ok].astype("datetime64[ns]")

    restantes = resultado.isna() & texto.notna() & texto.ne("")
    if restantes.any():
        try:
            fallback = pd.to_datetime(
                texto.loc[restantes], format="mixed", dayfirst=True, errors="coerce"
            )
        except ValueError:
            fallback = pd.to_datetime(
                texto.loc[restantes], utc=True, errors="coerce"
            ).dt.tz_localize(None)
        ok_fb = fallback.notna()
        if ok_fb.any():
            idx_fb = fallback.index[ok_fb]
            resultado.loc[idx_fb] = fallback.loc[idx_fb].astype("datetime64[ns]")
    return resultado


def _variacao_pct(atual: float | int, base: float | int) -> float | None:
    if float(base) == 0.0:
        return None
    return ((float(atual) - float(base)) / float(base)) * 100.0


def _formatar_pct_br(valor: float | None, com_sinal: bool = True) -> str:
    if valor is None or pd.isna(valor):
        return "Novo"
    sinal = "+" if (com_sinal and valor > 0) else ""
    numero = f"{valor:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}{numero}%"


def _formatar_decimal_br(valor: float, casas: int = 2, com_sinal: bool = False) -> str:
    sinal = "+" if (com_sinal and valor > 0) else ""
    numero = f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{sinal}{numero}"


def _descrever_meses(meses: Sequence[int]) -> str:
    ordenados = sorted({int(m) for m in meses if 1 <= int(m) <= 12})
    if not ordenados:
        return "Nenhum mês"
    if ordenados == list(range(1, 13)):
        return "Jan a Dez (12 meses)"
    if (
        ordenados == list(range(ordenados[0], ordenados[-1] + 1))
        and len(ordenados) >= 2
    ):
        ini = MESES_NOMES[ordenados[0] - 1]
        fim = MESES_NOMES[ordenados[-1] - 1]
        return f"{ini} a {fim} ({len(ordenados)} meses)"
    nomes = ", ".join(MESES_NOMES[m - 1] for m in ordenados)
    sufixo = "mês" if len(ordenados) == 1 else "meses"
    return f"{nomes} ({len(ordenados)} {sufixo})"


def _preparar_base_limpa(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    """Normaliza técnicos, competências, contratos válidos e origem Prod/Gpon."""
    colunas_saida = [
        "technician",
        "period",
        "year",
        "month",
        "source_sheet",
        "project",
        "base",
        "monitor",
        "roster_status",
        "points",
        "contract_clean",
        "contract_valid",
    ]
    if frame.empty:
        return pd.DataFrame(columns=colunas_saida), 0, 0

    if "technician" in frame.columns:
        tecnicos = frame["technician"].astype("string").str.strip()
    else:
        tecnicos = pd.Series(pd.NA, index=frame.index, dtype="string")

    datas = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    if "period" in frame.columns:
        datas = _parse_datas_seguras(frame["period"])
    if "reference_date" in frame.columns:
        faltam = datas.isna()
        if faltam.any():
            datas.loc[faltam] = _parse_datas_seguras(
                frame.loc[faltam, "reference_date"]
            ).astype("datetime64[ns]")
    competencias = datas.dt.to_period("M").dt.to_timestamp()

    incompletos = (
        tecnicos.isna()
        | tecnicos.str.casefold().isin(
            ["", "sem técnico", "sem tecnico", "none", "nan", "null"]
        )
        | competencias.isna()
    )
    linhas_incompletas = int(incompletos.sum())
    if incompletos.all():
        return pd.DataFrame(columns=colunas_saida), 0, linhas_incompletas

    mask_ok = ~incompletos
    recorte = frame.loc[mask_ok]
    comp_ok = competencias.loc[mask_ok]

    if "contract" in recorte.columns:
        contratos_raw = recorte["contract"].astype("string")
        unicos_raw = contratos_raw.dropna().unique()
        mapa_limpo = {valor: clean_contract(valor) for valor in unicos_raw}
        contratos_limpos = contratos_raw.map(mapa_limpo)
        unicos_limpos = pd.Series(contratos_limpos).dropna().unique()
        mapa_valido = {valor: is_valid_contract(valor) for valor in unicos_limpos}
        contrato_valido = (
            pd.Series(contratos_limpos, index=recorte.index)
            .map(mapa_valido)
            .fillna(False)
            .astype(bool)
        )
    else:
        contratos_limpos = pd.Series("", index=recorte.index, dtype="object")
        contrato_valido = pd.Series(False, index=recorte.index, dtype="bool")

    sem_contrato = int((~contrato_valido).sum())

    origens = (
        recorte["source_sheet"].astype("string").str.strip().fillna(PROD)
        if "source_sheet" in recorte.columns
        else pd.Series(PROD, index=recorte.index, dtype="string")
    )
    pontos = (
        pd.to_numeric(recorte["points"], errors="coerce").fillna(0.0)
        if "points" in recorte.columns
        else pd.Series(0.0, index=recorte.index, dtype="float64")
    )

    def _dim_col(nome: str, padrao: str) -> pd.Series:
        if nome not in recorte.columns:
            return pd.Series(padrao, index=recorte.index, dtype="object")
        limpa = recorte[nome].fillna("").astype(str).str.strip()
        return limpa.mask(
            limpa.eq("") | limpa.str.casefold().isin(["nan", "none", "null"]),
            padrao,
        )

    preparado = pd.DataFrame(
        {
            "technician": tecnicos.loc[mask_ok].astype(str),
            "period": comp_ok,
            "year": comp_ok.dt.year.astype(int),
            "month": comp_ok.dt.month.astype(int),
            "source_sheet": origens.astype(str),
            "project": _dim_col("project", "Sem projeto"),
            "base": _dim_col("base", "Sem base"),
            "monitor": _dim_col("monitor", "Sem monitor"),
            "roster_status": _dim_col("roster_status", "Sem cadastro"),
            "points": pontos.where(origens.isin([PROD, GPON]), 0.0).astype(float),
            "contract_clean": pd.Series(contratos_limpos, index=recorte.index).fillna(
                ""
            ),
            "contract_valid": contrato_valido,
        },
        index=recorte.index,
    )
    return preparado, sem_contrato, linhas_incompletas


def _montar_resumo_dimensao(
    base_recorte: pd.DataFrame,
    coluna_dim: str,
    rotulo_dim: str,
    ano_base: int,
    ano_comp: int,
) -> pd.DataFrame:
    """Consolida Contratos, O.S. e relação O.S./Contrato por dimensão operacional."""
    colunas = [
        rotulo_dim,
        f"Contratos {ano_base}",
        f"Contratos {ano_comp}",
        "Δ Contratos",
        "Var. Contratos (%)",
        f"Part. Contratos {ano_comp} (%)",
        f"O.S. {ano_base}",
        f"O.S. {ano_comp}",
        "Δ O.S.",
        "Var. O.S. (%)",
        f"O.S./Contrato {ano_base}",
        f"O.S./Contrato {ano_comp}",
    ]
    if base_recorte.empty:
        return pd.DataFrame(columns=colunas)

    # Contratos distintos por (dimensão, técnico, competência, contrato) em cada ano.
    ct_validos = base_recorte[base_recorte["contract_valid"]].drop_duplicates(
        [coluna_dim, "year", "technician", "period", "contract_clean"]
    )
    ct_grp = (
        ct_validos.groupby([coluna_dim, "year"], dropna=False)
        .size()
        .unstack(fill_value=0)
    )
    os_prod = base_recorte[base_recorte["source_sheet"].eq(PROD)]
    os_grp = (
        os_prod.groupby([coluna_dim, "year"], dropna=False).size().unstack(fill_value=0)
    )

    chaves = sorted(set(ct_grp.index).union(set(os_grp.index)))
    if not chaves:
        return pd.DataFrame(columns=colunas)

    linhas: list[dict[str, object]] = []
    for chave in chaves:
        c_b = (
            int(ct_grp.loc[chave, ano_base])
            if (chave in ct_grp.index and ano_base in ct_grp.columns)
            else 0
        )
        c_c = (
            int(ct_grp.loc[chave, ano_comp])
            if (chave in ct_grp.index and ano_comp in ct_grp.columns)
            else 0
        )
        o_b = (
            int(os_grp.loc[chave, ano_base])
            if (chave in os_grp.index and ano_base in os_grp.columns)
            else 0
        )
        o_c = (
            int(os_grp.loc[chave, ano_comp])
            if (chave in os_grp.index and ano_comp in os_grp.columns)
            else 0
        )
        if c_b == 0 and c_c == 0 and o_b == 0 and o_c == 0:
            continue
        linhas.append(
            {
                rotulo_dim: str(chave),
                f"Contratos {ano_base}": c_b,
                f"Contratos {ano_comp}": c_c,
                "Δ Contratos": c_c - c_b,
                "Var. Contratos (%)": _variacao_pct(c_c, c_b),
                f"O.S. {ano_base}": o_b,
                f"O.S. {ano_comp}": o_c,
                "Δ O.S.": o_c - o_b,
                "Var. O.S. (%)": _variacao_pct(o_c, o_b),
                f"O.S./Contrato {ano_base}": (o_b / c_b) if c_b > 0 else 0.0,
                f"O.S./Contrato {ano_comp}": (o_c / c_c) if c_c > 0 else 0.0,
            }
        )

    if not linhas:
        return pd.DataFrame(columns=colunas)

    tabela = pd.DataFrame(linhas)
    soma_ct_comp = int(tabela[f"Contratos {ano_comp}"].sum())
    tabela[f"Part. Contratos {ano_comp} (%)"] = (
        (tabela[f"Contratos {ano_comp}"] / soma_ct_comp) * 100.0
        if soma_ct_comp > 0
        else 0.0
    )
    tabela = tabela.sort_values(
        by=[
            f"Contratos {ano_comp}",
            f"O.S. {ano_comp}",
            f"Contratos {ano_base}",
            rotulo_dim,
        ],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    return tabela[colunas]


def _classificar_status_tecnico(
    ct_b: int, ct_c: int, os_b: int, os_c: int, ano_base: int, ano_comp: int
) -> str:
    ativo_b = (ct_b > 0) or (os_b > 0)
    ativo_c = (ct_c > 0) or (os_c > 0)
    if ativo_c and not ativo_b:
        return f"Novo em {ano_comp}"
    if ativo_b and not ativo_c:
        return f"Apenas em {ano_base}"
    if not ativo_b and not ativo_c:
        return "Sem movimento"
    ref_b = ct_b if (ct_b > 0 or ct_c > 0) else os_b
    ref_c = ct_c if (ct_b > 0 or ct_c > 0) else os_c
    if ref_b > 0:
        var = ((ref_c - ref_b) / ref_b) * 100.0
        if var >= 5.0:
            return "Em evolução"
        if var <= -5.0:
            return "Retração"
    elif ref_c > 0:
        return "Em evolução"
    return "Estável"


def calcular_comparativo_anos(
    frame: pd.DataFrame,
    *,
    ano_base: int = 2025,
    ano_comp: int = 2026,
    modo_meses: ModoMesesComparativo = "equivalente",
    meses_selecionados: Sequence[int] | None = None,
    escopo_equipe: EscopoEquipeComparativo = "todos",
) -> ResumoComparativoAnos:
    """Executa toda a apuração interanual de Contratos, O.S. e Giro O.S./Contrato."""
    preparado, sem_contrato, incompletos = _preparar_base_limpa(frame)

    if not preparado.empty:
        preparado = preparado[preparado["year"].isin([ano_base, ano_comp])].copy()

    if (
        not preparado.empty
        and escopo_equipe == "ativos"
        and preparado["roster_status"].ne("Sem cadastro").any()
    ):
        preparado = preparado[preparado["roster_status"].eq("ATIVO")].copy()

    # Identifica meses com movimento real (contrato válido ou O.S. Prod) em cada ano.
    if preparado.empty:
        meses_disp_base: list[int] = []
        meses_disp_comp: list[int] = []
    else:
        mov = preparado[
            preparado["contract_valid"] | preparado["source_sheet"].eq(PROD)
        ]
        meses_disp_base = sorted(
            int(m) for m in mov.loc[mov["year"].eq(ano_base), "month"].unique()
        )
        meses_disp_comp = sorted(
            int(m) for m in mov.loc[mov["year"].eq(ano_comp), "month"].unique()
        )

    meses_intersecao = sorted(set(meses_disp_base) & set(meses_disp_comp))
    fallback_sem_intersecao = False
    modo_efetivo: ModoMesesComparativo = modo_meses

    if modo_meses == "equivalente":
        if meses_intersecao:
            meses_considerados = meses_intersecao
        else:
            uniao = sorted(set(meses_disp_base) | set(meses_disp_comp))
            meses_considerados = uniao if uniao else list(range(1, 13))
            modo_efetivo = "ano_completo"
            fallback_sem_intersecao = bool(meses_disp_base or meses_disp_comp)
    elif modo_meses == "personalizado":
        escolhidos = sorted(
            {int(m) for m in (meses_selecionados or range(1, 13)) if 1 <= int(m) <= 12}
        )
        meses_considerados = escolhidos or list(range(1, 13))
    else:
        meses_considerados = list(range(1, 13))

    # Escopo de "mesma equipe": técnicos com atividade em ambos os anos dentro dos meses considerados.
    if not preparado.empty and escopo_equipe == "mesma_equipe":
        mov_rec = preparado[
            preparado["month"].isin(meses_considerados)
            & (preparado["contract_valid"] | preparado["source_sheet"].eq(PROD))
        ]
        tecs_b = set(mov_rec.loc[mov_rec["year"].eq(ano_base), "technician"].unique())
        tecs_c = set(mov_rec.loc[mov_rec["year"].eq(ano_comp), "technician"].unique())
        comuns_filtro = tecs_b & tecs_c
        preparado = preparado[preparado["technician"].isin(comuns_filtro)].copy()

    # Série mensal completa (1..12) para visão panorâmica Jan–Dez + flag de mês considerado.
    if preparado.empty:
        ct_por_ano_mes: dict[tuple[int, int], int] = {}
        os_por_ano_mes: dict[tuple[int, int], int] = {}
    else:
        ct_dedup_all = preparado[preparado["contract_valid"]].drop_duplicates(
            ["year", "month", "technician", "period", "contract_clean"]
        )
        ct_por_ano_mes = {
            (int(k[0]), int(k[1])): int(v)
            for k, v in ct_dedup_all.groupby(["year", "month"]).size().items()
        }
        os_prod_all = preparado[preparado["source_sheet"].eq(PROD)]
        os_por_ano_mes = {
            (int(k[0]), int(k[1])): int(v)
            for k, v in os_prod_all.groupby(["year", "month"]).size().items()
        }

    linhas_mensais: list[dict[str, object]] = []
    acum_ct_b = 0
    acum_ct_c = 0
    acum_os_b = 0
    acum_os_c = 0
    considerados_set = set(meses_considerados)
    for mes_num in range(1, 13):
        cb = ct_por_ano_mes.get((ano_base, mes_num), 0)
        cc = ct_por_ano_mes.get((ano_comp, mes_num), 0)
        ob = os_por_ano_mes.get((ano_base, mes_num), 0)
        oc = os_por_ano_mes.get((ano_comp, mes_num), 0)
        eh_considerado = mes_num in considerados_set
        if eh_considerado:
            acum_ct_b += cb
            acum_ct_c += cc
            acum_os_b += ob
            acum_os_c += oc
        linhas_mensais.append(
            {
                "month": mes_num,
                "mes_label": MESES_NOMES[mes_num - 1],
                "mes_curto": MONTHS_SHORT[mes_num - 1],
                "considerado": eh_considerado,
                "contratos_base": cb,
                "contratos_comp": cc,
                "delta_contratos": cc - cb,
                "pct_contratos": _variacao_pct(cc, cb),
                "acum_contratos_base": acum_ct_b if eh_considerado else None,
                "acum_contratos_comp": acum_ct_c if eh_considerado else None,
                "os_base": ob,
                "os_comp": oc,
                "delta_os": oc - ob,
                "pct_os": _variacao_pct(oc, ob),
                "acum_os_base": acum_os_b if eh_considerado else None,
                "acum_os_comp": acum_os_c if eh_considerado else None,
                "os_por_contrato_base": (ob / cb) if cb > 0 else 0.0,
                "os_por_contrato_comp": (oc / cc) if cc > 0 else 0.0,
            }
        )
    mensal_df = pd.DataFrame(linhas_mensais)

    # Recorte efetivo para KPIs, totais e quebras dimensionais.
    recorte = (
        preparado[preparado["month"].isin(considerados_set)].copy()
        if not preparado.empty
        else preparado
    )

    mensal_rec = mensal_df[mensal_df["considerado"]].copy()
    contratos_base = int(mensal_rec["contratos_base"].sum())
    contratos_comp = int(mensal_rec["contratos_comp"].sum())
    delta_contratos = contratos_comp - contratos_base
    pct_contratos = _variacao_pct(contratos_comp, contratos_base)

    os_base = int(mensal_rec["os_base"].sum())
    os_comp = int(mensal_rec["os_comp"].sum())
    delta_os = os_comp - os_base
    pct_os = _variacao_pct(os_comp, os_base)

    giro_base = (os_base / contratos_base) if contratos_base > 0 else 0.0
    giro_comp = (os_comp / contratos_comp) if contratos_comp > 0 else 0.0
    delta_giro = giro_comp - giro_base
    pct_giro = _variacao_pct(giro_comp, giro_base)

    meses_ct_b = int(mensal_rec["contratos_base"].gt(0).sum())
    meses_ct_c = int(mensal_rec["contratos_comp"].gt(0).sum())
    media_ct_b = (contratos_base / meses_ct_b) if meses_ct_b > 0 else 0.0
    media_ct_c = (contratos_comp / meses_ct_c) if meses_ct_c > 0 else 0.0
    pct_media_ct = _variacao_pct(media_ct_c, media_ct_b)

    meses_os_b = int(mensal_rec["os_base"].gt(0).sum())
    meses_os_c = int(mensal_rec["os_comp"].gt(0).sum())
    media_os_b = (os_base / meses_os_b) if meses_os_b > 0 else 0.0
    media_os_c = (os_comp / meses_os_c) if meses_os_c > 0 else 0.0
    pct_media_os = _variacao_pct(media_os_c, media_os_b)

    if recorte.empty:
        tecs_ativos_b = 0
        tecs_ativos_c = 0
        tecs_comuns = 0
        pts_prod_b = 0.0
        pts_prod_c = 0.0
        pts_tot_b = 0.0
        pts_tot_c = 0.0
    else:
        mov_ef = recorte[recorte["contract_valid"] | recorte["source_sheet"].eq(PROD)]
        set_b = set(mov_ef.loc[mov_ef["year"].eq(ano_base), "technician"].unique())
        set_c = set(mov_ef.loc[mov_ef["year"].eq(ano_comp), "technician"].unique())
        tecs_ativos_b = len(set_b)
        tecs_ativos_c = len(set_c)
        tecs_comuns = len(set_b & set_c)
        pts_prod_b = float(
            recorte.loc[
                recorte["year"].eq(ano_base) & recorte["source_sheet"].eq(PROD),
                "points",
            ].sum()
        )
        pts_prod_c = float(
            recorte.loc[
                recorte["year"].eq(ano_comp) & recorte["source_sheet"].eq(PROD),
                "points",
            ].sum()
        )
        pts_tot_b = float(recorte.loc[recorte["year"].eq(ano_base), "points"].sum())
        pts_tot_c = float(recorte.loc[recorte["year"].eq(ano_comp), "points"].sum())

    ct_por_tec_b = (contratos_base / tecs_ativos_b) if tecs_ativos_b > 0 else 0.0
    ct_por_tec_c = (contratos_comp / tecs_ativos_c) if tecs_ativos_c > 0 else 0.0
    os_por_tec_b = (os_base / tecs_ativos_b) if tecs_ativos_b > 0 else 0.0
    os_por_tec_c = (os_comp / tecs_ativos_c) if tecs_ativos_c > 0 else 0.0

    # Tabela mensal formatada para exibição e exportação CSV.
    linhas_tbl_mensal: list[dict[str, object]] = []
    for _, row in mensal_rec.iterrows():
        linhas_tbl_mensal.append(
            {
                "Mês": str(row["mes_label"]),
                f"Contratos {ano_base}": int(row["contratos_base"]),
                f"Contratos {ano_comp}": int(row["contratos_comp"]),
                "Δ Contratos": int(row["delta_contratos"]),
                "Var. Contratos (%)": row["pct_contratos"],
                f"O.S. {ano_base}": int(row["os_base"]),
                f"O.S. {ano_comp}": int(row["os_comp"]),
                "Δ O.S.": int(row["delta_os"]),
                "Var. O.S. (%)": row["pct_os"],
                f"O.S./Contrato {ano_base}": float(row["os_por_contrato_base"]),
                f"O.S./Contrato {ano_comp}": float(row["os_por_contrato_comp"]),
            }
        )
    linhas_tbl_mensal.append(
        {
            "Mês": "Total no recorte",
            f"Contratos {ano_base}": contratos_base,
            f"Contratos {ano_comp}": contratos_comp,
            "Δ Contratos": delta_contratos,
            "Var. Contratos (%)": pct_contratos,
            f"O.S. {ano_base}": os_base,
            f"O.S. {ano_comp}": os_comp,
            "Δ O.S.": delta_os,
            "Var. O.S. (%)": pct_os,
            f"O.S./Contrato {ano_base}": giro_base,
            f"O.S./Contrato {ano_comp}": giro_comp,
        }
    )
    linhas_tbl_mensal.append(
        {
            "Mês": "Média mensal ativa",
            f"Contratos {ano_base}": round(media_ct_b, 1),
            f"Contratos {ano_comp}": round(media_ct_c, 1),
            "Δ Contratos": round(media_ct_c - media_ct_b, 1),
            "Var. Contratos (%)": pct_media_ct,
            f"O.S. {ano_base}": round(media_os_b, 1),
            f"O.S. {ano_comp}": round(media_os_c, 1),
            "Δ O.S.": round(media_os_c - media_os_b, 1),
            "Var. O.S. (%)": pct_media_os,
            f"O.S./Contrato {ano_base}": giro_base,
            f"O.S./Contrato {ano_comp}": giro_comp,
        }
    )
    tabela_mensal = pd.DataFrame(linhas_tbl_mensal)

    por_projeto = _montar_resumo_dimensao(
        recorte, "project", "Projeto", ano_base, ano_comp
    )
    por_base = _montar_resumo_dimensao(recorte, "base", "Base", ano_base, ano_comp)
    por_monitor = _montar_resumo_dimensao(
        recorte, "monitor", "Monitor", ano_base, ano_comp
    )

    # Tabela analítica por técnico.
    colunas_tec = [
        "Técnico",
        "Situação",
        "Base",
        "Monitor",
        f"Meses {ano_base}",
        f"Meses {ano_comp}",
        f"Contratos {ano_base}",
        f"Contratos {ano_comp}",
        "Δ Contratos",
        "Var. Contratos (%)",
        f"O.S. {ano_base}",
        f"O.S. {ano_comp}",
        "Δ O.S.",
        "Var. O.S. (%)",
        f"O.S./Contrato {ano_base}",
        f"O.S./Contrato {ano_comp}",
        "Status Comparativo",
    ]
    if recorte.empty:
        por_tecnico = pd.DataFrame(columns=colunas_tec)
    else:
        meta_tec = (
            recorte.sort_values("period")
            .drop_duplicates("technician", keep="last")
            .set_index("technician")[["roster_status", "base", "monitor"]]
        )
        ct_tec = (
            recorte[recorte["contract_valid"]]
            .drop_duplicates(["technician", "year", "period", "contract_clean"])
            .groupby(["technician", "year"])
            .size()
            .unstack(fill_value=0)
        )
        os_tec = (
            recorte[recorte["source_sheet"].eq(PROD)]
            .groupby(["technician", "year"])
            .size()
            .unstack(fill_value=0)
        )
        mov_tec = recorte[recorte["contract_valid"] | recorte["source_sheet"].eq(PROD)]
        meses_tec = (
            mov_tec.groupby(["technician", "year"])["month"]
            .nunique()
            .unstack(fill_value=0)
        )

        todos_tecs = sorted(set(ct_tec.index).union(set(os_tec.index)))
        linhas_tec: list[dict[str, object]] = []
        for tec in todos_tecs:
            cb = (
                int(ct_tec.loc[tec, ano_base])
                if (tec in ct_tec.index and ano_base in ct_tec.columns)
                else 0
            )
            cc = (
                int(ct_tec.loc[tec, ano_comp])
                if (tec in ct_tec.index and ano_comp in ct_tec.columns)
                else 0
            )
            ob = (
                int(os_tec.loc[tec, ano_base])
                if (tec in os_tec.index and ano_base in os_tec.columns)
                else 0
            )
            oc = (
                int(os_tec.loc[tec, ano_comp])
                if (tec in os_tec.index and ano_comp in os_tec.columns)
                else 0
            )
            if cb == 0 and cc == 0 and ob == 0 and oc == 0:
                continue
            mb = (
                int(meses_tec.loc[tec, ano_base])
                if (tec in meses_tec.index and ano_base in meses_tec.columns)
                else 0
            )
            mc = (
                int(meses_tec.loc[tec, ano_comp])
                if (tec in meses_tec.index and ano_comp in meses_tec.columns)
                else 0
            )
            info = meta_tec.loc[tec] if tec in meta_tec.index else None
            linhas_tec.append(
                {
                    "Técnico": str(tec),
                    "Situação": str(info["roster_status"])
                    if info is not None
                    else "Sem cadastro",
                    "Base": str(info["base"]) if info is not None else "Sem base",
                    "Monitor": str(info["monitor"])
                    if info is not None
                    else "Sem monitor",
                    f"Meses {ano_base}": mb,
                    f"Meses {ano_comp}": mc,
                    f"Contratos {ano_base}": cb,
                    f"Contratos {ano_comp}": cc,
                    "Δ Contratos": cc - cb,
                    "Var. Contratos (%)": _variacao_pct(cc, cb),
                    f"O.S. {ano_base}": ob,
                    f"O.S. {ano_comp}": oc,
                    "Δ O.S.": oc - ob,
                    "Var. O.S. (%)": _variacao_pct(oc, ob),
                    f"O.S./Contrato {ano_base}": (ob / cb) if cb > 0 else 0.0,
                    f"O.S./Contrato {ano_comp}": (oc / cc) if cc > 0 else 0.0,
                    "Status Comparativo": _classificar_status_tecnico(
                        cb, cc, ob, oc, ano_base, ano_comp
                    ),
                }
            )
        por_tecnico = (
            pd.DataFrame(linhas_tec)[colunas_tec]
            .sort_values(
                by=[
                    f"Contratos {ano_comp}",
                    f"O.S. {ano_comp}",
                    f"Contratos {ano_base}",
                    "Técnico",
                ],
                ascending=[False, False, False, True],
            )
            .reset_index(drop=True)
            if linhas_tec
            else pd.DataFrame(columns=colunas_tec)
        )

    return ResumoComparativoAnos(
        ano_base=ano_base,
        ano_comp=ano_comp,
        modo_solicitado=modo_meses,
        modo_efetivo=modo_efetivo,
        fallback_sem_intersecao=fallback_sem_intersecao,
        escopo_equipe=escopo_equipe,
        meses_disponiveis_base=meses_disp_base,
        meses_disponiveis_comp=meses_disp_comp,
        meses_intersecao=meses_intersecao,
        meses_considerados=meses_considerados,
        rotulo_recorte_meses=_descrever_meses(meses_considerados),
        contratos_base=contratos_base,
        contratos_comp=contratos_comp,
        delta_contratos=delta_contratos,
        pct_contratos=pct_contratos,
        os_base=os_base,
        os_comp=os_comp,
        delta_os=delta_os,
        pct_os=pct_os,
        os_por_contrato_base=giro_base,
        os_por_contrato_comp=giro_comp,
        delta_os_por_contrato=delta_giro,
        pct_os_por_contrato=pct_giro,
        meses_ativos_contratos_base=meses_ct_b,
        meses_ativos_contratos_comp=meses_ct_c,
        media_mensal_contratos_base=media_ct_b,
        media_mensal_contratos_comp=media_ct_c,
        pct_media_contratos=pct_media_ct,
        meses_ativos_os_base=meses_os_b,
        meses_ativos_os_comp=meses_os_c,
        media_mensal_os_base=media_os_b,
        media_mensal_os_comp=media_os_c,
        pct_media_os=pct_media_os,
        tecnicos_ativos_base=tecs_ativos_b,
        tecnicos_ativos_comp=tecs_ativos_c,
        tecnicos_comuns=tecs_comuns,
        contratos_por_tecnico_base=ct_por_tec_b,
        contratos_por_tecnico_comp=ct_por_tec_c,
        os_por_tecnico_base=os_por_tec_b,
        os_por_tecnico_comp=os_por_tec_c,
        pontos_prod_base=pts_prod_b,
        pontos_prod_comp=pts_prod_c,
        pontos_totais_base=pts_tot_b,
        pontos_totais_comp=pts_tot_c,
        sem_contrato_registros=sem_contrato,
        linhas_incompletas=incompletos,
        mensal=mensal_df,
        tabela_mensal=tabela_mensal,
        por_projeto=por_projeto,
        por_base=por_base,
        por_monitor=por_monitor,
        por_tecnico=por_tecnico,
    )


def _aplicar_layout_grafico(fig: go.Figure, height: int = 350) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=14, t=26, b=10),
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
        bargap=0.26,
        bargroupgap=0.12,
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=False,
        tickfont=dict(size=10.5),
    )
    fig.update_yaxes(
        gridcolor=Cores.BORDA,
        zeroline=False,
        showline=False,
        tickfont=dict(size=10),
        separatethousands=True,
    )
    return fig


def _grafico_mensal_comparativo(
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
    """Gráfico mensal Jan–Dez lado a lado entre os dois anos com média tracejada."""
    fig = go.Figure()
    opacidades_base = [1.0 if bool(c) else 0.30 for c in mensal["considerado"]]
    opacidades_comp = [1.0 if bool(c) else 0.30 for c in mensal["considerado"]]

    fig.add_bar(
        x=mensal["mes_label"],
        y=mensal[col_base],
        name=str(ano_base),
        marker=dict(color=cor_base, opacity=opacidades_base),
        text=[formatar_numero_br(v) if int(v) > 0 else "" for v in mensal[col_base]],
        textposition="outside",
        textfont=dict(size=9.5, color="#475569"),
        cliponaxis=False,
        hovertemplate=f"<b>%{{x}}/{ano_base}</b><br>{unidade}: %{{y:,.0f}}<extra></extra>",
    )
    fig.add_bar(
        x=mensal["mes_label"],
        y=mensal[col_comp],
        name=str(ano_comp),
        marker=dict(color=cor_comp, opacity=opacidades_comp),
        text=[formatar_numero_br(v) if int(v) > 0 else "" for v in mensal[col_comp]],
        textposition="outside",
        textfont=dict(size=9.5, color=cor_comp),
        cliponaxis=False,
        hovertemplate=f"<b>%{{x}}/{ano_comp}</b><br>{unidade}: %{{y:,.0f}}<extra></extra>",
    )

    ativos_comp = mensal.loc[mensal["considerado"] & mensal[col_comp].gt(0), col_comp]
    if not ativos_comp.empty:
        media_c = float(ativos_comp.mean())
        fig.add_hline(
            y=media_c,
            line_dash="dot",
            line_color=cor_comp,
            annotation_text=f"Média {ano_comp}: {_formatar_decimal_br(media_c, 1)}",
            annotation_position="top left",
            annotation_font=dict(size=10, color=cor_comp),
        )

    fig.update_layout(barmode="group")
    max_y = max(
        float(mensal[col_base].max()) if not mensal.empty else 0.0,
        float(mensal[col_comp].max()) if not mensal.empty else 0.0,
        1.0,
    )
    fig.update_yaxes(range=[0, max_y * 1.24])
    return _aplicar_layout_grafico(fig, height=345)


def _grafico_acumulado_ytd(
    mensal: pd.DataFrame,
    *,
    metrica: Literal["contratos", "os"],
    ano_base: int,
    ano_comp: int,
) -> go.Figure:
    """Curva de ritmo acumulado no recorte selecionado (2025 vs 2026)."""
    rec = mensal[mensal["considerado"]].copy()
    col_b = f"acum_{metrica}_base"
    col_c = f"acum_{metrica}_comp"
    cor_c = _COR_2026_CONTRATOS if metrica == "contratos" else _COR_2026_OS
    rotulo = "Contratos acumulados" if metrica == "contratos" else "O.S. acumuladas"

    fig = go.Figure()
    fig.add_scatter(
        x=rec["mes_label"],
        y=rec[col_b],
        name=f"Acumulado {ano_base}",
        mode="lines+markers",
        line=dict(color="#64748B", width=2.4, dash="dash"),
        marker=dict(size=6.5, color="#64748B"),
        hovertemplate=f"<b>Até %{{x}}/{ano_base}</b><br>{rotulo}: %{{y:,.0f}}<extra></extra>",
    )
    fig.add_scatter(
        x=rec["mes_label"],
        y=rec[col_c],
        name=f"Acumulado {ano_comp}",
        mode="lines+markers",
        fill="tonexty",
        fillcolor=(
            "rgba(1, 40, 105, 0.08)"
            if metrica == "contratos"
            else "rgba(243, 124, 4, 0.10)"
        ),
        line=dict(color=cor_c, width=3.0),
        marker=dict(size=7.5, color=cor_c),
        hovertemplate=f"<b>Até %{{x}}/{ano_comp}</b><br>{rotulo}: %{{y:,.0f}}<extra></extra>",
    )
    return _aplicar_layout_grafico(fig, height=320)


def _grafico_giro_os_contrato(
    mensal: pd.DataFrame, ano_base: int, ano_comp: int
) -> go.Figure:
    """Evolução mensal do giro O.S. por Contrato (2025 vs 2026)."""
    rec = mensal[mensal["considerado"]].copy()
    y_b = [v if v > 0 else None for v in rec["os_por_contrato_base"]]
    y_c = [v if v > 0 else None for v in rec["os_por_contrato_comp"]]

    fig = go.Figure()
    fig.add_scatter(
        x=rec["mes_label"],
        y=y_b,
        name=f"O.S./Contrato {ano_base}",
        mode="lines+markers",
        connectgaps=True,
        line=dict(color="#94A3B8", width=2.2, dash="dot"),
        marker=dict(size=6.5, color="#64748B"),
        hovertemplate=f"<b>%{{x}}/{ano_base}</b><br>Giro: %{{y:,.2f}} O.S./contrato<extra></extra>",
    )
    fig.add_scatter(
        x=rec["mes_label"],
        y=y_c,
        name=f"O.S./Contrato {ano_comp}",
        mode="lines+markers+text",
        connectgaps=True,
        line=dict(color=_ROXO, width=2.8),
        marker=dict(size=7.5, color=_ROXO),
        text=[_formatar_decimal_br(float(v), 2) if v is not None else "" for v in y_c],
        textposition="top center",
        textfont=dict(size=9.5, color=_ROXO),
        cliponaxis=False,
        hovertemplate=f"<b>%{{x}}/{ano_comp}</b><br>Giro: %{{y:,.2f}} O.S./contrato<extra></extra>",
    )
    valores_validos = [
        float(v) for v in (*y_b, *y_c) if v is not None and not pd.isna(v)
    ]
    max_v = max(valores_validos, default=2.0)
    fig.update_yaxes(range=[0, max_v * 1.28])
    return _aplicar_layout_grafico(fig, height=320)


def _grafico_dimensao_horizontal(
    tabela_dim: pd.DataFrame,
    rotulo_dim: str,
    ano_base: int,
    ano_comp: int,
    metrica: Literal["Contratos", "O.S."],
    top_n: int = 12,
) -> go.Figure:
    col_b = f"{metrica} {ano_base}"
    col_c = f"{metrica} {ano_comp}"
    top = tabela_dim.head(top_n).iloc[::-1].copy()
    cor_b = _COR_2025_CONTRATOS if metrica == "Contratos" else _COR_2025_OS
    cor_c = _COR_2026_CONTRATOS if metrica == "Contratos" else _COR_2026_OS

    fig = go.Figure()
    fig.add_bar(
        y=top[rotulo_dim],
        x=top[col_b],
        name=str(ano_base),
        orientation="h",
        marker_color=cor_b,
        hovertemplate=f"<b>%{{y}}</b><br>{col_b}: %{{x:,.0f}}<extra></extra>",
    )
    fig.add_bar(
        y=top[rotulo_dim],
        x=top[col_c],
        name=str(ano_comp),
        orientation="h",
        marker_color=cor_c,
        text=[formatar_numero_br(v) for v in top[col_c]],
        textposition="outside",
        textfont=dict(size=10, color=cor_c),
        cliponaxis=False,
        hovertemplate=f"<b>%{{y}}</b><br>{col_c}: %{{x:,.0f}}<extra></extra>",
    )
    fig.update_layout(barmode="group")
    max_x = max(
        float(top[col_b].max()) if not top.empty else 0.0,
        float(top[col_c].max()) if not top.empty else 0.0,
        1.0,
    )
    fig.update_xaxes(range=[0, max_x * 1.22], showgrid=True, gridcolor=Cores.BORDA)
    fig.update_yaxes(showgrid=False)
    altura = max(290, len(top) * 42 + 80)
    return _aplicar_layout_grafico(fig, height=altura)


def _grafico_dispersao_deltas_tecnico(
    por_tecnico: pd.DataFrame, ano_base: int, ano_comp: int
) -> go.Figure:
    """Quadrantes de Δ Contratos × Δ O.S. por técnico entre os dois anos."""
    cores_status = {
        "Em evolução": _VERDE,
        "Estável": AZUL_TOTALE,
        "Retração": _VERMELHO,
        f"Novo em {ano_comp}": LARANJA_TOTALE,
        f"Apenas em {ano_base}": "#64748B",
    }
    fig = go.Figure()
    for status, grupo in por_tecnico.groupby("Status Comparativo", sort=False):
        cor = cores_status.get(str(status), "#475569")
        fig.add_scatter(
            x=grupo["Δ Contratos"],
            y=grupo["Δ O.S."],
            mode="markers",
            name=str(status),
            text=grupo["Técnico"],
            customdata=grupo[
                [
                    f"Contratos {ano_base}",
                    f"Contratos {ano_comp}",
                    f"O.S. {ano_base}",
                    f"O.S. {ano_comp}",
                ]
            ],
            marker=dict(
                size=10.5,
                color=cor,
                opacity=0.86,
                line=dict(width=1, color="#FFFFFF"),
            ),
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Contratos: %{customdata[0]:,.0f} → %{customdata[1]:,.0f} (Δ %{x:+,.0f})<br>"
                "O.S.: %{customdata[2]:,.0f} → %{customdata[3]:,.0f} (Δ %{y:+,.0f})<extra></extra>"
            ),
        )
    fig.add_hline(y=0, line_dash="dash", line_color="#CBD5E1")
    fig.add_vline(x=0, line_dash="dash", line_color="#CBD5E1")
    fig = _aplicar_layout_grafico(fig, height=360)
    fig.update_xaxes(
        title_text=f"Δ Contratos ({ano_comp} − {ano_base})",
        showgrid=True,
        gridcolor=Cores.BORDA,
    )
    fig.update_yaxes(title_text=f"Δ O.S. Prod ({ano_comp} − {ano_base})")
    return fig


def _estilizar_delta(valor: object) -> str:
    try:
        num = float(str(valor))
    except (TypeError, ValueError):
        return ""
    if pd.isna(num) or num == 0:
        return "color: #64748B;"
    if num > 0:
        return "background-color: #ECFDF5; color: #065F46; font-weight: 700;"
    return "background-color: #FEF2F2; color: #991B1B; font-weight: 700;"


def _estilizar_status_comparativo(valor: object) -> str:
    txt = str(valor or "")
    if txt == "Em evolução":
        return "background-color: #DCFCE7; color: #166534; font-weight: 700;"
    if txt == "Retração":
        return "background-color: #FEE2E2; color: #991B1B; font-weight: 700;"
    if txt == "Estável":
        return "background-color: #E8EEF8; color: #012869; font-weight: 600;"
    if txt.startswith("Novo em"):
        return "background-color: #FFF7ED; color: #9A3412; font-weight: 700;"
    if txt.startswith("Apenas em"):
        return "background-color: #F1F5F9; color: #475569; font-weight: 600;"
    return ""


def _formatar_styler_comparativo(
    tabela: pd.DataFrame, ano_base: int, ano_comp: int
) -> pd.DataFrame | Styler:
    if tabela.empty or tabela.size > pd.get_option("styler.render.max_elements"):
        return tabela

    formatadores: dict[str, object] = {}
    for col in tabela.columns:
        if col.startswith(("Contratos ", "O.S. ", "Meses ")):
            formatadores[col] = lambda v: (
                formatar_numero_br(v)
                if isinstance(v, int)
                or (isinstance(v, float) and float(v).is_integer())
                else _formatar_decimal_br(float(v), 1)
            )
        elif col in ("Δ Contratos", "Δ O.S."):
            formatadores[col] = lambda v: (
                f"{int(v):+d}".replace(",", ".")
                if isinstance(v, int)
                or (isinstance(v, float) and float(v).is_integer())
                else _formatar_decimal_br(float(v), 1, com_sinal=True)
            )
        elif col in ("Var. Contratos (%)", "Var. O.S. (%)"):
            formatadores[col] = lambda v: _formatar_pct_br(
                None if v is None or pd.isna(v) else float(v)
            )
        elif col.startswith("Part. Contratos"):
            formatadores[col] = lambda v: f"{_formatar_decimal_br(float(v), 1)}%"
        elif col.startswith("O.S./Contrato"):
            formatadores[col] = lambda v: _formatar_decimal_br(float(v), 2)

    styler = tabela.style.format(formatadores)  # type: ignore[arg-type]
    cols_delta = [
        c
        for c in ("Δ Contratos", "Var. Contratos (%)", "Δ O.S.", "Var. O.S. (%)")
        if c in tabela.columns
    ]
    if cols_delta:
        styler = styler.map(_estilizar_delta, subset=cols_delta)
    if "Status Comparativo" in tabela.columns:
        styler = styler.map(
            _estilizar_status_comparativo, subset=["Status Comparativo"]
        )
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


def render_comparativo_anos(
    records: pd.DataFrame,
    roster: pd.DataFrame | None = None,
) -> None:
    """Renderiza a página executiva de Comparativo 2025 x 2026 (Contratos e O.S.)."""
    del roster
    injetar_css(_CSS_COMPARATIVO)

    if records.empty:
        st.info(
            "Ainda não há registros de produção carregados para comparar 2025 e 2026."
        )
        return

    # Descobre anos presentes na base mantendo 2025 e 2026 sempre disponíveis no seletor.
    datas_disp = _parse_datas_seguras(
        records["period"] if "period" in records.columns else records["reference_date"]
    )
    anos_presentes = sorted(
        {2025, 2026, *(int(a) for a in datas_disp.dropna().dt.year.unique())}
    )
    ano_base_default = 2025 if 2025 in anos_presentes else anos_presentes[0]
    ano_comp_default = (
        2026
        if 2026 in anos_presentes
        else (anos_presentes[-1] if len(anos_presentes) > 1 else ano_base_default + 1)
    )

    with st.container(border=True):
        f_top = st.columns([0.9, 0.9, 1.85, 1.85])
        with f_top[0]:
            ano_base = int(
                st.selectbox(
                    "Ano base",
                    anos_presentes,
                    index=anos_presentes.index(ano_base_default),
                    key="comp_ano_base",
                )
            )
        with f_top[1]:
            opcoes_comp = [a for a in anos_presentes if a != ano_base] or [ano_base + 1]
            idx_comp = (
                opcoes_comp.index(ano_comp_default)
                if ano_comp_default in opcoes_comp
                else len(opcoes_comp) - 1
            )
            ano_comp = int(
                st.selectbox(
                    "Ano comparado",
                    opcoes_comp,
                    index=idx_comp,
                    key="comp_ano_comp",
                )
            )
        with f_top[2]:
            rotulos_modo: dict[ModoMesesComparativo, str] = {
                "equivalente": "⚖️ Mesmos meses nos 2 anos (Equivalente)",
                "ano_completo": "📅 Ano completo (Jan–Dez disponíveis)",
                "personalizado": "🎯 Seleção manual de meses",
            }
            modo_meses = st.selectbox(
                "Recorte temporal de comparação",
                options=list(rotulos_modo.keys()),
                format_func=lambda k: rotulos_modo[k],
                key="comp_modo_meses",
            )
        with f_top[3]:
            rotulos_escopo: dict[EscopoEquipeComparativo, str] = {
                "todos": "🏢 Operação completa (todos que produziram)",
                "ativos": "✅ Apenas ativos atuais (lista_ativos = ATIVO)",
                "mesma_equipe": "🔁 Mesma equipe (ativos nos 2 anos)",
            }
            escopo_equipe = st.selectbox(
                "Escopo de colaboradores",
                options=list(rotulos_escopo.keys()),
                format_func=lambda k: rotulos_escopo[k],
                key="comp_escopo_equipe",
            )

        meses_manuais: list[int] | None = None
        if modo_meses == "personalizado":
            nomes_para_num = {MESES_NOMES[i]: i + 1 for i in range(12)}
            escolhidos_lbl = st.multiselect(
                "Meses do calendário incluídos na comparação",
                options=list(MESES_NOMES),
                default=list(MESES_NOMES),
                key="comp_meses_manuais",
            )
            meses_manuais = [nomes_para_num[m] for m in escolhidos_lbl]

        tem_cadastro = bool(
            "roster_status" in records.columns
            and records["roster_status"].ne("Sem cadastro").any()
        )
        projetos_opcoes = sorted(
            str(p)
            for p in records.get("project", pd.Series(dtype="object")).dropna().unique()
            if str(p).strip()
        )
        if tem_cadastro:
            f_dim = st.columns([1.25, 1.15, 1.25, 1.55])
            with f_dim[0]:
                sel_projetos = st.multiselect(
                    "Projeto",
                    projetos_opcoes,
                    default=[],
                    placeholder="Todos os projetos",
                    key="comp_projeto_filter",
                )
            with f_dim[1]:
                bases_opcoes = sorted(
                    str(b) for b in records["base"].dropna().unique() if str(b).strip()
                )
                sel_bases = st.multiselect(
                    "Base",
                    bases_opcoes,
                    default=[],
                    placeholder="Todas as bases",
                    key="comp_base_filter",
                )
            with f_dim[2]:
                monitores_opcoes = sorted(
                    str(m)
                    for m in records["monitor"].dropna().unique()
                    if str(m).strip()
                )
                sel_monitores = st.multiselect(
                    "Monitor",
                    monitores_opcoes,
                    default=[],
                    placeholder="Todos os monitores",
                    key="comp_monitor_filter",
                )
            col_tec_container = f_dim[3]
        else:
            sel_bases = []
            sel_monitores = []
            f_dim_simples = st.columns([1.3, 1.9])
            with f_dim_simples[0]:
                sel_projetos = st.multiselect(
                    "Projeto",
                    projetos_opcoes,
                    default=[],
                    placeholder="Todos os projetos",
                    key="comp_projeto_filter",
                )
            col_tec_container = f_dim_simples[1]

        recorte_dim = records
        if sel_projetos:
            recorte_dim = recorte_dim[recorte_dim["project"].isin(sel_projetos)]
        if sel_bases and "base" in recorte_dim.columns:
            recorte_dim = recorte_dim[recorte_dim["base"].isin(sel_bases)]
        if sel_monitores and "monitor" in recorte_dim.columns:
            recorte_dim = recorte_dim[recorte_dim["monitor"].isin(sel_monitores)]

        with col_tec_container:
            tecs_opcoes = sorted(
                str(t)
                for t in recorte_dim["technician"].dropna().unique()
                if str(t).strip()
            )
            sel_tecnicos = st.multiselect(
                "Técnico",
                tecs_opcoes,
                default=[],
                placeholder="Todos os técnicos",
                key="comp_tecnico_filter",
            )
        if sel_tecnicos:
            recorte_dim = recorte_dim[recorte_dim["technician"].isin(sel_tecnicos)]

    resumo = calcular_comparativo_anos(
        recorte_dim,
        ano_base=ano_base,
        ano_comp=ano_comp,
        modo_meses=modo_meses,
        meses_selecionados=meses_manuais,
        escopo_equipe=escopo_equipe,
    )

    modo_badge = {
        "equivalente": "Mesmos meses equivalentes",
        "ano_completo": "Todos os meses disponíveis",
        "personalizado": "Meses selecionados manualmente",
    }[resumo.modo_efetivo]
    escopo_badge = {
        "todos": "Operação completa",
        "ativos": "Quadro ativo atual",
        "mesma_equipe": f"Mesma equipe ({resumo.tecnicos_comuns} técnicos)",
    }[resumo.escopo_equipe]

    st.markdown(
        f"""
        <div class="comp-hero">
            <div class="comp-hero-top">
                <div>
                    <span class="comp-hero-eyebrow">⚖️ Análise Interanual · {ano_base} x {ano_comp}</span>
                    <h2>Comparativo {ano_base} x {ano_comp} · Contratos e O.S.</h2>
                    <p>Visão analítica integrada de volume de contratos distintos, quantidade de Ordens de Serviço (aba Prod), giro O.S./contrato e produtividade por equipe.</p>
                </div>
            </div>
            <div class="comp-pills">
                <span class="comp-pill">Recorte: <strong>{html.escape(modo_badge)} · {html.escape(resumo.rotulo_recorte_meses)}</strong></span>
                <span class="comp-pill">Escopo: <strong>{html.escape(escopo_badge)}</strong></span>
                <span class="comp-pill">Cobertura {ano_base}: <strong>{len(resumo.meses_disponiveis_base)}/12 meses</strong></span>
                <span class="comp-pill">Cobertura {ano_comp}: <strong>{len(resumo.meses_disponiveis_comp)}/12 meses</strong></span>
                <span class="comp-pill">Técnicos c/ prod.: <strong>{resumo.tecnicos_ativos_base} ({ano_base}) → {resumo.tecnicos_ativos_comp} ({ano_comp})</strong></span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Avisos inteligentes de cobertura parcial ou ausência de um dos anos.
    if not resumo.meses_disponiveis_base and not resumo.meses_disponiveis_comp:
        st.info(
            f"Não há contratos ou O.S. válidos para {ano_base} e {ano_comp} nos filtros atuais."
        )
        return

    if not resumo.meses_disponiveis_base:
        render_insight(
            f"<strong>Base de {ano_base} ainda não localizada no banco atual:</strong> "
            f"foram encontradas competências em <strong>{ano_comp}</strong> ({html.escape(_descrever_meses(resumo.meses_disponiveis_comp))}), "
            f"mas nenhuma competência de <strong>{ano_base}</strong>. Sincronize as planilhas de {ano_base} na pasta do Google Drive "
            f"(<em>Atualizar dados</em> na barra lateral) para destravar as variações interanuais.",
            tipo="alerta",
        )
    elif not resumo.meses_disponiveis_comp:
        render_insight(
            f"<strong>Base de {ano_comp} sem competências nos filtros atuais:</strong> "
            f"há dados em <strong>{ano_base}</strong> ({html.escape(_descrever_meses(resumo.meses_disponiveis_base))}), "
            f"mas nenhum registro em <strong>{ano_comp}</strong> para este recorte.",
            tipo="alerta",
        )
    elif resumo.fallback_sem_intersecao:
        render_insight(
            f"<strong>Competências sem sobreposição direta ainda:</strong> "
            f"<strong>{ano_base}</strong> possui dados em <em>{html.escape(_descrever_meses(resumo.meses_disponiveis_base))}</em> e "
            f"<strong>{ano_comp}</strong> em <em>{html.escape(_descrever_meses(resumo.meses_disponiveis_comp))}</em>. "
            f"Os painéis abaixo exibem todos os meses disponíveis e destacam a <strong>Média Mensal Ativa</strong> "
            f"para comparação proporcional até que os mesmos meses estejam sincronizados.",
            tipo="alerta",
        )
    else:
        direcao_ct = (
            "expansão"
            if resumo.delta_contratos > 0
            else ("retração" if resumo.delta_contratos < 0 else "estabilidade")
        )
        tipo_diag: TipoInsightType = (
            "ok"
            if resumo.delta_contratos >= 0 and resumo.delta_os >= 0
            else (
                "alerta"
                if resumo.delta_contratos >= 0 or resumo.delta_os >= 0
                else "critico"
            )
        )
        render_insight(
            f"<strong>Diagnóstico {ano_base} → {ano_comp} ({html.escape(resumo.rotulo_recorte_meses)}):</strong> "
            f"Carteira em <strong>{direcao_ct}</strong> de <strong>{formatar_numero_br(resumo.contratos_base)}</strong> para "
            f"<strong>{formatar_numero_br(resumo.contratos_comp)}</strong> contratos "
            f"(<strong>{_formatar_pct_br(resumo.pct_contratos)}</strong>), enquanto o volume de O.S. Prod passou de "
            f"<strong>{formatar_numero_br(resumo.os_base)}</strong> para <strong>{formatar_numero_br(resumo.os_comp)}</strong> "
            f"(<strong>{_formatar_pct_br(resumo.pct_os)}</strong>) — giro médio de "
            f"<strong>{_formatar_decimal_br(resumo.os_por_contrato_comp, 2)} O.S./contrato</strong> em {ano_comp} "
            f"(ante {_formatar_decimal_br(resumo.os_por_contrato_base, 2)} em {ano_base}).",
            tipo=tipo_diag,
        )

    render_ticker(
        [
            (
                f"CONTRATOS {ano_comp}",
                f"{formatar_numero_br(resumo.contratos_comp)} ({_formatar_pct_br(resumo.pct_contratos)})",
            ),
            (
                f"O.S. PROD {ano_comp}",
                f"{formatar_numero_br(resumo.os_comp)} ({_formatar_pct_br(resumo.pct_os)})",
            ),
            (
                f"GIRO O.S./CONTRATO {ano_comp}",
                f"{_formatar_decimal_br(resumo.os_por_contrato_comp, 2)}x",
            ),
            (
                "MÉDIA MENSAL CONTRATOS",
                f"{_formatar_decimal_br(resumo.media_mensal_contratos_base, 1)} → {_formatar_decimal_br(resumo.media_mensal_contratos_comp, 1)}",
            ),
            (
                "MÉDIA MENSAL O.S.",
                f"{_formatar_decimal_br(resumo.media_mensal_os_base, 1)} → {_formatar_decimal_br(resumo.media_mensal_os_comp, 1)}",
            ),
            (
                f"PONTOS TOTAIS {ano_comp}",
                format_points(resumo.pontos_totais_comp),
            ),
        ]
    )

    st.markdown(
        f'<div class="comp-rule-note"><strong>Critério oficial unificado:</strong> {html.escape(REGRA_COMPARATIVO_ANOS)}</div>',
        unsafe_allow_html=True,
    )

    # Linha 1 de KPIs: Volumes Acumulados + Giro O.S./Contrato.
    k_row1 = st.columns(3)
    render_kpi(
        k_row1[0],
        f"Contratos ({ano_comp} vs {ano_base})",
        formatar_numero_br(resumo.contratos_comp),
        sub=(
            f"Base {ano_base}: {formatar_numero_br(resumo.contratos_base)} · "
            f"Δ {resumo.delta_contratos:+d}".replace(",", ".")
        ),
        icone="📄",
        tema=_tema_variacao(resumo.delta_contratos, "azul"),
        delta=_formatar_pct_br(resumo.pct_contratos),
        delta_tipo=_trend_variacao(resumo.delta_contratos),
    )
    render_kpi(
        k_row1[1],
        f"Quantidade de O.S. ({ano_comp} vs {ano_base})",
        formatar_numero_br(resumo.os_comp),
        sub=(
            f"Base {ano_base}: {formatar_numero_br(resumo.os_base)} · "
            f"Δ {resumo.delta_os:+d}".replace(",", ".")
        ),
        icone="📋",
        tema=_tema_variacao(resumo.delta_os, "laranja"),
        delta=_formatar_pct_br(resumo.pct_os),
        delta_tipo=_trend_variacao(resumo.delta_os),
    )
    render_kpi(
        k_row1[2],
        f"Giro O.S. / Contrato ({ano_comp})",
        f"{_formatar_decimal_br(resumo.os_por_contrato_comp, 2)}x",
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.os_por_contrato_base, 2)}x · "
            f"Δ {_formatar_decimal_br(resumo.delta_os_por_contrato, 2, com_sinal=True)}"
        ),
        icone="🔄",
        tema="roxo",
        delta=_formatar_pct_br(resumo.pct_os_por_contrato),
        delta_tipo=_trend_variacao(resumo.delta_os_por_contrato),
    )

    st.markdown("<div style='height:0.55rem'></div>", unsafe_allow_html=True)

    # Linha 2 de KPIs: Médias Mensais Ativas e Produtividade por Técnico.
    diff_media_ct = (
        resumo.media_mensal_contratos_comp - resumo.media_mensal_contratos_base
    )
    diff_media_os = resumo.media_mensal_os_comp - resumo.media_mensal_os_base
    k_row2 = st.columns(3)
    render_kpi(
        k_row2[0],
        f"Média Mensal · Contratos ({ano_comp})",
        _formatar_decimal_br(resumo.media_mensal_contratos_comp, 1),
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.media_mensal_contratos_base, 1)}/mês "
            f"({resumo.meses_ativos_contratos_base}→{resumo.meses_ativos_contratos_comp}m)"
        ),
        icone="📆",
        tema=_tema_variacao(diff_media_ct, "azul"),
        delta=_formatar_pct_br(resumo.pct_media_contratos),
        delta_tipo=_trend_variacao(diff_media_ct),
    )
    render_kpi(
        k_row2[1],
        f"Média Mensal · O.S. Prod ({ano_comp})",
        _formatar_decimal_br(resumo.media_mensal_os_comp, 1),
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.media_mensal_os_base, 1)}/mês "
            f"({resumo.meses_ativos_os_base}→{resumo.meses_ativos_os_comp}m)"
        ),
        icone="⚡",
        tema=_tema_variacao(diff_media_os, "laranja"),
        delta=_formatar_pct_br(resumo.pct_media_os),
        delta_tipo=_trend_variacao(diff_media_os),
    )
    render_kpi(
        k_row2[2],
        f"Volume / Técnico Ativo ({ano_comp})",
        f"{_formatar_decimal_br(resumo.contratos_por_tecnico_comp, 1)} ct · {_formatar_decimal_br(resumo.os_por_tecnico_comp, 1)} O.S.",
        sub=(
            f"Base {ano_base}: {_formatar_decimal_br(resumo.contratos_por_tecnico_base, 1)} ct · "
            f"{_formatar_decimal_br(resumo.os_por_tecnico_base, 1)} O.S. "
            f"({resumo.tecnicos_ativos_base}→{resumo.tecnicos_ativos_comp} téc.)"
        ),
        icone="👷",
        tema="gradiente",
    )

    st.markdown("<div style='height:0.65rem'></div>", unsafe_allow_html=True)

    aba_mensal, aba_dimensoes, aba_tecnicos = st.tabs(
        [
            "📈 Evolução Mensal (Jan–Dez)",
            "🏗️ Projetos, Bases e Monitores",
            "👷 Comparativo por Técnico",
        ]
    )

    with aba_mensal:
        g_cols = st.columns(2)
        with g_cols[0]:
            with st.container(border=True):
                render_section_header(
                    f"Contratos por mês · {ano_base} x {ano_comp}",
                    subtitulo="Barras sólidas indicam os meses dentro do recorte comparativo ativo",
                    icone="📄",
                )
                st.plotly_chart(
                    _grafico_mensal_comparativo(
                        resumo.mensal,
                        col_base="contratos_base",
                        col_comp="contratos_comp",
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                        cor_base=_COR_2025_CONTRATOS,
                        cor_comp=_COR_2026_CONTRATOS,
                        unidade="Contratos",
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_chart_mensal_contratos",
                )
        with g_cols[1]:
            with st.container(border=True):
                render_section_header(
                    f"Quantidade de O.S. (Prod) por mês · {ano_base} x {ano_comp}",
                    subtitulo="Comparação mensal direta das ordens de serviço produtivas",
                    icone="📋",
                )
                st.plotly_chart(
                    _grafico_mensal_comparativo(
                        resumo.mensal,
                        col_base="os_base",
                        col_comp="os_comp",
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                        cor_base=_COR_2025_OS,
                        cor_comp=_COR_2026_OS,
                        unidade="O.S. (Prod)",
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_chart_mensal_os",
                )

        g_cols2 = st.columns([1.15, 1.0])
        with g_cols2[0]:
            with st.container(border=True):
                top_acc_cols = st.columns([1.5, 1.0])
                with top_acc_cols[0]:
                    render_section_header(
                        f"Ritmo acumulado no recorte · {ano_base} x {ano_comp}",
                        subtitulo="Trajetória acumulada mês a mês nos meses selecionados",
                        icone="🚀",
                    )
                with top_acc_cols[1]:
                    metrica_acum = st.radio(
                        "Indicador acumulado",
                        options=["contratos", "os"],
                        format_func=lambda m: (
                            "Contratos" if m == "contratos" else "O.S. (Prod)"
                        ),
                        horizontal=True,
                        key="comp_acum_metrica",
                        label_visibility="collapsed",
                    )
                metrica_acum_lit: Literal["contratos", "os"] = (
                    "os" if metrica_acum == "os" else "contratos"
                )
                st.plotly_chart(
                    _grafico_acumulado_ytd(
                        resumo.mensal,
                        metrica=metrica_acum_lit,
                        ano_base=ano_base,
                        ano_comp=ano_comp,
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_chart_acumulado",
                )
        with g_cols2[1]:
            with st.container(border=True):
                render_section_header(
                    f"Densidade O.S. / Contrato · {ano_base} x {ano_comp}",
                    subtitulo="Média de ordens de serviço executadas por contrato em cada mês",
                    icone="🔄",
                )
                st.plotly_chart(
                    _grafico_giro_os_contrato(resumo.mensal, ano_base, ano_comp),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_chart_giro",
                )

        with st.container(border=True):
            render_section_header(
                f"Matriz mensal consolidada · {ano_base} x {ano_comp}",
                subtitulo="Volumes absolutos, deltas, variações percentuais e relação O.S./contrato por competência",
                icone="📊",
            )
            st.dataframe(
                _formatar_styler_comparativo(resumo.tabela_mensal, ano_base, ano_comp),
                width="stretch",
                hide_index=True,
            )
            st.download_button(
                f"Baixar comparativo mensal {ano_base} x {ano_comp} em CSV",
                data=csv_download(resumo.tabela_mensal),
                file_name=f"comparativo_mensal_{ano_base}_{ano_comp}.csv",
                mime="text/csv",
                key="download_comp_mensal_csv",
            )

    with aba_dimensoes:
        dim_opcoes = ["Projeto"]
        if tem_cadastro:
            dim_opcoes.extend(["Base", "Monitor"])
        dim_escolhida = st.radio(
            "Dimensão de abertura",
            options=dim_opcoes,
            horizontal=True,
            key="comp_dimensao_abertura",
        )
        tabela_dim = (
            resumo.por_projeto
            if dim_escolhida == "Projeto"
            else (resumo.por_base if dim_escolhida == "Base" else resumo.por_monitor)
        )
        if tabela_dim.empty:
            st.info(f"Não há dados por {dim_escolhida.lower()} para o recorte atual.")
        else:
            d_cols = st.columns(2)
            with d_cols[0]:
                with st.container(border=True):
                    render_section_header(
                        f"Contratos por {dim_escolhida} · {ano_base} x {ano_comp}",
                        subtitulo="Ordenado pelo maior volume do ano comparado",
                        icone="📄",
                    )
                    st.plotly_chart(
                        _grafico_dimensao_horizontal(
                            tabela_dim,
                            dim_escolhida,
                            ano_base,
                            ano_comp,
                            "Contratos",
                        ),
                        width="stretch",
                        config=CHART_CONFIG,
                        key=f"comp_chart_dim_ct_{dim_escolhida}",
                    )
            with d_cols[1]:
                with st.container(border=True):
                    render_section_header(
                        f"O.S. (Prod) por {dim_escolhida} · {ano_base} x {ano_comp}",
                        subtitulo="Volume de ordens de serviço produtivas por agrupamento",
                        icone="📋",
                    )
                    st.plotly_chart(
                        _grafico_dimensao_horizontal(
                            tabela_dim,
                            dim_escolhida,
                            ano_base,
                            ano_comp,
                            "O.S.",
                        ),
                        width="stretch",
                        config=CHART_CONFIG,
                        key=f"comp_chart_dim_os_{dim_escolhida}",
                    )

            with st.container(border=True):
                render_section_header(
                    f"Resumo comparativo por {dim_escolhida}",
                    subtitulo="Participação no mix de contratos, evolução percentual e giro O.S./contrato",
                    icone="🗂️",
                )
                st.dataframe(
                    _formatar_styler_comparativo(tabela_dim, ano_base, ano_comp),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    f"Baixar comparativo por {dim_escolhida.lower()} em CSV",
                    data=csv_download(tabela_dim),
                    file_name=f"comparativo_{dim_escolhida.lower()}_{ano_base}_{ano_comp}.csv",
                    mime="text/csv",
                    key=f"download_comp_dim_{dim_escolhida.lower()}_csv",
                )

    with aba_tecnicos:
        if resumo.por_tecnico.empty:
            st.info("Não há técnicos com Contratos ou O.S. válidos no recorte atual.")
        else:
            with st.container(border=True):
                render_section_header(
                    f"Mapa de evolução individual · Δ Contratos × Δ O.S. ({ano_comp} − {ano_base})",
                    subtitulo="Cada ponto representa um técnico: quadrante superior direito indica expansão simultânea de contratos e O.S.",
                    icone="🎯",
                )
                st.plotly_chart(
                    _grafico_dispersao_deltas_tecnico(
                        resumo.por_tecnico, ano_base, ano_comp
                    ),
                    width="stretch",
                    config=CHART_CONFIG,
                    key="comp_chart_scatter_tecnicos",
                )

            with st.container(border=True):
                t_filtros = st.columns([1.4, 1.4])
                with t_filtros[0]:
                    busca_tec = st.text_input(
                        "Buscar colaborador",
                        placeholder="Digite parte do nome, base ou monitor...",
                        key="comp_busca_tecnico",
                    )
                with t_filtros[1]:
                    status_disp = [
                        "Todos",
                        *sorted(
                            str(s)
                            for s in resumo.por_tecnico["Status Comparativo"]
                            .dropna()
                            .unique()
                        ),
                    ]
                    status_sel = st.selectbox(
                        "Filtrar por status comparativo",
                        options=status_disp,
                        key="comp_status_tecnico_filter",
                    )

                tec_filtrado = resumo.por_tecnico
                if busca_tec.strip():
                    termo = busca_tec.strip().casefold()
                    mask_busca = (
                        tec_filtrado["Técnico"]
                        .str.casefold()
                        .str.contains(termo, na=False)
                        | tec_filtrado["Base"]
                        .str.casefold()
                        .str.contains(termo, na=False)
                        | tec_filtrado["Monitor"]
                        .str.casefold()
                        .str.contains(termo, na=False)
                    )
                    tec_filtrado = tec_filtrado[mask_busca]
                if status_sel != "Todos":
                    tec_filtrado = tec_filtrado[
                        tec_filtrado["Status Comparativo"].eq(status_sel)
                    ]

                render_section_header(
                    f"Comparativo analítico por técnico ({len(tec_filtrado)} colaboradores)",
                    subtitulo="Meses ativos, contratos distintos, O.S. (Prod), variações e giro O.S./contrato",
                    icone="👷",
                )
                st.dataframe(
                    _formatar_styler_comparativo(tec_filtrado, ano_base, ano_comp),
                    width="stretch",
                    hide_index=True,
                )
                st.download_button(
                    f"Baixar comparativo por técnico {ano_base} x {ano_comp} em CSV",
                    data=csv_download(tec_filtrado),
                    file_name=f"comparativo_tecnicos_{ano_base}_{ano_comp}.csv",
                    mime="text/csv",
                    key="download_comp_tecnicos_csv",
                )
