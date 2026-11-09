from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import pandas as pd
import requests
import structlog
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from tenacity import retry, stop_after_attempt, wait_exponential

from production import PROD, process_upload

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
SUPPORTED_SUFFIXES = {".csv", ".xls", ".xlsx"}
MAX_PARALLEL_DOWNLOADS = 8
IMPORT_PARSER_VERSION = "contracts-v2"

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


@retry(
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
    while True:
        params: dict[str, str | int | bool] = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": (
                "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,size)"
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
        if not isinstance(page, dict) or not isinstance(page.get("files", []), list):
            raise DriveImportError(
                "O Google Drive retornou uma lista de arquivos inválida."
            )
        files.extend(file for file in page.get("files", []) if isinstance(file, dict))
        page_token = page.get("nextPageToken")
        if not page_token:
            return files


def _file_fingerprint(drive_file: dict[str, str]) -> str | None:
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
            params={"alt": "media"},
        )
    return filename, response.content


def _import_drive_file(
    credentials: Any,
    service_account_info: Mapping[str, Any],
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
        worker_session = (
            AuthorizedSession(credentials)
            if credentials is not None
            else create_drive_session(service_account_info)
        )
        downloaded = download_file(worker_session, drive_file)
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
    logger.info("iniciando_sincronizacao_drive", pasta_id=folder_id)
    session = create_drive_session(service_account_info)
    files = list_folder_files(session, folder_id)
    records: list[dict] = []
    issues: list[str] = []
    successful_files = 0
    file_ids = {
        file_id for drive_file in files if (file_id := drive_file.get("id", "").strip())
    }
    refreshed_file_ids: set[str] = set()
    file_fingerprints: dict[str, str] = {}
    credentials = getattr(session, "credentials", None)
    known_file_fingerprints = known_file_fingerprints or {}
    changed_files: list[dict[str, str]] = []
    for drive_file in files:
        fingerprint = _file_fingerprint(drive_file)
        file_id = drive_file.get("id", "")
        if fingerprint is None or fingerprint != known_file_fingerprints.get(file_id):
            changed_files.append(drive_file)

    if changed_files:
        with ThreadPoolExecutor(
            max_workers=min(MAX_PARALLEL_DOWNLOADS, len(changed_files))
        ) as executor:
            results = executor.map(
                lambda drive_file: _import_drive_file(
                    credentials,
                    service_account_info,
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
                        fingerprint = _file_fingerprint(drive_file)
                        if fingerprint is not None:
                            file_fingerprints[file_id] = fingerprint
                if file_records:
                    records.extend(file_records)
                    successful_files += 1
                issues.extend(file_issues)

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
