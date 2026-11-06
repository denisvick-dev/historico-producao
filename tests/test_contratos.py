import sqlite3

import pandas as pd

import production
from components.contratos import resumir_contratos


def test_contagem_distinta_e_ausentes():
    frame = pd.DataFrame({"project": ["A", "A", "A", "A", "B", "B"], "technician": ["Ana", "Ana", "Ana", "Bia", "Ana", "Ana"], "contract": ["001", "001", "002", "001", "001", " NULL "]})
    resumo, total, ausentes = resumir_contratos(frame)
    assert resumo.to_dict("records") == [
        {"Projeto": "A", "Técnico": "Ana", "Contratos": 2},
        {"Projeto": "A", "Técnico": "Bia", "Contratos": 1},
        {"Projeto": "B", "Técnico": "Ana", "Contratos": 1},
    ]
    assert (total, ausentes) == (2, 1)


def test_importacao_csv_e_persistencia(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "DB_PATH", tmp_path / "dados.db")
    data = 'Técnico;Projeto;Contrato;Pontos;Data\nAna;P1;00123;10;01/01/2026\nAna;P1;;5;01/01/2026\n'.encode()
    registros, problemas = production.process_upload("teste.csv", data)
    assert not problemas
    assert [r["contract"] for r in registros] == ["00123", None]
    production.save_records(registros)
    for frame in (production.load_records(), production.load_dashboard_snapshot()[0]):
        assert frame.iloc[0]["contract"] == "00123"
        assert pd.isna(frame.iloc[1]["contract"])


def test_migracao_banco_antigo(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    monkeypatch.setattr(production, "DB_PATH", path)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE production_records (id INTEGER PRIMARY KEY, technician TEXT, reference_date TEXT, source_sheet TEXT, project TEXT, points REAL, source_file TEXT, source_row INTEGER, is_demo INTEGER, imported_at TEXT)")
        db.execute("INSERT INTO production_records VALUES (1, 'Ana', '2026-01-01', 'Prod', 'P1', 10, 'a.csv', 2, 0, '2026-01-01')")
    production.init_database()
    assert production.load_records().iloc[0]["contract"] is None


def test_sync_preserva_contrato(tmp_path, monkeypatch):
    monkeypatch.setattr(production, "DB_PATH", tmp_path / "dados.db")
    registros, _ = production.process_upload("arquivo [abc].csv", b'Tecnico;Contrato;Pontos;Data\nAna;0001;10;01/01/2026\n')
    production.sync_drive_records(registros, {"abc"}, {"abc"})
    assert production.load_records().iloc[0]["contract"] == "0001"
