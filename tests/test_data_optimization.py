"""Regressões das rotinas compartilhadas de carregamento e agregação."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pandas as pd
from pandas.testing import assert_frame_equal

import production


class NormalizacaoRepetidaTests(unittest.TestCase):
    def test_contratos_textuais_repetidos_sao_validados_uma_vez_por_valor(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a"] * 7,
                "contract": ["001", "001", "002", "Sem contrato", None, "002", "001"],
            }
        )
        with mock.patch.object(
            production, "is_valid_contract", wraps=production.is_valid_contract
        ) as validar:
            resultado = production.add_contracts_qty(frame)
        self.assertEqual(validar.call_count, 3)
        self.assertEqual(resultado["contracts_qty"].tolist(), [2] * 7)

    def test_tipos_mistos_mantem_semantica_da_normalizacao_original(self) -> None:
        values = pd.Series([1, 1.0, " 001 ", None, "Sem contrato", pd.NA], dtype=object)
        expected = values.map(production._contract_or_placeholder)
        actual = production._map_repeated_text(
            values, production._contract_or_placeholder, null_value="Sem contrato"
        )
        self.assertEqual(actual.tolist(), expected.tolist())
        self.assertEqual(actual.iloc[:2].tolist(), ["1", "1.0"])

    def test_texto_nulo_e_marcas_de_ausencia_preservados(self) -> None:
        values = pd.Series(
            ["001", " 001 ", None, "Sem contrato", "NULL", "001"], dtype="string"
        )
        expected = values.map(production._contract_or_placeholder)
        actual = production._map_repeated_text(
            values, production._contract_or_placeholder, null_value="Sem contrato"
        )
        self.assertEqual(actual.tolist(), expected.tolist())

    def test_resumo_nao_altera_dataframe_original(self) -> None:
        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Ana"],
                "source_sheet": ["Prod", "Gpon"],
                "points": [10.0, 5.0],
                "extra": ["x", "y"],
            }
        )
        antes = frame.copy(deep=True)
        self.assertEqual(
            production.summarize(frame, "technician").iloc[0]["points_total"], 15
        )
        assert_frame_equal(frame, antes)


class LeituraCompartilhadaTests(unittest.TestCase):
    def test_carregamentos_compartilham_normalizacao_e_totais_por_arquivo(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(production, "DB_PATH", Path(tmp) / "test.db"),
        ):
            rows = [
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-01",
                    "source_sheet": "Prod",
                    "project": "A",
                    "contract": "001",
                    "wo": "WO1",
                    "contract_flag": 1,
                    "points": 2,
                    "source_file": "a.csv",
                    "source_row": 1,
                },
                {
                    "technician": "Ana",
                    "reference_date": "2026-01-01",
                    "source_sheet": "Gpon",
                    "project": "A",
                    "contract": "001",
                    "wo": "WO1",
                    "contract_flag": 0,
                    "points": 3,
                    "source_file": "a.csv",
                    "source_row": 2,
                },
                {
                    "technician": "Bia",
                    "reference_date": "2026-02-01",
                    "source_sheet": "Prod",
                    "project": "B",
                    "contract": "Sem contrato",
                    "points": 4,
                    "source_file": "b.csv",
                    "source_row": 1,
                },
            ]
            production.save_records(rows)
            snapshot, stats = production.load_dashboard_snapshot()
            assert_frame_equal(snapshot, production.load_records())
            self.assertEqual(stats["records"], 3)
            self.assertEqual(snapshot["contracts_qty"].tolist(), [1, 1, 0])
            lotes = production.import_batches().set_index("source_file")
            self.assertEqual(int(cast(Any, lotes.loc["a.csv", "contracts_count"])), 1)
            self.assertEqual(int(cast(Any, lotes.loc["b.csv", "contracts_count"])), 0)

    def test_banco_vazio_mantem_formato_das_duas_leituras(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(production, "DB_PATH", Path(tmp) / "empty.db"),
        ):
            records = production.load_records()
            snapshot, stats = production.load_dashboard_snapshot()
            self.assertTrue(records.empty and snapshot.empty)
            self.assertIn("contracts_qty", records.columns)
            self.assertEqual(stats["records"], 0)


if __name__ == "__main__":
    unittest.main()
