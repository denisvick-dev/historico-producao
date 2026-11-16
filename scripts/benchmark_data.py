"""Mede operações comuns e motores analíticos com dados sintéticos, sem alterar o banco."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from time import perf_counter

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import production
from components.modo_reuniao import gerar_briefing_html, montar_briefing_reuniao
from components.pacote_executivo import gerar_pacote_executivo_xlsx
from components.qualidade_ritmo import (
    calcular_reincidencia_contratos,
    calcular_ritmo_diario_producao,
)
from components.radar_alertas import calcular_radar_alertas
from components.scorecard_supervisao import calcular_scorecard_supervisao
from components.tecnicos_comparacao import calcular_comparacao_tecnicos
from components.turnover_rampup import calcular_curva_rampup, calcular_turnover
from components.visao_360 import calcular_visao_360


def _gerar_bases_sinteticas(
    n_prod: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    datas = pd.date_range("2025-01-02", periods=300, freq="B")
    tecs = [f"Tecnico {i:03d}" for i in range(60)]
    monitores = [f"Monitor {i % 6}" for i in range(60)]
    bases = [f"BASE-{i % 4}" for i in range(60)]
    uns = [f"UN-{i % 2}" for i in range(60)]

    prod = pd.DataFrame(
        {
            "source_file": [f"arquivo-{i % 20}.xlsx" for i in range(n_prod)],
            "contract": [f"CT-{i % 1500:05d}" for i in range(n_prod)],
            "contract_flag": [None] * n_prod,
            "source_sheet": ["Prod" if i % 2 == 0 else "Gpon" for i in range(n_prod)],
            "points": [float((i % 15) + 5) for i in range(n_prod)],
            "technician": [tecs[i % len(tecs)] for i in range(n_prod)],
            "project": [f"Projeto {i % 5}" for i in range(n_prod)],
            "reference_date": [datas[i % len(datas)] for i in range(n_prod)],
            "monitor": [monitores[i % len(tecs)] for i in range(n_prod)],
            "base": [bases[i % len(tecs)] for i in range(n_prod)],
            "un": [uns[i % len(tecs)] for i in range(n_prod)],
            "roster_status": ["ATIVO"] * n_prod,
        }
    )
    prod["period"] = prod["reference_date"].dt.to_period("M").dt.to_timestamp()

    n_cons = max(500, n_prod // 4)
    cons = pd.DataFrame(
        {
            "DATA": [datas[i % len(datas)] for i in range(n_cons)],
            "VENDEDOR": [tecs[i % len(tecs)] for i in range(n_cons)],
            "Técnico": [tecs[i % len(tecs)] for i in range(n_cons)],
            "LOGIN NETSALES": [f"Z{640000 + (i % len(tecs))}" for i in range(n_cons)],
            "Monitor": [monitores[i % len(tecs)] for i in range(n_cons)],
            "Base": [bases[i % len(tecs)] for i in range(n_cons)],
            "U.N.": [uns[i % len(tecs)] for i in range(n_cons)],
            "Situação": ["ATIVO"] * n_cons,
            "CONTRATO": [f"CT-{i % 1500:05d}" for i in range(n_cons)],
            "Qtde. Cons.": [1] * n_cons,
            "Qtde. Prod.": [1 if i % 3 == 0 else 0 for i in range(n_cons)],
            "Qtde. Mesh": [1 if i % 6 == 0 else 0 for i in range(n_cons)],
            "Qtde. TV": [1 if i % 9 == 0 else 0 for i in range(n_cons)],
            "Qtde. Virtua": [1 if i % 5 == 0 else 0 for i in range(n_cons)],
        }
    )
    cons["period"] = cons["DATA"].dt.to_period("M").dt.to_timestamp()

    roster = pd.DataFrame(
        {
            "technician_key": [production.normalize_text(t) for t in tecs],
            "technician": tecs,
            "re_code": [f"RE{i:04d}" for i in range(len(tecs))],
            "login": [f"Z{640000 + i}" for i in range(len(tecs))],
            "monitor": monitores,
            "base": bases,
            "un": uns,
            "status": ["DESLIGADO" if i >= 54 else "ATIVO" for i in range(len(tecs))],
            "source_tab": [
                "desligados" if i >= 54 else "lista_ativos" for i in range(len(tecs))
            ],
            "termination_date": [
                "2025-10-15" if i >= 54 else "" for i in range(len(tecs))
            ],
            "termination_reason": [
                "Pedido de demissão" if i >= 54 else "" for i in range(len(tecs))
            ],
        }
    )
    return prod, cons, roster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows", type=int, default=20_000, help="Número de registros sintéticos"
    )
    args = parser.parse_args()
    if args.rows <= 0:
        parser.error("--rows deve ser positivo")

    prod, cons, roster = _gerar_bases_sinteticas(args.rows)
    briefing_ref = montar_briefing_reuniao(
        prod, cons, roster, periodo_label="Benchmark"
    )

    etapas = [
        (
            f"add_contracts_qty ({args.rows:,} linhas)",
            lambda: production.add_contracts_qty(prod.copy()),
        ),
        (
            "summarize por técnico (5x)",
            lambda: [production.summarize(prod, "technician") for _ in range(5)],
        ),
        (
            "calcular_visao_360",
            lambda: calcular_visao_360(prod, cons, roster),
        ),
        (
            "calcular_radar_alertas",
            lambda: calcular_radar_alertas(prod, cons, roster),
        ),
        (
            "calcular_scorecard_supervisao",
            lambda: calcular_scorecard_supervisao(prod, cons, roster),
        ),
        (
            "calcular_reincidencia_contratos (30d)",
            lambda: calcular_reincidencia_contratos(prod, janela_dias=30),
        ),
        (
            "calcular_ritmo_diario_producao",
            lambda: calcular_ritmo_diario_producao(prod),
        ),
        (
            "calcular_turnover",
            lambda: calcular_turnover(roster, prod),
        ),
        (
            "calcular_curva_rampup",
            lambda: calcular_curva_rampup(prod, roster),
        ),
        (
            "montar_briefing_reuniao (Modo Reunião)",
            lambda: montar_briefing_reuniao(prod, cons, roster),
        ),
        (
            "gerar_briefing_html (HTML5/PDF)",
            lambda: gerar_briefing_html(briefing_ref),
        ),
        (
            "calcular_comparacao_tecnicos (1:1)",
            lambda: calcular_comparacao_tecnicos(
                prod,
                "Tecnico 000",
                modo="media_base",
                consultivo_frame=cons,
            ),
        ),
        (
            "gerar_pacote_executivo_xlsx (5 abas)",
            lambda: gerar_pacote_executivo_xlsx(prod, cons, roster),
        ),
    ]

    for nome, fn in etapas:
        inicio = perf_counter()
        fn()
        dur_ms = (perf_counter() - inicio) * 1000.0
        print(f"{nome:<44} {dur_ms:8.1f} ms")

    # Benchmark SQLite: resumo materializado + pushdown SQL vs carga completa
    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_db = production.DB_PATH
        try:
            production.DB_PATH = Path(tmp_dir) / "bench_materialized.db"
            production._INITIALIZED_DBS.clear()
            production.init_database()
            rows_sql = [
                {
                    "technician": str(tech),
                    "reference_date": str(ref_dt),
                    "source_sheet": str(sheet),
                    "project": str(proj),
                    "contract": str(ct),
                    "wo": f"WO-{idx}",
                    "points": float(pts),
                    "source_file": str(sf),
                    "source_row": idx + 2,
                }
                for idx, (tech, ref_dt, sheet, proj, ct, pts, sf) in enumerate(
                    zip(
                        prod["technician"].tolist(),
                        prod["reference_date"].dt.strftime("%Y-%m-%d").tolist(),
                        prod["source_sheet"].tolist(),
                        prod["project"].tolist(),
                        prod["contract"].tolist(),
                        prod["points"].tolist(),
                        prod["source_file"].tolist(),
                        strict=False,
                    )
                )
            ]
            production.save_records(rows_sql, is_demo=False)

            for nome_sql, fn_sql in (
                (
                    "SQLite load_sidebar_pulse_summary",
                    production.load_sidebar_pulse_summary,
                ),
                (
                    "SQLite load_monthly_production_summary",
                    production.load_monthly_production_summary,
                ),
                (
                    "SQLite load_records_window (30d pushdown)",
                    lambda: production.load_records_window(
                        date_start="2025-11-01", date_end="2025-11-30"
                    ),
                ),
                (
                    "SQLite load_records (full scan)",
                    production.load_records,
                ),
            ):
                t0 = perf_counter()
                fn_sql()
                print(f"{nome_sql:<44} {(perf_counter() - t0) * 1000.0:8.1f} ms")
        finally:
            production.DB_PATH = orig_db
            production._INITIALIZED_DBS.clear()


if __name__ == "__main__":
    main()
