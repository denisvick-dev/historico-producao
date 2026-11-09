import sqlite3
import unittest

import pandas as pd

import production
from components.contratos import resumir_contratos


def test_contagem_distinta_e_ausentes():
    frame = pd.DataFrame(
        {
            "project": ["A", "A", "A", "A", "B", "B"],
            "technician": ["Ana", "Ana", "Ana", "Bia", "Ana", "Ana"],
            "contract": ["001", "001", "002", "001", "001", " NULL "],
        }
    )
    resumo, total, ausentes = resumir_contratos(frame)
    assert resumo.to_dict("records") == [
        {"Projeto": "A", "Técnico": "Ana", "Contratos distintos": 2},
        {"Projeto": "A", "Técnico": "Bia", "Contratos distintos": 1},
        {"Projeto": "B", "Técnico": "Ana", "Contratos distintos": 1},
    ]
    assert (total, ausentes) == (2, 1)


def test_importacao_csv_e_persistencia(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "DB_PATH", tmp_path / "dados.db")
    data = "Técnico;Projeto;Contrato;Pontos;Data\nAna;P1;00123;10;01/01/2026\nAna;P1;;5;01/01/2026\n".encode()
    registros, problemas = production.process_upload("teste.csv", data)
    assert not problemas
    # Contratos ausentes são persistidos com o marcador "Sem contrato", que o
    # contador da aba Contratos trata como ausência (nunca como contrato real).
    assert [r["contract"] for r in registros] == ["00123", "Sem contrato"]
    production.save_records(registros)
    for frame in (production.load_records(), production.load_dashboard_snapshot()[0]):
        assert frame.iloc[0]["contract"] == "00123"
        assert frame.iloc[1]["contract"] == "Sem contrato"


def test_migracao_banco_antigo(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(production, "DB_PATH", path)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE production_records (id INTEGER PRIMARY KEY, technician TEXT, reference_date TEXT, source_sheet TEXT, project TEXT, points REAL, source_file TEXT, source_row INTEGER, is_demo INTEGER, imported_at TEXT)"
        )
        db.execute(
            "INSERT INTO production_records VALUES (1, 'Ana', '2026-01-01', 'Prod', 'P1', 10, 'a.csv', 2, 0, '2026-01-01')"
        )
    production.init_database()
    assert production.load_records().iloc[0]["contract"] == "Sem contrato"


def test_sync_preserva_contrato(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "DB_PATH", tmp_path / "dados.db")
    registros, _ = production.process_upload(
        "arquivo [abc].csv", b"Tecnico;Contrato;Pontos;Data\nAna;0001;10;01/01/2026\n"
    )
    production.sync_drive_records(registros, {"abc"}, {"abc"})
    assert production.load_records().iloc[0]["contract"] == "0001"


def test_sync_persiste_placeholders_em_banco_legado(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(production, "DB_PATH", path)
    with sqlite3.connect(path) as db:
        db.execute(
            """
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
            """
        )

    registros, problemas = production.process_upload(
        "arquivo [abc].csv",
        b"Tecnico;Pontos;Data\nAna;10;01/01/2026\n",
    )
    assert not problemas
    assert registros[0]["contract"] == "Sem contrato"
    assert registros[0]["wo"] == "Sem WO"
    production.sync_drive_records(registros, {"abc"}, {"abc"})
    assert production.load_records().iloc[0][["contract", "wo"]].to_dict() == {
        "contract": "Sem contrato",
        "wo": "Sem WO",
    }


def test_contador_por_tecnico():
    from components.contratos import contar_contratos_por_tecnico

    frame = pd.DataFrame(
        {
            "project": ["A", "A", "A", "B", "B"],
            "technician": ["Ana", "Ana", "Bia", "Ana", None],
            "contract": ["001", "001", "002", "003", "004"],
        }
    )
    contagem = contar_contratos_por_tecnico(frame)
    assert contagem.to_dict("records") == [
        {"Técnico": "Ana", "Contratos": 2, "Participação (%)": 50.0},
        {"Técnico": "Bia", "Contratos": 1, "Participação (%)": 25.0},
        {"Técnico": "Sem técnico", "Contratos": 1, "Participação (%)": 25.0},
    ]


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

    def test_contador_mensal_preenche_lacunas_e_acumula_distintos(self) -> None:
        from components.contratos import contar_contratos_por_mes

        frame = pd.DataFrame(
            {
                "technician": ["Ana"] * 6,
                "contract": ["001", "002", "002", "003", "003", "004"],
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
                    "Contratos ativos": 2,
                    "Contratos acumulados": 2,
                },
                {
                    "Competência": "fev/26",
                    "Contratos ativos": 2,
                    "Contratos acumulados": 3,
                },
                {
                    "Competência": "mar/26",
                    "Contratos ativos": 0,
                    "Contratos acumulados": 3,
                },
                {
                    "Competência": "abr/26",
                    "Contratos ativos": 2,
                    "Contratos acumulados": 4,
                },
            ],
        )

    def test_contador_mensal_usa_data_de_referencia(self) -> None:
        from components.contratos import contar_contratos_por_mes

        frame = pd.DataFrame(
            {
                "contract": ["001", "001"],
                "reference_date": pd.to_datetime(["2026-03-15", "2026-03-20"]),
            }
        )
        self.assertEqual(
            contar_contratos_por_mes(frame).to_dict("records"),
            [
                {
                    "Competência": "mar/26",
                    "Contratos ativos": 1,
                    "Contratos acumulados": 1,
                }
            ],
        )

    def test_contadores_com_frame_vazio(self) -> None:
        from components.contratos import contar_contratos_por_mes

        vazio = pd.DataFrame(columns=["technician", "contract", "period"])
        self.assertTrue(contar_contratos_por_mes(vazio).empty)


if __name__ == "__main__":
    unittest.main()
