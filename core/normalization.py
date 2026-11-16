"""Normalização de textos, datas, pontos, contratos, WOs e cabeçalhos."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROD = "Prod"
GPON = "Gpon"
ORIGINS = (PROD, GPON)
DEMO_SOURCE = "dados_demonstracao"
DEFAULT_ROSTER_SHEET_ID = "1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg"
DEFAULT_CONSULTIVO_FOLDER_ID = "1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2"
ROSTER_METADATA_SCOPE = "__roster_sheet__"
CONSULTIVO_PRODUCT_REGEX = re.compile(r"\b\d{9,12}\b")
_CONSULTIVO_EMPTY_RE = re.compile(
    r"^(?:-|nan|none|na|n/a|<na>|nat|null)$", re.IGNORECASE
)
_CONSULTIVO_DATE_TOKEN_RE = re.compile(
    r"^(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?$"
)
_NETSALES_EXPORT_TS_RE = re.compile(
    r"numeros[-_ ]tabulacao[-_ ]20\d{2}[-_.]\d{1,2}[-_.]\d{1,2}(?:[-_.]\d{1,2}){2,3}",
    re.IGNORECASE,
)
ROSTER_ACTIVE_TAB = "lista_ativos"
ROSTER_TERMINATED_TAB = "desligados"
ROSTER_STATUS_ORDER = (
    "ATIVO",
    "FÉRIAS",
    "AFASTADO",
    "INOPERANTE",
    "DESLIGADO",
    "Não cadastrado",
)

RECORD_COLUMNS = [
    "technician",
    "reference_date",
    "source_sheet",
    "project",
    "contract",
    "wo",
    "points",
    "source_file",
    "source_row",
]

TECHNICIAN_ALIASES = {
    "tecnico",
    "nomtecnico",
    "nometecnico",
    "nomeequipe",
    "colaborador",
    "nomecolaborador",
    "funcionario",
    "nomefuncionario",
    "nome",
    "responsavel",
    "executor",
}
POINTS_ALIASES = {
    "pontos",
    "ponto",
    "pontuacao",
    "pontuacaototal",
    "totalpontos",
    "qtdpontos",
    "quantidadepontos",
    "pontosrealizados",
}
PROJECT_ALIASES = {
    "projeto",
    "nomeprojeto",
    "projetonome",
    "codprojeto",
    "codigoprojeto",
    "idprojeto",
    "projetoid",
}
CONTRACT_ALIASES = {
    "contrato",
    "contract",
    "codigocontrato",
    "codigodocontrato",
    "numerocontrato",
    "numerodocontrato",
    "numero_contrato",
    "numcontrato",
    "ncontrato",
    "idcontrato",
    "contratoid",
}
WO_ALIASES = {
    "wo",
    "workorder",
    "work_order",
    "ordemservico",
    "ordemdeservico",
    "ordem_de_servico",
    "os",
    "numero_wo",
    "numerowo",
    "wo_number",
}
QTD_CONTRATO_ALIASES = {
    "qtdecontrato",
    "qtdcontrato",
    "quantidadecontrato",
    "qtdecontratos",
    "qtdcontratos",
    "contratosqtde",
    "contratosqtd",
}
DATE_ALIASES = {
    "data",
    "dataproducao",
    "datareferencia",
    "datafechamento",
    "competencia",
    "mes",
    "mesano",
    "periodo",
    "referencia",
}
DATE_COLUMN_PREFERENCE = (
    "dataagendamento",
    "data",
    "dataproducao",
    "dataatendimento",
    "datareferencia",
    "datafechamento",
    "competencia",
    "mes",
    "mesano",
    "periodo",
    "referencia",
)
ROSTER_RE_ALIASES = {"re", "matricula", "codequipe", "registro", "recolaborador"}
ROSTER_LOGIN_ALIASES = {"login", "codauxequipe", "usuario", "logintecnico"}
ROSTER_MONITOR_ALIASES = {"monitor", "supervisor", "gestor", "lider"}
ROSTER_UN_ALIASES = {"un", "unidadenegocio", "unidade"}
ROSTER_BASE_ALIASES = {"base", "operacao", "regional"}
ROSTER_STATUS_ALIASES = {"situacao", "status", "condicao"}
ROSTER_MODIFIED_ALIASES = {"ultimamodificacao", "atualizadoem", "modificacao"}
ROSTER_TERM_DATE_ALIASES = {"datadesligamento", "desligamento"}
ROSTER_TERM_REASON_ALIASES = {"motivo", "motivodesligamento"}

MONTHS_PT = {
    "jan": 1,
    "janeiro": 1,
    "fev": 2,
    "fevereiro": 2,
    "mar": 3,
    "marco": 3,
    "abr": 4,
    "abril": 4,
    "mai": 5,
    "maio": 5,
    "jun": 6,
    "junho": 6,
    "jul": 7,
    "julho": 7,
    "ago": 8,
    "agosto": 8,
    "set": 9,
    "setembro": 9,
    "out": 10,
    "outubro": 10,
    "nov": 11,
    "novembro": 11,
    "dez": 12,
    "dezembro": 12,
}

MONTHS_SHORT = [
    "jan",
    "fev",
    "mar",
    "abr",
    "mai",
    "jun",
    "jul",
    "ago",
    "set",
    "out",
    "nov",
    "dez",
]

CONTRACT_PLACEHOLDERS = {
    "semcontrato",
    "seminformacao",
    "naoinformado",
    "naoinformacao",
    "naoinformacaocontrato",
    "notavailable",
    "null",
    "na",
    "nan",
    "none",
    "nat",
}


def normalize_text(value: object) -> str:
    """Remove acentos e caracteres não alfanuméricos para comparar cabeçalhos."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def clean_technician(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "semtecnico"}:
        return ""
    words = text.title().split(" ")
    particles = {"Da", "De", "Do", "Das", "Dos", "E"}
    return " ".join(
        word.lower() if index > 0 and word in particles else word
        for index, word in enumerate(words)
    )


def clean_project(value: object) -> str:
    """Normaliza o rótulo do projeto, mantendo códigos e capitalização de origem."""
    if value is None or value is pd.NA or value is pd.NaT:
        return "Sem projeto"
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "semprojeto"}:
        return "Sem projeto"
    return text


def extract_spreadsheet_id(value: str | None) -> str:
    """Extrai o ID de uma planilha Google a partir da URL completa ou do ID puro."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{10,}", text):
        return text
    return ""


def extract_drive_folder_id(value: str | None) -> str:
    """Extrai o ID de uma pasta do Google Drive a partir da URL ou do ID puro."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"/folders/([a-zA-Z0-9-_]+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{10,}", text):
        return text
    return ""


def clean_code(value: object) -> str:
    """Normaliza matrículas/RE e logins, removendo sufixo ``.0`` de leitura numérica."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip()
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "null"}:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def clean_roster_status(value: object, *, default: str = "ATIVO") -> str:
    """Padroniza a situação cadastral do técnico (ATIVO, FÉRIAS, AFASTADO, etc.)."""
    if value is None or value is pd.NA or value is pd.NaT:
        return default
    text = re.sub(r"\s+", " ", str(value)).strip()
    norm = normalize_text(text)
    if not norm or norm in {"nan", "none", "nat", "null"}:
        return default
    canonical = {
        "ativo": "ATIVO",
        "ativos": "ATIVO",
        "ferias": "FÉRIAS",
        "afastado": "AFASTADO",
        "afastada": "AFASTADO",
        "inoperante": "INOPERANTE",
        "desligado": "DESLIGADO",
        "desligada": "DESLIGADO",
        "inativo": "DESLIGADO",
    }
    return canonical.get(norm, text.upper())


def _clean_optional_label(
    value: object, placeholder: str, *, upper: bool = False
) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return placeholder
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "null"}:
        return placeholder
    return text.upper() if upper else text


def _clean_optional_date_str(value: object) -> str:
    parsed = parse_reference_date(value)
    if parsed is not None:
        return str(parsed.strftime("%Y-%m-%d"))
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "null"}:
        return ""
    return text


def clean_contract(value: object) -> str | None:
    """Normaliza o número ou nome do contrato."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {
        "nan",
        "none",
        "nat",
        "semcontrato",
        "null",
    }:
        return None
    return text


def is_valid_contract(value: object) -> bool:
    """Indica se o valor é um identificador de contrato real."""
    contrato = clean_contract(value)
    return contrato is not None and normalize_text(contrato) not in (
        CONTRACT_PLACEHOLDERS
    )


def parse_contract_flag(value: object) -> int | None:
    """Interpreta o flag da coluna ``Qtde_Contrato`` de uma linha."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return 1 if float(value) == 1 else 0 if float(value) == 0 else None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return 1 if number == 1 else 0 if number == 0 else None


def _map_repeated_text(
    values: pd.Series,
    transform: Callable[[Any], Any],
    *,
    null_value: str | int | float | bool | None,
) -> pd.Series:
    """Aplica transformações textuais uma vez por valor distinto."""
    if pd.api.types.infer_dtype(values, skipna=True) != "string":
        return values.map(transform)
    mapped = {value: transform(value) for value in values.dropna().unique()}
    return values.map(mapped).fillna(null_value)


def add_contracts_qty(
    frame: pd.DataFrame,
    *,
    contract_validator: Callable[[object], bool] | None = None,
) -> pd.DataFrame:
    """Adiciona a coluna ``contracts_qty`` (Qtde_Contrato) ao frame."""
    if frame.empty:
        frame["contracts_qty"] = pd.Series(dtype="int64")
        return frame
    if "source_file" not in frame.columns or "contract" not in frame.columns:
        frame["contracts_qty"] = 0
        return frame
    validator = contract_validator or is_valid_contract
    mascara_valida = _map_repeated_text(
        frame["contract"], validator, null_value=False
    ).astype(bool)
    validos = frame.loc[mascara_valida]
    contagem = (
        validos.groupby("source_file")["contract"].nunique().astype(int)
        if not validos.empty
        else pd.Series(dtype="int64")
    )
    if "contract_flag" in frame.columns:
        flags = pd.to_numeric(validos["contract_flag"], errors="coerce")
        if flags.notna().any():
            soma_flags = flags.groupby(validos["source_file"]).sum().astype(int)
            com_flags = flags.notna().groupby(validos["source_file"]).any()
            contagem = soma_flags[com_flags].combine_first(contagem)
    frame["contracts_qty"] = frame["source_file"].map(contagem).fillna(0).astype(int)
    return frame


def clean_wo(value: object) -> str | None:
    """Normaliza a identificação da WO/OS."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text or normalize_text(text) in {
        "nan",
        "none",
        "nat",
        "semwo",
        "semos",
        "null",
    }:
        return None
    return text


def _contract_or_placeholder(value: object) -> str:
    return clean_contract(value) or "Sem contrato"


def _wo_or_placeholder(value: object) -> str:
    return clean_wo(value) or "Sem WO"


def parse_points(value: object) -> float | None:
    """Converte números brasileiros e internacionais sem perder precisão."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if pd.notna(value) else None

    text = str(value).strip()
    if not text:
        return None
    text = re.sub(r"(?i)pontos?", "", text).strip()
    text = text.replace("R$", "").replace(" ", "")
    text = re.sub(r"[^0-9,.-]", "", text)
    if not text or text in {"-", ",", "."}:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")

    try:
        return float(text)
    except ValueError:
        return None


def parse_reference_date(value: object) -> pd.Timestamp | None:
    """Interpreta datas completas, competências mensais e datas seriais do Excel."""
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        timestamp = pd.Timestamp(value)
        return timestamp.normalize() if pd.notna(timestamp) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if 1 <= float(value) <= 100000:
            ts_excel = pd.to_datetime(
                float(value), unit="D", origin="1899-12-30", errors="coerce"
            )
            return ts_excel.normalize() if isinstance(ts_excel, pd.Timestamp) else None
        return None

    text = str(value).strip()
    if not text:
        return None

    match = re.fullmatch(
        r"(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?"
        r"(?:[T\s]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
        text,
    )
    if match:
        year, month, day = match.groups()
        try:
            return pd.Timestamp(int(year), int(month), int(day or 1))
        except ValueError:
            return None

    br_match = re.fullmatch(
        r"(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2}|\d{2})"
        r"(?:[T\s]+\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
        text,
    )
    if br_match:
        day_s, month_s, year_s = br_match.groups()
        yr = int(year_s)
        yr = yr + 2000 if yr < 100 else yr
        try:
            return pd.Timestamp(yr, int(month_s), int(day_s))
        except ValueError:
            return None

    match = re.fullmatch(r"(\d{1,2})[-/.](20\d{2})", text)
    if match:
        month, year = match.groups()
        try:
            return pd.Timestamp(int(year), int(month), 1)
        except ValueError:
            return None

    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    month_match = re.search(
        r"\b(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\b",
        normalized,
    )
    year_match = re.search(r"\b(20\d{2}|\d{2})\b", normalized)
    if month_match and year_match:
        month = MONTHS_PT[month_match.group(1)]
        year = int(year_match.group(1))
        year = year + 2000 if year < 100 else year
        return pd.Timestamp(year, month, 1)

    ts_parsed = pd.to_datetime(text, dayfirst=True, format="mixed", errors="coerce")
    return ts_parsed.normalize() if isinstance(ts_parsed, pd.Timestamp) else None


def infer_date_from_filename(filename: str) -> pd.Timestamp | None:
    stem = re.sub(r"\s*\[[^\]]+\]\s*$", "", Path(filename).stem).strip()
    match = re.search(r"(?<!\d)(20\d{2})[-_.](0?[1-9]|1[0-2])(?!\d)", stem)
    if match:
        return pd.Timestamp(int(match.group(1)), int(match.group(2)), 1)
    match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[-_.](20\d{2})(?!\d)", stem)
    if match:
        return pd.Timestamp(int(match.group(2)), int(match.group(1)), 1)

    normalized = unicodedata.normalize("NFKD", stem.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    month_match = re.search(
        r"\b(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\b",
        normalized,
    )
    if month_match:
        remainder = (
            normalized[: month_match.start()] + " " + normalized[month_match.end() :]
        )
        year_match = re.search(r"(?<!\d)(20\d{2}|\d{2})(?!\d)", remainder)
        if year_match:
            month = MONTHS_PT[month_match.group(1)]
            year = int(year_match.group(1))
            year = year + 2000 if year < 100 else year
            if 2000 <= year <= 2099:
                return pd.Timestamp(year, month, 1)
    return None


def find_column(frame: pd.DataFrame, aliases: set[str]) -> str | None:
    normalized = {
        normalize_text(column): column
        for column in frame.columns
        if isinstance(column, str)
    }
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    for normalized_name, original in normalized.items():
        if any(len(alias) >= 6 and alias in normalized_name for alias in aliases):
            return original
    return None


def find_date_column(frame: pd.DataFrame) -> str | None:
    normalized = {
        normalize_text(column): column
        for column in frame.columns
        if isinstance(column, str)
    }
    for alias in DATE_COLUMN_PREFERENCE:
        if alias in normalized:
            return normalized[alias]
    return find_column(frame, DATE_ALIASES)


__all__ = [
    "PROD",
    "GPON",
    "ORIGINS",
    "DEMO_SOURCE",
    "DEFAULT_ROSTER_SHEET_ID",
    "DEFAULT_CONSULTIVO_FOLDER_ID",
    "ROSTER_METADATA_SCOPE",
    "CONSULTIVO_PRODUCT_REGEX",
    "ROSTER_ACTIVE_TAB",
    "ROSTER_TERMINATED_TAB",
    "ROSTER_STATUS_ORDER",
    "RECORD_COLUMNS",
    "TECHNICIAN_ALIASES",
    "POINTS_ALIASES",
    "PROJECT_ALIASES",
    "CONTRACT_ALIASES",
    "WO_ALIASES",
    "QTD_CONTRATO_ALIASES",
    "DATE_ALIASES",
    "DATE_COLUMN_PREFERENCE",
    "ROSTER_RE_ALIASES",
    "ROSTER_LOGIN_ALIASES",
    "ROSTER_MONITOR_ALIASES",
    "ROSTER_UN_ALIASES",
    "ROSTER_BASE_ALIASES",
    "ROSTER_STATUS_ALIASES",
    "ROSTER_MODIFIED_ALIASES",
    "ROSTER_TERM_DATE_ALIASES",
    "ROSTER_TERM_REASON_ALIASES",
    "MONTHS_PT",
    "MONTHS_SHORT",
    "CONTRACT_PLACEHOLDERS",
    "normalize_text",
    "clean_technician",
    "clean_project",
    "extract_spreadsheet_id",
    "extract_drive_folder_id",
    "clean_code",
    "clean_roster_status",
    "_clean_optional_label",
    "_clean_optional_date_str",
    "clean_contract",
    "is_valid_contract",
    "parse_contract_flag",
    "_map_repeated_text",
    "add_contracts_qty",
    "clean_wo",
    "_contract_or_placeholder",
    "_wo_or_placeholder",
    "parse_points",
    "parse_reference_date",
    "infer_date_from_filename",
    "find_column",
    "find_date_column",
]
