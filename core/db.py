"""Conexão SQLite, DDL, migrações incrementais, índices compostos e backup WAL-safe."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_DB_WRITE_LOCK = threading.RLock()
_INITIALIZED_DBS: set[tuple[str, int]] = set()


def _db_identity(path: Path) -> tuple[str, int] | None:
    try:
        resolved = path.resolve()
        return (str(resolved), resolved.stat().st_ino)
    except OSError:
        return None


@contextmanager
def connect_db(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Abre conexão SQLite com PRAGMAs otimizados de concorrência (WAL + busy_timeout)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA cache_size=-64000")
    connection.execute("PRAGMA temp_store=MEMORY")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_database_at(db_path: Path, *, force: bool = False) -> None:
    """Cria/migra o schema SQLite e os índices compostos no caminho informado."""
    if not force:
        identity = _db_identity(db_path)
        if identity is not None and identity in _INITIALIZED_DBS:
            return
    with _DB_WRITE_LOCK, connect_db(db_path) as connection:
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
            CREATE INDEX IF NOT EXISTS idx_production_date_tech
                ON production_records(reference_date, technician);
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS filter_presets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                page TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
            CREATE TABLE IF NOT EXISTS technician_aliases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alias_type TEXT NOT NULL CHECK(alias_type IN ('name', 'login')),
                source_value TEXT NOT NULL,
                canonical_technician TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(alias_type, source_value)
            );
            CREATE TABLE IF NOT EXISTS summary_production_monthly (
                period TEXT NOT NULL,
                technician TEXT NOT NULL,
                points_prod REAL NOT NULL DEFAULT 0,
                points_gpon REAL NOT NULL DEFAULT 0,
                points_total REAL NOT NULL DEFAULT 0,
                os_count INTEGER NOT NULL DEFAULT 0,
                contracts_count INTEGER NOT NULL DEFAULT 0,
                rows_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(period, technician)
            );
            CREATE TABLE IF NOT EXISTS summary_consultivo_monthly (
                period TEXT NOT NULL,
                login_netsales TEXT NOT NULL,
                seller TEXT NOT NULL,
                qtde_consultivo INTEGER NOT NULL DEFAULT 0,
                qtde_produtos INTEGER NOT NULL DEFAULT 0,
                qtde_mesh INTEGER NOT NULL DEFAULT 0,
                qtde_tv INTEGER NOT NULL DEFAULT 0,
                qtde_virtua INTEGER NOT NULL DEFAULT 0,
                rows_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(period, login_netsales, seller)
            );
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
            CREATE INDEX IF NOT EXISTS idx_consultivo_date_login
                ON consultivo_records(reference_date, login_netsales);
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
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_date_sheet "
            "ON production_records(reference_date, source_sheet)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_file_contract "
            "ON production_records(source_file, contract)"
        )
        consultivo_cols = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(consultivo_records)"
            ).fetchall()
        }
        if "status_netsales" in consultivo_cols:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_consultivo_date_status "
                "ON consultivo_records(reference_date, status_netsales)"
            )
    identity_after = _db_identity(db_path)
    if identity_after is not None:
        _INITIALIZED_DBS.add(identity_after)


def get_setting_at(db_path: Path, key: str) -> str | None:
    init_database_at(db_path)
    with connect_db(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return str(row["value"]) if row else None


def set_setting_at(db_path: Path, key: str, value: str) -> None:
    init_database_at(db_path)
    with _DB_WRITE_LOCK, connect_db(db_path) as connection:
        connection.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def backup_database_at(db_path: Path, destination: Path | None = None) -> Path | None:
    """Cria cópia consistente do SQLite via API nativa ``backup()`` (segura em WAL)."""
    init_database_at(db_path)
    if not db_path.exists():
        return None
    target = destination
    if target is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target = db_path.parent / "backups" / f"{db_path.stem}_{stamp}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    with _DB_WRITE_LOCK, connect_db(db_path) as source_conn:
        source_conn.execute("PRAGMA optimize")
        dest_conn = sqlite3.connect(target, timeout=30)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    return target
