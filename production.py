"""Regras de negócio e persistência do histórico de produção.

O módulo não depende do Streamlit para facilitar testes e reutilização.
Cada linha importada é mantida em sua origem (Prod ou Gpon); os relatórios
fazem a agregação e calculam sempre Pontos Totais = Prod + Gpon.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PROD = "Prod"
GPON = "Gpon"
ORIGINS = (PROD, GPON)
DEMO_SOURCE = "dados_demonstracao"
DB_PATH = Path(os.getenv("PRODUCAO_DB_PATH", "data/producao.db"))
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
#: Coluna opcional de contagem de contratos exportada pelo sistema de origem:
#: traz ``1`` na primeira linha de cada contrato do arquivo e ``0`` nas demais.
#: É a fonte oficial de ``contracts_qty`` (soma por arquivo); arquivos sem a
#: coluna caem no fallback de contratos distintos (``nunique``).
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


def normalize_text(value: object) -> str:
    """Remove acentos e caracteres não alfanuméricos para comparar cabeçalhos."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def clean_technician(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or normalize_text(text) in {"nan", "none", "nat", "semtecnico"}:
        return ""
    # Padroniza apenas a caixa. Mantém partículas usuais em minúsculo.
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
        return parsed.strftime("%Y-%m-%d")
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


#: Valores normalizados que representam ausência de contrato (nunca um contrato).
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


def is_valid_contract(value: object) -> bool:
    """Indica se o valor é um identificador de contrato real.

    O marcador ``"Sem contrato"`` gravado pela importação (e variações vazias
    ou nulas) representa ausência: não pode entrar em contagens.
    """
    contrato = clean_contract(value)
    return contrato is not None and normalize_text(contrato) not in (
        CONTRACT_PLACEHOLDERS
    )


def parse_contract_flag(value: object) -> int | None:
    """Interpreta o flag da coluna ``Qtde_Contrato`` de uma linha.

    O export marca ``1`` na primeira linha de cada contrato do arquivo e ``0``
    nas demais. Devolve ``1``/``0`` para valores válidos e ``None`` quando a
    célula está vazia ou inválida (a linha não contribui para a soma).
    """
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
    values: pd.Series, transform: Callable[[object], object], *, null_value: object
) -> pd.Series:
    """Aplica transformações textuais uma vez por valor distinto.

    Os registros importados são textuais e frequentemente se repetem em muitas
    linhas. Para tipos mistos mantemos o mapeamento por linha, pois pandas pode
    considerar valores como 1 e 1.0 iguais apesar de seus textos diferentes.
    """
    if pd.api.types.infer_dtype(values, skipna=True) != "string":
        return values.map(transform)
    mapped = {value: transform(value) for value in values.dropna().unique()}
    return values.map(mapped).fillna(null_value)


def add_contracts_qty(frame: pd.DataFrame) -> pd.DataFrame:
    """Adiciona a coluna ``contracts_qty`` (Qtde_Contrato) ao frame.

    O valor repete, em todas as linhas de um arquivo, o total de contratos
    daquele arquivo. A fonte oficial é a soma dos flags da coluna
    ``Qtde_Contrato`` do export (``1`` na primeira linha de cada contrato);
    arquivos sem flags (coluna ausente ou toda vazia) caem no fallback de
    contratos distintos (``nunique``). Registros sem contrato não entram na
    contagem; arquivos sem nenhum contrato ficam com zero.
    """
    if frame.empty:
        frame["contracts_qty"] = pd.Series(dtype="int64")
        return frame
    if "source_file" not in frame.columns or "contract" not in frame.columns:
        frame["contracts_qty"] = 0
        return frame
    mascara_valida = _map_repeated_text(
        frame["contract"], is_valid_contract, null_value=False
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
            # Arquivos com flags usam a soma oficial; os demais mantêm o nunique.
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

    # Formatos aceitos: 1.234,56 | 1,234.56 | 1234,56 | 1.234.
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        # Vírgula é decimal no padrão utilizado pelas planilhas brasileiras.
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
            timestamp = pd.to_datetime(
                float(value), unit="D", origin="1899-12-30", errors="coerce"
            )
            return (
                timestamp.normalize() if isinstance(timestamp, pd.Timestamp) else None
            )
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

    timestamp = pd.to_datetime(text, dayfirst=True, format="mixed", errors="coerce")
    return timestamp.normalize() if isinstance(timestamp, pd.Timestamp) else None


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
    # Tolerância a cabeçalhos como "Pontos do técnico" sem aceitar nomes vagos.
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


def process_dataframe(
    frame: pd.DataFrame,
    origin: str,
    source_file: str,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> tuple[list[dict], list[str]]:
    """Valida e converte uma aba em registros normalizados.

    Linhas sem técnico são ignoradas (comuns em totais ao fim da planilha).
    Erros de pontos/data são relatados com o número da linha original.
    """
    if origin not in ORIGINS:
        raise ValueError("A origem deve ser Prod ou Gpon.")
    if frame.empty:
        return [], ["A aba está vazia."]

    technician_col = find_column(frame, TECHNICIAN_ALIASES)
    points_col = find_column(frame, POINTS_ALIASES)
    project_col = find_column(frame, PROJECT_ALIASES)
    contract_col = find_column(frame, CONTRACT_ALIASES)
    wo_col = find_column(frame, WO_ALIASES)
    qtd_contrato_col = find_column(frame, QTD_CONTRATO_ALIASES)
    date_col = find_date_column(frame)
    available = ", ".join(str(column) for column in frame.columns)
    if technician_col is None or points_col is None:
        missing = []
        if technician_col is None:
            missing.append("Técnico")
        if points_col is None:
            missing.append("Pontos")
        raise ValueError(
            f"Coluna(s) obrigatória(s) não encontrada(s): {', '.join(missing)}. "
            f"Colunas disponíveis: {available or 'nenhuma'}."
        )

    fallback_date = (
        pd.Timestamp(default_date).normalize()
        if default_date is not None
        else infer_date_from_filename(source_file)
    )
    if date_col is None and fallback_date is None:
        raise ValueError(
            "Inclua uma coluna Data/Competência, informe a competência padrão "
            "ou use o ano e mês no nome do arquivo (ex.: 2026-10.xlsx)."
        )

    records: list[dict] = []
    issues: list[str] = []
    selected_columns = [technician_col, points_col]
    date_position = None
    project_position = None
    contract_position = None
    wo_position = None
    qtd_contrato_position = None
    if date_col is not None:
        date_position = len(selected_columns) + 1
        selected_columns.append(date_col)
    if project_col is not None:
        project_position = len(selected_columns) + 1
        selected_columns.append(project_col)
    if contract_col is not None:
        contract_position = len(selected_columns) + 1
        selected_columns.append(contract_col)
    if wo_col is not None:
        wo_position = len(selected_columns) + 1
        selected_columns.append(wo_col)
    if qtd_contrato_col is not None:
        qtd_contrato_position = len(selected_columns) + 1
        selected_columns.append(qtd_contrato_col)

    invalid_flags = 0
    for row in frame[selected_columns].itertuples(index=True, name=None):
        index = row[0]
        excel_row = int(index) + 2 if isinstance(index, int) else len(records) + 2
        technician = clean_technician(row[1])
        if not technician:
            continue

        points = parse_points(row[2])
        if points is None:
            issues.append(f"Linha {excel_row}: pontos inválidos ({row[2]!r}).")
            continue
        date_value = row[date_position] if date_position is not None else None
        reference_date = (
            parse_reference_date(date_value) if date_col is not None else fallback_date
        )
        if reference_date is None:
            reference_date = fallback_date
        if reference_date is None:
            issues.append(f"Linha {excel_row}: data inválida ({date_value!r}).")
            continue

        contract_flag = None
        if qtd_contrato_position is not None:
            flag_value = row[qtd_contrato_position]
            contract_flag = parse_contract_flag(flag_value)
            if (
                contract_flag is None
                and not pd.isna(flag_value)
                and str(flag_value).strip()
            ):
                invalid_flags += 1

        records.append(
            {
                "technician": technician,
                "reference_date": reference_date.strftime("%Y-%m-%d"),
                "source_sheet": origin,
                "project": (
                    clean_project(row[project_position])
                    if project_position is not None
                    else "Sem projeto"
                ),
                "contract": _contract_or_placeholder(
                    row[contract_position] if contract_position is not None else None
                ),
                "wo": _wo_or_placeholder(
                    row[wo_position] if wo_position is not None else None
                ),
                "contract_flag": contract_flag,
                "points": float(points),
                "source_file": source_file,
                "source_row": excel_row,
            }
        )

    if invalid_flags:
        issues.append(
            f"{invalid_flags} valor(es) inválido(s) na coluna Qtde_Contrato "
            "(esperado 1 ou 0); essas linhas não entram na soma de contratos."
        )
    if not records and not issues:
        issues.append("Nenhuma linha com técnico e pontos válidos foi encontrada.")
    return records, issues


def read_csv(content: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = content.decode(encoding)
            headers = pd.read_csv(io.StringIO(text), sep=None, engine="python", nrows=0)
            contract_col = find_column(headers, CONTRACT_ALIASES)
            dtype = {contract_col: str} if contract_col is not None else None
            return pd.read_csv(
                io.StringIO(text), sep=None, engine="python", dtype=dtype
            )
        except (UnicodeDecodeError, pd.errors.ParserError) as error:
            last_error = error
    raise ValueError(f"Não foi possível ler o CSV: {last_error}")


def process_upload(
    filename: str,
    content: bytes,
    csv_origin: str = PROD,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> tuple[list[dict], list[str]]:
    """Lê um arquivo enviado e processa as abas Prod e Gpon encontradas."""
    suffix = Path(filename).suffix.lower()
    records: list[dict] = []
    issues: list[str] = []

    if suffix == ".csv":
        sheet_records, sheet_issues = process_dataframe(
            read_csv(content), csv_origin, filename, default_date
        )
        return sheet_records, sheet_issues

    if suffix not in {".xlsx", ".xls"}:
        raise ValueError("Formato não suportado. Use XLSX, XLS ou CSV.")

    try:
        workbook = pd.ExcelFile(io.BytesIO(content))
    except Exception as error:
        raise ValueError(f"Não foi possível abrir o arquivo Excel: {error}") from error

    sheets = {normalize_text(sheet): sheet for sheet in workbook.sheet_names}
    found = False
    for origin in ORIGINS:
        sheet_name = sheets.get(normalize_text(origin))
        if sheet_name is None:
            continue
        found = True
        # Detecta a linha do cabeçalho numa prévia pequena (10 linhas) e só
        # então lê a aba inteira uma única vez — evita até 10 leituras
        # completas de arquivos de vários MB por aba.
        header_row = None
        for candidate_row in range(10):
            preview = pd.read_excel(
                workbook, sheet_name=sheet_name, header=candidate_row, nrows=10
            )
            if (
                find_column(preview, TECHNICIAN_ALIASES) is not None
                and find_column(preview, POINTS_ALIASES) is not None
            ):
                header_row = candidate_row
                break
        frame = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            header=header_row if header_row is not None else 0,
        )
        sheet_records, sheet_issues = process_dataframe(
            frame, origin, filename, default_date
        )
        records.extend(sheet_records)
        issues.extend(f"{origin}: {issue}" for issue in sheet_issues)

    if not found:
        raise ValueError(
            "O arquivo precisa conter uma aba chamada Prod e/ou Gpon. "
            f"Abas encontradas: {', '.join(map(str, workbook.sheet_names))}."
        )
    return records, issues


def process_roster_dataframe(
    frame: pd.DataFrame,
    *,
    source_tab: str = ROSTER_ACTIVE_TAB,
) -> tuple[list[dict], list[str]]:
    """Converte uma aba da planilha cadastral (lista_ativos ou desligados) em registros."""
    if frame.empty:
        return [], [f"A aba {source_tab} está vazia."]

    tech_col = find_column(frame, TECHNICIAN_ALIASES)
    if tech_col is None:
        available = ", ".join(str(col) for col in frame.columns)
        raise ValueError(
            f"Coluna de técnico não encontrada na aba {source_tab}. "
            f"Colunas disponíveis: {available or 'nenhuma'}."
        )

    re_col = find_column(frame, ROSTER_RE_ALIASES)
    login_col = find_column(frame, ROSTER_LOGIN_ALIASES)
    monitor_col = find_column(frame, ROSTER_MONITOR_ALIASES)
    un_col = find_column(frame, ROSTER_UN_ALIASES)
    base_col = find_column(frame, ROSTER_BASE_ALIASES)
    status_col = find_column(frame, ROSTER_STATUS_ALIASES)
    modified_col = find_column(frame, ROSTER_MODIFIED_ALIASES)
    term_date_col = find_column(frame, ROSTER_TERM_DATE_ALIASES)
    term_reason_col = find_column(frame, ROSTER_TERM_REASON_ALIASES)

    default_status = (
        "DESLIGADO"
        if normalize_text(source_tab) == normalize_text(ROSTER_TERMINATED_TAB)
        else "ATIVO"
    )
    rows: list[dict] = []
    issues: list[str] = []
    for _, series in frame.iterrows():
        technician = clean_technician(series.get(tech_col))
        tech_key = normalize_text(technician)
        if not technician or not tech_key:
            continue
        monitor_raw = series.get(monitor_col) if monitor_col is not None else None
        monitor = clean_technician(monitor_raw) or "Sem monitor"
        rows.append(
            {
                "technician_key": tech_key,
                "technician": technician,
                "re_code": clean_code(series.get(re_col)) if re_col is not None else "",
                "login": (
                    clean_code(series.get(login_col)).upper()
                    if login_col is not None
                    else ""
                ),
                "monitor": monitor,
                "un": (
                    _clean_optional_label(series.get(un_col), "Sem U.N.", upper=True)
                    if un_col is not None
                    else "Sem U.N."
                ),
                "base": (
                    _clean_optional_label(series.get(base_col), "Sem base", upper=True)
                    if base_col is not None
                    else "Sem base"
                ),
                "status": clean_roster_status(
                    series.get(status_col) if status_col is not None else None,
                    default=default_status,
                ),
                "source_tab": source_tab,
                "last_modified": (
                    _clean_optional_date_str(series.get(modified_col))
                    if modified_col is not None
                    else ""
                ),
                "termination_date": (
                    _clean_optional_date_str(series.get(term_date_col))
                    if term_date_col is not None
                    else ""
                ),
                "termination_reason": (
                    _clean_optional_label(series.get(term_reason_col), "")
                    if term_reason_col is not None
                    else ""
                ),
            }
        )
    if not rows:
        issues.append(f"Nenhum técnico válido encontrado na aba {source_tab}.")
    return rows, issues


def process_roster_workbook(
    content: bytes,
    *,
    filename: str = "lista_ativos.xlsx",
) -> tuple[list[dict], list[str]]:
    """Lê a planilha cadastral (XLSX com lista_ativos/desligados ou CSV)."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return process_roster_dataframe(read_csv(content), source_tab=ROSTER_ACTIVE_TAB)

    try:
        workbook = pd.ExcelFile(io.BytesIO(content))
    except Exception as error:
        raise ValueError(
            f"Não foi possível abrir a planilha cadastral ({filename}): {error}"
        ) from error

    normalized_sheets = {normalize_text(sheet): sheet for sheet in workbook.sheet_names}
    target_tabs: list[tuple[str, str]] = []
    for canonical in (ROSTER_ACTIVE_TAB, ROSTER_TERMINATED_TAB):
        key = normalize_text(canonical)
        if key in normalized_sheets:
            target_tabs.append((canonical, normalized_sheets[key]))

    if not target_tabs and workbook.sheet_names:
        target_tabs.append((ROSTER_ACTIVE_TAB, str(workbook.sheet_names[0])))

    by_key: dict[str, dict] = {}
    issues: list[str] = []
    for canonical, actual_sheet in target_tabs:
        frame = pd.read_excel(workbook, sheet_name=actual_sheet)
        try:
            tab_rows, tab_issues = process_roster_dataframe(frame, source_tab=canonical)
        except ValueError as error:
            issues.append(str(error))
            continue
        issues.extend(tab_issues)
        for item in tab_rows:
            # A aba lista_ativos tem precedência sobre desligados em caso de homônimo/readmissão.
            if item["technician_key"] not in by_key or canonical == ROSTER_ACTIVE_TAB:
                by_key[item["technician_key"]] = item

    if not by_key:
        raise ValueError(
            "Nenhum colaborador válido encontrado na planilha cadastral "
            f"({', '.join(map(str, workbook.sheet_names))})."
        )
    return list(by_key.values()), issues


def _normalize_consultivo_series(serie: pd.Series) -> pd.Series:
    texto = serie.fillna("").astype(str).str.strip()
    return texto.where(~texto.str.match(_CONSULTIVO_EMPTY_RE), "")


_CONSULTIVO_DATE_FORMATS_BR: tuple[str, ...] = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d/%m/%y %H:%M:%S",
    "%d/%m/%y %H:%M",
    "%d/%m/%y",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y",
    "%d-%m-%y",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d",
)


def converter_data_consultivo_br(serie: pd.Series) -> pd.Series:
    """Converte série de datas priorizando sempre DIA/MÊS/ANO sem inverter ISO YYYY-MM-DD."""
    if serie is None or len(serie) == 0:
        return pd.Series(dtype="datetime64[ns]")

    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce").astype("datetime64[ns]")

    resultado = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")

    try:
        numericos = pd.to_numeric(serie, errors="coerce")
    except (TypeError, ValueError):
        numericos = pd.Series(float("nan"), index=serie.index)
    mask_serial = numericos.between(20_000, 80_000)
    if mask_serial.any():
        resultado.loc[mask_serial] = pd.to_datetime(
            numericos[mask_serial], unit="D", origin="1899-12-30", errors="coerce"
        ).astype("datetime64[ns]")

    textos = serie.astype(str).str.strip()
    textos = textos.mask(textos.isin(["", "nan", "None", "NaT", "NaN", "-", "NULL"]))
    pendentes = resultado.isna() & textos.notna()

    for fmt in _CONSULTIVO_DATE_FORMATS_BR:
        if not pendentes.any():
            break
        parsed = pd.to_datetime(textos[pendentes], format=fmt, errors="coerce")
        ok = parsed.notna()
        if ok.any():
            idx = parsed.index[ok]
            resultado.loc[idx] = parsed.loc[idx].astype("datetime64[ns]")
            pendentes.loc[idx] = False

    if pendentes.any():
        re_parsed = textos[pendentes].map(parse_reference_date)
        parsed_fb = pd.to_datetime(re_parsed, errors="coerce")
        ok_fb = parsed_fb.notna()
        if ok_fb.any():
            idx_fb = parsed_fb.index[ok_fb]
            resultado.loc[idx_fb] = parsed_fb.loc[idx_fb].astype("datetime64[ns]")

    return resultado


def _separar_internet_tv(internet_bruta: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Separa TV embutida depois do ponto em PLANO INTERNET."""
    bruto = _normalize_consultivo_series(internet_bruta)
    partes = bruto.str.split(".", n=1, expand=True)
    primeira = _normalize_consultivo_series(partes[0])
    if partes.shape[1] < 2:
        return primeira, pd.Series("", index=bruto.index, dtype="object")

    segunda = _normalize_consultivo_series(partes[1])
    tem_letra = segunda.str.contains(r"[A-Za-z]", na=False)
    comeca_digito = segunda.str.match(r"\d", na=False)
    parece_tv = tem_letra & ~comeca_digito
    decimal_puro = segunda.str.fullmatch(r"\d+", na=False)
    preservar = segunda.ne("") & ~decimal_puro & ~parece_tv
    internet = primeira.where(~preservar, bruto)
    tv = segunda.where(parece_tv, "")
    return internet, tv


def tratar_planos_consultivo(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica as regras oficiais de separação de planos e contagem de consultivos."""
    if not {"PLANO TV", "PLANO INTERNET"}.issubset(df.columns):
        return df

    work = df.copy()
    internet_limpa, tv_embutida = _separar_internet_tv(work["PLANO INTERNET"])
    tv_original = _normalize_consultivo_series(work["PLANO TV"])
    tv_final = tv_original.mask(tv_original.eq(""), tv_embutida).str.replace(
        "SERVIÇOS AVANÇADOS", "CLARO TV+ BOX", regex=False
    )

    tem_tv = tv_final.ne("")
    tem_net = internet_limpa.ne("")
    work["QTDE_CONSULTIVO"] = tem_tv.astype(int) + tem_net.astype(int)

    tipo_servico = pd.Series("Sem Tipo", index=work.index, dtype="object")
    mask_ambos = tem_tv & tem_net
    mask_tv = tem_tv & ~tem_net
    mask_net = ~tem_tv & tem_net
    tipo_servico.loc[mask_ambos] = (
        tv_final.loc[mask_ambos] + " & " + internet_limpa.loc[mask_ambos]
    )
    tipo_servico.loc[mask_tv] = tv_final.loc[mask_tv]
    tipo_servico.loc[mask_net] = internet_limpa.loc[mask_net]

    work["TIPO SERVIÇO"] = tipo_servico
    work["PLANO TV"] = tv_final
    work["PLANO INTERNET"] = internet_limpa
    return work


def processar_quantidades_consultivo(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula QTDE_PRODUTOS, QTDE_TV, QTDE_VIRTUA e QTDE_MESH a partir de OBSERVACAO e TIPO SERVIÇO."""
    work = df.copy()
    if "OBSERVACAO" in work.columns and "QTDE_PRODUTOS" not in work.columns:
        obs = work["OBSERVACAO"].fillna("").astype(str)
        produtos_encontrados = obs.str.findall(CONSULTIVO_PRODUCT_REGEX)
        work["QTDE_PRODUTOS"] = (
            produtos_encontrados.map(
                lambda item: len(item) if isinstance(item, (list, tuple)) else 0
            )
            .fillna(0)
            .astype(int)
        )
    elif "QTDE_PRODUTOS" in work.columns:
        work["QTDE_PRODUTOS"] = (
            pd.to_numeric(work["QTDE_PRODUTOS"], errors="coerce").fillna(0).astype(int)
        )
    else:
        work["QTDE_PRODUTOS"] = 0

    if {"QTDE_TV", "QTDE_VIRTUA", "QTDE_MESH"}.issubset(work.columns):
        for col in ("QTDE_TV", "QTDE_VIRTUA", "QTDE_MESH"):
            work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)
        return work

    tipo_servico = (
        work["TIPO SERVIÇO"].fillna("").astype(str)
        if "TIPO SERVIÇO" in work.columns
        else pd.Series("", index=work.index, dtype="object")
    )
    qtde_prod = work["QTDE_PRODUTOS"].fillna(0).astype(int)

    tem_tv_bool = tipo_servico.str.contains("TV", case=False, regex=False, na=False)
    tem_virtua_bool = tipo_servico.str.contains(
        r"MEGA|GIGA", case=False, regex=True, na=False
    )
    is_combinado = tipo_servico.str.contains("&", case=False, regex=False, na=False) | (
        tem_tv_bool & tem_virtua_bool
    )
    tem_tv = tem_tv_bool.astype(int)
    tem_virtua = tem_virtua_bool.astype(int)
    work["QTDE_TV"] = (tem_tv * qtde_prod).mask(is_combinado, tem_tv).astype(int)
    work["QTDE_VIRTUA"] = (
        (tem_virtua * qtde_prod).mask(is_combinado, tem_virtua).astype(int)
    )
    work["QTDE_MESH"] = (
        (work["QTDE_PRODUTOS"] - work["QTDE_TV"] - work["QTDE_VIRTUA"])
        .clip(lower=0)
        .astype(int)
    )
    return work


def _infer_consultivo_filename_date(filename: str) -> pd.Timestamp | None:
    """Infere competência de arquivo Consultivo ignorando carimbos de download NetSales."""
    stem = re.sub(r"\s*\[[^\]]+\]\s*$", "", Path(filename).stem).strip()
    if _NETSALES_EXPORT_TS_RE.search(stem):
        return None
    return infer_date_from_filename(filename)


def _strip_excel_sep_directive(text: str) -> tuple[str, str | None]:
    """Remove diretiva opcional ``sep=;`` no topo do CSV e retorna o separador declarado."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if (
            len(stripped) == 5
            and stripped[:4].lower() == "sep="
            and stripped[4] in {";", ",", "\t", "|"}
        ):
            return "\n".join(lines[idx + 1 :]), stripped[4]
        break
    return normalized, None


def _looks_rfc4180_quoted(text: str, sep: str) -> bool:
    """Detecta se o CSV usa encapsulamento intencional por aspas duplas (RFC-4180)."""
    if '"' not in text:
        return False
    first_non_empty = next(
        (ln.strip() for ln in text.split("\n") if ln.strip()),
        "",
    )
    if first_non_empty.startswith('"') and f'"{sep}"' in first_non_empty:
        return True
    escaped_sep = re.escape(sep)
    # Aspas intencionais abrem imediatamente após delimitador/início de linha e fecham antes de delimitador/fim de linha
    for line in text.split("\n")[1:50]:
        if re.search(
            rf'(?:^|{escaped_sep})"[^"\n]*{escaped_sep}[^"\n]*"(?:{escaped_sep}|$)',
            line,
        ):
            return True
    return False


def _parse_delimited_consultivo_text(text: str, sep: str) -> pd.DataFrame:
    """Parser tolerante para exportações NetSales sem aspas (com ``;``, ``\"`` ou ``\\n`` livres)."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return pd.DataFrame()

    header = [col.strip() for col in lines[0].split(sep)]
    n_cols = len(header)
    if n_cols <= 1:
        return pd.DataFrame(columns=header)

    norm_headers = [normalize_text(col) for col in header]
    data_idx = next(
        (
            idx
            for idx, name in enumerate(norm_headers)
            if name in {"data", "datareferencia", "datacadastro", "datatabulacao"}
        ),
        None,
    )
    obs_idx = next(
        (
            idx
            for idx, name in enumerate(norm_headers)
            if name in {"observacao", "observacoes", "obs"}
        ),
        None,
    )

    merged_rows: list[list[str]] = []
    pending: list[str] | None = None

    for raw_line in lines[1:]:
        parts = raw_line.split(sep)
        is_new_dated_row = len(parts) >= n_cols or (
            data_idx is not None
            and len(parts) > data_idx
            and bool(_CONSULTIVO_DATE_TOKEN_RE.match(parts[data_idx].strip()))
        )
        if pending is not None:
            if is_new_dated_row:
                merged_rows.append(pending)
                pending = None
            else:
                combined = (
                    pending[:-1] + [f"{pending[-1]} {parts[0]}".strip()] + parts[1:]
                )
                if len(combined) < n_cols:
                    pending = combined
                else:
                    merged_rows.append(combined)
                    pending = None
                continue

        if len(parts) < n_cols:
            pending = parts
        else:
            merged_rows.append(parts)

    if pending is not None:
        merged_rows.append(pending)

    aligned_rows: list[list[str]] = []
    for raw_parts in merged_rows:
        parts = list(raw_parts)
        if len(parts) > n_cols and data_idx is not None and data_idx < len(parts):
            extra = len(parts) - n_cols
            if not _CONSULTIVO_DATE_TOKEN_RE.match(parts[data_idx].strip()):
                shift_found = next(
                    (
                        shift
                        for shift in range(1, extra + 1)
                        if data_idx + shift < len(parts)
                        and _CONSULTIVO_DATE_TOKEN_RE.match(
                            parts[data_idx + shift].strip()
                        )
                    ),
                    0,
                )
                if shift_found > 0:
                    anchor = min(12, data_idx - 1) if data_idx > 4 else 0
                    merged_cell = f"{sep} ".join(
                        p.strip() for p in parts[anchor : anchor + shift_found + 1]
                    )
                    parts = (
                        parts[:anchor]
                        + [merged_cell]
                        + parts[anchor + shift_found + 1 :]
                    )

        if len(parts) > n_cols:
            if obs_idx is not None and 0 <= obs_idx < n_cols:
                right_count = n_cols - 1 - obs_idx
                mid_end = len(parts) - right_count if right_count > 0 else len(parts)
                obs_cell = f"{sep} ".join(p.strip() for p in parts[obs_idx:mid_end])
                right_part = parts[mid_end:] if right_count > 0 else []
                parts = parts[:obs_idx] + [obs_cell] + right_part
            else:
                tail_cell = f"{sep} ".join(p.strip() for p in parts[n_cols - 1 :])
                parts = parts[: n_cols - 1] + [tail_cell]
        elif len(parts) < n_cols:
            parts = parts + [""] * (n_cols - len(parts))

        aligned_rows.append(parts)

    return pd.DataFrame(aligned_rows, columns=header, dtype="object").fillna("")


def read_consultivo_csv(content: bytes) -> pd.DataFrame:
    """Lê arquivos CSV de tabulação consultiva preservando zeros à esquerda e textos longos."""
    clean_bytes = content.replace(b"\x00", b"") if content else b""
    if not clean_bytes or not clean_bytes.strip():
        raise ValueError("O arquivo CSV de consultivo está vazio.")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            raw_text = clean_bytes.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error
            continue

        body_text, declared_sep = _strip_excel_sep_directive(raw_text)
        non_empty_lines = [ln for ln in body_text.split("\n") if ln.strip()]
        if not non_empty_lines:
            raise ValueError("O arquivo CSV de consultivo está vazio.")

        first_line = non_empty_lines[0]
        if declared_sep:
            candidates = [declared_sep]
        else:
            candidates = (
                [";", ","]
                if first_line.count(";") >= first_line.count(",")
                else [",", ";"]
            )

        expected_data_rows = max(0, len(non_empty_lines) - 1)
        for sep in candidates:
            header_sep_count = first_line.count(sep)
            if header_sep_count == 0:
                continue
            rfc_quoted = _looks_rfc4180_quoted(body_text, sep)
            uniform_unquoted = not rfc_quoted and all(
                ln.count(sep) == header_sep_count for ln in non_empty_lines[1:]
            )
            if rfc_quoted or uniform_unquoted:
                quoting_mode = csv.QUOTE_MINIMAL if rfc_quoted else csv.QUOTE_NONE
                try:
                    frame = pd.read_csv(
                        io.StringIO(body_text),
                        sep=sep,
                        dtype=str,
                        keep_default_na=False,
                        quoting=quoting_mode,
                    )
                    swallowed_rows = expected_data_rows >= 4 and len(frame) < max(
                        1, expected_data_rows // 2
                    )
                    shifted_index = not isinstance(frame.index, pd.RangeIndex)
                    if frame.shape[1] > 1 and not swallowed_rows and not shifted_index:
                        return frame
                except (pd.errors.ParserError, csv.Error) as error:
                    last_error = error

            tolerant = _parse_delimited_consultivo_text(body_text, sep)
            if tolerant.shape[1] > 1:
                return tolerant

        try:
            return pd.read_csv(
                io.StringIO(body_text),
                sep=None,
                engine="python",
                dtype=str,
                keep_default_na=False,
            )
        except (pd.errors.ParserError, csv.Error) as error:
            last_error = error
    raise ValueError(f"Não foi possível ler o CSV de consultivo: {last_error}")


def process_consultivo_dataframe(
    frame: pd.DataFrame,
    source_file: str,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> tuple[list[dict], list[str]]:
    """Normaliza um DataFrame de tabulação/consultivo para persistência no SQLite."""
    if frame.empty:
        return [], ["O arquivo de consultivo está vazio."]

    work = frame.copy()
    work.columns = [str(col).strip() for col in work.columns]

    canonical_aliases: dict[str, set[str]] = {
        "DATA": {"data", "datareferencia", "datacadastro", "datatabulacao"},
        "LOGIN NETSALES": {"loginnetsales", "login", "logintecnico"},
        "VENDEDOR": {"vendedor", "tecnico", "colaborador", "nomevendedor"},
        "HP": {"hp", "codigohp"},
        "CÓDIGO CONTATO": {"codigocontato", "codcontato", "idcontato"},
        "CONTRATO": {"contrato", "numerocontrato", "codigocontrato"},
        "TIPO DE TABULAÇÃO": {"tipodetabulacao", "tipotabulacao"},
        "STATUS NETSALES": {"statusnetsales", "status"},
        "PLANO TV": {"planotv"},
        "PLANO INTERNET": {"planointernet"},
        "OBSERVACAO": {"observacao", "obs"},
        "TIPO SERVIÇO": {"tiposervico", "tipodeservico"},
        "QTDE_CONSULTIVO": {"qtdeconsultivo", "qtdconsultivo", "qtdecons"},
        "QTDE_PRODUTOS": {"qtdeprodutos", "qtdprodutos", "qtdeprod"},
        "QTDE_MESH": {"qtdemesh", "qtdmesh", "mesh"},
        "QTDE_TV": {"qtdetv", "qtdtv", "tvbox"},
        "QTDE_VIRTUA": {"qtdevirtua", "qtdvirtua", "virtua"},
    }
    rename_map: dict[object, str] = {}
    for target, aliases in canonical_aliases.items():
        if target in work.columns:
            continue
        found_col = find_column(work, aliases)
        if found_col is not None and found_col not in rename_map:
            rename_map[found_col] = target
    if rename_map:
        work = work.rename(columns=rename_map)

    if "LOGIN NETSALES" not in work.columns and "VENDEDOR" not in work.columns:
        available = ", ".join(str(col) for col in work.columns[:12])
        raise ValueError(
            "Colunas de identificação (LOGIN NETSALES / VENDEDOR) não encontradas "
            f"no arquivo {source_file}. Colunas vistas: {available or 'nenhuma'}."
        )

    if {"PLANO TV", "PLANO INTERNET"}.issubset(
        work.columns
    ) and "QTDE_CONSULTIVO" not in work.columns:
        work = tratar_planos_consultivo(work)
    elif "QTDE_CONSULTIVO" in work.columns:
        work["QTDE_CONSULTIVO"] = (
            pd.to_numeric(work["QTDE_CONSULTIVO"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
    else:
        work["QTDE_CONSULTIVO"] = 0

    work = processar_quantidades_consultivo(work)

    explicit_fallback_dt = parse_reference_date(default_date)
    if "DATA" in work.columns:
        parsed_dates = converter_data_consultivo_br(work["DATA"])
    else:
        parsed_dates = pd.Series(pd.NaT, index=work.index, dtype="datetime64[ns]")

    if explicit_fallback_dt is not None:
        parsed_dates = parsed_dates.fillna(explicit_fallback_dt)
    elif parsed_dates.notna().sum() == 0:
        inferred_dt = _infer_consultivo_filename_date(source_file)
        if inferred_dt is not None:
            parsed_dates = parsed_dates.fillna(inferred_dt)

    issues: list[str] = []
    invalid_mask = parsed_dates.isna()
    invalid_count = int(invalid_mask.sum())
    if invalid_count:
        issues.append(
            f"{invalid_count} linha(s) ignorada(s) sem data válida em {source_file}."
        )
    valid = work.loc[~invalid_mask].copy()
    valid_dates = parsed_dates.loc[~invalid_mask].dt.strftime("%Y-%m-%d")
    if valid.empty:
        return [], issues or ["Nenhuma linha válida encontrada no arquivo consultivo."]

    def _col_clean(col_name: str, *, upper: bool = False) -> list[str]:
        if col_name not in valid.columns:
            return [""] * len(valid)
        cleaned = _normalize_consultivo_series(valid[col_name])
        if upper:
            cleaned = cleaned.str.upper()
        return [str(v) for v in cleaned.tolist()]

    logins = [
        clean_code(val).upper()
        for val in (
            valid["LOGIN NETSALES"].tolist()
            if "LOGIN NETSALES" in valid.columns
            else [""] * len(valid)
        )
    ]
    sellers = [
        clean_technician(val)
        for val in (
            valid["VENDEDOR"].tolist()
            if "VENDEDOR" in valid.columns
            else [""] * len(valid)
        )
    ]
    hps = _col_clean("HP")
    contacts = _col_clean("CÓDIGO CONTATO")
    contracts = _col_clean("CONTRATO")
    tab_types = _col_clean("TIPO DE TABULAÇÃO", upper=True)
    statuses = _col_clean("STATUS NETSALES", upper=True)
    planos_tv = _col_clean("PLANO TV")
    planos_net = _col_clean("PLANO INTERNET")
    tipos_serv = (
        valid["TIPO SERVIÇO"].fillna("Sem Tipo").astype(str).tolist()
        if "TIPO SERVIÇO" in valid.columns
        else ["Sem Tipo"] * len(valid)
    )
    q_cons = valid["QTDE_CONSULTIVO"].fillna(0).astype(int).tolist()
    q_prod = valid["QTDE_PRODUTOS"].fillna(0).astype(int).tolist()
    q_mesh = valid["QTDE_MESH"].fillna(0).astype(int).tolist()
    q_tv = valid["QTDE_TV"].fillna(0).astype(int).tolist()
    q_virtua = valid["QTDE_VIRTUA"].fillna(0).astype(int).tolist()
    ref_dates = valid_dates.tolist()
    row_numbers = [int(idx) + 2 for idx in range(len(valid))]

    records = [
        {
            "reference_date": ref_dates[i],
            "login_netsales": logins[i],
            "seller": sellers[i],
            "hp": hps[i],
            "contact_code": contacts[i],
            "contract": contracts[i],
            "tabulation_type": tab_types[i],
            "status_netsales": statuses[i],
            "plano_tv": planos_tv[i],
            "plano_internet": planos_net[i],
            "tipo_servico": tipos_serv[i] or "Sem Tipo",
            "qtde_consultivo": int(q_cons[i]),
            "qtde_produtos": int(q_prod[i]),
            "qtde_mesh": int(q_mesh[i]),
            "qtde_tv": int(q_tv[i]),
            "qtde_virtua": int(q_virtua[i]),
            "source_file": source_file,
            "source_row": row_numbers[i],
        }
        for i in range(len(valid))
    ]
    return records, issues


def process_consultivo_upload(
    filename: str,
    content: bytes,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> tuple[list[dict], list[str]]:
    """Lê um arquivo CSV ou Excel da pasta de Histórico Consultivo."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return process_consultivo_dataframe(
            read_consultivo_csv(content), filename, default_date
        )
    if suffix not in {".xlsx", ".xls"}:
        raise ValueError("Formato não suportado para Consultivo. Use CSV, XLSX ou XLS.")
    try:
        workbook = pd.ExcelFile(io.BytesIO(content))
    except Exception as error:
        raise ValueError(
            f"Não foi possível abrir a planilha de consultivo ({filename}): {error}"
        ) from error
    normalized = {normalize_text(name): name for name in workbook.sheet_names}
    sheet_name = normalized.get("consultivo") or (
        str(workbook.sheet_names[0]) if workbook.sheet_names else None
    )
    if sheet_name is None:
        return [], ["A planilha de consultivo não possui abas."]
    frame = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str)
    return process_consultivo_dataframe(frame, filename, default_date)


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                technician TEXT NOT NULL,
                reference_date TEXT NOT NULL,
                source_sheet TEXT NOT NULL CHECK(source_sheet IN ('Prod', 'Gpon')),
                project TEXT NOT NULL DEFAULT 'Sem projeto',
                contract TEXT DEFAULT NULL,
                wo TEXT DEFAULT NULL,
                contract_flag INTEGER DEFAULT NULL,
                points REAL NOT NULL,
                source_file TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_file, source_sheet, source_row)
            );
            CREATE INDEX IF NOT EXISTS idx_production_date
                ON production_records(reference_date);
            CREATE INDEX IF NOT EXISTS idx_production_technician
                ON production_records(technician);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS drive_file_metadata (
                folder_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                PRIMARY KEY(folder_id, file_id)
            );
            CREATE TABLE IF NOT EXISTS technician_roster (
                technician_key TEXT PRIMARY KEY,
                technician TEXT NOT NULL,
                re_code TEXT NOT NULL DEFAULT '',
                login TEXT NOT NULL DEFAULT '',
                monitor TEXT NOT NULL DEFAULT 'Sem monitor',
                un TEXT NOT NULL DEFAULT 'Sem U.N.',
                base TEXT NOT NULL DEFAULT 'Sem base',
                status TEXT NOT NULL DEFAULT 'ATIVO',
                source_tab TEXT NOT NULL DEFAULT 'lista_ativos',
                last_modified TEXT NOT NULL DEFAULT '',
                termination_date TEXT NOT NULL DEFAULT '',
                termination_reason TEXT NOT NULL DEFAULT '',
                is_demo INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_roster_status
                ON technician_roster(status);
            CREATE INDEX IF NOT EXISTS idx_roster_monitor
                ON technician_roster(monitor);
            CREATE INDEX IF NOT EXISTS idx_roster_base
                ON technician_roster(base);
            CREATE TABLE IF NOT EXISTS consultivo_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_date TEXT NOT NULL,
                login_netsales TEXT NOT NULL DEFAULT '',
                seller TEXT NOT NULL DEFAULT '',
                hp TEXT NOT NULL DEFAULT '',
                contact_code TEXT NOT NULL DEFAULT '',
                contract TEXT NOT NULL DEFAULT '',
                tabulation_type TEXT NOT NULL DEFAULT '',
                status_netsales TEXT NOT NULL DEFAULT '',
                plano_tv TEXT NOT NULL DEFAULT '',
                plano_internet TEXT NOT NULL DEFAULT '',
                tipo_servico TEXT NOT NULL DEFAULT 'Sem Tipo',
                qtde_consultivo INTEGER NOT NULL DEFAULT 0,
                qtde_produtos INTEGER NOT NULL DEFAULT 0,
                qtde_mesh INTEGER NOT NULL DEFAULT 0,
                qtde_tv INTEGER NOT NULL DEFAULT 0,
                qtde_virtua INTEGER NOT NULL DEFAULT 0,
                source_file TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                is_demo INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_file, source_row)
            );
            CREATE INDEX IF NOT EXISTS idx_consultivo_date
                ON consultivo_records(reference_date);
            CREATE INDEX IF NOT EXISTS idx_consultivo_login
                ON consultivo_records(login_netsales);
            """
        )
        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(production_records)"
            ).fetchall()
        }
        if "project" not in columns:
            connection.execute(
                "ALTER TABLE production_records ADD COLUMN project TEXT NOT NULL DEFAULT 'Sem projeto'"
            )
        if "contract" not in columns:
            connection.execute(
                "ALTER TABLE production_records ADD COLUMN contract TEXT"
            )
        if "wo" not in columns:
            connection.execute("ALTER TABLE production_records ADD COLUMN wo TEXT")
        if "contract_flag" not in columns:
            connection.execute(
                "ALTER TABLE production_records ADD COLUMN contract_flag INTEGER"
            )
        if "is_demo" not in columns:
            connection.execute(
                "ALTER TABLE production_records "
                "ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
            )
        for table_name in ("technician_roster", "consultivo_records"):
            table_columns = {
                row["name"]
                for row in connection.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
            if "is_demo" not in table_columns:
                connection.execute(
                    f"ALTER TABLE {table_name} "
                    "ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0"
                )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_project ON production_records(project)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_contract ON production_records(contract)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_wo ON production_records(wo)"
        )


def get_setting(key: str) -> str | None:
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    init_database()
    with connect() as connection:
        connection.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_drive_file_fingerprints(folder_id: str) -> dict[str, str]:
    init_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT file_id, fingerprint FROM drive_file_metadata WHERE folder_id = ?",
            (folder_id,),
        ).fetchall()
    return {row["file_id"]: row["fingerprint"] for row in rows}


def get_consultivo_file_fingerprints(folder_id: str) -> dict[str, str]:
    """Retorna fingerprints de Consultivo somente para arquivos com linhas efetivamente salvas."""
    init_database()
    with connect() as connection:
        meta_rows = connection.execute(
            "SELECT file_id, fingerprint FROM drive_file_metadata WHERE folder_id = ?",
            (folder_id,),
        ).fetchall()
        if not meta_rows:
            return {}
        source_rows = connection.execute(
            "SELECT DISTINCT source_file FROM consultivo_records WHERE is_demo = 0"
        ).fetchall()
    persisted_ids: set[str] = set()
    for row in source_rows:
        source_file = str(row["source_file"] or "")
        match = re.search(r" \[([^\]]+)\]\.[^.]+$", source_file)
        if match:
            persisted_ids.add(match.group(1))
    return {
        row["file_id"]: row["fingerprint"]
        for row in meta_rows
        if row["file_id"] in persisted_ids
    }


def get_roster_fingerprint(sheet_id: str) -> str | None:
    clean_id = extract_spreadsheet_id(sheet_id)
    if not clean_id:
        return None
    return get_drive_file_fingerprints(ROSTER_METADATA_SCOPE).get(clean_id)


def save_roster_records(
    records: Iterable[dict],
    *,
    is_demo: bool = False,
    sheet_id: str | None = None,
    fingerprint: str | None = None,
) -> int:
    """Persiste o quadro cadastral de técnicos (lista_ativos + desligados)."""
    rows = list(records)
    if not rows:
        return 0
    init_database()
    clean_id = extract_spreadsheet_id(sheet_id)
    with connect() as connection:
        if is_demo:
            existing = connection.execute(
                "SELECT COUNT(*) AS total FROM technician_roster WHERE is_demo = 0"
            ).fetchone()
            if existing and existing["total"] > 0:
                return 0
            connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
        else:
            connection.execute("DELETE FROM technician_roster")
            if clean_id and fingerprint:
                connection.execute(
                    """
                    INSERT INTO drive_file_metadata (folder_id, file_id, fingerprint)
                    VALUES (?, ?, ?)
                    ON CONFLICT(folder_id, file_id)
                    DO UPDATE SET fingerprint = excluded.fingerprint
                    """,
                    (ROSTER_METADATA_SCOPE, clean_id, fingerprint),
                )
        connection.executemany(
            """
            INSERT INTO technician_roster (
                technician_key, technician, re_code, login, monitor, un, base,
                status, source_tab, last_modified, termination_date,
                termination_reason, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(technician_key) DO UPDATE SET
                technician = excluded.technician,
                re_code = excluded.re_code,
                login = excluded.login,
                monitor = excluded.monitor,
                un = excluded.un,
                base = excluded.base,
                status = excluded.status,
                source_tab = excluded.source_tab,
                last_modified = excluded.last_modified,
                termination_date = excluded.termination_date,
                termination_reason = excluded.termination_reason,
                is_demo = excluded.is_demo,
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                (
                    row.get("technician_key") or normalize_text(row["technician"]),
                    clean_technician(row["technician"]) or str(row["technician"]),
                    clean_code(row.get("re_code", "")),
                    clean_code(row.get("login", "")).upper(),
                    clean_technician(row.get("monitor", "")) or "Sem monitor",
                    _clean_optional_label(row.get("un"), "Sem U.N.", upper=True),
                    _clean_optional_label(row.get("base"), "Sem base", upper=True),
                    clean_roster_status(row.get("status"), default="ATIVO"),
                    str(row.get("source_tab") or ROSTER_ACTIVE_TAB),
                    str(row.get("last_modified") or ""),
                    str(row.get("termination_date") or ""),
                    str(row.get("termination_reason") or ""),
                    1 if is_demo else 0,
                )
                for row in rows
                if clean_technician(row.get("technician"))
            ],
        )
    return len(rows)


def _read_roster_rows(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT technician_key, technician, re_code, login, monitor, un, base,
               status, source_tab, last_modified, termination_date,
               termination_reason, is_demo, updated_at
        FROM technician_roster
        ORDER BY technician
        """,
        connection,
    )


def load_roster() -> pd.DataFrame:
    """Retorna o cadastro completo de colaboradores (ativos e desligados)."""
    init_database()
    with connect() as connection:
        return _read_roster_rows(connection)


def enrich_records_with_roster(
    frame: pd.DataFrame,
    roster: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Cruza registros de produção com ``lista_ativos``/``desligados`` por nome normalizado."""
    work = frame.copy()
    if work.empty:
        for col in ("re_code", "login", "monitor", "un", "base", "roster_status"):
            work[col] = pd.Series(dtype="object")
        return work

    if roster is None or roster.empty:
        work["re_code"] = ""
        work["login"] = ""
        work["monitor"] = "Sem monitor"
        work["un"] = "Sem U.N."
        work["base"] = "Sem base"
        work["roster_status"] = "Sem cadastro"
        return work

    indexed = roster.drop_duplicates("technician_key").set_index("technician_key")
    keys = _map_repeated_text(work["technician"], normalize_text, null_value="")
    canonical_names = keys.map(indexed["technician"])
    work["technician"] = canonical_names.fillna(work["technician"])
    work["re_code"] = keys.map(indexed["re_code"]).fillna("")
    work["login"] = keys.map(indexed["login"]).fillna("")
    work["monitor"] = keys.map(indexed["monitor"]).fillna("Sem monitor")
    work["un"] = keys.map(indexed["un"]).fillna("Sem U.N.")
    work["base"] = keys.map(indexed["base"]).fillna("Sem base")
    work["roster_status"] = keys.map(indexed["status"]).fillna("Não cadastrado")
    return work


def save_records(records: Iterable[dict], is_demo: bool = False) -> int:
    rows = list(records)
    if not rows:
        return 0
    init_database()
    sources = {(row["source_file"], row["source_sheet"]) for row in rows}
    with connect() as connection:
        if not is_demo:
            connection.execute("DELETE FROM production_records WHERE is_demo = 1")
            connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES ('demo_disabled', '1') "
                "ON CONFLICT(key) DO UPDATE SET value = '1'"
            )
        for source_file, source_sheet in sources:
            connection.execute(
                "DELETE FROM production_records WHERE source_file = ? AND source_sheet = ?",
                (source_file, source_sheet),
            )
        connection.executemany(
            """
            INSERT INTO production_records (
                technician, reference_date, source_sheet, project, contract, wo,
                contract_flag, points, source_file, source_row, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["technician"],
                    row["reference_date"],
                    row["source_sheet"],
                    clean_project(row.get("project", "Sem projeto")),
                    _contract_or_placeholder(row.get("contract")),
                    _wo_or_placeholder(row.get("wo")),
                    row.get("contract_flag"),
                    row["points"],
                    row["source_file"],
                    row["source_row"],
                    1 if is_demo else 0,
                )
                for row in rows
            ],
        )
    return len(rows)


def sync_drive_records(
    records: Iterable[dict],
    live_file_ids: set[str],
    refreshed_file_ids: set[str],
    *,
    folder_id: str | None = None,
    file_fingerprints: Mapping[str, str] | None = None,
) -> int:
    rows = list(records)
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM production_records WHERE is_demo = 1")
        connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
        connection.execute(
            "INSERT INTO app_settings(key, value) VALUES ('demo_disabled', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        source_files = connection.execute(
            "SELECT DISTINCT source_file FROM production_records"
        ).fetchall()
        for row in source_files:
            source_file = row["source_file"]
            match = re.search(r" \[([^\]]+)\]\.[^.]+$", source_file)
            if not match:
                continue
            file_id = match.group(1)
            if file_id not in live_file_ids or file_id in refreshed_file_ids:
                connection.execute(
                    "DELETE FROM production_records WHERE source_file = ?",
                    (source_file,),
                )
        if folder_id is not None:
            known_file_ids = connection.execute(
                "SELECT file_id FROM drive_file_metadata WHERE folder_id = ?",
                (folder_id,),
            ).fetchall()
            connection.executemany(
                "DELETE FROM drive_file_metadata WHERE folder_id = ? AND file_id = ?",
                [
                    (folder_id, row["file_id"])
                    for row in known_file_ids
                    if row["file_id"] not in live_file_ids
                ],
            )
            # Um arquivo atualizado sem metadados verificáveis não pode manter
            # o fingerprint anterior: ele precisa ser reprocessado na próxima vez.
            connection.executemany(
                "DELETE FROM drive_file_metadata WHERE folder_id = ? AND file_id = ?",
                [
                    (folder_id, file_id)
                    for file_id in refreshed_file_ids
                    if file_id not in (file_fingerprints or {})
                ],
            )
            connection.executemany(
                """
                INSERT INTO drive_file_metadata (folder_id, file_id, fingerprint)
                VALUES (?, ?, ?)
                ON CONFLICT(folder_id, file_id)
                DO UPDATE SET fingerprint = excluded.fingerprint
                """,
                [
                    (folder_id, file_id, fingerprint)
                    for file_id, fingerprint in (file_fingerprints or {}).items()
                    if file_id in refreshed_file_ids and file_id in live_file_ids
                ],
            )
        connection.executemany(
            """
            INSERT INTO production_records (
                technician, reference_date, source_sheet, project, contract, wo,
                contract_flag, points, source_file, source_row, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            [
                (
                    row["technician"],
                    row["reference_date"],
                    row["source_sheet"],
                    clean_project(row.get("project", "Sem projeto")),
                    _contract_or_placeholder(row.get("contract")),
                    _wo_or_placeholder(row.get("wo")),
                    row.get("contract_flag"),
                    row["points"],
                    row["source_file"],
                    row["source_row"],
                )
                for row in rows
            ],
        )
    return len(rows)


def _read_record_rows(connection: sqlite3.Connection) -> pd.DataFrame:
    """Consulta comum aos carregamentos de registros e do dashboard."""
    available_columns = {
        row["name"]
        for row in connection.execute(
            "PRAGMA table_info(production_records)"
        ).fetchall()
    }
    select_columns = [
        "id",
        "technician",
        "reference_date",
        "source_sheet",
        "project",
        "points",
        "source_file",
        "source_row",
        "is_demo",
        "imported_at",
    ]
    if "contract" in available_columns:
        select_columns.insert(5, "contract")
    if "wo" in available_columns:
        select_columns.insert(6, "wo")
    if "contract_flag" in available_columns:
        select_columns.append("contract_flag")
    return pd.read_sql_query(
        f"""
        SELECT {", ".join(select_columns)}
        FROM production_records
        ORDER BY reference_date, technician, source_sheet
        """,
        connection,
    )


def _prepare_loaded_records(
    frame: pd.DataFrame, roster: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Normaliza o frame carregado, sem consultar ou alterar o banco."""
    if frame.empty:
        return enrich_records_with_roster(frame, roster)
    if "contract" not in frame.columns:
        frame["contract"] = "Sem contrato"
    else:
        frame["contract"] = _map_repeated_text(
            frame["contract"], _contract_or_placeholder, null_value="Sem contrato"
        )
    if "wo" not in frame.columns:
        frame["wo"] = "Sem WO"
    else:
        frame["wo"] = _map_repeated_text(
            frame["wo"], _wo_or_placeholder, null_value="Sem WO"
        )
    frame = add_contracts_qty(frame)
    frame["reference_date"] = pd.to_datetime(frame["reference_date"])
    frame["period"] = frame["reference_date"].dt.to_period("M").dt.to_timestamp()
    return enrich_records_with_roster(frame, roster)


def load_records() -> pd.DataFrame:
    init_database()
    with connect() as connection:
        frame = _read_record_rows(connection)
        roster = _read_roster_rows(connection)
    if frame.empty:
        return enrich_records_with_roster(add_contracts_qty(frame), roster)
    return _prepare_loaded_records(frame, roster)


def database_stats() -> dict:
    init_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS records, COUNT(DISTINCT technician) AS technicians,
                   MIN(reference_date) AS first_date, MAX(reference_date) AS last_date,
                   MAX(imported_at) AS last_import, COALESCE(SUM(is_demo), 0) AS demo_rows
            FROM production_records
            """
        ).fetchone()
    return dict(row)


def load_dashboard_snapshot() -> tuple[pd.DataFrame, dict]:
    """Carrega os registros e seus metadados numa única conexão SQLite."""
    init_database()
    with connect() as connection:
        frame = _read_record_rows(connection)
        roster = _read_roster_rows(connection)
        stats = dict(
            connection.execute(
                """
                SELECT COUNT(*) AS records, COUNT(DISTINCT technician) AS technicians,
                       MIN(reference_date) AS first_date, MAX(reference_date) AS last_date,
                       MAX(imported_at) AS last_import,
                       COALESCE(SUM(is_demo), 0) AS demo_rows
                FROM production_records
                """
            ).fetchone()
        )
    stats["roster_total"] = int(len(roster))
    stats["roster_active"] = (
        int(roster["status"].eq("ATIVO").sum()) if not roster.empty else 0
    )
    if frame.empty:
        return enrich_records_with_roster(add_contracts_qty(frame), roster), stats
    return _prepare_loaded_records(frame, roster), stats


def import_batches() -> pd.DataFrame:
    """Resumo por arquivo importado, incluindo o contador de contratos.

    ``contracts_count`` conta identificadores de contrato distintos no arquivo;
    registros sem contrato (marcador ``"Sem contrato"`` e variações nulas) não
    entram na contagem.
    """
    init_database()
    with connect() as connection:
        frame = pd.read_sql_query(
            """
            SELECT source_file,
                   GROUP_CONCAT(DISTINCT source_sheet) AS origins,
                   COUNT(*) AS rows_count,
                   ROUND(SUM(points), 2) AS points,
                   MAX(imported_at) AS imported_at
            FROM production_records
            GROUP BY source_file
            ORDER BY imported_at DESC, source_file
            """,
            connection,
        )
        contratos = pd.read_sql_query(
            "SELECT DISTINCT source_file, contract FROM production_records",
            connection,
        )
    contratos = add_contracts_qty(contratos)
    contagem = (
        contratos.groupby("source_file")["contracts_qty"].max()
        if not contratos.empty
        else pd.Series(dtype="int64")
    )
    if frame.empty:
        frame["contracts_count"] = pd.Series(dtype="int64")
        return frame
    frame.insert(
        3,
        "contracts_count",
        frame["source_file"].map(contagem).fillna(0).astype(int),
    )
    return frame


def save_consultivo_records(
    records: Iterable[dict],
    *,
    is_demo: bool = False,
) -> int:
    """Persiste registros de histórico consultivo no SQLite."""
    rows = list(records)
    if not rows:
        return 0
    init_database()
    sources = {str(row["source_file"]) for row in rows}
    with connect() as connection:
        if not is_demo:
            connection.execute("DELETE FROM consultivo_records WHERE is_demo = 1")
            connection.execute(
                "INSERT INTO app_settings(key, value) VALUES ('consultivo_demo_disabled', '1') "
                "ON CONFLICT(key) DO UPDATE SET value = '1'"
            )
        for source_file in sources:
            connection.execute(
                "DELETE FROM consultivo_records WHERE source_file = ?",
                (source_file,),
            )
        connection.executemany(
            """
            INSERT INTO consultivo_records (
                reference_date, login_netsales, seller, hp, contact_code,
                contract, tabulation_type, status_netsales, plano_tv,
                plano_internet, tipo_servico, qtde_consultivo, qtde_produtos,
                qtde_mesh, qtde_tv, qtde_virtua, source_file, source_row, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row["reference_date"]),
                    clean_code(row.get("login_netsales", "")).upper(),
                    clean_technician(row.get("seller", "")),
                    str(row.get("hp") or ""),
                    str(row.get("contact_code") or ""),
                    str(row.get("contract") or ""),
                    str(row.get("tabulation_type") or ""),
                    str(row.get("status_netsales") or ""),
                    str(row.get("plano_tv") or ""),
                    str(row.get("plano_internet") or ""),
                    str(row.get("tipo_servico") or "Sem Tipo"),
                    int(row.get("qtde_consultivo") or 0),
                    int(row.get("qtde_produtos") or 0),
                    int(row.get("qtde_mesh") or 0),
                    int(row.get("qtde_tv") or 0),
                    int(row.get("qtde_virtua") or 0),
                    str(row["source_file"]),
                    int(row["source_row"]),
                    1 if is_demo else 0,
                )
                for row in rows
            ],
        )
    return len(rows)


def sync_consultivo_drive_records(
    records: Iterable[dict],
    live_file_ids: set[str],
    refreshed_file_ids: set[str],
    *,
    folder_id: str | None = None,
    file_fingerprints: Mapping[str, str] | None = None,
) -> int:
    """Sincroniza incrementalmente os arquivos da pasta Histórico Consultivo no SQLite."""
    rows = list(records)
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM consultivo_records WHERE is_demo = 1")
        connection.execute(
            "INSERT INTO app_settings(key, value) VALUES ('consultivo_demo_disabled', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
        source_files = connection.execute(
            "SELECT DISTINCT source_file FROM consultivo_records"
        ).fetchall()
        for row in source_files:
            source_file = row["source_file"]
            match = re.search(r" \[([^\]]+)\]\.[^.]+$", source_file)
            if not match:
                continue
            file_id = match.group(1)
            if file_id not in live_file_ids or file_id in refreshed_file_ids:
                connection.execute(
                    "DELETE FROM consultivo_records WHERE source_file = ?",
                    (source_file,),
                )
        if folder_id is not None:
            known_file_ids = connection.execute(
                "SELECT file_id FROM drive_file_metadata WHERE folder_id = ?",
                (folder_id,),
            ).fetchall()
            connection.executemany(
                "DELETE FROM drive_file_metadata WHERE folder_id = ? AND file_id = ?",
                [
                    (folder_id, row["file_id"])
                    for row in known_file_ids
                    if row["file_id"] not in live_file_ids
                ],
            )
            connection.executemany(
                "DELETE FROM drive_file_metadata WHERE folder_id = ? AND file_id = ?",
                [
                    (folder_id, file_id)
                    for file_id in refreshed_file_ids
                    if file_id not in (file_fingerprints or {})
                ],
            )
            connection.executemany(
                """
                INSERT INTO drive_file_metadata (folder_id, file_id, fingerprint)
                VALUES (?, ?, ?)
                ON CONFLICT(folder_id, file_id)
                DO UPDATE SET fingerprint = excluded.fingerprint
                """,
                [
                    (folder_id, file_id, fingerprint)
                    for file_id, fingerprint in (file_fingerprints or {}).items()
                    if file_id in refreshed_file_ids and file_id in live_file_ids
                ],
            )
        connection.executemany(
            """
            INSERT INTO consultivo_records (
                reference_date, login_netsales, seller, hp, contact_code,
                contract, tabulation_type, status_netsales, plano_tv,
                plano_internet, tipo_servico, qtde_consultivo, qtde_produtos,
                qtde_mesh, qtde_tv, qtde_virtua, source_file, source_row, is_demo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            [
                (
                    str(row["reference_date"]),
                    clean_code(row.get("login_netsales", "")).upper(),
                    clean_technician(row.get("seller", "")),
                    str(row.get("hp") or ""),
                    str(row.get("contact_code") or ""),
                    str(row.get("contract") or ""),
                    str(row.get("tabulation_type") or ""),
                    str(row.get("status_netsales") or ""),
                    str(row.get("plano_tv") or ""),
                    str(row.get("plano_internet") or ""),
                    str(row.get("tipo_servico") or "Sem Tipo"),
                    int(row.get("qtde_consultivo") or 0),
                    int(row.get("qtde_produtos") or 0),
                    int(row.get("qtde_mesh") or 0),
                    int(row.get("qtde_tv") or 0),
                    int(row.get("qtde_virtua") or 0),
                    str(row["source_file"]),
                    int(row["source_row"]),
                )
                for row in rows
            ],
        )
    return len(rows)


def _empty_consultivo_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "DATA",
            "period",
            "LOGIN NETSALES",
            "VENDEDOR",
            "Técnico",
            "Monitor",
            "U.N.",
            "Base",
            "Situação",
            "Qtde. Cons.",
            "Qtde. Prod.",
            "Qtde. Mesh",
            "Qtde. TV",
            "Qtde. Virtua",
            "QTDE_CONSULTIVO",
            "QTDE_PRODUTOS",
            "QTDE_MESH",
            "QTDE_TV",
            "QTDE_VIRTUA",
            "CONTRATO",
            "HP",
            "CÓDIGO CONTATO",
            "TIPO DE TABULAÇÃO",
            "STATUS NETSALES",
            "TIPO SERVIÇO",
            "PLANO TV",
            "PLANO INTERNET",
            "source_file",
            "source_row",
            "is_demo",
            "imported_at",
        ]
    )


def enrich_consultivo_with_roster(
    frame: pd.DataFrame,
    roster: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Enriquece os registros de consultivo com ``lista_ativos``/``desligados`` por Login e Técnico."""
    if frame.empty:
        return _empty_consultivo_frame()

    work = frame.copy()
    # Deduplica contatos idênticos se houver sobreposição entre exportações mensais.
    if "contact_code" in work.columns:
        non_empty = work["contact_code"].fillna("").astype(str).str.strip().ne("")
        if non_empty.any():
            duplicated = work.loc[non_empty].duplicated(
                subset=["contact_code"], keep="last"
            )
            drop_index = duplicated[duplicated].index
            if len(drop_index) > 0:
                work = work.drop(index=drop_index).reset_index(drop=True)

    login_raw = (
        work["login_netsales"].map(lambda v: clean_code(v).upper())
        if "login_netsales" in work.columns
        else pd.Series("", index=work.index, dtype="object")
    )
    seller_raw = (
        work["seller"].map(clean_technician)
        if "seller" in work.columns
        else pd.Series("", index=work.index, dtype="object")
    )

    tech_matched = pd.Series("", index=work.index, dtype="object")
    monitor_matched = pd.Series("", index=work.index, dtype="object")
    un_matched = pd.Series("", index=work.index, dtype="object")
    base_matched = pd.Series("", index=work.index, dtype="object")
    status_matched = pd.Series("", index=work.index, dtype="object")
    login_matched = login_raw.copy()

    if roster is not None and not roster.empty:
        ordered_roster = roster.copy()
        ordered_roster["_tab_prio"] = ordered_roster["source_tab"].map(
            lambda t: 0 if str(t) == ROSTER_ACTIVE_TAB else 1
        )
        ordered_roster = ordered_roster.sort_values("_tab_prio")
        ordered_roster["_login_clean"] = ordered_roster["login"].map(
            lambda v: clean_code(v).upper()
        )
        by_login = (
            ordered_roster.loc[ordered_roster["_login_clean"].ne("")]
            .drop_duplicates("_login_clean", keep="first")
            .set_index("_login_clean")
        )
        by_name = ordered_roster.drop_duplicates(
            "technician_key", keep="first"
        ).set_index("technician_key")

        if not by_login.empty:
            tech_matched = login_raw.map(by_login["technician"]).fillna("")
            monitor_matched = login_raw.map(by_login["monitor"]).fillna("")
            un_matched = login_raw.map(by_login["un"]).fillna("")
            base_matched = login_raw.map(by_login["base"]).fillna("")
            status_matched = login_raw.map(by_login["status"]).fillna("")

        unmatched = tech_matched.eq("") & seller_raw.ne("")
        if unmatched.any() and not by_name.empty:
            seller_keys = seller_raw.loc[unmatched].map(normalize_text)
            tech_matched.loc[unmatched] = seller_keys.map(by_name["technician"]).fillna(
                ""
            )
            monitor_matched.loc[unmatched] = seller_keys.map(by_name["monitor"]).fillna(
                ""
            )
            un_matched.loc[unmatched] = seller_keys.map(by_name["un"]).fillna("")
            base_matched.loc[unmatched] = seller_keys.map(by_name["base"]).fillna("")
            status_matched.loc[unmatched] = seller_keys.map(by_name["status"]).fillna(
                ""
            )
            missing_login = unmatched & login_matched.eq("")
            if missing_login.any():
                login_matched.loc[missing_login] = (
                    seller_raw.loc[missing_login]
                    .map(normalize_text)
                    .map(by_name["_login_clean"])
                    .fillna("")
                )

    monitor_clean = monitor_matched.replace({"Sem monitor": "", "": pd.NA}).fillna(
        "Não Identificado"
    )
    un_clean = un_matched.replace({"Sem U.N.": "", "": pd.NA}).fillna(
        "Não Identificada"
    )
    base_clean = base_matched.replace({"Sem base": "", "": pd.NA}).fillna(
        "Não Identificada"
    )
    status_clean = status_matched.replace({"": pd.NA}).fillna("Não cadastrado")

    login_final = login_matched.replace({"": pd.NA}).fillna("SEM LOGIN")
    vendedor_final = (
        tech_matched.replace({"": pd.NA})
        .fillna(seller_raw.replace({"": pd.NA}))
        .fillna(login_final.replace({"SEM LOGIN": pd.NA}))
        .fillna("Nome Não Cadastrado")
    )

    dt_series = converter_data_consultivo_br(work["reference_date"])
    q_cons = (
        pd.to_numeric(work["qtde_consultivo"], errors="coerce").fillna(0).astype(int)
    )
    q_prod = pd.to_numeric(work["qtde_produtos"], errors="coerce").fillna(0).astype(int)
    q_mesh = pd.to_numeric(work["qtde_mesh"], errors="coerce").fillna(0).astype(int)
    q_tv = pd.to_numeric(work["qtde_tv"], errors="coerce").fillna(0).astype(int)
    q_virtua = pd.to_numeric(work["qtde_virtua"], errors="coerce").fillna(0).astype(int)

    return pd.DataFrame(
        {
            "DATA": dt_series,
            "period": dt_series.dt.to_period("M").dt.to_timestamp(),
            "LOGIN NETSALES": login_final.astype(str),
            "VENDEDOR": vendedor_final.astype(str),
            "Técnico": tech_matched.astype(str),
            "Monitor": monitor_clean.astype(str),
            "U.N.": un_clean.astype(str),
            "Base": base_clean.astype(str),
            "Situação": status_clean.astype(str),
            "Qtde. Cons.": q_cons,
            "Qtde. Prod.": q_prod,
            "Qtde. Mesh": q_mesh,
            "Qtde. TV": q_tv,
            "Qtde. Virtua": q_virtua,
            "QTDE_CONSULTIVO": q_cons,
            "QTDE_PRODUTOS": q_prod,
            "QTDE_MESH": q_mesh,
            "QTDE_TV": q_tv,
            "QTDE_VIRTUA": q_virtua,
            "CONTRATO": work.get("contract", pd.Series("", index=work.index))
            .fillna("")
            .astype(str),
            "HP": work.get("hp", pd.Series("", index=work.index))
            .fillna("")
            .astype(str),
            "CÓDIGO CONTATO": work.get("contact_code", pd.Series("", index=work.index))
            .fillna("")
            .astype(str),
            "TIPO DE TABULAÇÃO": work.get(
                "tabulation_type", pd.Series("", index=work.index)
            )
            .fillna("")
            .astype(str),
            "STATUS NETSALES": work.get(
                "status_netsales", pd.Series("", index=work.index)
            )
            .fillna("")
            .astype(str),
            "TIPO SERVIÇO": work.get(
                "tipo_servico", pd.Series("Sem Tipo", index=work.index)
            )
            .fillna("Sem Tipo")
            .astype(str),
            "PLANO TV": work.get("plano_tv", pd.Series("", index=work.index))
            .fillna("")
            .astype(str),
            "PLANO INTERNET": work.get(
                "plano_internet", pd.Series("", index=work.index)
            )
            .fillna("")
            .astype(str),
            "source_file": work["source_file"].astype(str),
            "source_row": pd.to_numeric(work["source_row"], errors="coerce")
            .fillna(0)
            .astype(int),
            "is_demo": pd.to_numeric(work["is_demo"], errors="coerce")
            .fillna(0)
            .astype(int),
            "imported_at": work["imported_at"].fillna("").astype(str),
        }
    )


def _read_consultivo_rows(connection: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT id, reference_date, login_netsales, seller, hp, contact_code,
               contract, tabulation_type, status_netsales, plano_tv,
               plano_internet, tipo_servico, qtde_consultivo, qtde_produtos,
               qtde_mesh, qtde_tv, qtde_virtua, source_file, source_row,
               is_demo, imported_at
        FROM consultivo_records
        ORDER BY reference_date, id
        """,
        connection,
    )


def load_consultivo_records() -> pd.DataFrame:
    """Carrega o histórico consultivo enriquecido com lista_ativos / desligados."""
    init_database()
    with connect() as connection:
        raw = _read_consultivo_rows(connection)
        roster = _read_roster_rows(connection)
    return enrich_consultivo_with_roster(raw, roster)


def load_consultivo_snapshot() -> tuple[pd.DataFrame, dict]:
    """Carrega os registros de consultivo e suas estatísticas em uma única conexão."""
    init_database()
    with connect() as connection:
        raw = _read_consultivo_rows(connection)
        roster = _read_roster_rows(connection)
        stats = dict(
            connection.execute(
                """
                SELECT COUNT(*) AS records,
                       COUNT(DISTINCT source_file) AS files,
                       MIN(reference_date) AS first_date,
                       MAX(reference_date) AS last_date,
                       MAX(imported_at) AS last_import,
                       COALESCE(SUM(is_demo), 0) AS demo_rows,
                       COALESCE(SUM(qtde_consultivo), 0) AS total_consultivos,
                       COALESCE(SUM(qtde_produtos), 0) AS total_produtos
                FROM consultivo_records
                """
            ).fetchone()
        )
    enriched = enrich_consultivo_with_roster(raw, roster)
    return enriched, stats


def consultivo_import_batches() -> pd.DataFrame:
    """Resumo por arquivo de consultivo importado."""
    init_database()
    with connect() as connection:
        return pd.read_sql_query(
            """
            SELECT source_file,
                   COUNT(*) AS rows_count,
                   COALESCE(SUM(qtde_consultivo), 0) AS consultivos_count,
                   COALESCE(SUM(qtde_produtos), 0) AS produtos_count,
                   MAX(imported_at) AS imported_at
            FROM consultivo_records
            GROUP BY source_file
            ORDER BY imported_at DESC, source_file
            """,
            connection,
        )


def clear_demonstration() -> None:
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM production_records WHERE is_demo = 1")
        connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
        connection.execute("DELETE FROM consultivo_records WHERE is_demo = 1")
    set_setting("demo_disabled", "1")
    set_setting("consultivo_demo_disabled", "1")


def clear_database() -> None:
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM production_records")
        connection.execute("DELETE FROM technician_roster")
        connection.execute("DELETE FROM consultivo_records")
        connection.execute("DELETE FROM drive_file_metadata")
    set_setting("demo_disabled", "1")
    set_setting("consultivo_demo_disabled", "1")


def _seed_consultivo_demonstration(
    names: list[str],
    periods: pd.PeriodIndex,
) -> None:
    if get_setting("consultivo_demo_disabled") == "1":
        return
    with connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(is_demo), 0) AS demo_rows,
                   MIN(reference_date) AS first_date
            FROM consultivo_records
            """
        ).fetchone()
        if row and int(row["total"]) > 0:
            is_pure_demo = int(row["demo_rows"]) == int(row["total"])
            first_date = str(row["first_date"] or "")
            if not is_pure_demo or (first_date and first_date <= "2025-01-31"):
                return
            connection.execute("DELETE FROM consultivo_records WHERE is_demo = 1")

    consultivo_demo: list[dict] = []
    seq = 1
    for month_index, period in enumerate(periods):
        source_file = f"{DEMO_SOURCE}_consultivo_{period.strftime('%Y-%m')}.csv"
        file_row = 2
        for tech_index, technician in enumerate(names):
            # Mantém 2 técnicos ativos zerados na competência mais recente para exercitar
            # "Técnicos Zerados" e "Equipes sem Consultivos" na demonstração.
            if month_index == len(periods) - 1 and tech_index >= len(names) - 2:
                continue
            login = f"Z64{tech_index:04d}"
            bonus_2026 = (
                1 if period.year >= 2026 and (tech_index + month_index) % 3 == 0 else 0
            )
            entries = 2 + ((tech_index + month_index) % 4) + bonus_2026
            for offset in range(entries):
                day_num = min(27, 2 + offset * 4 + (tech_index % 4))
                ref_date = (
                    period.to_timestamp().replace(day=day_num).strftime("%Y-%m-%d")
                )
                kind = (tech_index + month_index + offset) % 4
                if kind == 0:
                    extra_mesh = 1 if period.year >= 2026 and offset == 0 else 0
                    q_cons, q_prod, q_mesh, q_tv, q_vir = (
                        1,
                        2 + extra_mesh,
                        2 + extra_mesh,
                        0,
                        0,
                    )
                    plano_tv, plano_net, tipo_serv = (
                        "",
                        "SERVIÇOS AVANÇADOS",
                        "SERVIÇOS AVANÇADOS",
                    )
                elif kind == 1:
                    q_cons, q_prod, q_mesh, q_tv, q_vir = 1, 1, 0, 0, 1
                    plano_tv, plano_net, tipo_serv = (
                        "",
                        "1 GIGA (FIBRA)",
                        "1 GIGA (FIBRA)",
                    )
                elif kind == 2:
                    q_cons, q_prod, q_mesh, q_tv, q_vir = 1, 1, 0, 1, 0
                    plano_tv, plano_net, tipo_serv = (
                        "CLARO TV+ BOX",
                        "",
                        "CLARO TV+ BOX",
                    )
                else:
                    q_cons, q_prod, q_mesh, q_tv, q_vir = 2, 3, 1, 1, 1
                    plano_tv, plano_net, tipo_serv = (
                        "CLARO TV+ BOX",
                        "600 MEGA (FIBRA)",
                        "CLARO TV+ BOX & 600 MEGA (FIBRA)",
                    )
                consultivo_demo.append(
                    {
                        "reference_date": ref_date,
                        "login_netsales": login,
                        "seller": technician,
                        "hp": f"1193{seq:06d}",
                        "contact_code": f"1127{seq:05d}",
                        "contract": f"CT-{((tech_index + month_index * 3 + offset) % 12) + 1:03d}",
                        "tabulation_type": "VENDA",
                        "status_netsales": "INSTALADA",
                        "plano_tv": plano_tv,
                        "plano_internet": plano_net,
                        "tipo_servico": tipo_serv,
                        "qtde_consultivo": q_cons,
                        "qtde_produtos": q_prod,
                        "qtde_mesh": q_mesh,
                        "qtde_tv": q_tv,
                        "qtde_virtua": q_vir,
                        "source_file": source_file,
                        "source_row": file_row,
                    }
                )
                seq += 1
                file_row += 1
        # Inclui histórico de colaborador hoje desligado nas competências anteriores (especialmente 2025).
        if period.year == 2025 or month_index < len(periods) - 3:
            consultivo_demo.append(
                {
                    "reference_date": period.to_timestamp()
                    .replace(day=15)
                    .strftime("%Y-%m-%d"),
                    "login_netsales": "Z649002",
                    "seller": "Tiago Henrique Mendes",
                    "hp": f"1193{seq:06d}",
                    "contact_code": f"1127{seq:05d}",
                    "contract": "CT-099",
                    "tabulation_type": "VENDA",
                    "status_netsales": "INSTALADA",
                    "plano_tv": "",
                    "plano_internet": "SERVIÇOS AVANÇADOS",
                    "tipo_servico": "SERVIÇOS AVANÇADOS",
                    "qtde_consultivo": 1,
                    "qtde_produtos": 2 if period.year == 2025 else 1,
                    "qtde_mesh": 2 if period.year == 2025 else 1,
                    "qtde_tv": 0,
                    "qtde_virtua": 0,
                    "source_file": source_file,
                    "source_row": file_row,
                }
            )
            seq += 1
    save_consultivo_records(consultivo_demo, is_demo=True)


def create_demonstration() -> None:
    """Cria uma base identificada apenas quando o banco está vazio."""
    init_database()
    if os.getenv("SHOW_DEMO_DATA", "1") == "0":
        return

    names = [
        "André Santos",
        "Bruno Oliveira",
        "Carlos Ferreira",
        "Diego Almeida",
        "Eduardo Lima",
        "Felipe Rocha",
        "Gustavo Martins",
        "Henrique Souza",
        "Igor Cardoso",
        "João Pedro Silva",
        "Lucas Moreira",
        "Marcelo Dias",
    ]
    demo_monitors = [
        ("Edson Marco Pinheiro", "ABCDM-TOTALE", "NET-ABCDM"),
        ("Adriano Nascimento da Silva", "GRS-TOTALE", "NET-GUARULHOS"),
        ("Elisangela Cassimiro Goncalves", "SPO-TOTALLESTE", "NET-LESTE"),
    ]
    end_period = max(
        pd.Period("2026-10", freq="M"), pd.Timestamp.today().to_period("M")
    )
    periods = pd.period_range(start="2025-01", end=end_period, freq="M")
    consultivo_periods = periods
    stats = database_stats()
    if get_setting("demo_disabled") == "1":
        return
    if stats["records"]:
        if stats["demo_rows"] == stats["records"]:
            min_date = str(stats.get("min_date") or "")
            if min_date and min_date <= "2025-01-31":
                _seed_consultivo_demonstration(names, consultivo_periods)
                return
            with connect() as connection:
                connection.execute("DELETE FROM production_records WHERE is_demo = 1")
                connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
        else:
            return

    records: list[dict] = []
    source_row = 2
    for tech_index, technician in enumerate(names):
        project_name = demo_monitors[tech_index % len(demo_monitors)][2]
        for month_index, period in enumerate(periods):
            # Série determinística 2025–2026 com múltiplos contratos e giro O.S./contrato realista.
            year_boost = 1.09 if period.year >= 2026 else 1.0
            prod_total = round(
                (
                    480
                    + tech_index * 42
                    + (month_index % 12) * (15 + (tech_index % 4) * 3)
                    + ((tech_index * 7 + month_index * 5) % 9) * 34
                )
                * year_boost,
                2,
            )
            gpon_total = round(
                (
                    165
                    + (tech_index % 6) * 35
                    + (month_index % 12) * (7 + tech_index % 3)
                    + ((tech_index * 3 + month_index * 2) % 7) * 22
                )
                * year_boost,
                2,
            )
            if (tech_index + month_index) % 11 == 0:
                gpon_total = 0.0

            contracts_in_month = (
                2
                + (tech_index + month_index * 2) % 3
                + (
                    1
                    if period.year >= 2026 and (tech_index + month_index) % 3 == 0
                    else 0
                )
            )
            pool = 18 + (month_index % 8)
            month_contracts = [
                f"CT-{((tech_index * 5 + month_index * 3 + c_idx * 7) % pool) + 1:03d}"
                for c_idx in range(contracts_in_month)
            ]
            # Garante contratos distintos dentro da competência do técnico.
            distinct_contracts: list[str] = []
            for idx_ct, candidate in enumerate(month_contracts):
                if candidate in distinct_contracts:
                    candidate = f"CT-{pool + idx_ct + 1:03d}"
                distinct_contracts.append(candidate)

            extra_os = 1 + ((tech_index + month_index) % 2)
            total_os_rows = len(distinct_contracts) + extra_os
            os_weights = [1.25 if i == 0 else 1.0 for i in range(total_os_rows)]
            weight_sum = sum(os_weights)
            allocated_prod = 0.0
            for os_idx in range(total_os_rows):
                ct = distinct_contracts[os_idx % len(distinct_contracts)]
                if os_idx == total_os_rows - 1:
                    pts = round(prod_total - allocated_prod, 2)
                else:
                    pts = round(prod_total * (os_weights[os_idx] / weight_sum), 2)
                    allocated_prod = round(allocated_prod + pts, 2)
                records.append(
                    {
                        "technician": technician,
                        "reference_date": period.to_timestamp().strftime("%Y-%m-%d"),
                        "source_sheet": PROD,
                        "project": project_name,
                        "contract": ct,
                        "points": float(pts),
                        "source_file": f"{DEMO_SOURCE}_{period.strftime('%Y-%m')}",
                        "source_row": source_row,
                    }
                )
                source_row += 1

            records.append(
                {
                    "technician": technician,
                    "reference_date": period.to_timestamp().strftime("%Y-%m-%d"),
                    "source_sheet": GPON,
                    "project": project_name,
                    "contract": distinct_contracts[0],
                    "points": float(gpon_total),
                    "source_file": f"{DEMO_SOURCE}_{period.strftime('%Y-%m')}",
                    "source_row": source_row,
                }
            )
            source_row += 1

    # Histórico 2025 de colaborador desligado para exercitar escopos de equipe no comparativo 2025 x 2026.
    for month_index, period in enumerate(periods):
        if period.year != 2025 or period.month > 8:
            continue
        for ct_offset in range(2):
            records.append(
                {
                    "technician": "Tiago Henrique Mendes",
                    "reference_date": period.to_timestamp().strftime("%Y-%m-%d"),
                    "source_sheet": PROD,
                    "project": "NET-GUARULHOS",
                    "contract": f"CT-9{period.month:02d}{ct_offset}",
                    "points": float(210 + month_index * 12 + ct_offset * 35),
                    "source_file": f"{DEMO_SOURCE}_{period.strftime('%Y-%m')}",
                    "source_row": source_row,
                }
            )
            source_row += 1

    save_records(records, is_demo=True)
    demo_roster = [
        {
            "technician": technician,
            "re_code": str(8100 + index),
            "login": f"Z64{index:04d}",
            "monitor": demo_monitors[index % len(demo_monitors)][0],
            "un": demo_monitors[index % len(demo_monitors)][1],
            "base": demo_monitors[index % len(demo_monitors)][2],
            "status": "ATIVO",
            "source_tab": ROSTER_ACTIVE_TAB,
            "last_modified": pd.Timestamp.today().strftime("%Y-%m-%d"),
        }
        for index, technician in enumerate(names)
    ]
    demo_roster.extend(
        [
            {
                "technician": "Rafael Augusto Pereira",
                "re_code": "8290",
                "login": "Z649001",
                "monitor": demo_monitors[0][0],
                "un": demo_monitors[0][1],
                "base": demo_monitors[0][2],
                "status": "FÉRIAS",
                "source_tab": ROSTER_ACTIVE_TAB,
                "last_modified": pd.Timestamp.today().strftime("%Y-%m-%d"),
            },
            {
                "technician": "Tiago Henrique Mendes",
                "re_code": "7980",
                "login": "Z649002",
                "monitor": demo_monitors[1][0],
                "un": demo_monitors[1][1],
                "base": demo_monitors[1][2],
                "status": "DESLIGADO",
                "source_tab": ROSTER_TERMINATED_TAB,
                "last_modified": pd.Timestamp.today().strftime("%Y-%m-%d"),
                "termination_date": pd.Timestamp.today().strftime("%Y-%m-%d"),
                "termination_reason": "Encerramento de contrato",
            },
        ]
    )
    save_roster_records(demo_roster, is_demo=True)
    _seed_consultivo_demonstration(names, consultivo_periods)


def summarize(frame: pd.DataFrame, keys: str | list[str]) -> pd.DataFrame:
    """Agrupa qualquer recorte mantendo a fórmula oficial dos pontos totais."""
    if isinstance(keys, str):
        keys = [keys]
    columns = keys + ["points_prod", "points_gpon", "points_total"]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    work = frame.copy(deep=False)
    work["points_prod"] = work["points"].where(work["source_sheet"].eq(PROD), 0.0)
    work["points_gpon"] = work["points"].where(work["source_sheet"].eq(GPON), 0.0)
    if not keys:
        return pd.DataFrame(
            [
                {
                    "points_prod": work["points_prod"].sum(),
                    "points_gpon": work["points_gpon"].sum(),
                    "points_total": work["points"].sum(),
                }
            ]
        )
    result = work.groupby(keys, as_index=False, dropna=False)[
        ["points_prod", "points_gpon"]
    ].sum()
    result["points_total"] = result["points_prod"] + result["points_gpon"]
    return result[columns]


def count_active_months_by_technician(frame: pd.DataFrame) -> pd.Series:
    """Conta as competências com registros de produção para cada técnico."""
    if frame.empty:
        return pd.Series(dtype="int64", name="active_months")
    return (
        frame.groupby("technician", dropna=False)["period"]
        .nunique()
        .rename("active_months")
    )


def best_month_by_technician(frame: pd.DataFrame) -> pd.Series:
    """Retorna o mês com mais Pontos Totais por técnico no recorte."""
    if frame.empty:
        return pd.Series(dtype="object", name="best_month")

    monthly = summarize(frame, ["technician", "period"])
    best = (
        monthly.sort_values(["points_total", "period"], ascending=[False, False])
        .drop_duplicates("technician")
        .set_index("technician")
    )
    return best["period"].map(month_label).rename("best_month")


def summarize_os(frame: pd.DataFrame, keys: str | list[str]) -> pd.DataFrame:
    """Conta O.S. da aba Prod; cada linha válida importada equivale a uma O.S."""
    if isinstance(keys, str):
        keys = [keys]
    columns = keys + ["os_count"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    prod = frame[frame["source_sheet"].eq(PROD)].copy()
    if prod.empty:
        return pd.DataFrame(columns=columns)
    if not keys:
        return pd.DataFrame([{"os_count": len(prod)}])
    return (
        prod.groupby(keys, as_index=False, dropna=False)
        .size()
        .rename(columns={"size": "os_count"})[columns]
    )


def month_label(value: float | str | date | datetime, include_year: bool = True) -> str:
    timestamp = pd.Timestamp(value)
    label = MONTHS_SHORT[timestamp.month - 1]
    return f"{label}/{str(timestamp.year)[2:]}" if include_year else label.capitalize()


def format_points(value: object) -> str:
    """Formata pontos sempre com duas casas decimais no padrão pt-BR."""
    number = float(str(value or 0))
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
