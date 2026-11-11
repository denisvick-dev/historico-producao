import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pandas as pd

import production


class ImportacaoContratosTests(unittest.TestCase):
    """Importação/persistência de contratos com banco temporário."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "dados.db"
        patcher = mock.patch.object(production, "DB_PATH", self.db_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_importacao_csv_e_persistencia(self) -> None:
        data = "Técnico;Projeto;Contrato;Pontos;Data\nAna;P1;00123;10;01/01/2026\nAna;P1;;5;01/01/2026\n".encode()
        registros, problemas = production.process_upload("teste.csv", data)
        self.assertFalse(problemas)
        # Contratos ausentes são persistidos com o marcador "Sem contrato".
        self.assertEqual([r["contract"] for r in registros], ["00123", "Sem contrato"])
        production.save_records(registros)
        for frame in (
            production.load_records(),
            production.load_dashboard_snapshot()[0],
        ):
            self.assertEqual(frame.iloc[0]["contract"], "00123")
            self.assertEqual(frame.iloc[1]["contract"], "Sem contrato")

    def test_migracao_banco_antigo(self) -> None:
        path = Path(self._tmp.name) / "legacy.db"
        with mock.patch.object(production, "DB_PATH", path):
            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE production_records (id INTEGER PRIMARY KEY, technician TEXT, reference_date TEXT, source_sheet TEXT, project TEXT, points REAL, source_file TEXT, source_row INTEGER, is_demo INTEGER, imported_at TEXT)"
                )
                db.execute(
                    "INSERT INTO production_records VALUES (1, 'Ana', '2026-01-01', 'Prod', 'P1', 10, 'a.csv', 2, 0, '2026-01-01')"
                )
            production.init_database()
            self.assertEqual(
                production.load_records().iloc[0]["contract"], "Sem contrato"
            )

    def test_sync_preserva_contrato(self) -> None:
        registros, _ = production.process_upload(
            "arquivo [abc].csv",
            b"Tecnico;Contrato;Pontos;Data\nAna;0001;10;01/01/2026\n",
        )
        production.sync_drive_records(registros, {"abc"}, {"abc"})
        self.assertEqual(production.load_records().iloc[0]["contract"], "0001")

    def test_sync_persiste_placeholders_em_banco_legado(self) -> None:
        path = Path(self._tmp.name) / "legacy.db"
        with mock.patch.object(production, "DB_PATH", path):
            with sqlite3.connect(path) as db:
                db.execute("""
                    CREATE TABLE production_records (
                        id INTEGER PRIMARY KEY,
                        technician TEXT NOT NULL,
                        reference_date TEXT NOT NULL,
                        source_sheet TEXT NOT NULL,
                        project TEXT NOT NULL DEFAULT 'Sem projeto',
                        contract TEXT NOT NULL DEFAULT 'Sem contrato',
                        wo TEXT NOT NULL DEFAULT 'Sem WO',
                        points REAL NOT NULL,
                        source_file TEXT NOT NULL,
                        source_row INTEGER NOT NULL,
                        is_demo INTEGER NOT NULL DEFAULT 0,
                        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """)

            registros, problemas = production.process_upload(
                "arquivo [abc].csv",
                b"Tecnico;Pontos;Data\nAna;10;01/01/2026\n",
            )
            self.assertFalse(problemas)
            self.assertEqual(registros[0]["contract"], "Sem contrato")
            self.assertEqual(registros[0]["wo"], "Sem WO")
            production.sync_drive_records(registros, {"abc"}, {"abc"})
            self.assertEqual(
                production.load_records().iloc[0][["contract", "wo"]].to_dict(),
                {"contract": "Sem contrato", "wo": "Sem WO"},
            )


class IdentificacaoContratoTests(unittest.TestCase):
    def test_identifica_numero_do_contrato_em_cabecalho_variado(self) -> None:
        frame = pd.DataFrame(
            {
                "Técnico": ["Ana"],
                "Pontos": [10],
                "Data": ["01/01/2026"],
                "Número do Contrato": ["00123"],
            }
        )
        registros, problemas = production.process_dataframe(frame, "Prod", "teste.csv")
        self.assertFalse(problemas)
        self.assertEqual(registros[0]["contract"], "00123")


class QtdeContratoTests(unittest.TestCase):
    """Coluna Qtde_Contrato do export como fonte oficial de contracts_qty."""

    def test_parse_contract_flag(self) -> None:
        from production import parse_contract_flag

        self.assertEqual(parse_contract_flag(1), 1)
        self.assertEqual(parse_contract_flag(0), 0)
        self.assertEqual(parse_contract_flag(1.0), 1)
        self.assertEqual(parse_contract_flag("1"), 1)
        self.assertEqual(parse_contract_flag("0"), 0)
        self.assertEqual(parse_contract_flag(True), 1)
        self.assertIsNone(parse_contract_flag(None))
        self.assertIsNone(parse_contract_flag(""))
        self.assertIsNone(parse_contract_flag(float("nan")))
        self.assertIsNone(parse_contract_flag(2))
        self.assertIsNone(parse_contract_flag("abc"))

    def test_process_dataframe_captura_flag_por_linha(self) -> None:
        frame = pd.DataFrame(
            {
                "Técnico": ["Ana", "Ana", "Bia"],
                "Pontos": [10, 5, 7],
                "Data": ["01/01/2026"] * 3,
                "Contrato": ["001", "001", "002"],
                "Qtde_Contrato": [1, 0, 1],
            }
        )
        registros, problemas = production.process_dataframe(frame, "Prod", "teste.csv")
        self.assertFalse(problemas)
        self.assertEqual([r["contract_flag"] for r in registros], [1, 0, 1])

    def test_process_dataframe_sem_coluna_flag_fica_none(self) -> None:
        frame = pd.DataFrame(
            {
                "Técnico": ["Ana"],
                "Pontos": [10],
                "Data": ["01/01/2026"],
                "Contrato": ["001"],
            }
        )
        registros, problemas = production.process_dataframe(frame, "Prod", "teste.csv")
        self.assertFalse(problemas)
        self.assertIsNone(registros[0]["contract_flag"])

    def test_process_dataframe_flag_invalido_vira_issue_unica(self) -> None:
        frame = pd.DataFrame(
            {
                "Técnico": ["Ana", "Ana"],
                "Pontos": [10, 5],
                "Data": ["01/01/2026"] * 2,
                "Contrato": ["001", "001"],
                "Qtde_Contrato": ["x", "y"],
            }
        )
        registros, problemas = production.process_dataframe(frame, "Prod", "teste.csv")
        self.assertEqual([r["contract_flag"] for r in registros], [None, None])
        self.assertEqual(len(problemas), 1)
        self.assertIn("Qtde_Contrato", problemas[0])

    def test_add_contracts_qty_soma_flags_por_arquivo(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
                "contract": ["001", "001", "002", "003", "003"],
                "contract_flag": [1, 0, 1, 1, 0],
            }
        )
        resultado = production.add_contracts_qty(frame)
        self.assertEqual(resultado["contracts_qty"].tolist(), [2, 2, 2, 1, 1])

    def test_add_contracts_qty_fallback_nunique_sem_flags(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx", "a.xlsx"],
                "contract": ["001", "001", "002"],
                "contract_flag": [None, None, None],
            }
        )
        resultado = production.add_contracts_qty(frame)
        self.assertEqual(resultado["contracts_qty"].tolist(), [2, 2, 2])

    def test_add_contracts_qty_misto_flags_e_fallback(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
                "contract": ["001", "002", "003", "003"],
                "contract_flag": [1, 1, None, None],
            }
        )
        resultado = production.add_contracts_qty(frame)
        # a.xlsx usa a soma dos flags (2); b.xlsx cai no nunique (1).
        self.assertEqual(resultado["contracts_qty"].tolist(), [2, 2, 1, 1])

    def test_add_contracts_qty_flag_ignora_sem_contrato(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx"],
                "contract": ["Sem contrato", "001"],
                "contract_flag": [1, 1],
            }
        )
        resultado = production.add_contracts_qty(frame)
        self.assertEqual(resultado["contracts_qty"].tolist(), [1, 1])

    def test_roundtrip_csv_com_qtde_contrato(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(production, "DB_PATH", Path(tmp) / "dados.db"):
                data = (
                    "Técnico;Contrato;Pontos;Data;Qtde_Contrato\n"
                    "Ana;001;10;01/01/2026;1\n"
                    "Ana;001;5;01/01/2026;0\n"
                    "Bia;002;7;01/01/2026;1\n"
                ).encode()
                registros, problemas = production.process_upload("teste.csv", data)
                self.assertFalse(problemas)
                production.save_records(registros)
                frame = production.load_records()
                self.assertEqual(frame["contract_flag"].tolist(), [1, 0, 1])
                self.assertEqual(frame["contracts_qty"].tolist(), [2, 2, 2])

    def test_migracao_adiciona_contract_flag_em_banco_legado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            with mock.patch.object(production, "DB_PATH", path):
                with sqlite3.connect(path) as db:
                    db.execute(
                        "CREATE TABLE production_records (id INTEGER PRIMARY KEY, technician TEXT, reference_date TEXT, source_sheet TEXT, project TEXT, points REAL, source_file TEXT, source_row INTEGER, is_demo INTEGER, imported_at TEXT)"
                    )
                    db.execute(
                        "INSERT INTO production_records VALUES (1, 'Ana', '2026-01-01', 'Prod', 'P1', 10, 'a.csv', 2, 0, '2026-01-01')"
                    )
                production.init_database()
                with sqlite3.connect(path) as db:
                    colunas = {
                        row[1]
                        for row in db.execute("PRAGMA table_info(production_records)")
                    }
                self.assertIn("contract_flag", colunas)
                frame = production.load_records()
                self.assertIn("contract_flag", frame.columns)
                self.assertTrue(frame["contract_flag"].isna().all())


class PainelContratosTests(unittest.TestCase):
    def test_distintos_por_tecnico_mes_consistentes_com_totais(self) -> None:
        from components.contratos import resumir_contratos

        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Ana", "Ana", "Ana", "Bia", "Bia", "Ana", "Ana"],
                "contract": [
                    " 001 ",
                    "001",
                    "002",
                    "001",
                    "001",
                    "003",
                    "Sem contrato",
                    "Não informado",
                ],
                "period": pd.to_datetime(
                    ["2026-01-01"] * 3
                    + [
                        "2026-02-01",
                        "2026-01-01",
                        "2026-02-01",
                        "2026-01-01",
                        "2026-01-01",
                    ]
                ),
                "source_sheet": [
                    "Prod",
                    "Gpon",
                    "Prod",
                    "Prod",
                    "Gpon",
                    "Prod",
                    "Prod",
                    "Prod",
                ],
                "source_file": [
                    "a.xlsx",
                    "b.xlsx",
                    "a.xlsx",
                    "b.xlsx",
                    "b.xlsx",
                    "b.xlsx",
                    "a.xlsx",
                    "a.xlsx",
                ],
                "contracts_qty": [999] * 8,
            }
        )
        mensal, ranking, matriz, sem_contrato, incompletos = resumir_contratos(frame)
        self.assertEqual(mensal["contratos"].tolist(), [3, 2])
        self.assertEqual(
            ranking.set_index("technician")["contratos"].to_dict(), {"Ana": 3, "Bia": 2}
        )
        linhas = matriz.set_index("Técnico")
        self.assertEqual(
            linhas.loc["Ana"].to_dict(),
            {
                "jan/26": 2,
                "fev/26": 1,
                "Total": 3,
                "Meses com produção": 2,
                "Média mensal": 1.5,
            },
        )
        self.assertEqual(
            linhas.loc["Bia"].to_dict(),
            {
                "jan/26": 1,
                "fev/26": 1,
                "Total": 2,
                "Meses com produção": 2,
                "Média mensal": 1.0,
            },
        )
        self.assertEqual(
            linhas.loc["Total geral"].to_dict(),
            {
                "jan/26": 3,
                "fev/26": 2,
                "Total": 5,
                "Meses com produção": 2,
                "Média mensal": 2.5,
            },
        )
        self.assertEqual((sem_contrato, incompletos), (2, 0))

    def test_media_considera_apenas_meses_com_contrato_por_tecnico(self) -> None:
        from components.contratos import resumir_contratos

        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Ana", "Ana", "Ana", "Bia", "Bia", "Bia"],
                "contract": ["001", "002", "001", "Sem contrato", "010", "011", "011"],
                "period": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-01",
                        "2026-03-01",
                        "2026-02-01",
                        "2026-02-01",
                        "2026-02-01",
                        "2026-02-01",
                    ]
                ),
                "source_sheet": [
                    "Prod",
                    "Prod",
                    "Gpon",
                    "Prod",
                    "Prod",
                    "Prod",
                    "Gpon",
                ],
            }
        )
        _, _, matriz, _, _ = resumir_contratos(frame)
        linhas = matriz.set_index("Técnico")
        self.assertEqual(linhas.loc["Ana", "fev/26"], 0)
        self.assertEqual(linhas.loc["Ana", "Meses com produção"], 2)
        self.assertAlmostEqual(float(cast(Any, linhas.loc["Ana", "Média mensal"])), 1.5)
        self.assertEqual(linhas.loc["Bia", "Meses com produção"], 1)
        self.assertEqual(linhas.loc["Bia", "Média mensal"], 2.0)
        self.assertEqual(linhas.loc["Total geral", "Meses com produção"], 3)
        self.assertAlmostEqual(
            float(cast(Any, linhas.loc["Total geral", "Média mensal"])), 5 / 3
        )
        _, _, filtrada, _, _ = resumir_contratos(frame[frame["technician"] == "Ana"])
        self.assertEqual(filtrada.iloc[0]["Meses com produção"], 2)
        self.assertEqual(filtrada.iloc[0]["Média mensal"], 1.5)

    def test_destaque_e_csv_nao_confundem_resumos_com_competencias(self) -> None:
        from components.contratos import resumir_contratos
        from components.painel_quantidades import best_month_style, csv_download

        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Bia"],
                "contract": ["001", "002"],
                "period": pd.to_datetime(["2026-01-01", "2026-02-01"]),
            }
        )
        _, _, matriz, _, _ = resumir_contratos(frame)
        row = matriz.iloc[0].copy()
        row["Meses com produção"] = 100
        row["Média mensal"] = 50.0
        styles = best_month_style(
            row, exclude_columns=("Meses com produção", "Média mensal")
        )
        self.assertIn("#DCFCE7", styles["jan/26"])
        self.assertEqual(styles["Meses com produção"], "")
        self.assertEqual(styles["Média mensal"], "")
        csv = csv_download(matriz).decode("utf-8-sig")
        self.assertIn("Meses com produção;Média mensal", csv)
        self.assertIn("Ana;1;0;1;1;1,0", csv)

    def test_filtros_e_competencia_de_referencia(self) -> None:
        from components.contratos import resumir_contratos

        frame = pd.DataFrame(
            {
                "contract": ["001", "002", "003", "004", None],
                "technician": ["Ana", "Bia", None, "Ana", "Ana"],
                "period": pd.to_datetime(
                    pd.Series(["2026-01-01", None, "2026-01-01", None, "2026-01-01"])
                ),
                "reference_date": pd.to_datetime(
                    pd.Series(
                        ["2026-01-05", "2026-02-05", "2026-01-01", None, "2026-01-01"]
                    )
                ),
            }
        )
        mensal, ranking, matriz, ausentes, incompletos = resumir_contratos(frame)
        self.assertEqual(mensal["contratos"].tolist(), [1, 1])
        self.assertEqual((ausentes, incompletos), (1, 2))
        self.assertEqual(matriz.iloc[-1]["Total"], 2)
        mensal, ranking, matriz, ausentes, incompletos = resumir_contratos(
            frame[frame["technician"].eq("Ana")]
        )
        self.assertEqual(mensal["contratos"].tolist(), [1])
        self.assertEqual(ranking["technician"].tolist(), ["Ana"])
        self.assertEqual((ausentes, incompletos), (1, 1))

    def test_sem_contratos_ou_colunas_obrigatorias(self) -> None:
        from components.contratos import resumir_contratos

        for frame, ausentes, incompletos in (
            (pd.DataFrame(), 0, 0),
            (pd.DataFrame({"technician": ["Ana"]}), 1, 0),
            (pd.DataFrame({"contract": ["Sem contrato", "NULL"]}), 2, 0),
            (pd.DataFrame({"contract": ["001"]}), 0, 1),
        ):
            mensal, ranking, matriz, qtd_ausentes, qtd_incompletos = resumir_contratos(
                frame
            )
            self.assertTrue(mensal.empty and ranking.empty and matriz.empty)
            self.assertEqual((qtd_ausentes, qtd_incompletos), (ausentes, incompletos))


if __name__ == "__main__":
    unittest.main()
