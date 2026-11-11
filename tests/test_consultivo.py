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
    formatar_data_br_consultivo,
    gerar_html_tabela_cons,
    injetar_ativos_sem_movimentacao,
    normalizar_coluna_data_consultivo,
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

            known = production.get_consultivo_file_fingerprints(
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

            # Se consultivo_records perder as linhas de um arquivo (ex.: falha anterior),
            # get_consultivo_file_fingerprints omite esse file_id para forçar reimportação.
            with production.connect() as conn:
                conn.execute("DELETE FROM consultivo_records")
            known_after_clear = production.get_consultivo_file_fingerprints(
                production.DEFAULT_CONSULTIVO_FOLDER_ID
            )
            self.assertEqual(known_after_clear, {})

    def test_netsales_2025_csv_55_colunas_com_aspas_ponto_virgula_e_quebra_linha(
        self,
    ) -> None:
        header_55 = (
            "HP;AA_CNPJ;AA_RAZAO_SOCIAL;VENDEDOR;VENDEDOR_CPF;CLIENTE;CPF_CNPJ;ESTADO;"
            "CIDADE;CEP;LOGRADOURO;NUMERO;COMPLEMENTO;BAIRRO;TELEFONE RESIDENCIAL;"
            "TELEFONE COMERCIAL;TELEFONE CELULAR;TELEFONE CONTATO 1;TELEFONE CONTATO 2;"
            "TIPO DE TABULAÇÃO;MOTIVO DE TABULAÇÃO;PROPOSTA;CONTRATO;ORIGEM DA VENDA;"
            "DATA AGENDAMENTO;PERÍODO AGENDAMENTO;DATA;HORA FINALIZAÇÃO DA TABULAÇÃO;"
            "RETORNO;OPERAÇÃO;LOGIN NETSALES;STATUS NETSALES;MOTIVO PENDENCIA;"
            "CÓDIGO CONTATO;PONTO DE REFERÊNCIA;OBSERVACAO;FORMA DE PAGAMENTO;BANCO;"
            "CONTA CORRENTE;POSSUI TV;POSSUI INTERNET;POSSUI FONE;POSSUI CELULAR;"
            "PLANO TV;PLANO INTERNET;PLANO FONE;PLANO CELULAR;FIDELIDADE TV;"
            "FIDELIDADE INTERNET;FIDELIDADE FONE;EMAIL DO CLIENTE;DATA DE VENCIMENTO;"
            "AGENCIA;RECEBER MENSAGENS PUBLICITÁRIAS;TIPOS DE MENSAGENS PUBLICITÁRIAS"
        )
        # Linha 1: exportação real 2025 com ponto-e-vírgula extra e aspas soltas na OBSERVACAO
        row_1 = (
            "1161057901;6014327000120;TOTALE;NATANAEL QUEIROZ DOS SANTOS;45053555863;"
            'CLIENTE UM;111;SP;SAO BERNARDO DO CAMPO;09854430;RUA A;10;CASA "B;CENTRO;'
            "-;-;11999999999;-;-;VENDA;VENDA;-;162086807;OUTROS;-;-;02/01/2025;09:08:05;"
            "-;OP;Z407899;INSTALADA;-;108479594;-;"
            '"OFERTA CADASTRADA; O.S: 2524680364; 2524680353;OK;'
            "BOLETO;-;-;SIM;SIM;NÃO;NÃO;-;SERVIÇOS AVANÇADOS;-;-;-;C/ FIDELIDADE;-;"
            "cli1@mail.com;10;-;NÃO;-"
        )
        # Linha 2: ponto-e-vírgula extra ANTES de DATA (em COMPLEMENTO) + quebra de linha na OBSERVACAO
        row_2 = (
            "1161057902;6014327000120;TOTALE;EDER SALES MONTEIRO;37760542886;"
            "CLIENTE DOIS;222;SP;DIADEMA;09990080;RUA B;20;BLOCO A; APTO 12;CENTRO;"
            "-;-;11988888888;-;-;VENDA;VENDA;-;221700399;OUTROS;-;-;15/02/2025;10:15:00;"
            "-;OP;Z517209;INSTALADA;-;108479595;-;"
            "[OFERTA CADASTRADA\nNÚMERO DA O.S 2549720232 e 2549720243];"
            "BOLETO;-;-;SIM;SIM;NÃO;NÃO;BOX CLARO TV+;SERVIÇOS AVANÇADOS;-;-;C/ FIDELIDADE;"
            "C/ FIDELIDADE;-;cli2@mail.com;15;-;NÃO;-"
        )
        # Linha 3: linha sem DATA em arquivo com timestamp de download 2026-11-11 no nome
        # NÃO deve herdar 2026-11-01 como data de competência!
        row_sem_data = (
            "1161057903;6014327000120;TOTALE;EDER SALES MONTEIRO;37760542886;"
            "CLIENTE TRES;333;SP;DIADEMA;09990080;RUA C;30;-;CENTRO;"
            "-;-;11977777777;-;-;VENDA;VENDA;-;221700400;OUTROS;-;-;-;11:00:00;"
            "-;OP;Z517209;INSTALADA;-;108479596;-;O.S 2549720999;"
            "BOLETO;-;-;SIM;SIM;NÃO;NÃO;-;SERVIÇOS AVANÇADOS;-;-;-;C/ FIDELIDADE;-;"
            "cli3@mail.com;15;-;NÃO;-"
        )
        raw_bytes = "\n".join([header_55, row_1, row_2, row_sem_data]).encode("cp1252")
        fname = "numeros-tabulacao-2026-11-11-09-20-55 [1aBiXEs0pLrm0YMYPAdOldy1XOFI9e_w-].csv"

        recs, issues = production.process_consultivo_upload(fname, raw_bytes)
        self.assertEqual(len(recs), 2)
        self.assertEqual(len(issues), 1)
        self.assertEqual(recs[0]["reference_date"], "2025-01-02")
        self.assertEqual(recs[0]["login_netsales"], "Z407899")
        self.assertEqual(recs[0]["qtde_consultivo"], 1)
        self.assertEqual(recs[0]["qtde_produtos"], 2)

        self.assertEqual(recs[1]["reference_date"], "2025-02-15")
        self.assertEqual(recs[1]["login_netsales"], "Z517209")
        self.assertEqual(recs[1]["qtde_consultivo"], 2)
        self.assertEqual(recs[1]["qtde_produtos"], 2)


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
        self.assertIn("10/09/2026", csv_txt)
        self.assertIn("10/10/2026", csv_txt)
        self.assertNotIn("2026-09-10", csv_txt)

    def test_datas_sempre_dd_mm_yyyy_sem_inversao_mm_dd_yyyy(self) -> None:
        # 1) ETL process_consultivo_upload: BR (DD/MM/YYYY, DD/MM/YY, com hora) e ISO (YYYY-MM-DD)
        csv_misto = (
            "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;PLANO TV;PLANO INTERNET;OBSERVAÇÃO\n"
            "02/10/2026;Z640001;Tecnico Um;50001;-;SERVIÇOS AVANÇADOS;111111111\n"
            "05/10/26;Z640001;Tecnico Um;50002;-;1 GIGA (FIBRA);222222222\n"
            "2026-10-08;Z640001;Tecnico Um;50003;-;1 GIGA (FIBRA);333333333\n"
            "2026-10-12 08:30:00;Z640001;Tecnico Um;50004;-;1 GIGA (FIBRA);444444444\n"
            "25/10/2026 14:20:00;Z640001;Tecnico Um;50005;-;1 GIGA (FIBRA);555555555\n"
        ).encode("utf-8-sig")
        recs, issues = production.process_consultivo_upload("misto.csv", csv_misto)
        self.assertEqual(issues, [])
        self.assertEqual(
            [r["reference_date"] for r in recs],
            [
                "2026-10-02",
                "2026-10-05",
                "2026-10-08",
                "2026-10-12",
                "2026-10-25",
            ],
        )

        # 2) Componentes Consultivo recebendo strings DD/MM/YYYY ambíguas (dia <= 12)
        df_str = pd.DataFrame(
            [
                {
                    "DATA": "02/10/2026",
                    "LOGIN NETSALES": "Z640001",
                    "VENDEDOR": "Tecnico Um",
                    "Monitor": "Monitor A",
                    "Base": "NET-ABCDM",
                    "Qtde. Cons.": 8,
                    "Qtde. Prod.": 12,
                    "Qtde. Mesh": 8,
                    "Qtde. TV": 2,
                    "Qtde. Virtua": 2,
                    "imported_at": "2026-11-02 08:49:11",
                }
            ]
        )
        df_norm = normalizar_coluna_data_consultivo(df_str)
        self.assertEqual(df_norm.iloc[0]["DATA"], pd.Timestamp("2026-10-02"))
        self.assertEqual(formatar_data_br_consultivo("02/10/2026"), "02/10/2026")
        self.assertEqual(formatar_data_br_consultivo("2026-10-02"), "02/10/2026")

        diario = preparar_resumo_diario_monitor(df_str)
        self.assertEqual(diario.iloc[0]["Data"], "02/10/2026")

        evol = preparar_evolucao_mensal_consultivo(df_str)
        self.assertEqual(evol.iloc[0]["Competência"], "out/26")

        html_dt = gerar_html_tabela_cons(
            pd.DataFrame([{"Data": pd.Timestamp("2026-10-02"), "Monitor": "Monitor A"}])
        )
        self.assertIn("02/10/2026", html_dt)
        self.assertNotIn("2026-10-02", html_dt)

        csv_out = sanitizar_csv_exportacao(df_str).decode("utf-8-sig")
        self.assertIn("02/10/2026", csv_out)
        self.assertIn("02/11/2026 08:49:11", csv_out)
        self.assertNotIn("10/02/2026", csv_out)

    def test_aba_consultivo_interativa_no_streamlit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "ui_consultivo.db"
            with (
                mock.patch.object(production, "DB_PATH", db_file),
                mock.patch.dict(os.environ, {"SHOW_DEMO_DATA": "1"}, clear=False),
            ):
                app = AppTest.from_file(_APP_PATH).run(timeout=30)
                app.selectbox(key="period_filter").set_value("Personalizado").run(
                    timeout=30
                )
                for di in app.date_input:
                    self.assertEqual(di.proto.format, "DD/MM/YYYY")

                app.radio(key="navigation").set_value("Consultivo").run(timeout=30)
                self.assertFalse(app.exception)
                for di in app.date_input:
                    self.assertEqual(di.proto.format, "DD/MM/YYYY")

                # Alterna para Detalhar por Técnico
                app.toggle(key="cons_toggle_vendedor").set_value(True).run(timeout=30)
                self.assertFalse(app.exception)

                # Seleciona Ano 2025 e Todo período e aciona botão Dia vigente
                app.selectbox(key="cons_periodo_preset").set_value("Ano 2025").run(
                    timeout=30
                )
                self.assertFalse(app.exception)

                app.selectbox(key="cons_periodo_preset").set_value("Todo período").run(
                    timeout=30
                )
                self.assertFalse(app.exception)

                app.button(key="cons_btn_dia_vigente").click().run(timeout=30)
                self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
