from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock, local
from time import perf_counter
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
import structlog
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from production import (
    PROD,
    extract_drive_folder_id,
    extract_spreadsheet_id,
    process_consultivo_upload,
    process_roster_workbook,
    process_upload,
)

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
GOOGLE_SHEETS_EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
SUPPORTED_SUFFIXES = {".csv", ".xls", ".xlsx"}
MAX_PARALLEL_DOWNLOADS = 8
IMPORT_PARSER_VERSION = "contracts-v2"
ROSTER_PARSER_VERSION = "roster-v2"
CONSULTIVO_PARSER_VERSION = "consultivo-v2"

logger = structlog.get_logger(__name__)


class DriveImportError(RuntimeError):
    """Erro ao autenticar ou consultar arquivos no Google Drive."""


@dataclass(frozen=True)
class DriveFolderImport:
    records: list[dict]
    issues: list[str]
    successful_files: int
    file_ids: set[str]
    refreshed_file_ids: set[str]
    file_fingerprints: dict[str, str]


@dataclass(frozen=True)
class RosterSheetImport:
    records: list[dict]
    issues: list[str]
    refreshed: bool
    unchanged: bool
    fingerprint: str | None
    sheet_name: str


def create_drive_session(
    service_account_info: Mapping[str, Any],
) -> AuthorizedSession:
    try:
        credentials = Credentials.from_service_account_info(
            dict(service_account_info), scopes=[DRIVE_SCOPE]
        )
    except (GoogleAuthError, KeyError, TypeError, ValueError) as error:
        raise DriveImportError(
            "As credenciais da conta de serviço do Google Drive são inválidas."
        ) from error
    return AuthorizedSession(credentials)


def _is_transient_error(error: BaseException) -> bool:
    cause = error.__cause__
    if isinstance(cause, requests.HTTPError):
        return cause.response is not None and (
            cause.response.status_code == 429 or cause.response.status_code >= 500
        )
    return isinstance(cause, (requests.ConnectionError, requests.Timeout))


@retry(
    retry=retry_if_exception(_is_transient_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _request(
    session: Any,
    url: str,
    *,
    params: dict[str, str | int | bool] | None = None,
) -> requests.Response:
    try:
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
    except requests.HTTPError as error:
        status = (
            error.response.status_code if error.response is not None else "desconhecido"
        )
        raise DriveImportError(
            f"O Google Drive retornou HTTP {status}. Confirme que a pasta foi "
            "compartilhada com a conta de serviço e que a API Drive está habilitada."
        ) from error
    except (GoogleAuthError, requests.RequestException) as error:
        raise DriveImportError(
            "Não foi possível acessar o Google Drive. Verifique a conexão e as credenciais."
        ) from error
    return response


def list_folder_files(session: Any, folder_id: str) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    page_token: str | None = None
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, str | int | bool] = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": (
                "nextPageToken,incompleteSearch,files(id,name,mimeType,modifiedTime,md5Checksum,size)"
            ),
            "pageSize": 1000,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if page_token:
            params["pageToken"] = page_token
        response = _request(session, f"{DRIVE_API_URL}/files", params=params)
        try:
            page = response.json()
        except ValueError as error:
            raise DriveImportError(
                "O Google Drive retornou uma resposta inválida."
            ) from error
        if (
            not isinstance(page, dict)
            or not isinstance(page.get("files"), list)
            or page.get("incompleteSearch", False) is not False
            or any(
                not isinstance(item, dict)
                or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("id", "name", "mimeType")
                )
                or any(
                    key in item and not isinstance(item[key], str)
                    for key in ("modifiedTime", "md5Checksum", "size")
                )
                for item in page["files"]
            )
        ):
            raise DriveImportError(
                "O Google Drive retornou uma lista de arquivos incompleta ou inválida."
            )
        files.extend(page["files"])
        page_token = page.get("nextPageToken")
        if page_token is None or page_token == "":
            return files
        if not isinstance(page_token, str) or page_token in seen_tokens:
            raise DriveImportError("O Google Drive retornou uma paginação inválida.")
        seen_tokens.add(page_token)


def _file_fingerprint(
    drive_file: dict[str, str],
    *,
    csv_origin: str = PROD,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> str | None:
    modified_time = drive_file.get("modifiedTime", "")
    checksum = drive_file.get("md5Checksum", "")
    size = drive_file.get("size", "")
    if not (modified_time or checksum or size):
        return None
    return "|".join(
        (
            drive_file.get("name", ""),
            drive_file.get("mimeType", ""),
            modified_time,
            checksum,
            size,
            IMPORT_PARSER_VERSION,
            csv_origin,
            str(default_date) if default_date is not None else "",
        )
    )


def _source_filename(file: dict[str, str]) -> str | None:
    name = file.get("name", "").strip()
    suffix = Path(name).suffix.lower()
    if file.get("mimeType") == GOOGLE_SHEET_MIME_TYPE:
        suffix = ".xlsx"
    elif suffix not in SUPPORTED_SUFFIXES:
        return None

    stem = Path(name).stem or "planilha"
    file_id = file.get("id", "").strip()
    if not file_id:
        return None
    return f"{stem} [{file_id}]{suffix}"


def download_file(session: Any, file: dict[str, str]) -> tuple[str, bytes] | None:
    filename = _source_filename(file)
    if filename is None:
        return None

    file_id = quote(file["id"], safe="")
    if file.get("mimeType") == GOOGLE_SHEET_MIME_TYPE:
        response = _request(
            session,
            f"{DRIVE_API_URL}/files/{file_id}/export",
            params={
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            },
        )
    else:
        response = _request(
            session,
            f"{DRIVE_API_URL}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": True},
        )
    return filename, response.content


def _import_drive_file(
    get_session: Callable[[], Any],
    drive_file: dict[str, str],
    *,
    csv_origin: str,
    default_date: date | datetime | pd.Timestamp | None,
) -> tuple[list[dict], list[str], bool]:
    drive_name = drive_file.get("name", "Arquivo sem nome")
    if _source_filename(drive_file) is None:
        return (
            [],
            [
                f"{drive_name} · formato não suportado; use XLSX, XLS, CSV ou Planilhas Google."
            ],
            False,
        )

    try:
        downloaded = download_file(get_session(), drive_file)
    except DriveImportError as error:
        return [], [f"{drive_name} · {error}"], False
    if downloaded is None:
        return (
            [],
            [
                f"{drive_name} · formato não suportado; use XLSX, XLS, CSV ou Planilhas Google."
            ],
            False,
        )

    filename, content = downloaded
    try:
        file_records, file_issues = process_upload(
            filename,
            content,
            csv_origin=csv_origin,
            default_date=default_date,
        )
    except ValueError as error:
        return [], [f"{drive_name} · {error}"], False

    # O arquivo foi baixado e processado: mesmo com issues pontuais (linhas
    # inválidas), o fingerprint deve ser salvo para não rebaixar o arquivo a
    # cada sincronização. Só os retornos antecipados acima (formato não
    # suportado, falha de download ou erro fatal de leitura) não refrescam.
    refreshed = True
    issues = [f"{drive_name} · {issue}" for issue in file_issues[:20]]
    return file_records, issues, refreshed


def import_drive_folder_snapshot(
    service_account_info: Mapping[str, Any],
    folder_id: str,
    *,
    csv_origin: str = PROD,
    default_date: date | datetime | pd.Timestamp | None = None,
    known_file_fingerprints: Mapping[str, str] | None = None,
) -> DriveFolderImport:
    started = perf_counter()
    logger.info("iniciando_sincronizacao_drive", pasta_id=folder_id)
    session = create_drive_session(service_account_info)
    try:
        files = list_folder_files(session, folder_id)
        # Cada worker recebe uma cópia independente com o token já obtido na
        # listagem. Renovações posteriores não compartilham estado mutável.
        credentials = getattr(session, "credentials", None)
    finally:
        if callable(getattr(session, "close", None)):
            session.close()
    listing_seconds = perf_counter() - started
    records: list[dict] = []
    issues: list[str] = []
    successful_files = 0
    file_ids = {
        file_id for drive_file in files if (file_id := drive_file.get("id", "").strip())
    }
    refreshed_file_ids: set[str] = set()
    file_fingerprints: dict[str, str] = {}
    known_file_fingerprints = known_file_fingerprints or {}
    changed_files: list[dict[str, str]] = []
    for drive_file in files:
        fingerprint = _file_fingerprint(
            drive_file, csv_origin=csv_origin, default_date=default_date
        )
        file_id = drive_file.get("id", "")
        if fingerprint is None or fingerprint != known_file_fingerprints.get(file_id):
            changed_files.append(drive_file)

    if changed_files:
        thread_state = local()
        sessions: list[Any] = []
        sessions_lock = Lock()

        def get_worker_session() -> Any:
            worker_session = getattr(thread_state, "session", None)
            if worker_session is None:
                worker_session = (
                    AuthorizedSession(copy(credentials))
                    if credentials is not None
                    else create_drive_session(service_account_info)
                )
                thread_state.session = worker_session
                with sessions_lock:
                    sessions.append(worker_session)
            return worker_session

        try:
            with ThreadPoolExecutor(
                max_workers=min(MAX_PARALLEL_DOWNLOADS, len(changed_files))
            ) as executor:
                results = executor.map(
                    lambda drive_file: _import_drive_file(
                        get_worker_session,
                        drive_file,
                        csv_origin=csv_origin,
                        default_date=default_date,
                    ),
                    changed_files,
                )
                for drive_file, (file_records, file_issues, refreshed) in zip(
                    changed_files, results
                ):
                    if refreshed:
                        file_id = drive_file.get("id", "").strip()
                        if file_id:
                            refreshed_file_ids.add(file_id)
                            fingerprint = _file_fingerprint(
                                drive_file,
                                csv_origin=csv_origin,
                                default_date=default_date,
                            )
                            if fingerprint is not None:
                                file_fingerprints[file_id] = fingerprint
                    if file_records:
                        records.extend(file_records)
                        successful_files += 1
                    issues.extend(file_issues)
        finally:
            for worker_session in sessions:
                if callable(getattr(worker_session, "close", None)):
                    worker_session.close()

    if not files:
        issues.append("A pasta do Google Drive não contém arquivos.")
    logger.info(
        "sincronizacao_drive_concluida",
        pasta_id=folder_id,
        arquivos_encontrados=len(files),
        arquivos_processados=successful_files,
        arquivos_sem_alteracao=len(files) - len(changed_files),
        total_registros=len(records),
        total_issues=len(issues),
        duracao_listagem_segundos=round(listing_seconds, 3),
        duracao_total_segundos=round(perf_counter() - started, 3),
    )
    return DriveFolderImport(
        records=records,
        issues=issues,
        successful_files=successful_files,
        file_ids=file_ids,
        refreshed_file_ids=refreshed_file_ids,
        file_fingerprints=file_fingerprints,
    )


def import_drive_folder(
    service_account_info: Mapping[str, Any],
    folder_id: str,
    *,
    csv_origin: str = PROD,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> tuple[list[dict], list[str], int]:
    result = import_drive_folder_snapshot(
        service_account_info,
        folder_id,
        csv_origin=csv_origin,
        default_date=default_date,
    )
    return result.records, result.issues, result.successful_files


def _roster_fingerprint(drive_file: Mapping[str, str]) -> str | None:
    modified_time = drive_file.get("modifiedTime", "")
    checksum = drive_file.get("md5Checksum", "")
    size = drive_file.get("size", "")
    if not (modified_time or checksum or size):
        return None
    return "|".join(
        (
            drive_file.get("name", ""),
            drive_file.get("mimeType", ""),
            modified_time,
            checksum,
            size,
            ROSTER_PARSER_VERSION,
        )
    )


def get_file_metadata(session: Any, file_id: str) -> dict[str, str]:
    encoded_id = quote(file_id, safe="")
    response = _request(
        session,
        f"{DRIVE_API_URL}/files/{encoded_id}",
        params={
            "fields": "id,name,mimeType,modifiedTime,md5Checksum,size",
            "supportsAllDrives": True,
        },
    )
    try:
        payload = response.json()
    except ValueError as error:
        raise DriveImportError(
            "O Google Drive retornou metadados inválidos da planilha cadastral."
        ) from error
    if not isinstance(payload, dict) or not payload.get("id"):
        raise DriveImportError(
            "Não foi possível obter os metadados da planilha cadastral."
        )
    return {str(k): str(v) for k, v in payload.items() if v is not None}


def import_roster_spreadsheet(
    service_account_info: Mapping[str, Any] | None,
    spreadsheet_id: str,
    *,
    known_fingerprint: str | None = None,
    allow_public_fallback: bool = True,
) -> RosterSheetImport:
    """Sincroniza a planilha cadastral (lista_ativos / desligados) pelo ID."""
    clean_id = extract_spreadsheet_id(spreadsheet_id)
    if not clean_id:
        raise DriveImportError("O identificador da planilha cadastral é inválido.")

    started = perf_counter()
    last_drive_error: DriveImportError | None = None
    if service_account_info is not None:
        session = create_drive_session(service_account_info)
        try:
            metadata = get_file_metadata(session, clean_id)
            sheet_name = metadata.get("name", "lista_ativos")
            fingerprint = _roster_fingerprint(metadata)
            if fingerprint is not None and fingerprint == known_fingerprint:
                return RosterSheetImport(
                    records=[],
                    issues=[],
                    refreshed=False,
                    unchanged=True,
                    fingerprint=fingerprint,
                    sheet_name=sheet_name,
                )
            downloaded = download_file(session, metadata)
            if downloaded is None:
                raise DriveImportError(
                    f"O arquivo '{sheet_name}' não é uma planilha suportada."
                )
            filename, content = downloaded
            try:
                records, issues = process_roster_workbook(content, filename=filename)
            except ValueError as error:
                raise DriveImportError(f"{sheet_name} · {error}") from error
            logger.info(
                "sincronizacao_cadastro_concluida",
                planilha_id=clean_id,
                total_colaboradores=len(records),
                duracao_segundos=round(perf_counter() - started, 3),
                modo="service_account",
            )
            return RosterSheetImport(
                records=records,
                issues=issues,
                refreshed=True,
                unchanged=False,
                fingerprint=fingerprint,
                sheet_name=sheet_name,
            )
        except DriveImportError as error:
            if not allow_public_fallback:
                raise
            last_drive_error = error
        finally:
            if callable(getattr(session, "close", None)):
                session.close()

    if not allow_public_fallback and last_drive_error is not None:
        raise last_drive_error

    export_url = GOOGLE_SHEETS_EXPORT_URL.format(sheet_id=quote(clean_id, safe=""))
    http_session = requests.Session()
    try:
        response = _request(
            http_session,
            export_url,
            params={"format": "xlsx"},
        )
    except DriveImportError as error:
        if last_drive_error is not None:
            raise last_drive_error from error
        raise
    finally:
        http_session.close()

    content = response.content
    digest = hashlib.sha256(content).hexdigest()
    fingerprint = f"public-sha256|{digest}|{ROSTER_PARSER_VERSION}"
    if fingerprint == known_fingerprint:
        return RosterSheetImport(
            records=[],
            issues=[],
            refreshed=False,
            unchanged=True,
            fingerprint=fingerprint,
            sheet_name="lista_ativos",
        )
    try:
        records, issues = process_roster_workbook(
            content, filename=f"lista_ativos [{clean_id}].xlsx"
        )
    except ValueError as error:
        raise DriveImportError(f"lista_ativos · {error}") from error
    logger.info(
        "sincronizacao_cadastro_concluida",
        planilha_id=clean_id,
        total_colaboradores=len(records),
        duracao_segundos=round(perf_counter() - started, 3),
        modo="public_export",
    )
    return RosterSheetImport(
        records=records,
        issues=issues,
        refreshed=True,
        unchanged=False,
        fingerprint=fingerprint,
        sheet_name="lista_ativos",
    )


def _consultivo_file_fingerprint(drive_file: dict[str, str]) -> str | None:
    modified_time = drive_file.get("modifiedTime", "")
    checksum = drive_file.get("md5Checksum", "")
    size = drive_file.get("size", "")
    if not (modified_time or checksum or size):
        return None
    return "|".join(
        (
            drive_file.get("name", ""),
            drive_file.get("mimeType", ""),
            modified_time,
            checksum,
            size,
            CONSULTIVO_PARSER_VERSION,
        )
    )


def _import_consultivo_drive_file(
    get_session: Callable[[], Any],
    drive_file: dict[str, str],
) -> tuple[list[dict], list[str], bool]:
    drive_name = drive_file.get("name", "Arquivo sem nome")
    if _source_filename(drive_file) is None:
        return (
            [],
            [
                f"{drive_name} · formato não suportado; use XLSX, XLS, CSV ou Planilhas Google."
            ],
            False,
        )

    try:
        downloaded = download_file(get_session(), drive_file)
    except DriveImportError as error:
        return [], [f"{drive_name} · {error}"], False
    if downloaded is None:
        return (
            [],
            [
                f"{drive_name} · formato não suportado; use XLSX, XLS, CSV ou Planilhas Google."
            ],
            False,
        )

    filename, content = downloaded
    try:
        file_records, file_issues = process_consultivo_upload(filename, content)
    except ValueError as error:
        return [], [f"{drive_name} · {error}"], False

    refreshed = True
    issues = [f"{drive_name} · {issue}" for issue in file_issues[:20]]
    return file_records, issues, refreshed


def import_consultivo_folder_snapshot(
    service_account_info: Mapping[str, Any],
    folder_id: str,
    *,
    known_file_fingerprints: Mapping[str, str] | None = None,
) -> DriveFolderImport:
    """Sincroniza os arquivos CSV/XLSX da pasta Histórico Consultivo no Google Drive."""
    clean_folder_id = extract_drive_folder_id(folder_id)
    if not clean_folder_id:
        raise DriveImportError(
            "O identificador da pasta Histórico Consultivo é inválido."
        )

    started = perf_counter()
    logger.info("iniciando_sincronizacao_consultivo", pasta_id=clean_folder_id)
    session = create_drive_session(service_account_info)
    try:
        files = list_folder_files(session, clean_folder_id)
        credentials = getattr(session, "credentials", None)
    finally:
        if callable(getattr(session, "close", None)):
            session.close()
    listing_seconds = perf_counter() - started

    records: list[dict] = []
    issues: list[str] = []
    successful_files = 0
    file_ids = {
        file_id for drive_file in files if (file_id := drive_file.get("id", "").strip())
    }
    refreshed_file_ids: set[str] = set()
    file_fingerprints: dict[str, str] = {}
    known_file_fingerprints = known_file_fingerprints or {}
    changed_files: list[dict[str, str]] = []
    for drive_file in files:
        fingerprint = _consultivo_file_fingerprint(drive_file)
        file_id = drive_file.get("id", "")
        if fingerprint is None or fingerprint != known_file_fingerprints.get(file_id):
            changed_files.append(drive_file)

    if changed_files:
        thread_state = local()
        sessions: list[Any] = []
        sessions_lock = Lock()

        def get_worker_session() -> Any:
            worker_session = getattr(thread_state, "session", None)
            if worker_session is None:
                worker_session = (
                    AuthorizedSession(copy(credentials))
                    if credentials is not None
                    else create_drive_session(service_account_info)
                )
                thread_state.session = worker_session
                with sessions_lock:
                    sessions.append(worker_session)
            return worker_session

        try:
            with ThreadPoolExecutor(
                max_workers=min(MAX_PARALLEL_DOWNLOADS, len(changed_files))
            ) as executor:
                results = executor.map(
                    lambda drive_file: _import_consultivo_drive_file(
                        get_worker_session, drive_file
                    ),
                    changed_files,
                )
                for drive_file, (file_records, file_issues, refreshed) in zip(
                    changed_files, results
                ):
                    if refreshed:
                        file_id = drive_file.get("id", "").strip()
                        if file_id:
                            refreshed_file_ids.add(file_id)
                            fingerprint = _consultivo_file_fingerprint(drive_file)
                            if fingerprint is not None:
                                file_fingerprints[file_id] = fingerprint
                    if file_records:
                        records.extend(file_records)
                        successful_files += 1
                    issues.extend(file_issues)
        finally:
            for worker_session in sessions:
                if callable(getattr(worker_session, "close", None)):
                    worker_session.close()

    if not files:
        issues.append("A pasta de Histórico Consultivo não contém arquivos.")
    logger.info(
        "sincronizacao_consultivo_concluida",
        pasta_id=clean_folder_id,
        total_arquivos=len(files),
        arquivos_alterados=len(changed_files),
        arquivos_com_registros=successful_files,
        registros_importados=len(records),
        avisos=len(issues),
        listagem_segundos=round(listing_seconds, 3),
        duracao_segundos=round(perf_counter() - started, 3),
    )
    return DriveFolderImport(
        records=records,
        issues=issues,
        successful_files=successful_files,
        file_ids=file_ids,
        refreshed_file_ids=refreshed_file_ids,
        file_fingerprints=file_fingerprints,
    )
