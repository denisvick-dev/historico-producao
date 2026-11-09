import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

import production
from components.contratos import (
    _registros_com_contrato,
    contar_contratos_por_arquivo,
    contar_contratos_por_tecnico,
    contar_contratos_por_tecnico_mes,
    resumir_contratos,
    somar_qtde_contrato,
)


class ResumirContratosTests(unittest.TestCase):
    """Resumo de contratos distintos por projeto/técnico (funções puras)."""

    def test_contagem_distinta_e_ausentes(self) -> None:
        frame = pd.DataFrame(
            {
                "project": ["A", "A", "A", "A", "B", "B"],
                "technician": ["Ana", "Ana", "Ana", "Bia", "Ana", "Ana"],
                "contract": ["001", "001", "002", "001", "001", " NULL "],
            }
        )
        resumo, total, ausentes = resumir_contratos(frame)
        self.assertEqual(
            resumo.to_dict("records"),
            [
                {"Projeto": "A", "Técnico": "Ana", "Contratos distintos": 2},
                {"Projeto": "A", "Técnico": "Bia", "Contratos distintos": 1},
                {"Projeto": "B", "Técnico": "Ana", "Contratos distintos": 1},
            ],
        )
        self.assertEqual((total, ausentes), (2, 1))

    def test_funcoes_reutilizam_registros_validos_sem_alterar_resultados(self) -> None:
        frame = pd.DataFrame(
            {
                "project": ["A", "A", "B", "B"],
                "technician": ["Ana", "Ana", "Bia", "Bia"],
                "contract": ["001", "001", "002", "Sem contrato"],
                "source_file": ["jan.xlsx", "jan.xlsx", "fev.xlsx", "fev.xlsx"],
                "source_sheet": ["Prod"] * 4,
                "period": pd.to_datetime(
                    ["2026-01-01", "2026-02-01", "2026-02-01", "2026-02-01"]
                ),
            }
        )
        validos, ausentes = _registros_com_contrato(frame)

        resumo, total, sem_contrato = resumir_contratos(frame)
        resumo_prevalidado, total_prevalidado, _ = resumir_contratos(
            validos, _prevalidated=True
        )
        self.assertTrue(resumo.equals(resumo_prevalidado))
        self.assertEqual((total, total_prevalidado), (2, 2))
        self.assertEqual((sem_contrato, ausentes), (1, 1))

        self.assertTrue(
            contar_contratos_por_tecnico(frame).equals(
                contar_contratos_por_tecnico(validos, _prevalidated=True)
            )
        )
        self.assertTrue(
            contar_contratos_por_tecnico_mes(frame).equals(
                contar_contratos_por_tecnico_mes(validos, _prevalidated=True)
            )
        )
        self.assertTrue(
            contar_contratos_por_arquivo(frame).equals(
                contar_contratos_por_arquivo(validos, _prevalidated=True)
            )
        )
        self.assertEqual(
            somar_qtde_contrato(frame), somar_qtde_contrato(frame, _validos=validos)
        )


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
        # Contratos ausentes são persistidos com o marcador "Sem contrato", que o
        # contador da aba Contratos trata como ausência (nunca como contrato real).
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


class ContadorContratosTests(unittest.TestCase):
    """Contador de contratos da aba Contratos (funções puras)."""

    def test_contador_por_tecnico(self) -> None:
        from components.contratos import contar_contratos_por_tecnico

        frame = pd.DataFrame(
            {
                "project": ["A", "A", "A", "B", "B"],
                "technician": ["Ana", "Ana", "Bia", "Ana", None],
                "contract": ["001", "001", "002", "003", "004"],
            }
        )
        self.assertEqual(
            contar_contratos_por_tecnico(frame).to_dict("records"),
            [
                {"Técnico": "Ana", "Contratos": 2, "Participação (%)": 50.0},
                {"Técnico": "Bia", "Contratos": 1, "Participação (%)": 25.0},
                {"Técnico": "Sem técnico", "Contratos": 1, "Participação (%)": 25.0},
            ],
        )

    def test_marcador_sem_contrato_nao_e_contado(self) -> None:
        from components.contratos import contar_contratos_por_tecnico, resumir_contratos

        frame = pd.DataFrame(
            {
                "project": ["A", "A"],
                "technician": ["Ana", "Ana"],
                "contract": ["Sem contrato", "001"],
            }
        )
        _, total, ausentes = resumir_contratos(frame)
        self.assertEqual((total, ausentes), (1, 1))
        self.assertEqual(
            contar_contratos_por_tecnico(frame).to_dict("records"),
            [{"Técnico": "Ana", "Contratos": 1, "Participação (%)": 100.0}],
        )

    def test_contador_por_tecnico_sem_contratos(self) -> None:
        from components.contratos import contar_contratos_por_tecnico

        frame = pd.DataFrame({"technician": ["Ana"], "contract": [None]})
        contagem = contar_contratos_por_tecnico(frame)
        self.assertTrue(contagem.empty)
        self.assertEqual(
            list(contagem.columns), ["Técnico", "Contratos", "Participação (%)"]
        )

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

    def test_contador_mensal_preenche_lacunas_e_acumula_qtde_contrato(self) -> None:
        from components.contratos import contar_contratos_por_mes

        frame = pd.DataFrame(
            {
                "technician": ["Ana"] * 6,
                "contract": ["001", "002", "002", "003", "003", "004"],
                "source_file": [
                    "jan.xlsx",
                    "jan.xlsx",
                    "fev.xlsx",
                    "fev.xlsx",
                    "abr.xlsx",
                    "abr.xlsx",
                ],
                "contracts_qty": [2, 2, 3, 3, 1, 1],
                "period": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-01",
                        "2026-02-01",
                        "2026-02-01",
                        "2026-04-01",
                        "2026-04-01",
                    ]
                ),
            }
        )
        self.assertEqual(
            contar_contratos_por_mes(frame).to_dict("records"),
            [
                {
                    "Competência": "jan/26",
                    "Contratos no mês": 2,
                    "Acumulado (soma)": 2,
                },
                {
                    "Competência": "fev/26",
                    "Contratos no mês": 3,
                    "Acumulado (soma)": 5,
                },
                {
                    "Competência": "mar/26",
                    "Contratos no mês": 0,
                    "Acumulado (soma)": 5,
                },
                {
                    "Competência": "abr/26",
                    "Contratos no mês": 1,
                    "Acumulado (soma)": 6,
                },
            ],
        )

    def test_contador_mensal_soma_arquivos_na_mesma_competencia(self) -> None:
        from components.contratos import contar_contratos_por_mes

        frame = pd.DataFrame(
            {
                "technician": ["Ana"] * 4,
                "contract": ["001", "002", "003", "004"],
                "source_file": ["a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
                "contracts_qty": [5, 5, 7, 7],
                "period": pd.to_datetime(["2026-03-01"] * 4),
            }
        )
        self.assertEqual(
            contar_contratos_por_mes(frame).to_dict("records"),
            [
                {
                    "Competência": "mar/26",
                    "Contratos no mês": 12,
                    "Acumulado (soma)": 12,
                }
            ],
        )

    def test_contador_mensal_usa_data_de_referencia(self) -> None:
        from components.contratos import contar_contratos_por_mes

        frame = pd.DataFrame(
            {
                "contract": ["001", "001"],
                "source_file": ["mar.xlsx", "mar.xlsx"],
                "contracts_qty": [4, 4],
                "reference_date": pd.to_datetime(["2026-03-15", "2026-03-20"]),
            }
        )
        self.assertEqual(
            contar_contratos_por_mes(frame).to_dict("records"),
            [
                {
                    "Competência": "mar/26",
                    "Contratos no mês": 4,
                    "Acumulado (soma)": 4,
                }
            ],
        )

    def test_contador_por_arquivo_importado(self) -> None:
        from components.contratos import contar_contratos_por_arquivo

        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
                "source_sheet": ["Prod", "Gpon", "Prod", "Prod"],
                "contract": ["001", "001", "002", "Sem contrato"],
                "contracts_qty": [9, 9, 4, 4],
            }
        )
        self.assertEqual(
            contar_contratos_por_arquivo(frame).to_dict("records"),
            [
                {
                    "Arquivo": "a.xlsx",
                    "Origem": "Gpon / Prod",
                    "Registros com contrato": 2,
                    "Contratos": 9,
                },
                {
                    "Arquivo": "b.xlsx",
                    "Origem": "Prod",
                    "Registros com contrato": 1,
                    "Contratos": 4,
                },
            ],
        )

    def test_contador_por_arquivo_sem_coluna_qtde_cai_para_nunique(self) -> None:
        from components.contratos import contar_contratos_por_arquivo

        frame = pd.DataFrame(
            {
                "source_file": ["a.xlsx", "a.xlsx"],
                "source_sheet": ["Prod", "Prod"],
                "contract": ["001", "002"],
            }
        )
        self.assertEqual(
            contar_contratos_por_arquivo(frame).to_dict("records"),
            [
                {
                    "Arquivo": "a.xlsx",
                    "Origem": "Prod",
                    "Registros com contrato": 2,
                    "Contratos": 2,
                },
            ],
        )

    def test_somar_qtde_contrato_soma_arquivos_uma_vez_cada(self) -> None:
        from components.contratos import somar_qtde_contrato

        frame = pd.DataFrame(
            {
                "contract": ["001", "002", "001", "003"],
                "source_file": ["a.xlsx", "a.xlsx", "b.xlsx", "b.xlsx"],
                "contracts_qty": [2, 2, 1, 1],
            }
        )
        soma, arquivos = somar_qtde_contrato(frame)
        self.assertEqual((soma, arquivos), (3, 2))

    def test_somar_qtde_contrato_sem_arquivos(self) -> None:
        from components.contratos import somar_qtde_contrato

        frame = pd.DataFrame({"contract": ["001"], "contracts_qty": [0]})
        self.assertEqual(somar_qtde_contrato(frame), (0, 1))
        self.assertEqual(somar_qtde_contrato(frame.iloc[0:0]), (0, 0))

    def test_contador_por_arquivo_sem_coluna_de_origem(self) -> None:
        from components.contratos import contar_contratos_por_arquivo

        frame = pd.DataFrame({"contract": ["001"]})
        contagem = contar_contratos_por_arquivo(frame)
        self.assertTrue(contagem.empty)
        self.assertEqual(
            list(contagem.columns),
            ["Arquivo", "Origem", "Registros com contrato", "Contratos"],
        )

    def test_contadores_com_frame_vazio(self) -> None:
        from components.contratos import contar_contratos_por_mes

        vazio = pd.DataFrame(columns=["technician", "contract", "period"])
        self.assertTrue(contar_contratos_por_mes(vazio).empty)


if __name__ == "__main__":
    unittest.main()


class MatrizTecnicoMesTests(unittest.TestCase):
    """Matriz Técnico × Competência de contratos distintos (nunique)."""

    def test_matriz_nunique_com_total_geral(self) -> None:
        from components.contratos import contar_contratos_por_tecnico_mes

        frame = pd.DataFrame(
            {
                "technician": ["Ana", "Ana", "Ana", "Bia", "Ana", "Bia"],
                "contract": ["001", "001", "002", "003", "004", " Sem contrato "],
                "period": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-01",
                        "2026-02-01",
                        "2026-02-01",
                        "2026-03-01",
                        "2026-03-01",
                    ]
                ),
            }
        )
        matriz = contar_contratos_por_tecnico_mes(frame)
        self.assertEqual(
            list(matriz.columns),
            ["Técnico", "jan/26", "fev/26", "mar/26", "Total", "Participação (%)"],
        )
        registros = matriz.to_dict("records")
        self.assertEqual(registros[0]["Técnico"], "Ana")  # maior total primeiro
        self.assertEqual(
            registros[0],
            {
                "Técnico": "Ana",
                "jan/26": 1,
                "fev/26": 1,
                "mar/26": 1,
                "Total": 3,
                "Participação (%)": 75.0,
            },
        )
        self.assertEqual(
            registros[1],
            {
                "Técnico": "Bia",
                "jan/26": 0,
                "fev/26": 1,
                "mar/26": 0,
                "Total": 1,
                "Participação (%)": 25.0,
            },
        )
        self.assertEqual(
            registros[2],
            {
                "Técnico": "Total geral",
                "jan/26": 1,
                "fev/26": 2,
                "mar/26": 1,
                "Total": 4,
                "Participação (%)": 100.0,
            },
        )

    def test_matriz_sem_contrato_valido(self) -> None:
        from components.contratos import contar_contratos_por_tecnico_mes

        frame = pd.DataFrame(
            {
                "technician": ["Ana"],
                "contract": ["Sem contrato"],
                "period": pd.to_datetime(["2026-01-01"]),
            }
        )
        self.assertTrue(contar_contratos_por_tecnico_mes(frame).empty)

    def test_matriz_frame_vazio(self) -> None:
        from components.contratos import contar_contratos_por_tecnico_mes

        self.assertTrue(contar_contratos_por_tecnico_mes(pd.DataFrame()).empty)


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


class CarteiraContratosTests(unittest.TestCase):
    def test_carteira_agrupa_identificadores_validos_no_recorte(self) -> None:
        from components.contratos import resumir_carteira

        frame = pd.DataFrame(
            {
                "contract": [" 001 ", "001", "002", "Sem contrato"],
                "project": ["B", "A", None, "A"],
                "technician": ["Bia", "Ana", None, "Ana"],
                "points": [10, 5, 3, 100],
                "reference_date": pd.to_datetime(
                    ["2026-02-10", "2026-01-05", "2026-02-01", "2026-02-01"]
                ),
            }
        )
        carteira = resumir_carteira(frame)
        self.assertEqual(carteira["Contrato"].tolist(), ["001", "002"])
        primeiro = carteira.iloc[0]
        self.assertEqual(
            (primeiro["Projetos"], primeiro["Técnicos"]), ("A · B", "Ana · Bia")
        )
        self.assertEqual((primeiro["Registros"], primeiro["Pontos"]), (2, 15))
        self.assertEqual(primeiro["Primeiro registro"], pd.Timestamp("2026-01-05"))
        self.assertEqual(primeiro["Último registro"], pd.Timestamp("2026-02-10"))

    def test_evolucao_distinta_com_repeticoes_e_lacuna(self) -> None:
        from components.contratos import contratos_distintos_por_mes

        frame = pd.DataFrame(
            {
                "contract": ["001", "001", "001", "002", "Sem contrato"],
                "period": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-01",
                        "2026-03-01",
                        "2026-03-01",
                        "2026-03-01",
                    ]
                ),
            }
        )
        self.assertEqual(
            contratos_distintos_por_mes(frame).to_dict("records"),
            [
                {"Competência": "jan/26", "Contratos": 1},
                {"Competência": "fev/26", "Contratos": 0},
                {"Competência": "mar/26", "Contratos": 2},
            ],
        )

    def test_arquivo_sem_contrato_valido_ainda_contribui_para_conferencia(self) -> None:
        frame = pd.DataFrame(
            {
                "source_file": ["a.csv", "b.csv"],
                "contract": ["001", "Sem contrato"],
                "contracts_qty": [2, 5],
            }
        )
        tabela = contar_contratos_por_arquivo(frame)
        self.assertEqual(tabela["Contratos"].sum(), somar_qtde_contrato(frame)[0])
        self.assertEqual(
            tabela.loc[tabela["Arquivo"] == "b.csv", "Registros com contrato"].iloc[0],
            0,
        )

    def test_ausencia_de_coluna_contrato(self) -> None:
        from components.contratos import resumir_carteira

        frame = pd.DataFrame({"source_file": ["a.csv"], "contracts_qty": [2]})
        self.assertEqual(_registros_com_contrato(frame)[1], 1)
        self.assertTrue(resumir_carteira(frame).empty)
        self.assertEqual(contar_contratos_por_arquivo(frame).iloc[0]["Contratos"], 2)
