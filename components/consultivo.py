"""Painel de Histórico Consultivo interligado à planilha cadastral lista_ativos."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    TipoTrendType,
    Validadores,
    converter_data_br,
    formatar_delta_decimal_br,
    formatar_delta_inteiro_br,
    formatar_numero_br,
    formatar_variacao_pct_br,
    injetar_css,
    injetar_css_delta_cards,
    render_delta_card,
    render_hero_totale_2,
    render_insight,
    render_kpi,
    render_section_header,
    render_ticker,
)
from production import (
    DEFAULT_CONSULTIVO_FOLDER_ID,
    ROSTER_ACTIVE_TAB,
    clean_code,
    converter_data_consultivo_br,
    month_label,
    normalize_text,
)


def normalizar_coluna_data_consultivo(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza a coluna ``DATA`` (e ``period``) garantindo leitura DIA/MÊS/ANO (DD/MM/YYYY)."""
    if df.empty:
        return df.copy()
    work = df.copy()
    if "DATA" in work.columns:
        datas_dt = converter_data_consultivo_br(work["DATA"])
        if datas_dt.isna().any():
            mask_na = datas_dt.isna()
            datas_dt.loc[mask_na] = converter_data_br(work.loc[mask_na, "DATA"])
        work["DATA"] = datas_dt
        if "period" in work.columns:
            work["period"] = datas_dt.dt.to_period("M").dt.to_timestamp()
    return work


def formatar_data_br_consultivo(valor: object, *, incluir_hora: bool = False) -> str:
    """Formata datas e timestamps sempre no padrão brasileiro ``DD/MM/YYYY``."""
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return ""
    if isinstance(valor, float) and pd.isna(valor):
        return ""
    if isinstance(valor, (pd.Timestamp, datetime)):
        if pd.isna(valor):
            return ""
        return valor.strftime("%d/%m/%Y %H:%M:%S" if incluir_hora else "%d/%m/%Y")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "nat", "none", "null", "-"}:
        return ""
    serie_conv = converter_data_consultivo_br(pd.Series([texto]))
    if serie_conv.notna().iloc[0]:
        ts = pd.Timestamp(serie_conv.iloc[0])
        return ts.strftime("%d/%m/%Y %H:%M:%S" if incluir_hora else "%d/%m/%Y")
    return texto


@dataclass(frozen=True)
class ConfiguracoesConsultivo:
    """Parâmetros operacionais oficiais do painel de Consultivos."""

    meta_diaria_consultivos: int = 7
    meta_mensal_produtos_tecnico: int = 30
    meta_mensal_monitor: int = 350


CONFIG_CONSULTIVO = ConfiguracoesConsultivo()


def formatar_data_brasileira(
    valor: date | datetime | pd.Timestamp | str | None,
    *,
    incluir_hora: bool = False,
) -> str:
    """Padroniza datas para o formato brasileiro DD/MM/AAAA."""
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return "—"
    if isinstance(valor, float) and pd.isna(valor):
        return "—"
    if isinstance(valor, (pd.Timestamp, datetime)):
        if pd.isna(valor):
            return "—"
        formato = "%d/%m/%Y %H:%M" if incluir_hora else "%d/%m/%Y"
        return valor.strftime(formato)
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")

    texto = str(valor).strip()
    if not texto or texto.lower() in {"nan", "nat", "none", "null", "-"}:
        return "—"

    serie_conv = converter_data_consultivo_br(pd.Series([texto]))
    if not serie_conv.notna().iloc[0]:
        return "—"

    ts = pd.Timestamp(serie_conv.iloc[0])
    formato = "%d/%m/%Y %H:%M" if incluir_hora else "%d/%m/%Y"
    return ts.strftime(formato)


def formatar_numero_inteiro_br(valor: Any) -> str:
    """Converte valores numéricos ou nulos em texto inteiro com separador brasileiro."""
    if pd.isna(valor):
        return "0"

    try:
        numero = int(valor)
    except (TypeError, ValueError):
        try:
            numero = int(float(valor))
        except (TypeError, ValueError):
            return "0"

    return f"{numero:,}".replace(",", ".")


class CalculosConsultivo:
    """Utilitários matemáticos vetorizados do painel de Consultivos."""

    @staticmethod
    def variacao(atual: float, anterior: float) -> float | None:
        if anterior == 0:
            return None if atual == 0 else 100.0
        return ((atual - anterior) / anterior) * 100.0

    @staticmethod
    def share(parte: float, total: float) -> float:
        return (parte / total * 100.0) if total > 0 else 0.0

    @staticmethod
    def fator_projecao(
        datas_validas: pd.Series,
        hoje: date | None = None,
    ) -> tuple[float, int, int]:
        """Calcula o fator de projeção considerando dias úteis de Seg a Sáb."""
        datas_dt = converter_data_consultivo_br(datas_validas).dropna()
        if datas_dt.empty:
            return 1.0, 0, 0

        ref_hoje = hoje or date.today()
        max_dt = datas_dt.max()
        if max_dt.month != ref_hoje.month or max_dt.year != ref_hoje.year:
            return 1.0, 0, 0

        ano, mes = max_dt.year, max_dt.month
        ultimo_dia = calendar.monthrange(ano, mes)[1]

        todas_datas = pd.date_range(
            start=date(ano, mes, 1),
            end=date(ano, mes, ultimo_dia),
            freq="D",
        )
        dias_uteis_totais = int((todas_datas.day_of_week < 6).sum())

        datas_passadas = todas_datas[todas_datas.date <= max_dt.date()]
        dias_uteis_passados = max(1, int((datas_passadas.day_of_week < 6).sum()))

        fator = (
            dias_uteis_totais / dias_uteis_passados if dias_uteis_passados > 0 else 1.0
        )
        return fator, dias_uteis_passados, dias_uteis_totais


def _injetar_css_consultivo(dark_mode: bool = False) -> None:
    if dark_mode:
        table_css = """
        .corp-table-container {
            width: 100%; overflow-x: auto; overflow-y: auto; max-height: 580px;
            border-radius: 12px; box-shadow: 0 4px 14px rgba(0, 0, 0, 0.32);
            border: 1px solid #334155; background: #0F172A; margin-bottom: 16px;
        }
        .corp-table {
            width: 100%; border-collapse: collapse; font-family: 'Inter', 'Segoe UI', sans-serif;
            font-size: 13px; text-align: left; color: #E2E8F0;
        }
        .corp-table th {
            background: linear-gradient(180deg, #012869 0%, #1E40AF 100%);
            color: #FFFFFF !important; font-weight: 700; padding: 12px 16px;
            text-transform: uppercase; font-size: 11px; letter-spacing: 0.6px;
            position: sticky; top: 0; z-index: 10; white-space: nowrap;
            border-bottom: 2px solid #011840;
        }
        .corp-table td {
            padding: 10px 16px; border-bottom: 1px solid #1E293B;
            color: #E2E8F0; font-weight: 500; white-space: nowrap;
        }
        .corp-table tbody tr:nth-child(even) { background-color: #131E35; }
        .corp-table tbody tr:hover { background-color: #1E293B; transition: background-color 0.15s ease; }
        .corp-table td.col-real { background-color: rgba(30, 58, 138, 0.22); }
        .corp-table td.col-proj {
            background-color: rgba(243, 124, 4, 0.14); color: #FDBA74 !important;
            font-weight: 700 !important; border-left: 1px dashed rgba(243, 124, 4, 0.45);
        }
        .corp-table tbody tr:hover td.col-proj { background-color: rgba(243, 124, 4, 0.24) !important; }
        .corp-table td.meta-batida {
            background-color: rgba(22, 163, 74, 0.24) !important; color: #86EFAC !important; font-weight: 800 !important;
        }
        .corp-table td.falta-meta {
            background-color: rgba(220, 38, 38, 0.20) !important; color: #FCA5A5 !important; font-weight: 600 !important;
        }
        """
    else:
        table_css = """
        .corp-table-container {
            width: 100%; overflow-x: auto; overflow-y: auto; max-height: 580px;
            border-radius: 12px; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
            border: 1px solid #CBD5E1; background: #FFFFFF; margin-bottom: 16px;
        }
        .corp-table {
            width: 100%; border-collapse: collapse; font-family: 'Inter', 'Segoe UI', sans-serif;
            font-size: 13px; text-align: left;
        }
        .corp-table th {
            background: linear-gradient(180deg, #012869 0%, #1E40AF 100%);
            color: #FFFFFF !important; font-weight: 700; padding: 12px 16px;
            text-transform: uppercase; font-size: 11px; letter-spacing: 0.6px;
            position: sticky; top: 0; z-index: 10; white-space: nowrap;
            border-bottom: 2px solid #011840;
        }
        .corp-table td {
            padding: 10px 16px; border-bottom: 1px solid #E2E8F0;
            color: #1E293B; font-weight: 500; white-space: nowrap;
        }
        .corp-table tbody tr:nth-child(even) { background-color: #F8FAFC; }
        .corp-table tbody tr:hover { background-color: #EFF6FF; transition: background-color 0.15s ease; }
        .corp-table td.col-real { background-color: rgba(241, 245, 249, 0.45); }
        .corp-table td.col-proj {
            background-color: #FFFBEB; color: #B45309 !important;
            font-weight: 700 !important; border-left: 1px dashed #FCD34D;
        }
        .corp-table tbody tr:hover td.col-proj { background-color: #FEF3C7 !important; }
        .corp-table td.meta-batida {
            background-color: #DCFCE7 !important; color: #166534 !important; font-weight: 800 !important;
        }
        .corp-table td.falta-meta {
            background-color: #FEE2E2 !important; color: #991B1B !important; font-weight: 600 !important;
        }
        .corp-table tbody tr:hover td.meta-batida { background-color: #BBF7D0 !important; }
        .corp-table tbody tr:hover td.falta-meta { background-color: #FECACA !important; }
        """
    injetar_css(table_css)


def injetar_ativos_sem_movimentacao(
    df_periodo: pd.DataFrame,
    roster: pd.DataFrame | None,
) -> pd.DataFrame:
    """Inclui técnicos ATIVOS de ``lista_ativos`` ausentes na janela selecionada com volume zero."""
    if roster is None or roster.empty:
        return df_periodo.copy()

    ativos = roster.copy()
    if "source_tab" in ativos.columns:
        ativos = ativos[ativos["source_tab"].astype(str).eq(ROSTER_ACTIVE_TAB)]
    if "status" in ativos.columns:
        ativos = ativos[
            ativos["status"].astype(str).str.strip().str.upper().eq("ATIVO")
        ]
    if ativos.empty:
        return df_periodo.copy()

    ativos["_login_norm"] = ativos["login"].map(lambda v: clean_code(v).upper())
    ativos["_tech_key"] = ativos["technician"].map(normalize_text)
    ativos = ativos.drop_duplicates(subset=["_login_norm", "_tech_key"], keep="first")

    present_logins: set[str] = set()
    present_names: set[str] = set()
    if not df_periodo.empty:
        if "LOGIN NETSALES" in df_periodo.columns:
            present_logins = {
                clean_code(v).upper()
                for v in df_periodo["LOGIN NETSALES"].dropna().unique()
                if clean_code(v) and clean_code(v).upper() != "SEM LOGIN"
            }
        if "VENDEDOR" in df_periodo.columns:
            present_names = {
                normalize_text(v)
                for v in df_periodo["VENDEDOR"].dropna().unique()
                if normalize_text(v)
            }

    def _is_absent(row: pd.Series) -> bool:
        lg = str(row["_login_norm"])
        tk = str(row["_tech_key"])
        if lg:
            return lg not in present_logins
        return bool(tk) and tk not in present_names

    faltantes = ativos[ativos.apply(_is_absent, axis=1)]
    if faltantes.empty:
        return df_periodo.copy()

    zeros = pd.DataFrame(
        {
            "DATA": pd.Series(pd.NaT, index=faltantes.index, dtype="datetime64[ns]"),
            "period": pd.Series(pd.NaT, index=faltantes.index, dtype="datetime64[ns]"),
            "LOGIN NETSALES": faltantes["_login_norm"]
            .replace({"": "SEM LOGIN"})
            .astype(str),
            "VENDEDOR": faltantes["technician"]
            .fillna("Nome Não Cadastrado")
            .astype(str),
            "Técnico": faltantes["technician"].fillna("").astype(str),
            "Monitor": faltantes["monitor"]
            .replace({"Sem monitor": "Não Identificado", "": "Não Identificado"})
            .fillna("Não Identificado")
            .astype(str),
            "U.N.": faltantes["un"]
            .replace({"Sem U.N.": "Não Identificada", "": "Não Identificada"})
            .fillna("Não Identificada")
            .astype(str),
            "Base": faltantes["base"]
            .replace({"Sem base": "Não Identificada", "": "Não Identificada"})
            .fillna("Não Identificada")
            .astype(str),
            "Situação": "ATIVO",
            "Qtde. Cons.": 0,
            "Qtde. Prod.": 0,
            "Qtde. Mesh": 0,
            "Qtde. TV": 0,
            "Qtde. Virtua": 0,
            "QTDE_CONSULTIVO": 0,
            "QTDE_PRODUTOS": 0,
            "QTDE_MESH": 0,
            "QTDE_TV": 0,
            "QTDE_VIRTUA": 0,
            "CONTRATO": "",
            "HP": "",
            "CÓDIGO CONTATO": "",
            "TIPO DE TABULAÇÃO": "SEM MOVIMENTAÇÃO",
            "STATUS NETSALES": "",
            "TIPO SERVIÇO": "Sem Tipo",
            "PLANO TV": "",
            "PLANO INTERNET": "",
            "source_file": "lista_ativos",
            "source_row": 0,
            "is_demo": 0,
            "imported_at": "",
        }
    )

    if df_periodo.empty:
        return zeros.reset_index(drop=True)
    return pd.concat([df_periodo, zeros], ignore_index=True)


def preparar_ranking(
    df: pd.DataFrame,
    usar_vendedor: bool,
    fator_proj: float,
) -> pd.DataFrame:
    """Agrupa e projeta volumes de Consultivos e Produtos por Monitor ou Técnico."""
    cols_group = (
        ["VENDEDOR", "Monitor", "Base"] if usar_vendedor else ["Monitor", "Base"]
    )
    if df.empty:
        cols_out = cols_group + [
            "Total Consultivos",
            "Total Produtos",
            "Mesh",
            "TV Box",
            "Virtua",
        ]
        return pd.DataFrame(columns=cols_out)

    df_grp = (
        df.groupby(cols_group, dropna=False)
        .agg(
            **{
                "Total Consultivos": ("Qtde. Cons.", "sum"),
                "Total Produtos": ("Qtde. Prod.", "sum"),
                "Mesh": ("Qtde. Mesh", "sum"),
                "TV Box": ("Qtde. TV", "sum"),
                "Virtua": ("Qtde. Virtua", "sum"),
            }
        )
        .reset_index()
        .sort_values(
            ["Total Consultivos", "Total Produtos"],
            ascending=[False, False],
        )
    )

    cols_num = ["Total Consultivos", "Total Produtos", "Mesh", "TV Box", "Virtua"]
    for col in cols_num:
        df_grp[col] = pd.to_numeric(df_grp[col], errors="coerce").fillna(0).astype(int)

    if fator_proj > 1.0:
        df_grp["Proj. Consultivos"] = (
            (df_grp["Total Consultivos"] * fator_proj).round().astype(int)
        )
        df_grp["Proj. Produtos"] = (
            (df_grp["Total Produtos"] * fator_proj).round().astype(int)
        )
        ordem_cols = cols_group + [
            "Total Consultivos",
            "Proj. Consultivos",
            "Total Produtos",
            "Proj. Produtos",
            "Mesh",
            "TV Box",
            "Virtua",
        ]
        df_grp = df_grp[ordem_cols]

    return df_grp.reset_index(drop=True)


def preparar_resumo_diario_monitor(
    df: pd.DataFrame,
    meta_diaria: int = CONFIG_CONSULTIVO.meta_diaria_consultivos,
) -> pd.DataFrame:
    """Consolida os consultivos por dia e Monitor contra a meta diária operacional."""
    if df.empty or "DATA" not in df.columns or "Monitor" not in df.columns:
        return pd.DataFrame()

    df_norm = normalizar_coluna_data_consultivo(df)
    df_validos = df_norm.dropna(subset=["DATA"]).copy()
    if df_validos.empty:
        return pd.DataFrame()

    df_validos["Data_Ref"] = df_validos["DATA"].dt.date
    resumo = (
        df_validos.groupby(["Data_Ref", "Monitor"], dropna=False)
        .agg(
            Consultivos=("Qtde. Cons.", "sum"),
            Produtos=("Qtde. Prod.", "sum"),
        )
        .reset_index()
        .sort_values(["Data_Ref", "Consultivos"], ascending=[False, False])
    )
    resumo["Meta Diária"] = int(meta_diaria)
    resumo["Saldo Meta"] = resumo["Consultivos"] - resumo["Meta Diária"]
    resumo["Atingimento (%)"] = np.where(
        resumo["Meta Diária"] > 0,
        (resumo["Consultivos"] / resumo["Meta Diária"]) * 100.0,
        0.0,
    )
    resumo["Status"] = np.where(
        resumo["Consultivos"] >= resumo["Meta Diária"],
        "Meta atingida",
        "Abaixo da meta",
    )
    resumo["Data"] = resumo["Data_Ref"].map(formatar_data_brasileira)
    return resumo[
        [
            "Data",
            "Monitor",
            "Consultivos",
            "Meta Diária",
            "Saldo Meta",
            "Atingimento (%)",
            "Produtos",
            "Status",
            "Data_Ref",
        ]
    ].reset_index(drop=True)


def calcular_meta_acumulada_monitor(
    resumo_diario: pd.DataFrame,
    meta_diaria: int = CONFIG_CONSULTIVO.meta_diaria_consultivos,
) -> pd.DataFrame:
    """Consolida a meta acumulada por Monitor conforme os dias ativos no período."""
    if resumo_diario.empty:
        return pd.DataFrame()

    acumulado = (
        resumo_diario.groupby("Monitor", dropna=False)
        .agg(
            Dias_Ativos=("Data_Ref", "nunique"),
            Consultivos_Acumulados=("Consultivos", "sum"),
            Produtos_Acumulados=("Produtos", "sum"),
            Dias_Meta_Batida=("Status", lambda s: int((s == "Meta atingida").sum())),
        )
        .reset_index()
    )
    acumulado["Meta Acumulada"] = acumulado["Dias_Ativos"] * int(meta_diaria)
    acumulado["Saldo Acumulado"] = (
        acumulado["Consultivos_Acumulados"] - acumulado["Meta Acumulada"]
    )
    acumulado["Atingimento (%)"] = np.where(
        acumulado["Meta Acumulada"] > 0,
        (acumulado["Consultivos_Acumulados"] / acumulado["Meta Acumulada"]) * 100.0,
        0.0,
    )
    return acumulado.sort_values(
        ["Atingimento (%)", "Consultivos_Acumulados"],
        ascending=[False, False],
    ).reset_index(drop=True)


def preparar_evolucao_mensal_consultivo(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa o histórico consultivo por competência mensal (MM/AAAA)."""
    colunas = [
        "period",
        "Competência",
        "Técnicos Produtivos",
        "Total Consultivos",
        "Var. Mês (%)",
        "Total Produtos",
        "Mesh",
        "TV Box",
        "Virtua",
        "Conversão (%)",
    ]
    if df.empty or "DATA" not in df.columns:
        return pd.DataFrame(columns=colunas)

    df_norm = normalizar_coluna_data_consultivo(df)
    validos = df_norm.dropna(subset=["DATA"]).copy()
    if validos.empty:
        return pd.DataFrame(columns=colunas)

    validos["period"] = validos["DATA"].dt.to_period("M").dt.to_timestamp()
    prod_mask = validos["Qtde. Cons."] > 0
    prod_por_mes = (
        validos.loc[prod_mask]
        .groupby("period")["LOGIN NETSALES"]
        .nunique()
        .rename("Técnicos Produtivos")
    )

    mensal = (
        validos.groupby("period", as_index=False)
        .agg(
            **{
                "Total Consultivos": ("Qtde. Cons.", "sum"),
                "Total Produtos": ("Qtde. Prod.", "sum"),
                "Mesh": ("Qtde. Mesh", "sum"),
                "TV Box": ("Qtde. TV", "sum"),
                "Virtua": ("Qtde. Virtua", "sum"),
            }
        )
        .sort_values("period")
        .reset_index(drop=True)
    )
    mensal = mensal.merge(prod_por_mes, on="period", how="left")
    mensal["Técnicos Produtivos"] = mensal["Técnicos Produtivos"].fillna(0).astype(int)
    mensal["Competência"] = mensal["period"].map(month_label)

    prev = mensal["Total Consultivos"].shift(1)
    mensal["Var. Mês (%)"] = np.where(
        prev.isna() | (prev == 0),
        np.nan,
        ((mensal["Total Consultivos"] - prev) / prev) * 100.0,
    )
    mensal["Conversão (%)"] = np.where(
        mensal["Total Consultivos"] > 0,
        (mensal["Total Produtos"] / mensal["Total Consultivos"]) * 100.0,
        0.0,
    )
    return mensal[colunas]


def gerar_html_tabela_cons(df: pd.DataFrame, usar_vendedor: bool = False) -> str:
    """Gera o HTML corporativo com classes semânticas de meta e projeção."""
    if df.empty:
        return ""

    cols_proj = {"Proj. Consultivos", "Proj. Produtos"}
    cols_num = {
        "Total Consultivos",
        "Proj. Consultivos",
        "Total Produtos",
        "Proj. Produtos",
        "Mesh",
        "TV Box",
        "Virtua",
        "Dias Ativos",
        "Consultivos",
        "Meta Diária",
        "Meta Acumulada",
        "Saldo Meta",
        "Saldo Acumulado",
        "Produtos",
        "Técnicos Produtivos",
    }

    html = ['<div class="corp-table-container"><table class="corp-table"><thead><tr>']
    for col in df.columns:
        align = (
            ' style="text-align: right;"'
            if col in cols_num or "(%)" in str(col)
            else ""
        )
        html.append(f"<th{align}>{Validadores.html_escape(str(col))}</th>")
    html.append("</tr></thead><tbody>")

    records = df.to_dict("records")
    for row in records:
        html.append("<tr>")
        for col, val in row.items():
            classes: list[str] = []
            style = ""

            if col in cols_proj:
                classes.append("col-proj")
            elif col in cols_num:
                classes.append("col-real")

            if usar_vendedor and col == "Total Produtos":
                if isinstance(val, (int, float)) and not pd.isna(val):
                    classes.append(
                        "meta-batida"
                        if val >= CONFIG_CONSULTIVO.meta_mensal_produtos_tecnico
                        else "falta-meta"
                    )
            elif not usar_vendedor and col in ("Total Consultivos", "Total Produtos"):
                if isinstance(val, (int, float)) and not pd.isna(val):
                    classes.append(
                        "meta-batida"
                        if val >= CONFIG_CONSULTIVO.meta_mensal_monitor
                        else "falta-meta"
                    )

            if col in cols_num or "(%)" in str(col):
                style = ' style="text-align: right;"'
                if pd.isna(val):
                    val_str = "—"
                elif "(%)" in str(col):
                    val_str = (
                        f"{float(val):,.1f}%".replace(",", "§")
                        .replace(".", ",")
                        .replace("§", ".")
                    )
                elif isinstance(val, (int, np.integer)) or (
                    isinstance(val, float) and float(val).is_integer()
                ):
                    val_str = f"{int(val):,}".replace(",", ".")
                else:
                    val_str = str(val)
            else:
                if pd.isna(val):
                    val_str = "—"
                elif isinstance(val, (pd.Timestamp, datetime, date)):
                    val_str = Validadores.html_escape(formatar_data_br_consultivo(val))
                else:
                    val_str = Validadores.html_escape(str(val))

            cls_attr = f' class="{" ".join(classes)}"' if classes else ""
            html.append(f"<td{cls_attr}{style}>{val_str}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")
    return "".join(html)


def render_tabela_cons(df: pd.DataFrame, usar_vendedor: bool = False) -> None:
    """Renderiza a tabela corporativa de Consultivos ou exibe aviso quando vazia."""
    if df.empty:
        render_insight(
            "Nenhum registro encontrado para os filtros aplicados.",
            tipo="info",
        )
        return
    st.markdown(
        gerar_html_tabela_cons(df, usar_vendedor=usar_vendedor),
        unsafe_allow_html=True,
    )


def sanitizar_csv_exportacao(df: pd.DataFrame) -> bytes:
    """Gera CSV separado por ponto e vírgula protegido contra CSV Injection e com datas DD/MM/YYYY."""
    df_safe = normalizar_coluna_data_consultivo(df)
    for col in df_safe.columns:
        if pd.api.types.is_datetime64_any_dtype(df_safe[col]):
            df_safe[col] = (
                df_safe[col]
                .dt.strftime("%d/%m/%Y")
                .where(df_safe[col].notna(), "")
                .astype(str)
            )
        elif col == "imported_at":
            df_safe[col] = df_safe[col].map(
                lambda v: formatar_data_br_consultivo(v, incluir_hora=True)
            )
    obj_cols = df_safe.select_dtypes(include=["object", "string"]).columns
    for col in obj_cols:
        s = df_safe[col].astype(str)
        mask_formula = s.str.startswith(("=", "+", "-", "@"), na=False)
        if mask_formula.any():
            df_safe.loc[mask_formula, col] = "'" + s.loc[mask_formula]
    return df_safe.to_csv(index=False, sep=";").encode("utf-8-sig")


def _resolver_janela_datas(
    datas_validas: pd.Series,
    periodo_predefinido: str,
    competencia_sel: str,
    hoje: date | None = None,
) -> tuple[date, date, date, date]:
    """Calcula ``(data_min, data_max, default_ini, default_fim)`` com suporte multi-mês."""
    ref_hoje = hoje or date.today()
    if datas_validas.empty:
        return ref_hoje, ref_hoje, ref_hoje, ref_hoje

    data_min = datas_validas.min().date()
    max_dados = datas_validas.max().date()
    data_max = max(max_dados, ref_hoje)

    tem_mes_hoje = bool(
        (
            (datas_validas.dt.year == ref_hoje.year)
            & (datas_validas.dt.month == ref_hoje.month)
        ).any()
    )
    data_referencia = min(ref_hoje, max_dados) if tem_mes_hoje else max_dados

    if competencia_sel != "Automático (Atalho)":
        try:
            mes_str, ano_str = competencia_sel.split("/")
            mes_num, ano_num = int(mes_str), int(ano_str)
            ult = calendar.monthrange(ano_num, mes_num)[1]
            ini_comp = max(data_min, date(ano_num, mes_num, 1))
            fim_comp = min(data_max, date(ano_num, mes_num, ult))
            return data_min, data_max, ini_comp, fim_comp
        except (ValueError, TypeError):
            pass

    if periodo_predefinido == "Mês atual":
        default_ini = max(data_min, data_referencia.replace(day=1))
        ult_ref = calendar.monthrange(data_referencia.year, data_referencia.month)[1]
        default_fim = min(
            data_max, date(data_referencia.year, data_referencia.month, ult_ref)
        )
    elif periodo_predefinido == "Última semana":
        default_ini = max(data_min, data_referencia - timedelta(days=6))
        default_fim = data_referencia
    elif periodo_predefinido == "Últimos 15 dias":
        default_ini = max(data_min, data_referencia - timedelta(days=14))
        default_fim = data_referencia
    elif periodo_predefinido in ("Ano 2025", "Ano 2026"):
        ano_alvo = 2025 if periodo_predefinido == "Ano 2025" else 2026
        datas_ano = datas_validas[datas_validas.dt.year == ano_alvo]
        if not datas_ano.empty:
            default_ini = datas_ano.min().date()
            default_fim = datas_ano.max().date()
        else:
            default_ini = max(data_min, min(data_max, date(ano_alvo, 1, 1)))
            default_fim = max(default_ini, min(data_max, date(ano_alvo, 12, 31)))
    else:  # "Todo período" ou "Personalizado"
        default_ini = data_min
        default_fim = max_dados

    return data_min, data_max, default_ini, default_fim


def _aplicar_layout_grafico_consultivo(
    fig: go.Figure,
    *,
    dark_mode: bool,
    height: int = 380,
) -> go.Figure:
    text_color = "#E2E8F0" if dark_mode else Cores.TEXTO
    muted_color = "#94A3B8" if dark_mode else Cores.TEXTO_2
    grid_color = "#1E293B" if dark_mode else "#F1F5F9"
    fig.update_layout(
        height=height,
        margin={"l": 12, "r": 20, "t": 28, "b": 16},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": Fontes.TEXTO, "color": text_color, "size": 12},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "title_text": "",
            "font": {"color": muted_color},
        },
    )
    fig.update_xaxes(
        gridcolor=grid_color, zerolinecolor=grid_color, tickfont={"color": muted_color}
    )
    fig.update_yaxes(
        gridcolor=grid_color, zerolinecolor=grid_color, tickfont={"color": muted_color}
    )
    return fig


def render_consultivo(
    consultivo_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None = None,
    *,
    consultivo_stats: dict[str, Any] | None = None,
    consultivo_folder_id: str = DEFAULT_CONSULTIVO_FOLDER_ID,
    drive_configured: bool = False,
    on_sync_consultivo: Callable[[], None] | None = None,
    sync_issues: list[str] | None = None,
) -> None:
    """Renderiza a visão executiva e histórica de Consultivos interligada a lista_ativos."""
    dark_mode = st.session_state.get("theme_mode", "light") == "dark"
    _injetar_css_consultivo(dark_mode=dark_mode)

    stats = consultivo_stats or {}
    total_arquivos = int(stats.get("files") or 0)
    is_demo = bool(int(stats.get("demo_rows") or 0) > 0)

    if consultivo_frame.empty and (roster_frame is None or roster_frame.empty):
        render_hero_totale_2(
            badge="CONSULTIVOS · TOTALE",
            titulo="Total de Consultivos",
            subtitulo=(
                "Análise consolidada de consultivos realizados, mix de produtos "
                "(Mesh, TV Box, Virtua) e projeções operacionais."
            ),
            card_label="HISTÓRICO DRIVE",
            card_valor="0",
            card_sub="arquivos carregados",
        )
        render_insight(
            "Nenhum dado de Histórico Consultivo carregado no momento. "
            "Verifique a sincronização da pasta Google Drive na barra lateral.",
            tipo="alerta",
        )
        if on_sync_consultivo is not None and drive_configured:
            if st.button(
                "🔄 Sincronizar Histórico Consultivo agora", key="btn_sync_cons_empty"
            ):
                on_sync_consultivo()
        if sync_issues:
            with st.expander(
                f"Avisos da última sincronização do Consultivo ({len(sync_issues)})",
                expanded=True,
            ):
                for item in sync_issues[:20]:
                    st.caption(f"• {item}")
        return

    if sync_issues:
        with st.expander(
            f"Avisos da última sincronização do Consultivo ({len(sync_issues)})",
            expanded=False,
        ):
            for item in sync_issues[:20]:
                st.caption(f"• {item}")

    consultivo_work = normalizar_coluna_data_consultivo(consultivo_frame)
    datas_validas = (
        consultivo_work["DATA"].dropna()
        if "DATA" in consultivo_work.columns
        else pd.Series(dtype="datetime64[ns]")
    )

    competencias_opcoes = ["Automático (Atalho)"]
    if not datas_validas.empty:
        periodos_unicos = sorted(datas_validas.dt.to_period("M").unique(), reverse=True)
        competencias_opcoes.extend(p.strftime("%m/%Y") for p in periodos_unicos)

    # ── Barra de Filtros Operacionais (no corpo principal para compatibilidade com @st.fragment) ──
    with st.container(border=True):
        top_cols = st.columns([1.35, 1.15, 0.85, 1.55, 1.15])
        with top_cols[0]:
            opcoes_periodo = [
                "Mês atual",
                "Última semana",
                "Últimos 15 dias",
                "Ano 2026",
                "Ano 2025",
                "Todo período",
                "Personalizado",
            ]
            if "cons_periodo_preset" not in st.session_state:
                st.session_state["cons_periodo_preset"] = "Mês atual"

            def _ao_mudar_preset() -> None:
                st.session_state["cons_competencia_sel"] = "Automático (Atalho)"
                _, _, d_ini, d_fim = _resolver_janela_datas(
                    datas_validas,
                    st.session_state["cons_periodo_preset"],
                    "Automático (Atalho)",
                )
                st.session_state["cons_date_range"] = (d_ini, d_fim)

            periodo_predefinido = st.selectbox(
                "Atalho de Período",
                options=opcoes_periodo,
                key="cons_periodo_preset",
                on_change=_ao_mudar_preset,
            )

        with top_cols[1]:
            if "cons_competencia_sel" not in st.session_state:
                st.session_state["cons_competencia_sel"] = "Automático (Atalho)"

            def _ao_mudar_competencia() -> None:
                comp = st.session_state["cons_competencia_sel"]
                if comp != "Automático (Atalho)":
                    st.session_state["cons_periodo_preset"] = "Personalizado"
                    _, _, d_ini, d_fim = _resolver_janela_datas(
                        datas_validas,
                        "Personalizado",
                        comp,
                    )
                    st.session_state["cons_date_range"] = (d_ini, d_fim)

            competencia_sel = st.selectbox(
                "Competência Mensal",
                options=competencias_opcoes,
                key="cons_competencia_sel",
                on_change=_ao_mudar_competencia,
            )

        data_min, data_max, default_ini, default_fim = _resolver_janela_datas(
            datas_validas,
            periodo_predefinido,
            competencia_sel,
        )

        with top_cols[2]:
            st.markdown("<div style='height: 27px;'></div>", unsafe_allow_html=True)

            def _ao_clicar_dia_vigente() -> None:
                dia_alvo = (
                    min(date.today(), datas_validas.max().date())
                    if not datas_validas.empty
                    else date.today()
                )
                st.session_state["cons_periodo_preset"] = "Personalizado"
                st.session_state["cons_competencia_sel"] = "Automático (Atalho)"
                st.session_state["cons_date_range"] = (dia_alvo, dia_alvo)

            st.button(
                "📅 Dia vigente",
                width="stretch",
                key="cons_btn_dia_vigente",
                help="Filtra o último dia com movimentação (ou hoje, se houver registros hoje).",
                on_click=_ao_clicar_dia_vigente,
            )

        with top_cols[3]:
            if "cons_date_range" not in st.session_state:
                st.session_state["cons_date_range"] = (default_ini, default_fim)
            elif (
                periodo_predefinido != "Personalizado"
                and competencia_sel == "Automático (Atalho)"
            ):
                cur_preset_val = st.session_state["cons_date_range"]
                if not (
                    isinstance(cur_preset_val, (tuple, list))
                    and len(cur_preset_val) == 2
                    and tuple(cur_preset_val) == (default_ini, default_fim)
                ):
                    st.session_state["cons_date_range"] = (default_ini, default_fim)
            else:
                cur_val = st.session_state["cons_date_range"]
                if isinstance(cur_val, (tuple, list)) and len(cur_val) == 2:
                    c_ini = min(max(cur_val[0], data_min), data_max)
                    c_fim = min(max(cur_val[1], data_min), data_max)
                    if (c_ini, c_fim) != tuple(cur_val):
                        st.session_state["cons_date_range"] = (c_ini, c_fim)

            def _ao_mudar_datas_manual() -> None:
                st.session_state["cons_periodo_preset"] = "Personalizado"
                st.session_state["cons_competencia_sel"] = "Automático (Atalho)"

            datas_sel = st.date_input(
                "Intervalo de Datas",
                min_value=data_min,
                max_value=data_max,
                format="DD/MM/YYYY",
                key="cons_date_range",
                on_change=_ao_mudar_datas_manual,
            )

        with top_cols[4]:
            st.markdown("<div style='height: 27px;'></div>", unsafe_allow_html=True)
            manter_sem_movimentacao = st.checkbox(
                "Manter ativos sem mov.",
                value=True,
                key="cons_manter_sem_mov",
                help="Inclui técnicos com Situação = ATIVO em lista_ativos que não registraram consultivos no intervalo selecionado.",
            )

        if isinstance(datas_sel, (tuple, list)) and len(datas_sel) == 2:
            data_ini, data_fim = datas_sel[0], datas_sel[1]
        elif isinstance(datas_sel, (tuple, list)) and len(datas_sel) == 1:
            data_ini = data_fim = datas_sel[0]
        elif isinstance(datas_sel, date):
            data_ini = data_fim = datas_sel
        else:
            data_ini, data_fim = default_ini, default_fim

        if data_ini > data_fim:
            data_ini, data_fim = data_fim, data_ini

        # Filtra o histórico pelo intervalo selecionado e injeta os ATIVOS zerados dessa janela
        if not consultivo_work.empty and "DATA" in consultivo_work.columns:
            mask_periodo = consultivo_work["DATA"].notna() & (
                consultivo_work["DATA"].dt.date.between(data_ini, data_fim)
            )
            df_janela = consultivo_work.loc[mask_periodo].copy()
        else:
            df_janela = consultivo_work.copy()

        if manter_sem_movimentacao:
            df_janela = injetar_ativos_sem_movimentacao(df_janela, roster_frame)

        # Filtros em cascata: Base -> Monitor + ação de sincronização
        bot_cols = st.columns([1.6, 1.8, 1.1])
        with bot_cols[0]:
            bases_universo = set(
                df_janela["Base"].dropna().astype(str).unique()
                if "Base" in df_janela.columns
                else []
            )
            if not consultivo_work.empty and "Base" in consultivo_work.columns:
                bases_universo.update(
                    consultivo_work["Base"].dropna().astype(str).unique()
                )
            bases_disp = sorted(b for b in bases_universo if b.strip())
            sel_bases = st.multiselect(
                "Base",
                options=bases_disp,
                default=[],
                placeholder="Todas as bases",
                key="cons_sel_bases",
            )

        df_temp = (
            df_janela[df_janela["Base"].isin(sel_bases)] if sel_bases else df_janela
        )
        hist_temp = (
            consultivo_work[consultivo_work["Base"].isin(sel_bases)]
            if sel_bases and not consultivo_work.empty
            else consultivo_work
        )

        with bot_cols[1]:
            mon_universo = set(
                df_temp["Monitor"].dropna().astype(str).unique()
                if "Monitor" in df_temp.columns
                else []
            )
            if not hist_temp.empty and "Monitor" in hist_temp.columns:
                mon_universo.update(hist_temp["Monitor"].dropna().astype(str).unique())
            monitores_disp = sorted(m for m in mon_universo if m.strip())
            sel_monitores = st.multiselect(
                "Monitor",
                options=monitores_disp,
                default=[],
                placeholder="Todos os monitores",
                key="cons_sel_monitores",
            )

        with bot_cols[2]:
            if on_sync_consultivo is not None and drive_configured:
                st.markdown("<div style='height: 27px;'></div>", unsafe_allow_html=True)
                if st.button(
                    "🔄 Sincronizar Consultivo",
                    width="stretch",
                    key="cons_btn_sync_drive",
                    help=f"Sincroniza a pasta {consultivo_folder_id} do Google Drive.",
                ):
                    on_sync_consultivo()

    df_f = (
        df_temp[df_temp["Monitor"].isin(sel_monitores)].copy()
        if sel_monitores
        else df_temp.copy()
    )
    df_hist_filtrado = (
        hist_temp[hist_temp["Monitor"].isin(sel_monitores)].copy()
        if sel_monitores and not hist_temp.empty
        else hist_temp.copy()
    )

    # ── Cálculos Operacionais Principais ──
    tot_cons = int(df_f["Qtde. Cons."].sum()) if not df_f.empty else 0
    tot_prod = int(df_f["Qtde. Prod."].sum()) if not df_f.empty else 0
    tot_mesh = int(df_f["Qtde. Mesh"].sum()) if not df_f.empty else 0
    tot_tv = int(df_f["Qtde. TV"].sum()) if not df_f.empty else 0
    tot_virtua = int(df_f["Qtde. Virtua"].sum()) if not df_f.empty else 0

    tot_equipes = int(df_f["LOGIN NETSALES"].nunique()) if not df_f.empty else 0
    equipes_produtivas = (
        int(df_f.loc[df_f["Qtde. Cons."] > 0, "LOGIN NETSALES"].nunique())
        if not df_f.empty
        else 0
    )
    equipes_zeradas = max(0, tot_equipes - equipes_produtivas)
    perc_produtivos = CalculosConsultivo.share(equipes_produtivas, tot_equipes)

    fator_proj, dias_passados, dias_totais = CalculosConsultivo.fator_projecao(
        df_f["DATA"].dropna()
        if not df_f.empty and "DATA" in df_f.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    proj_cons = int(round(tot_cons * fator_proj))
    proj_prod = int(round(tot_prod * fator_proj))

    periodo_txt = (
        f"{formatar_data_brasileira(data_ini)} a {formatar_data_brasileira(data_fim)}"
    )

    # ── Hero Banner Corporativo ──
    render_hero_totale_2(
        badge="TOTALE · PERFORMANCE CONSULTIVA",
        titulo="Performance Consultiva & Mix Comercial",
        subtitulo=(
            "Monitoramento executivo de atendimentos consultivos, mix comercial (Mesh, TV Box, Virtua), "
            f"evolução histórica mensal e conciliação cadastral (lista_ativos) · Recorte: {periodo_txt}."
        ),
        card_label="TOTAL CONSULTIVOS",
        card_valor=f"{tot_cons:,}".replace(",", "."),
        card_sub=f"{tot_prod:,} produtos vinculados".replace(",", "."),
    )

    # Ticker de rastreabilidade Drive + lista_ativos
    ativos_cadastrados = 0
    if (
        roster_frame is not None
        and not roster_frame.empty
        and "status" in roster_frame.columns
    ):
        ativos_cadastrados = int(
            roster_frame["status"].astype(str).str.upper().eq("ATIVO").sum()
        )
    origem_txt = (
        "Base demonstrativa local" if is_demo else f"{total_arquivos} arquivo(s) Drive"
    )
    render_ticker(
        [
            ("Pasta Drive", consultivo_folder_id),
            ("Origem", origem_txt),
            ("Ativos em lista_ativos", str(ativos_cadastrados)),
            ("Período ativo", periodo_txt),
        ]
    )

    if df_f.empty:
        render_insight(
            "Nenhum dado disponível para os filtros selecionados.",
            tipo="alerta",
        )
        return

    # ── Visão Executiva de KPIs (Linha 1: Equipes & Eficiência) ──
    render_section_header(
        titulo="Visão Executiva de Resultados",
        subtitulo=f"Desempenho consolidado da operação ({periodo_txt})",
        icone="📊",
    )

    c1, c2, c3, c4 = st.columns(4)
    render_kpi(
        c1,
        "Total Equipes",
        f"{tot_equipes:,}".replace(",", "."),
        "Base ativa / monitorada",
        tema="azul",
        icone="👥",
    )
    render_kpi(
        c2,
        "Equipes Produtivas",
        f"{equipes_produtivas:,}".replace(",", "."),
        "do total monitorado",
        tema="verde",
        icone="⚡",
        delta=f"{perc_produtivos:.1f}%".replace(".", ","),
        delta_tipo="up" if perc_produtivos > 0 else "neutral",
    )
    perc_zerados = max(0.0, 100.0 - perc_produtivos) if tot_equipes > 0 else 0.0
    render_kpi(
        c3,
        "Técnicos Zerados",
        f"{equipes_zeradas:,}".replace(",", "."),
        "sem vendas no período",
        tema="vermelho" if equipes_zeradas > 0 else "cinza",
        icone="🚫",
        delta=f"{perc_zerados:.1f}%".replace(".", ","),
        delta_tipo="down" if equipes_zeradas > 0 else "neutral",
    )
    eficiencia_media = (tot_prod / tot_cons) if tot_cons > 0 else 0.0
    render_kpi(
        c4,
        "Eficiência (Conversão)",
        f"{eficiencia_media:.2f}".replace(".", ","),
        "Produtos por consultivo",
        tema="roxo",
        icone="🎯",
    )

    st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)

    # ── Visão Executiva de KPIs (Linha 2: Consultivos & Mix de Produtos) ──
    sh_mesh_op = CalculosConsultivo.share(tot_mesh, tot_prod)
    sh_tv_op = CalculosConsultivo.share(tot_tv, tot_prod)
    sh_virtua_op = CalculosConsultivo.share(tot_virtua, tot_prod)
    m1, m2, m3, m4, m5 = st.columns(5)
    render_kpi(
        m1,
        "Tot. Consultivos",
        f"{tot_cons:,}".replace(",", "."),
        "Atendimentos válidos",
        tema="azul",
        icone="📋",
    )
    render_kpi(
        m2,
        "Tot. Produtos",
        f"{tot_prod:,}".replace(",", "."),
        "Itens comercializados",
        tema="laranja",
        icone="📦",
    )
    render_kpi(
        m3,
        "Total Mesh",
        f"{tot_mesh:,}".replace(",", "."),
        "do mix de produtos",
        tema="verde",
        icone="📶",
        delta=f"{sh_mesh_op:.1f}%".replace(".", ","),
        delta_tipo="neutral",
    )
    render_kpi(
        m4,
        "Total TV Box",
        f"{tot_tv:,}".replace(",", "."),
        "do mix de produtos",
        tema="roxo",
        icone="📺",
        delta=f"{sh_tv_op:.1f}%".replace(".", ","),
        delta_tipo="neutral",
    )
    render_kpi(
        m5,
        "Total Virtua",
        f"{tot_virtua:,}".replace(",", "."),
        "do mix de produtos",
        tema="cinza",
        icone="🌐",
        delta=f"{sh_virtua_op:.1f}%".replace(".", ","),
        delta_tipo="neutral",
    )

    # ── Cards de Delta (Δ) contra a Janela Anterior Equivalente ──
    if not df_hist_filtrado.empty and "DATA" in df_hist_filtrado.columns:
        dias_jan = max(1, (data_fim - data_ini).days + 1)
        ant_fim_dt = data_ini - timedelta(days=1)
        ant_ini_dt = ant_fim_dt - timedelta(days=dias_jan - 1)
        datas_hist = pd.to_datetime(df_hist_filtrado["DATA"], errors="coerce").dt.date
        df_ant = df_hist_filtrado[datas_hist.ge(ant_ini_dt) & datas_hist.le(ant_fim_dt)]
        if not df_ant.empty:
            ant_cons = int(df_ant["Qtde. Cons."].sum())
            ant_prod = int(df_ant["Qtde. Prod."].sum())
            ant_conv = (ant_prod / ant_cons) if ant_cons > 0 else 0.0
            diff_c_ant = tot_cons - ant_cons
            diff_p_ant = tot_prod - ant_prod
            diff_conv_ant = eficiencia_media - ant_conv
            pct_c_ant = CalculosConsultivo.variacao(tot_cons, ant_cons)
            pct_p_ant = CalculosConsultivo.variacao(tot_prod, ant_prod)
            pct_conv_ant = CalculosConsultivo.variacao(eficiencia_media, ant_conv)
            ant_txt = f"{formatar_data_brasileira(ant_ini_dt)} a {formatar_data_brasileira(ant_fim_dt)}"

            injetar_css_delta_cards()
            st.markdown("<div style='height: 12px'></div>", unsafe_allow_html=True)
            d_c_cols = st.columns(3)
            render_delta_card(
                d_c_cols[0],
                "Δ Consultivos vs Janela Anterior",
                formatar_delta_inteiro_br(diff_c_ant, "cons."),
                valor_base=formatar_numero_br(ant_cons),
                valor_atual=formatar_numero_br(tot_cons),
                rotulo_base="Anterior",
                rotulo_atual="Atual",
                variacao_pct=formatar_variacao_pct_br(
                    pct_c_ant, atual=tot_cons, base=ant_cons
                ),
                direcao=(
                    "up"
                    if diff_c_ant > 0
                    else ("down" if diff_c_ant < 0 else "neutral")
                ),
                icone="📋",
                detalhe=f"Base anterior: {ant_txt}",
                num_base=ant_cons,
                num_atual=tot_cons,
            )
            render_delta_card(
                d_c_cols[1],
                "Δ Produtos vs Janela Anterior",
                formatar_delta_inteiro_br(diff_p_ant, "prod."),
                valor_base=formatar_numero_br(ant_prod),
                valor_atual=formatar_numero_br(tot_prod),
                rotulo_base="Anterior",
                rotulo_atual="Atual",
                variacao_pct=formatar_variacao_pct_br(
                    pct_p_ant, atual=tot_prod, base=ant_prod
                ),
                direcao=(
                    "up"
                    if diff_p_ant > 0
                    else ("down" if diff_p_ant < 0 else "neutral")
                ),
                icone="📦",
                detalhe=f"Mesh + TV Box + Virtua ({ant_txt})",
                num_base=ant_prod,
                num_atual=tot_prod,
            )
            render_delta_card(
                d_c_cols[2],
                "Δ Conversão vs Janela Anterior",
                formatar_delta_decimal_br(diff_conv_ant, 2, "x"),
                valor_base=f"{ant_conv:.2f}x".replace(".", ","),
                valor_atual=f"{eficiencia_media:.2f}x".replace(".", ","),
                rotulo_base="Anterior",
                rotulo_atual="Atual",
                variacao_pct=formatar_variacao_pct_br(
                    pct_conv_ant, atual=eficiencia_media, base=ant_conv
                ),
                direcao=(
                    "up"
                    if diff_conv_ant > 0
                    else ("down" if diff_conv_ant < 0 else "neutral")
                ),
                icone="🎯",
                detalhe="Variação de produtos comercializados por consultivo",
                num_base=ant_conv,
                num_atual=eficiencia_media,
            )

    # ── Projeção Fim do Mês (Seg-Sáb quando competência vigente em andamento) ──
    if fator_proj > 1.0:
        st.markdown("<div style='height: 16px'></div>", unsafe_allow_html=True)
        render_section_header(
            titulo="Projeção Fim do Mês",
            subtitulo=f"Ritmo atual baseado em {dias_passados} de {dias_totais} dias úteis (Seg-Sáb)",
            icone="📈",
        )
        p1, p2 = st.columns(2)
        delta_cons = CalculosConsultivo.variacao(proj_cons, tot_cons)
        trend_cons: TipoTrendType = (
            "up" if (delta_cons and delta_cons > 0) else "neutral"
        )
        render_kpi(
            p1,
            "Projeção Consultivos",
            f"{proj_cons:,}".replace(",", "."),
            "Estimativa fechamento",
            tema="azul",
            icone="🚀",
            delta=f"+{delta_cons:.0f}% vs atual" if delta_cons else "",
            delta_tipo=trend_cons,
        )
        delta_prod = CalculosConsultivo.variacao(proj_prod, tot_prod)
        trend_prod: TipoTrendType = (
            "up" if (delta_prod and delta_prod > 0) else "neutral"
        )
        render_kpi(
            p2,
            "Projeção Produtos",
            f"{proj_prod:,}".replace(",", "."),
            "Estimativa fechamento",
            tema="laranja",
            icone="🎯",
            delta=f"+{delta_prod:.0f}% vs atual" if delta_prod else "",
            delta_tipo=trend_prod,
        )

    st.markdown("<div style='height: 24px'></div>", unsafe_allow_html=True)

    # ── Evolução Histórica Mensal (Histórico Consultivo por Competência) ──
    col_evo_hdr, col_evo_opt = st.columns([3.2, 1.4])
    with col_evo_hdr:
        render_section_header(
            titulo="Evolução Histórica Mensal",
            subtitulo="Série histórica por competência de Consultivos, Produtos e Mix (Mesh, TV Box e Virtua)",
            icone="🗓️",
        )
    with col_evo_opt:
        escopo_evolucao = st.radio(
            "Escopo da série mensal",
            options=["Histórico completo", "Período filtrado"],
            horizontal=True,
            key="cons_escopo_evolucao",
            help="Histórico completo exibe todas as competências importadas respeitando Base e Monitor.",
        )

    fonte_mensal = (
        df_hist_filtrado
        if escopo_evolucao == "Histórico completo"
        else df_f.dropna(subset=["DATA"])
    )
    df_mensal = preparar_evolucao_mensal_consultivo(fonte_mensal)

    if not df_mensal.empty:
        ch1, ch2 = st.columns(2)
        with ch1:
            st.markdown("##### Consultivos & Produtos por Competência")
            fig_evol = go.Figure()
            fig_evol.add_trace(
                go.Bar(
                    x=df_mensal["Competência"],
                    y=df_mensal["Total Consultivos"],
                    name="Total Consultivos",
                    marker_color=Cores.PRIMARIA,
                    text=df_mensal["Total Consultivos"].map(
                        lambda v: (
                            f"{int(v):,}".replace(",", ".") if pd.notna(v) else "0"
                        )
                    ),
                    textposition="outside",
                )
            )
            fig_evol.add_trace(
                go.Scatter(
                    x=df_mensal["Competência"],
                    y=df_mensal["Total Produtos"],
                    name="Total Produtos",
                    mode="lines+markers+text",
                    line={"color": Cores.SECUNDARIA, "width": 3},
                    marker={"size": 8, "color": Cores.SECUNDARIA},
                    text=df_mensal["Total Produtos"].map(
                        lambda v: (
                            f"{int(v):,}".replace(",", ".") if pd.notna(v) else "0"
                        )
                    ),
                    textposition="top center",
                )
            )
            _aplicar_layout_grafico_consultivo(
                fig_evol, dark_mode=dark_mode, height=360
            )
            max_y = max(
                int(df_mensal["Total Consultivos"].max()),
                int(df_mensal["Total Produtos"].max()),
                1,
            )
            fig_evol.update_yaxes(range=[0, max_y * 1.22])
            st.plotly_chart(fig_evol, width="stretch")

        with ch2:
            st.markdown("##### Evolução do Mix (Mesh, TV Box e Virtua)")
            fig_mix = go.Figure()
            for nome_mix, cor_mix in (
                ("Mesh", Cores.SUCESSO),
                ("TV Box", Cores.ROXO),
                ("Virtua", "#0EA5E9"),
            ):
                fig_mix.add_trace(
                    go.Bar(
                        x=df_mensal["Competência"],
                        y=df_mensal[nome_mix],
                        name=nome_mix,
                        marker_color=cor_mix,
                    )
                )
            fig_mix.update_layout(barmode="stack")
            _aplicar_layout_grafico_consultivo(fig_mix, dark_mode=dark_mode, height=360)
            st.plotly_chart(fig_mix, width="stretch")

        with st.expander(
            "📋 Ver tabela consolidada por competência mensal", expanded=False
        ):
            tabela_mensal_exib = df_mensal.drop(columns=["period"]).copy()
            st.markdown(
                gerar_html_tabela_cons(tabela_mensal_exib, usar_vendedor=True),
                unsafe_allow_html=True,
            )
    else:
        render_insight(
            "Não há datas válidas suficientes para compor a série histórica mensal neste recorte.",
            tipo="info",
        )

    st.markdown("<div style='height: 20px'></div>", unsafe_allow_html=True)

    # ── Visão Consolidada (Monitor vs Detalhar por Técnico) ──
    col_tit, col_chk = st.columns([3.5, 1])
    with col_tit:
        render_section_header(
            titulo="Visão Consolidada",
            subtitulo="Acompanhamento detalhado de entregas e projeções contra metas mensais",
            icone="📋",
        )
    with col_chk:
        st.markdown("<div style='height: 18px'></div>", unsafe_allow_html=True)
        usar_vendedor = st.toggle(
            "Detalhar por Técnico",
            value=False,
            key="cons_toggle_vendedor",
        )

    df_ranking = preparar_ranking(df_f, usar_vendedor, fator_proj)
    meta_txt = (
        f"Meta batida (≥ {CONFIG_CONSULTIVO.meta_mensal_produtos_tecnico} Produtos por Técnico)"
        if usar_vendedor
        else f"Meta batida (≥ {CONFIG_CONSULTIVO.meta_mensal_monitor} por Monitor)"
    )
    st.markdown(
        f"""
        <div style="display:flex; gap:18px; flex-wrap:wrap; margin-bottom:12px; font-size:12px; color:#64748B; font-weight:600;">
            <span style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; background:#DCFCE7; border:1px solid #166534; border-radius:3px;"></span> {meta_txt}</span>
            <span style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; background:#FEE2E2; border:1px solid #991B1B; border-radius:3px;"></span> Abaixo da meta</span>
            <span style="display:flex; align-items:center; gap:6px;"><span style="width:12px; height:12px; background:#FFFBEB; border:1px dashed #F59E0B; border-radius:3px;"></span> Colunas de Projeção</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_tabela_cons(df_ranking, usar_vendedor=usar_vendedor)

    st.markdown("<div style='height: 20px'></div>", unsafe_allow_html=True)

    # ── Abas Analíticas Inferiores ──
    aba_graf, aba_zeros, aba_meta_diaria = st.tabs(
        [
            "📈 Desempenho e Matriz",
            "🚫 Equipes sem Consultivos",
            "📅 Meta Diária por Monitor",
        ]
    )

    with aba_graf:
        df_prod_vendedores = (
            df_f.groupby(["VENDEDOR", "Monitor", "Base"], dropna=False)
            .agg(
                {
                    "Qtde. Cons.": "sum",
                    "Qtde. Prod.": "sum",
                }
            )
            .reset_index()
        )
        df_ativos_graf = df_prod_vendedores[
            df_prod_vendedores["Qtde. Cons."] > 0
        ].copy()

        if df_ativos_graf.empty:
            render_insight(
                "Não há dados produtivos para gerar os gráficos neste período.",
                tipo="info",
            )
        else:
            cg1, cg2 = st.columns(2)
            with cg1:
                st.markdown("##### Top 10 Equipes — Consultivos e Produtos")
                top10 = df_ativos_graf.nlargest(10, "Qtde. Cons.").sort_values(
                    "Qtde. Cons.", ascending=True
                )
                fig_bar = go.Figure()
                fig_bar.add_trace(
                    go.Bar(
                        x=top10["Qtde. Cons."],
                        y=top10["VENDEDOR"],
                        orientation="h",
                        name="Total Consultivos",
                        marker_color=Cores.PRIMARIA,
                        text=top10["Qtde. Cons."],
                        textposition="outside",
                    )
                )
                fig_bar.add_trace(
                    go.Bar(
                        x=top10["Qtde. Prod."],
                        y=top10["VENDEDOR"],
                        orientation="h",
                        name="Total Produtos",
                        marker_color=Cores.SECUNDARIA,
                        text=top10["Qtde. Prod."],
                        textposition="outside",
                    )
                )
                fig_bar.update_layout(barmode="group")
                _aplicar_layout_grafico_consultivo(
                    fig_bar, dark_mode=dark_mode, height=420
                )
                max_x = max(
                    int(top10["Qtde. Cons."].max()),
                    int(top10["Qtde. Prod."].max()),
                    1,
                )
                fig_bar.update_xaxes(range=[0, max_x * 1.2])
                st.plotly_chart(fig_bar, width="stretch")

            with cg2:
                st.markdown("##### Matriz de Eficiência (Consultivos vs Produtos)")
                fig_scat = px.scatter(
                    df_ativos_graf,
                    x="Qtde. Cons.",
                    y="Qtde. Prod.",
                    color="Base",
                    hover_name="VENDEDOR",
                    hover_data=["Monitor"],
                    size="Qtde. Prod.",
                    size_max=18,
                    color_discrete_sequence=[
                        Cores.PRIMARIA,
                        Cores.SECUNDARIA,
                        Cores.SUCESSO,
                        Cores.ROXO,
                        "#0EA5E9",
                        "#EC4899",
                    ],
                )
                if (
                    len(df_ativos_graf) >= 2
                    and df_ativos_graf["Qtde. Cons."].nunique() >= 2
                ):
                    x_vals = df_ativos_graf["Qtde. Cons."].to_numpy(dtype=float)
                    y_vals = df_ativos_graf["Qtde. Prod."].to_numpy(dtype=float)
                    coef = np.polyfit(x_vals, y_vals, 1)
                    x_line = np.linspace(float(x_vals.min()), float(x_vals.max()), 30)
                    y_line = coef[0] * x_line + coef[1]
                    fig_scat.add_trace(
                        go.Scatter(
                            x=x_line,
                            y=y_line,
                            mode="lines",
                            name="Tendência linear",
                            line={"color": "#94A3B8", "dash": "dash", "width": 2},
                        )
                    )
                _aplicar_layout_grafico_consultivo(
                    fig_scat, dark_mode=dark_mode, height=420
                )
                st.plotly_chart(fig_scat, width="stretch")

    with aba_zeros:
        df_por_equipe = (
            df_f.groupby(
                ["VENDEDOR", "LOGIN NETSALES", "Monitor", "Base", "U.N.", "Situação"],
                dropna=False,
            )["Qtde. Cons."]
            .sum()
            .reset_index()
        )
        df_zerados = (
            df_por_equipe[df_por_equipe["Qtde. Cons."] == 0]
            .drop(columns=["Qtde. Cons."])
            .sort_values(["Base", "Monitor", "VENDEDOR"])
            .reset_index(drop=True)
        )

        if df_zerados.empty:
            render_insight(
                "Excelente! Todas as equipes listadas realizaram ao menos um consultivo neste período.",
                tipo="ok",
            )
        else:
            render_insight(
                f"Existem **{len(df_zerados)} equipes** com zero consultivos registrados no período selecionado "
                "(cruzamento direto com colaboradores ATIVOS de lista_ativos).",
                tipo="alerta",
            )
            st.markdown(
                gerar_html_tabela_cons(df_zerados, usar_vendedor=True),
                unsafe_allow_html=True,
            )

    with aba_meta_diaria:
        resumo_diario = preparar_resumo_diario_monitor(
            df_f,
            meta_diaria=CONFIG_CONSULTIVO.meta_diaria_consultivos,
        )
        if resumo_diario.empty:
            render_insight(
                "Não há movimentação diária datada para apurar a meta diária por Monitor neste recorte.",
                tipo="info",
            )
        else:
            meta_acum = calcular_meta_acumulada_monitor(
                resumo_diario,
                meta_diaria=CONFIG_CONSULTIVO.meta_diaria_consultivos,
            ).rename(
                columns={
                    "Dias_Ativos": "Dias Ativos",
                    "Consultivos_Acumulados": "Total Consultivos",
                    "Produtos_Acumulados": "Total Produtos",
                    "Dias_Meta_Batida": "Dias c/ Meta Batida",
                }
            )
            st.markdown(
                f"##### Acumulado por Monitor (Meta operacional: {CONFIG_CONSULTIVO.meta_diaria_consultivos} consultivos/dia ativo)"
            )
            st.markdown(
                gerar_html_tabela_cons(meta_acum, usar_vendedor=True),
                unsafe_allow_html=True,
            )
            with st.expander("📅 Ver detalhamento diário por Monitor", expanded=False):
                diario_exib = resumo_diario.drop(columns=["Data_Ref"]).copy()
                st.markdown(
                    gerar_html_tabela_cons(diario_exib, usar_vendedor=True),
                    unsafe_allow_html=True,
                )

    st.markdown("<div style='height: 16px'></div>", unsafe_allow_html=True)

    # ── Exportação Segura CSV ──
    csv_bytes = sanitizar_csv_exportacao(df_f)
    st.download_button(
        label="📥 Exportar Base Filtrada (CSV)",
        data=csv_bytes,
        file_name=f"relatorio_consultivos_{date.today().strftime('%d_%m_%Y')}.csv",
        mime="text/csv",
        key="cons_btn_export_csv",
    )
