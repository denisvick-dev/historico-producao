"""Persistência de Presets de Filtros (recortes salvos) no SQLite."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from core.db import _DB_WRITE_LOCK, connect_db, init_database_at

ALLOWED_PRESET_KEYS = (
    "period_filter",
    "monitor_filter",
    "base_filter",
    "un_filter",
    "project_filter",
    "technician_filter",
    "roster_status_filter",
    "navigation",
    "sidebar_nav_group",
)


def normalize_preset_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Filtra e sanitiza o dicionário de filtros antes de gravar no banco."""
    cleaned: dict[str, Any] = {}
    for key in ALLOWED_PRESET_KEYS:
        if key not in payload:
            continue
        val = payload[key]
        if isinstance(val, (list, tuple, set)):
            cleaned[key] = [str(item).strip() for item in val if str(item).strip()]
        elif isinstance(val, str):
            text = val.strip()
            if text:
                cleaned[key] = text
    return cleaned


def load_filter_presets_at(db_path: Path) -> pd.DataFrame:
    """Retorna todos os presets salvos ordenados alfabeticamente."""
    init_database_at(db_path)
    with connect_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, page, payload_json, updated_at
            FROM filter_presets
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["id", "name", "page", "payload", "payload_json", "updated_at"]
        )
    records: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed = json.loads(str(row["payload_json"] or "{}"))
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}
        records.append(
            {
                "id": int(row["id"]),
                "name": str(row["name"]),
                "page": str(row["page"] or ""),
                "payload": parsed,
                "payload_json": str(row["payload_json"] or "{}"),
                "updated_at": str(row["updated_at"] or ""),
            }
        )
    return pd.DataFrame(records)


def save_filter_preset_at(
    db_path: Path,
    name: str,
    payload: Mapping[str, Any],
    *,
    page: str = "",
) -> bool:
    """Cria ou atualiza um preset de filtros nomeado no SQLite."""
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        return False
    normalized = normalize_preset_payload(payload)
    payload_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    init_database_at(db_path)
    with _DB_WRITE_LOCK, connect_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO filter_presets (name, page, payload_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET
                page = excluded.page,
                payload_json = excluded.payload_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (clean_name, str(page or "").strip(), payload_json),
        )
    return True


def delete_filter_preset_at(db_path: Path, preset_id_or_name: int | str) -> None:
    """Remove um preset salvo pelo ID inteiro ou pelo nome."""
    init_database_at(db_path)
    with _DB_WRITE_LOCK, connect_db(db_path) as connection:
        if isinstance(preset_id_or_name, int):
            connection.execute(
                "DELETE FROM filter_presets WHERE id = ?", (int(preset_id_or_name),)
            )
        else:
            connection.execute(
                "DELETE FROM filter_presets WHERE name = ?",
                (str(preset_id_or_name).strip(),),
            )
