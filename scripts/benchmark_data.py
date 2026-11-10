"""Mede operações comuns com dados sintéticos, sem acessar ou modificar o banco."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import production


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows", type=int, default=200_000, help="Número de registros sintéticos"
    )
    args = parser.parse_args()
    if args.rows <= 0:
        parser.error("--rows deve ser positivo")
    n = args.rows
    frame = pd.DataFrame(
        {
            "source_file": [f"arquivo-{i % 20}" for i in range(n)],
            "contract": [f"CT-{i % 1000}" for i in range(n)],
            "contract_flag": [None] * n,
            "source_sheet": ["Prod" if i % 2 else "Gpon" for i in range(n)],
            "points": [1.0] * n,
            "technician": [f"T{i % 50}" for i in range(n)],
        }
    )
    inicio = perf_counter()
    production.add_contracts_qty(frame.copy())
    print(f"Contratos por arquivo: {perf_counter() - inicio:.3f} s ({n:,} registros)")
    inicio = perf_counter()
    for _ in range(5):
        production.summarize(frame, "technician")
    print(f"Resumo por técnico, 5 vezes: {perf_counter() - inicio:.3f} s")


if __name__ == "__main__":
    main()
