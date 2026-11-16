"""Tabelas materializadas mensais e consultas com pushdown SQL por período."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.db import _DB_WRITE_LOCK, connect_db, init_database_at


def _iso_date(value: date | datetime | pd.Timestamp | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned[:10] if cleaned else None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    return str(ts.strftime("%Y-%m-%d"))


def _iso_month(value: date | datetime | pd.Timestamp | str | None) -> str | None:
    iso = _iso_date(value)
    if not iso or len(iso) < 7:
        return None
    return f"{iso[:7]}-01"


def refresh_monthly_summaries_in_conn(connection: sqlite3.Connection) -> None:
    """Atualiza as tabelas materializadas mensais dentro de uma conexão já aberta."""
    prod_cols = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(production_records)"
        ).fetchall()
    }
    connection.execute("DELETE FROM summary_production_monthly")
    if {"reference_date", "technician", "source_sheet", "points"}.issubset(prod_cols):
        contract_expr = (
            """
            COUNT(DISTINCT CASE
                WHEN contract IS NOT NULL AND TRIM(contract) <> ''
                     AND LOWER(TRIM(contract)) <> 'sem contrato'
                THEN TRIM(contract)
                ELSE NULL
            END)
            """
            if "contract" in prod_cols
            else "0"
        )
        connection.execute(
            f"""
            INSERT INTO summary_production_monthly (
                period, technician, points_prod, points_gpon, points_total,
                os_count, contracts_count, rows_count, updated_at
            )
            SELECT substr(reference_date, 1, 7) || '-01' AS period,
                   technician,
                   ROUND(SUM(CASE WHEN source_sheet = 'Prod' THEN points ELSE 0 END), 4) AS points_prod,
                   ROUND(SUM(CASE WHEN source_sheet = 'Gpon' THEN points ELSE 0 END), 4) AS points_gpon,
                   ROUND(SUM(points), 4) AS points_total,
                   SUM(CASE WHEN source_sheet = 'Prod' THEN 1 ELSE 0 END) AS os_count,
                   {contract_expr} AS contracts_count,
                   COUNT(*) AS rows_count,
                   CURRENT_TIMESTAMP
            FROM production_records
            WHERE reference_date IS NOT NULL AND LENGTH(reference_date) >= 7
            GROUP BY substr(reference_date, 1, 7), technician
            """
        )

    cons_cols = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(consultivo_records)"
        ).fetchall()
    }
    connection.execute("DELETE FROM summary_consultivo_monthly")
    if {"reference_date", "login_netsales"}.issubset(cons_cols):
        seller_expr = "seller" if "seller" in cons_cols else "''"
        seller_group = ", seller" if "seller" in cons_cols else ""
        q_cons_expr = (
            "COALESCE(SUM(qtde_consultivo), 0)"
            if "qtde_consultivo" in cons_cols
            else "0"
        )
        q_prod_expr = (
            "COALESCE(SUM(qtde_produtos), 0)" if "qtde_produtos" in cons_cols else "0"
        )
        q_mesh_expr = "COALESCE(SUM(qtde_mesh), 0)" if "qtde_mesh" in cons_cols else "0"
        q_tv_expr = "COALESCE(SUM(qtde_tv), 0)" if "qtde_tv" in cons_cols else "0"
        q_vir_expr = (
            "COALESCE(SUM(qtde_virtua), 0)" if "qtde_virtua" in cons_cols else "0"
        )
        connection.execute(
            f"""
            INSERT INTO summary_consultivo_monthly (
                period, login_netsales, seller, qtde_consultivo, qtde_produtos,
                qtde_mesh, qtde_tv, qtde_virtua, rows_count, updated_at
            )
            SELECT substr(reference_date, 1, 7) || '-01' AS period,
                   login_netsales,
                   {seller_expr} AS seller,
                   {q_cons_expr},
                   {q_prod_expr},
                   {q_mesh_expr},
                   {q_tv_expr},
                   {q_vir_expr},
                   COUNT(*),
                   CURRENT_TIMESTAMP
            FROM consultivo_records
            WHERE reference_date IS NOT NULL AND LENGTH(reference_date) >= 7
            GROUP BY substr(reference_date, 1, 7), login_netsales{seller_group}
            """
        )


def refresh_monthly_summaries_at(db_path: Path) -> None:
    """Recalcula as tabelas materializadas mensais de Produção e Consultivo."""
    init_database_at(db_path)
    with _DB_WRITE_LOCK, connect_db(db_path) as connection:
        refresh_monthly_summaries_in_conn(connection)


def load_monthly_production_summary_at(
    db_path: Path,
    *,
    date_start: date | datetime | pd.Timestamp | str | None = None,
    date_end: date | datetime | pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Lê a tabela materializada mensal de produção (com pushdown opcional de competência)."""
    init_database_at(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    start_m = _iso_month(date_start)
    end_m = _iso_month(date_end)
    if start_m:
        clauses.append("period >= ?")
        params.append(start_m)
    if end_m:
        clauses.append("period <= ?")
        params.append(end_m)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect_db(db_path) as connection:
        frame = pd.read_sql_query(
            f"""
            SELECT period, technician, points_prod, points_gpon, points_total,
                   os_count, contracts_count, rows_count, updated_at
            FROM summary_production_monthly
            {where_sql}
            ORDER BY period, technician
            """,
            connection,
            params=params,
        )
    if not frame.empty:
        frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    return frame


def load_monthly_consultivo_summary_at(
    db_path: Path,
    *,
    date_start: date | datetime | pd.Timestamp | str | None = None,
    date_end: date | datetime | pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Lê a tabela materializada mensal de consultivo (com pushdown opcional de competência)."""
    init_database_at(db_path)
    clauses: list[str] = []
    params: list[Any] = []
    start_m = _iso_month(date_start)
    end_m = _iso_month(date_end)
    if start_m:
        clauses.append("period >= ?")
        params.append(start_m)
    if end_m:
        clauses.append("period <= ?")
        params.append(end_m)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect_db(db_path) as connection:
        frame = pd.read_sql_query(
            f"""
            SELECT period, login_netsales, seller, qtde_consultivo, qtde_produtos,
                   qtde_mesh, qtde_tv, qtde_virtua, rows_count, updated_at
            FROM summary_consultivo_monthly
            {where_sql}
            ORDER BY period, seller
            """,
            connection,
            params=params,
        )
    if not frame.empty:
        frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    return frame


def load_sidebar_pulse_summary_at(db_path: Path) -> dict[str, Any]:
    """Calcula estatísticas instantâneas do Pulse a partir das tabelas materializadas.

    Fallback automático para contagem leve em ``production_records`` quando a
    tabela materializada ainda não tiver sido populada (ex.: banco legado).
    """
    init_database_at(db_path)
    with connect_db(db_path) as connection:
        mat_prod = connection.execute(
            """
            SELECT COUNT(*) AS summary_rows,
                   COALESCE(SUM(rows_count), 0) AS records,
                   COUNT(DISTINCT technician) AS technicians,
                   COUNT(DISTINCT period) AS months_count,
                   MIN(period) AS first_period,
                   MAX(period) AS last_period,
                   ROUND(COALESCE(SUM(points_total), 0), 2) AS points_total,
                   COALESCE(SUM(os_count), 0) AS os_total,
                   MAX(updated_at) AS refreshed_at
            FROM summary_production_monthly
            """
        ).fetchone()
        mat_cons = connection.execute(
            """
            SELECT COUNT(*) AS summary_rows,
                   COALESCE(SUM(rows_count), 0) AS records,
                   COALESCE(SUM(qtde_consultivo), 0) AS consultivos_total,
                   COALESCE(SUM(qtde_produtos), 0) AS produtos_total,
                   COUNT(DISTINCT period) AS months_count
            FROM summary_consultivo_monthly
            """
        ).fetchone()
        meta_prod = connection.execute(
            """
            SELECT COUNT(DISTINCT source_file) AS files,
                   MIN(reference_date) AS first_date,
                   MAX(reference_date) AS last_date,
                   MAX(imported_at) AS last_import,
                   COALESCE(SUM(is_demo), 0) AS demo_rows,
                   COUNT(*) AS raw_records
            FROM production_records
            """
        ).fetchone()

    use_mat = bool(mat_prod and int(mat_prod["summary_rows"] or 0) > 0)
    if use_mat:
        records = int(mat_prod["records"] or 0)
        technicians = int(mat_prod["technicians"] or 0)
        months_count = int(mat_prod["months_count"] or 0)
        points_total = float(mat_prod["points_total"] or 0.0)
        os_total = int(mat_prod["os_total"] or 0)
    else:
        records = int(meta_prod["raw_records"] or 0) if meta_prod else 0
        technicians = 0
        months_count = 0
        points_total = 0.0
        os_total = 0
        if records > 0:
            with connect_db(db_path) as connection:
                fb = connection.execute(
                    """
                    SELECT COUNT(DISTINCT technician) AS technicians,
                           COUNT(DISTINCT substr(reference_date, 1, 7)) AS months_count,
                           ROUND(COALESCE(SUM(points), 0), 2) AS points_total,
                           SUM(CASE WHEN source_sheet = 'Prod' THEN 1 ELSE 0 END) AS os_total
                    FROM production_records
                    """
                ).fetchone()
                if fb:
                    technicians = int(fb["technicians"] or 0)
                    months_count = int(fb["months_count"] or 0)
                    points_total = float(fb["points_total"] or 0.0)
                    os_total = int(fb["os_total"] or 0)

    return {
        "materialized": use_mat,
        "summary_prod_rows": int(mat_prod["summary_rows"] or 0) if mat_prod else 0,
        "summary_cons_rows": int(mat_cons["summary_rows"] or 0) if mat_cons else 0,
        "records": records,
        "technicians": technicians,
        "months_count": months_count,
        "points_total": points_total,
        "os_total": os_total,
        "files": int(meta_prod["files"] or 0) if meta_prod else 0,
        "first_date": meta_prod["first_date"] if meta_prod else None,
        "last_date": meta_prod["last_date"] if meta_prod else None,
        "last_import": meta_prod["last_import"] if meta_prod else None,
        "demo_rows": int(meta_prod["demo_rows"] or 0) if meta_prod else 0,
        "consultivos_total": (
            int(mat_cons["consultivos_total"] or 0) if mat_cons else 0
        ),
        "produtos_total": int(mat_cons["produtos_total"] or 0) if mat_cons else 0,
        "refreshed_at": mat_prod["refreshed_at"] if mat_prod else None,
    }


def read_record_rows_window(
    connection: sqlite3.Connection,
    *,
    date_start: date | datetime | pd.Timestamp | str | None = None,
    date_end: date | datetime | pd.Timestamp | str | None = None,
    source_sheet: str | None = None,
    technician: str | None = None,
) -> pd.DataFrame:
    """Lê ``production_records`` com pushdown SQL usando índices compostos de data/origem."""
    clauses: list[str] = []
    params: list[Any] = []
    start_s = _iso_date(date_start)
    end_s = _iso_date(date_end)
    if start_s:
        clauses.append("reference_date >= ?")
        params.append(start_s)
    if end_s:
        clauses.append("reference_date <= ?")
        params.append(end_s)
    if source_sheet:
        clauses.append("source_sheet = ?")
        params.append(str(source_sheet))
    if technician:
        clauses.append("technician = ?")
        params.append(str(technician))
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return pd.read_sql_query(
        f"""
        SELECT id, technician, reference_date, source_sheet, project,
               contract, wo, contract_flag, points, source_file, source_row,
               is_demo, imported_at
        FROM production_records
        {where_sql}
        ORDER BY reference_date, technician, source_sheet
        """,
        connection,
        params=params,
    )


def read_consultivo_rows_window(
    connection: sqlite3.Connection,
    *,
    date_start: date | datetime | pd.Timestamp | str | None = None,
    date_end: date | datetime | pd.Timestamp | str | None = None,
    login_netsales: str | None = None,
) -> pd.DataFrame:
    """Lê ``consultivo_records`` com pushdown SQL usando ``idx_consultivo_date_login``."""
    clauses: list[str] = []
    params: list[Any] = []
    start_s = _iso_date(date_start)
    end_s = _iso_date(date_end)
    if start_s:
        clauses.append("reference_date >= ?")
        params.append(start_s)
    if end_s:
        clauses.append("reference_date <= ?")
        params.append(end_s)
    if login_netsales:
        clauses.append("login_netsales = ?")
        params.append(str(login_netsales).strip().upper())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return pd.read_sql_query(
        f"""
        SELECT id, reference_date, login_netsales, seller, hp, contact_code,
               contract, tabulation_type, status_netsales, plano_tv,
               plano_internet, tipo_servico, qtde_consultivo, qtde_produtos,
               qtde_mesh, qtde_tv, qtde_virtua, source_file, source_row,
               is_demo, imported_at
        FROM consultivo_records
        {where_sql}
        ORDER BY reference_date, id
        """,
        connection,
        params=params,
    )
