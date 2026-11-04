from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

import pandas as pd
import requests
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from production import PROD, process_upload

DRIVE_API_URL = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
SUPPORTED_SUFFIXES = {".csv", ".xls", ".xlsx"}


class DriveImportError(RuntimeError):
    """Erro ao autenticar ou consultar arquivos no Google Drive."""


@dataclass(frozen=True)
class DriveFolderImport:
    records: list[dict]
    issues: list[str]
    successful_files: int
    file_ids: set[str]
    refreshed_file_ids: set[str]


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
        status = error.response.status_code if error.response is not None else "desconhecido"
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
            "fields": "nextPageToken,files(id,name,mimeType)",
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
            raise DriveImportError("O Google Drive retornou uma resposta inválida.") from error
        if not isinstance(page, dict) or not isinstance(page.get("files", []), list):
            raise DriveImportError("O Google Drive retornou uma lista de arquivos inválida.")
        files.extend(file for file in page.get("files", []) if isinstance(file, dict))
        page_token = page.get("nextPageToken")
        if not page_token:
            return files


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


def download_file(
    session: Any, file: dict[str, str]
) -> tuple[str, bytes] | None:
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


def import_drive_folder_snapshot(
    service_account_info: Mapping[str, Any],
    folder_id: str,
    *,
    csv_origin: str = PROD,
    default_date: date | datetime | pd.Timestamp | None = None,
) -> DriveFolderImport:
    session = create_drive_session(service_account_info)
    files = list_folder_files(session, folder_id)
    records: list[dict] = []
    issues: list[str] = []
    successful_files = 0
    file_ids = {
        file_id
        for drive_file in files
        if (file_id := drive_file.get("id", "").strip())
    }
    refreshed_file_ids: set[str] = set()

    for drive_file in files:
        drive_name = drive_file.get("name", "Arquivo sem nome")
        try:
            downloaded = download_file(session, drive_file)
        except DriveImportError as error:
            issues.append(f"{drive_name} · {error}")
            continue
        if downloaded is None:
            issues.append(f"{drive_name} · formato não suportado; use XLSX, XLS, CSV ou Planilhas Google.")
            continue

        filename, content = downloaded
        try:
            file_records, file_issues = process_upload(
                filename,
                content,
                csv_origin=csv_origin,
                default_date=default_date,
            )
        except ValueError as error:
            issues.append(f"{drive_name} · {error}")
            continue
        if file_records or not file_issues:
            file_id = drive_file.get("id", "").strip()
            if file_id:
                refreshed_file_ids.add(file_id)
        if file_records:
            records.extend(file_records)
            successful_files += 1
        issues.extend(f"{drive_name} · {issue}" for issue in file_issues[:20])

    if not files:
        issues.append("A pasta do Google Drive não contém arquivos.")
    return DriveFolderImport(
        records=records,
        issues=issues,
        successful_files=successful_files,
        file_ids=file_ids,
        refreshed_file_ids=refreshed_file_ids,
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
