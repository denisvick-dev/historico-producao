"""Testes da interligação com a planilha cadastral lista_ativos e Quadro de técnicos."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

import drive_import
import production
from components.quadro_tecnicos import conciliar_quadro_tecnicos

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def _criar_xlsx_cadastro() -> bytes:
    buffer = io.BytesIO()
    ativos = pd.DataFrame(
        {
            "RE": [8368.0, 8025.0, 8210.0],
            "Login": ["z641759", "Z571872", "Z709560"],
            "Técnico": [
                "ALEX BERNARDES DA SILVA",
                "JOAS SILVA BEZERRA",
                "JOÃO VITOR PEREIRA",
            ],
            "Monitor": [
                "EDSON MARCO PINHEIRO",
                "ADRIANO NASCIMENTO DA SILVA",
                "NELSON ALVES OLIVEIRA JUNIOR",
            ],
            "U.N.": ["ABCDM-TOTALE", "GRS-TOTALE", "ABCDM-TOTALE"],
            "Base": ["NET-ABCDM", "NET-GUARULHOS", "NET-ABCDM"],
            "Situação": ["ATIVO", "FÉRIAS", "ATIVO"],
            "Ultima_Modificacao": ["24/06/2026", "24/06/2026", "29/10/2026"],
        }
    )
    desligados = pd.DataFrame(
        {
            "RE": [7980, 8368],
            "Login": ["Z490001", "Z641759"],
            "Técnico": ["CARLOS EX COLABORADOR", "ALEX BERNARDES DA SILVA"],
            "Monitor": ["ADRIANO NASCIMENTO DA SILVA", "EDSON MARCO PINHEIRO"],
            "U.N.": ["GRS-TOTALE", "ABCDM-TOTALE"],
            "Base": ["NET-GUARULHOS", "NET-ABCDM"],
            "Situação": ["DESLIGADO", "DESLIGADO"],
            "Ultima_Modificacao": ["10/05/2026", "01/01/2026"],
            "Data_Desligamento": ["10/05/2026", "01/01/2026"],
            "Motivo": ["Pedido de demissão", "Readmitido"],
        }
    )
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        ativos.to_excel(writer, sheet_name="lista_ativos", index=False)
        desligados.to_excel(writer, sheet_name="desligados", index=False)
    return buffer.getvalue()


class RosterIntegrationTests(unittest.TestCase):
    def test_extrai_id_planilha_de_url_ou_id_puro(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg/edit?usp=sharing"
        self.assertEqual(
            production.extract_spreadsheet_id(url),
            "1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg",
        )
        self.assertEqual(
            production.extract_spreadsheet_id(
                "1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg"
            ),
            "1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg",
        )
        self.assertEqual(production.extract_spreadsheet_id(""), "")

    def test_process_roster_workbook_prioriza_lista_ativos_e_limpa_re(self) -> None:
        registros, issues = production.process_roster_workbook(_criar_xlsx_cadastro())
        self.assertEqual(issues, [])
        por_chave = {item["technician_key"]: item for item in registros}

        alex = por_chave["alexbernardesdasilva"]
        self.assertEqual(alex["re_code"], "8368")
        self.assertEqual(alex["login"], "Z641759")
        self.assertEqual(alex["status"], "ATIVO")
        self.assertEqual(alex["source_tab"], "lista_ativos")

        joas = por_chave["joassilvabezerra"]
        self.assertEqual(joas["status"], "FÉRIAS")

        carlos = por_chave["carlosexcolaborador"]
        self.assertEqual(carlos["status"], "DESLIGADO")
        self.assertEqual(carlos["termination_reason"], "Pedido de demissão")

    def test_persistencia_e_cruzamento_sem_acento(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(production, "DB_PATH", Path(tmp) / "roster.db"),
        ):
            registros_cad, _ = production.process_roster_workbook(
                _criar_xlsx_cadastro()
            )
            production.save_roster_records(
                registros_cad,
                is_demo=False,
                sheet_id=production.DEFAULT_ROSTER_SHEET_ID,
                fingerprint="fp-v1",
            )
            self.assertEqual(
                production.get_roster_fingerprint(production.DEFAULT_ROSTER_SHEET_ID),
                "fp-v1",
            )

            production.save_records(
                [
                    {
                        "technician": "Joao Vitor Pereira",  # sem acento na produção
                        "reference_date": "2026-10-05",
                        "source_sheet": "Prod",
                        "project": "NET-ABCDM",
                        "contract": "CT-10",
                        "points": 320.0,
                        "source_file": "out.xlsx",
                        "source_row": 2,
                    },
                    {
                        "technician": "Visitante Terceiro",
                        "reference_date": "2026-10-05",
                        "source_sheet": "Prod",
                        "project": "NET-ABCDM",
                        "contract": "CT-11",
                        "points": 100.0,
                        "source_file": "out.xlsx",
                        "source_row": 3,
                    },
                ]
            )

            carregado, stats = production.load_dashboard_snapshot()
            self.assertEqual(stats["roster_total"], 4)
            self.assertEqual(stats["roster_active"], 2)

            joao = carregado[carregado["re_code"].eq("8210")].iloc[0]
            self.assertEqual(joao["technician"], "João Vitor Pereira")
            self.assertEqual(joao["roster_status"], "ATIVO")
            self.assertEqual(joao["base"], "NET-ABCDM")

            visitante = carregado[
                carregado["technician"].eq("Visitante Terceiro")
            ].iloc[0]
            self.assertEqual(visitante["roster_status"], "Não cadastrado")

    def test_import_roster_spreadsheet_com_fingerprint_e_fallback_publico(self) -> None:
        conteudo_xlsx = _criar_xlsx_cadastro()
        fake_session = mock.MagicMock()

        meta_resp = mock.MagicMock()
        meta_resp.json.return_value = {
            "id": production.DEFAULT_ROSTER_SHEET_ID,
            "name": "lista_ativos",
            "mimeType": drive_import.GOOGLE_SHEET_MIME_TYPE,
            "modifiedTime": "2026-10-29T14:05:33.760Z",
        }
        export_resp = mock.MagicMock()
        export_resp.content = conteudo_xlsx
        fake_session.get.side_effect = [meta_resp, export_resp]

        with mock.patch.object(
            drive_import, "create_drive_session", return_value=fake_session
        ):
            resultado = drive_import.import_roster_spreadsheet(
                {"client_email": "svc@example.com"},
                production.DEFAULT_ROSTER_SHEET_ID,
                allow_public_fallback=False,
            )
            self.assertTrue(resultado.refreshed)
            self.assertFalse(resultado.unchanged)
            self.assertEqual(len(resultado.records), 4)

            meta_unchanged = mock.MagicMock()
            meta_unchanged.json.return_value = meta_resp.json.return_value
            fake_session.get.side_effect = [meta_unchanged]
            inalterado = drive_import.import_roster_spreadsheet(
                {"client_email": "svc@example.com"},
                production.DEFAULT_ROSTER_SHEET_ID,
                known_fingerprint=resultado.fingerprint,
                allow_public_fallback=False,
            )
            self.assertTrue(inalterado.unchanged)
            self.assertFalse(inalterado.refreshed)

        # Fallback público sem conta de serviço
        pub_resp = mock.MagicMock()
        pub_resp.content = conteudo_xlsx
        with mock.patch.object(drive_import, "_request", return_value=pub_resp):
            publico = drive_import.import_roster_spreadsheet(
                None,
                production.DEFAULT_ROSTER_SHEET_ID,
                allow_public_fallback=True,
            )
            self.assertTrue(publico.refreshed)
            self.assertEqual(len(publico.records), 4)

    def test_conciliacao_quadro_identifica_ativos_sem_producao_e_nao_cadastrados(
        self,
    ) -> None:
        registros_cad, _ = production.process_roster_workbook(_criar_xlsx_cadastro())
        roster = pd.DataFrame(registros_cad)
        prod_df = pd.DataFrame(
            {
                "technician": [
                    "Alex Bernardes da Silva",
                    "Alex Bernardes da Silva",
                    "Tecnico Sem Cadastro",
                ],
                "source_sheet": ["Prod", "Gpon", "Prod"],
                "points": [200.0, 150.0, 90.0],
                "contract": ["C1", "C1", "C2"],
                "period": pd.to_datetime(["2026-10-01", "2026-10-01", "2026-10-01"]),
            }
        )
        quadro = conciliar_quadro_tecnicos(roster, prod_df).set_index("Técnico")

        self.assertAlmostEqual(
            quadro.loc["Alex Bernardes da Silva", "Pontos Totais"], 350.0
        )
        self.assertEqual(quadro.loc["Alex Bernardes da Silva", "O.S. (Prod)"], 1)
        self.assertEqual(quadro.loc["Alex Bernardes da Silva", "Contratos"], 1)
        self.assertEqual(quadro.loc["João Vitor Pereira", "Com produção"], "Não")
        self.assertEqual(
            quadro.loc["Tecnico Sem Cadastro", "Situação"], "Não cadastrado"
        )

    def test_painel_restringe_por_padrao_a_situacao_ativo_e_exibe_aba_quadro(
        self,
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(production, "DB_PATH", Path(tmp) / "ui_roster.db"),
        ):
            registros_cad, _ = production.process_roster_workbook(
                _criar_xlsx_cadastro()
            )
            production.save_roster_records(registros_cad, is_demo=False)
            production.save_records(
                [
                    {
                        "technician": "Alex Bernardes da Silva",  # ATIVO
                        "reference_date": "2026-10-10",
                        "source_sheet": "Prod",
                        "project": "NET-ABCDM",
                        "contract": "CT-01",
                        "points": 410.0,
                        "source_file": "outubro.xlsx",
                        "source_row": 2,
                    },
                    {
                        "technician": "Carlos Ex Colaborador",  # DESLIGADO
                        "reference_date": "2026-10-10",
                        "source_sheet": "Prod",
                        "project": "NET-GUARULHOS",
                        "contract": "CT-02",
                        "points": 180.0,
                        "source_file": "outubro.xlsx",
                        "source_row": 3,
                    },
                    {
                        "technician": "Externo Avulso",  # Não cadastrado
                        "reference_date": "2026-10-10",
                        "source_sheet": "Prod",
                        "project": "NET-ABCDM",
                        "contract": "CT-03",
                        "points": 95.0,
                        "source_file": "outubro.xlsx",
                        "source_row": 4,
                    },
                ],
                is_demo=False,
            )

            app = AppTest.from_file(_APP_PATH).run(timeout=30)
            self.assertFalse(app.exception)
            # Filtro padrão deve restringir exclusivamente a Situação = ATIVO
            self.assertEqual(
                app.multiselect(key="roster_status_filter").value, ["ATIVO"]
            )
            tabela_visao_geral = cast(
                "pd.DataFrame", cast("Any", app.get("dataframe")[0]).value
            )
            self.assertEqual(
                tabela_visao_geral["Técnico"].tolist(), ["Alex Bernardes da Silva"]
            )

            # Incluindo DESLIGADO e Não cadastrado no filtro, todos aparecem
            app.multiselect(key="roster_status_filter").set_value(
                ["ATIVO", "DESLIGADO", "Não cadastrado"]
            ).run(timeout=30)
            self.assertFalse(app.exception)
            tabela_expandida = cast(
                "pd.DataFrame", cast("Any", app.get("dataframe")[0]).value
            )
            self.assertEqual(len(tabela_expandida), 3)

            # Navegando para a aba dedicada Quadro de técnicos
            app.radio(key="navigation").set_value("Quadro de técnicos").run(timeout=30)
            self.assertFalse(app.exception)
            markdown = " ".join(str(item.value) for item in app.markdown)
            self.assertIn("TÉCNICOS ATIVOS", markdown)
            self.assertIn("ATIVOS SEM PRODUÇÃO", markdown)
            self.assertIn("PRODUÇÃO NÃO CADASTRADA", markdown)
            self.assertGreaterEqual(len(app.get("plotly_chart")), 2)
            self.assertTrue(
                any(
                    "Baixar quadro de técnicos em CSV" in str(cast("Any", item).label)
                    for item in app.get("download_button")
                )
            )

            # Aba Saúde dos dados exibe cobertura cadastral lista_ativos
            app.radio(key="navigation").set_value("Saúde dos dados").run(timeout=30)
            self.assertFalse(app.exception)
            saude_md = " ".join(str(item.value) for item in app.markdown)
            self.assertIn("Cobertura cadastral (lista_ativos)", saude_md)


if __name__ == "__main__":
    unittest.main()
