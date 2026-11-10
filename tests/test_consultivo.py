from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

import drive_import
import production
from components.consultivo import (
    CONFIG_CONSULTIVO,
    CalculosConsultivo,
    calcular_meta_acumulada_monitor,
    gerar_html_tabela_cons,
    injetar_ativos_sem_movimentacao,
    preparar_evolucao_mensal_consultivo,
    preparar_ranking,
    preparar_resumo_diario_monitor,
    sanitizar_csv_exportacao,
)

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class ConsultivoEtlAndRosterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = mock.patch.object(
            production, "DB_PATH", Path(self.temp_dir.name) / "consultivo_test.db"
        )
        self.db_patch.start()
        production.init_database()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_extract_drive_folder_id(self) -> None:
        url = "https://drive.google.com/drive/folders/1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2?usp=sharing"
        self.assertEqual(
            production.extract_drive_folder_id(url),
            "1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2",
        )
        self.assertEqual(
            production.extract_drive_folder_id("1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2"),
            "1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2",
        )
        self.assertEqual(production.extract_drive_folder_id("curto"), "")

    def test_tratar_planos_e_processar_quantidades_casos_reais(self) -> None:
        raw = pd.DataFrame(
            [
                {
                    # Combinado embutido no PLANO INTERNET com TV na segunda parte
                    "PLANO TV": "-",
                    "PLANO INTERNET": "1 GIGA (FIBRA).SERVIÇOS AVANÇADOS",
                    "OBSERVACAO": "Produtos 100000001, 100000002 e 100000003 instalados",
                },
                {
                    # Mesh puro via SERVIÇOS AVANÇADOS
                    "PLANO TV": "-",
                    "PLANO INTERNET": "SERVIÇOS AVANÇADOS",
                    "OBSERVACAO": "Mesh serial 2000000001 e 2000000002",
                },
                {
                    # Segunda parte iniciando com dígito não deve ser confundida com TV
                    "PLANO TV": "-",
                    "PLANO INTERNET": "SERVIÇOS AVANÇADOS.1 GIGA (FIBRA)",
                    "OBSERVACAO": "Upgrade 3000000001",
                },
                {
                    # Não venda sem planos
                    "PLANO TV": "-",
                    "PLANO INTERNET": "nan",
                    "OBSERVACAO": "-",
                },
            ]
        )
        tratado = production.tratar_planos_consultivo(raw)
        proc = production.processar_quantidades_consultivo(tratado)

        # Linha 0: CLARO TV+ BOX & 1 GIGA (FIBRA) -> Cons=2, Prod=3, TV=1, Virtua=1, Mesh=1
        self.assertEqual(proc.loc[0, "PLANO TV"], "CLARO TV+ BOX")
        self.assertEqual(proc.loc[0, "PLANO INTERNET"], "1 GIGA (FIBRA)")
        self.assertEqual(proc.loc[0, "QTDE_CONSULTIVO"], 2)
        self.assertEqual(proc.loc[0, "QTDE_PRODUTOS"], 3)
        self.assertEqual(proc.loc[0, "QTDE_TV"], 1)
        self.assertEqual(proc.loc[0, "QTDE_VIRTUA"], 1)
        self.assertEqual(proc.loc[0, "QTDE_MESH"], 1)

        # Linha 1: Mesh puro -> Cons=1, Prod=2, Mesh=2
        self.assertEqual(proc.loc[1, "QTDE_CONSULTIVO"], 1)
        self.assertEqual(proc.loc[1, "QTDE_PRODUTOS"], 2)
        self.assertEqual(proc.loc[1, "QTDE_MESH"], 2)
        self.assertEqual(proc.loc[1, "QTDE_TV"], 0)
        self.assertEqual(proc.loc[1, "QTDE_VIRTUA"], 0)

        # Linha 2: preserva string completa quando segunda parte começa com dígito
        self.assertEqual(proc.loc[2, "PLANO TV"], "")
        self.assertEqual(
            proc.loc[2, "PLANO INTERNET"], "SERVIÇOS AVANÇADOS.1 GIGA (FIBRA)"
        )
        self.assertEqual(proc.loc[2, "QTDE_CONSULTIVO"], 1)
        self.assertEqual(proc.loc[2, "QTDE_VIRTUA"], 1)

        # Linha 3: Não venda zerada
        self.assertEqual(proc.loc[3, "QTDE_CONSULTIVO"], 0)
        self.assertEqual(proc.loc[3, "QTDE_PRODUTOS"], 0)
        self.assertEqual(proc.loc[3, "TIPO SERVIÇO"], "Sem Tipo")

    def test_upload_enriquecimento_lista_ativos_e_deduplicacao_contato(self) -> None:
        production.save_roster_records(
            [
                {
                    "technician": "Alex Silva",
                    "re_code": "8001",
                    "login": "Z641001",
                    "monitor": "Edson Marco Pinheiro",
                    "un": "ABCDM-TOTALE",
                    "base": "NET-ABCDM",
                    "status": "ATIVO",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                },
                {
                    "technician": "Bruno Zerado",
                    "re_code": "8002",
                    "login": "Z641002",
                    "monitor": "Edson Marco Pinheiro",
                    "un": "ABCDM-TOTALE",
                    "base": "NET-ABCDM",
                    "status": "ATIVO",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                },
                {
                    "technician": "Carlos Ferias",
                    "re_code": "8003",
                    "login": "Z641003",
                    "monitor": "Adriano Silva",
                    "un": "GRS-TOTALE",
                    "base": "NET-GUARULHOS",
                    "status": "FÉRIAS",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                },
                {
                    "technician": "Diego ExColaborador",
                    "re_code": "7999",
                    "login": "Z649999",
                    "monitor": "Adriano Silva",
                    "un": "GRS-TOTALE",
                    "base": "NET-GUARULHOS",
                    "status": "DESLIGADO",
                    "source_tab": production.ROSTER_TERMINATED_TAB,
                },
            ],
            is_demo=False,
        )

        csv_set = (
            "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;CONTRATO;TIPO DE TABULAÇÃO;"
            "STATUS NETSALES;PLANO TV;PLANO INTERNET;OBSERVAÇÃO\n"
            "15/09/2026;Z649999;Diego Ex;90001;CT-10;VENDA;INSTALADA;-;600 MEGA (FIBRA);111111111\n"
            "20/09/2026;z641001;Alex S;90002;CT-11;VENDA;INSTALADA;-;SERVIÇOS AVANÇADOS;222222222 333333333\n"
        ).encode("utf-8-sig")

        csv_out = (
            "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;CONTRATO;TIPO DE TABULAÇÃO;"
            "STATUS NETSALES;PLANO TV;PLANO INTERNET;OBSERVAÇÃO\n"
            # Contato 90002 duplicado da exportação anterior deve ser deduplicado
            "20/09/2026;Z641001;Alex S;90002;CT-11;VENDA;INSTALADA;-;SERVIÇOS AVANÇADOS;222222222 333333333\n"
            # Fallback por nome quando LOGIN NETSALES vem vazio
            "10/10/2026;;Alex Silva;90003;CT-12;VENDA;INSTALADA;CLARO TV+ BOX;-;444444444\n"
        ).encode("utf-8-sig")

        rec_set, iss_set = production.process_consultivo_upload("set [f1].csv", csv_set)
        rec_out, iss_out = production.process_consultivo_upload("out [f2].csv", csv_out)
        self.assertEqual(iss_set, [])
        self.assertEqual(iss_out, [])

        production.save_consultivo_records(rec_set + rec_out, is_demo=False)
        enriched, stats = production.load_consultivo_snapshot()

        # 4 linhas brutas no banco, mas 3 após deduplicação de contact_code=90002
        self.assertEqual(stats["records"], 4)
        self.assertEqual(len(enriched), 3)

        # Histórico do DESLIGADO permanece preservado e enriquecido
        diego_rows = enriched[enriched["LOGIN NETSALES"] == "Z649999"]
        self.assertEqual(len(diego_rows), 1)
        self.assertEqual(diego_rows.iloc[0]["Situação"], "DESLIGADO")
        self.assertEqual(diego_rows.iloc[0]["Base"], "NET-GUARULHOS")

        # Fallback por nome preencheu login e Monitor de Alex Silva em 10/10/2026
        out_rows = enriched[
            enriched["DATA"].dt.date.between(date(2026, 10, 1), date(2026, 10, 31))
        ]
        self.assertEqual(len(out_rows), 1)
        self.assertEqual(out_rows.iloc[0]["LOGIN NETSALES"], "Z641001")
        self.assertEqual(out_rows.iloc[0]["Monitor"], "Edson Marco Pinheiro")

        # Injeção de ativos sem movimentação em Outubro traz apenas Bruno Zerado (ATIVO),
        # ignorando Carlos Ferias (FÉRIAS) e Diego (DESLIGADO).
        roster_df = production.load_roster()
        com_zeros = injetar_ativos_sem_movimentacao(out_rows, roster_df)
        logins_out = set(com_zeros["LOGIN NETSALES"])
        self.assertEqual(logins_out, {"Z641001", "Z641002"})

    def test_import_consultivo_folder_snapshot_incremental_sync(self) -> None:
        csv_content = (
            "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;PLANO TV;PLANO INTERNET;OBSERVAÇÃO\n"
            "05/10/2026;Z641759;Técnico A;77001;-;SERVIÇOS AVANÇADOS;1234567890\n"
        ).encode("utf-8-sig")

        fake_files = [
            {
                "id": "file-oct",
                "name": "numeros-tabulacao-2026-11-02.csv",
                "mimeType": "text/csv",
                "modifiedTime": "2026-11-02T08:49:11Z",
                "md5Checksum": "abc123",
                "size": str(len(csv_content)),
            }
        ]

        with (
            mock.patch.object(drive_import, "create_drive_session") as mock_sess,
            mock.patch.object(
                drive_import, "list_folder_files", return_value=fake_files
            ),
            mock.patch.object(
                drive_import,
                "download_file",
                return_value=(
                    "numeros-tabulacao-2026-11-02 [file-oct].csv",
                    csv_content,
                ),
            ) as mock_dl,
        ):
            mock_sess.return_value.credentials = None
            first = drive_import.import_consultivo_folder_snapshot(
                {},
                "https://drive.google.com/drive/folders/1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2",
            )
            self.assertEqual(len(first.records), 1)
            self.assertEqual(mock_dl.call_count, 1)
            production.sync_consultivo_drive_records(
                first.records,
                first.file_ids,
                first.refreshed_file_ids,
                folder_id=production.DEFAULT_CONSULTIVO_FOLDER_ID,
                file_fingerprints=first.file_fingerprints,
            )

            known = production.get_drive_file_fingerprints(
                production.DEFAULT_CONSULTIVO_FOLDER_ID
            )
            second = drive_import.import_consultivo_folder_snapshot(
                {},
                production.DEFAULT_CONSULTIVO_FOLDER_ID,
                known_file_fingerprints=known,
            )
            self.assertEqual(len(second.records), 0)
            self.assertEqual(second.refreshed_file_ids, set())
            self.assertEqual(mock_dl.call_count, 1)


class ConsultivoMetricsAndUiTests(unittest.TestCase):
    def test_projecao_ranking_html_meta_diaria_evolucao_e_csv_seguro(self) -> None:
        datas_mes = pd.Series(pd.to_datetime(["2026-10-05", "2026-10-10"]))
        fator_atual, passados, totais = CalculosConsultivo.fator_projecao(
            datas_mes, hoje=date(2026, 10, 15)
        )
        self.assertGreater(fator_atual, 1.0)
        self.assertGreater(totais, passados)

        fator_passado, _, _ = CalculosConsultivo.fator_projecao(
            datas_mes, hoje=date(2026, 11, 10)
        )
        self.assertEqual(fator_passado, 1.0)

        df = pd.DataFrame(
            [
                {
                    "DATA": pd.Timestamp("2026-09-10"),
                    "LOGIN NETSALES": "Z1",
                    "VENDEDOR": "=Malicioso",
                    "Monitor": "Mon A",
                    "Base": "NET-ABCDM",
                    "Qtde. Cons.": 10,
                    "Qtde. Prod.": 32,
                    "Qtde. Mesh": 20,
                    "Qtde. TV": 2,
                    "Qtde. Virtua": 10,
                },
                {
                    "DATA": pd.Timestamp("2026-10-10"),
                    "LOGIN NETSALES": "Z2",
                    "VENDEDOR": "Tecnico B",
                    "Monitor": "Mon A",
                    "Base": "NET-ABCDM",
                    "Qtde. Cons.": 5,
                    "Qtde. Prod.": 8,
                    "Qtde. Mesh": 5,
                    "Qtde. TV": 1,
                    "Qtde. Virtua": 2,
                },
            ]
        )

        rk_tec = preparar_ranking(df, usar_vendedor=True, fator_proj=1.5)
        self.assertIn("Proj. Consultivos", rk_tec.columns)
        html_tec = gerar_html_tabela_cons(rk_tec, usar_vendedor=True)
        self.assertIn("meta-batida", html_tec)
        self.assertIn("falta-meta", html_tec)
        self.assertIn("col-proj", html_tec)

        diario = preparar_resumo_diario_monitor(
            df, meta_diaria=CONFIG_CONSULTIVO.meta_diaria_consultivos
        )
        acum = calcular_meta_acumulada_monitor(
            diario, meta_diaria=CONFIG_CONSULTIVO.meta_diaria_consultivos
        )
        self.assertEqual(int(acum.iloc[0]["Dias_Ativos"]), 2)
        self.assertEqual(int(acum.iloc[0]["Meta Acumulada"]), 14)
        self.assertEqual(int(acum.iloc[0]["Consultivos_Acumulados"]), 15)

        evol = preparar_evolucao_mensal_consultivo(df)
        self.assertEqual(len(evol), 2)
        self.assertAlmostEqual(float(evol.iloc[1]["Var. Mês (%)"]), -50.0)

        csv_txt = sanitizar_csv_exportacao(df).decode("utf-8-sig")
        self.assertIn("'=Malicioso", csv_txt)

    def test_aba_consultivo_interativa_no_streamlit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "ui_consultivo.db"
            with (
                mock.patch.object(production, "DB_PATH", db_file),
                mock.patch.dict(os.environ, {"SHOW_DEMO_DATA": "1"}, clear=False),
            ):
                app = AppTest.from_file(_APP_PATH).run(timeout=30)
                app.radio(key="navigation").set_value("Consultivo").run(timeout=30)
                self.assertFalse(app.exception)

                # Alterna para Detalhar por Técnico
                app.toggle(key="cons_toggle_vendedor").set_value(True).run(timeout=30)
                self.assertFalse(app.exception)

                # Seleciona Todo período e aciona botão Dia vigente
                app.selectbox(key="cons_periodo_preset").set_value("Todo período").run(
                    timeout=30
                )
                self.assertFalse(app.exception)

                app.button(key="cons_btn_dia_vigente").click().run(timeout=30)
                self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
