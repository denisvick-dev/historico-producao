"""Regras de negócio e persistência do histórico de produção.

O módulo não depende do Streamlit para facilitar testes e reutilização.
Cada linha importada é mantida em sua origem (Prod ou Gpon); os relatórios
fazem a agregação e calculam sempre Pontos Totais = Prod + Gpon.
"""

from __future__ import annotations

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
ROSTER_METADATA_SCOPE = "__roster_sheet__"
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

    match = re.fullmatch(r"(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?", text)
    if match:
        year, month, day = match.groups()
        try:
            return pd.Timestamp(int(year), int(month), int(day or 1))
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

    timestamp = pd.to_datetime(text, dayfirst=True, errors="coerce")
    return timestamp.normalize() if isinstance(timestamp, pd.Timestamp) else None


def infer_date_from_filename(filename: str) -> pd.Timestamp | None:
    stem = Path(filename).stem
    match = re.search(r"(?<!\d)(20\d{2})[-_.](0?[1-9]|1[0-2])(?!\d)", stem)
    if match:
        return pd.Timestamp(int(match.group(1)), int(match.group(2)), 1)
    match = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[-_.](20\d{2})(?!\d)", stem)
    if match:
        return pd.Timestamp(int(match.group(2)), int(match.group(1)), 1)
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


def clear_demonstration() -> None:
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM production_records WHERE is_demo = 1")
        connection.execute("DELETE FROM technician_roster WHERE is_demo = 1")
    set_setting("demo_disabled", "1")


def clear_database() -> None:
    init_database()
    with connect() as connection:
        connection.execute("DELETE FROM production_records")
        connection.execute("DELETE FROM technician_roster")
        connection.execute("DELETE FROM drive_file_metadata")
    set_setting("demo_disabled", "1")


def create_demonstration() -> None:
    """Cria uma base identificada apenas quando o banco está vazio."""
    init_database()
    stats = database_stats()
    if stats["records"] or get_setting("demo_disabled") == "1":
        return
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
    periods = pd.period_range(
        end=pd.Timestamp.today().to_period("M"), periods=12, freq="M"
    )
    records: list[dict] = []
    for tech_index, technician in enumerate(names):
        for month_index, period in enumerate(periods):
            # Série determinística com tendência e variações entre técnicos/meses.
            prod = (
                520
                + tech_index * 47
                + month_index * (18 + tech_index % 4 * 3)
                + ((tech_index * 7 + month_index * 5) % 9) * 38
            )
            gpon = (
                180
                + (tech_index % 6) * 39
                + month_index * (8 + tech_index % 3)
                + ((tech_index * 3 + month_index * 2) % 7) * 24
            )
            if (tech_index + month_index) % 11 == 0:
                gpon = 0
            # Carteira demonstrativa: o pool de contratos cresce mês a mês.
            pool = 8 + month_index % 6
            contract = f"CT-{((tech_index + month_index * 3) % pool) + 1:03d}"
            for origin, points in ((PROD, prod), (GPON, gpon)):
                records.append(
                    {
                        "technician": technician,
                        "reference_date": period.to_timestamp().strftime("%Y-%m-%d"),
                        "source_sheet": origin,
                        "contract": contract,
                        "points": float(points),
                        # Um arquivo por competência, como nas exportações do Drive.
                        "source_file": f"{DEMO_SOURCE}_{period.strftime('%Y-%m')}",
                        "source_row": tech_index * len(periods) + month_index + 2,
                    }
                )
    save_records(records, is_demo=True)
    demo_monitors = [
        ("Edson Marco Pinheiro", "ABCDM-TOTALE", "NET-ABCDM"),
        ("Adriano Nascimento da Silva", "GRS-TOTALE", "NET-GUARULHOS"),
        ("Elisangela Cassimiro Goncalves", "SPO-TOTALLESTE", "NET-LESTE"),
    ]
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
