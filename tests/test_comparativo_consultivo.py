"""Testes unitários e de UI para o Comparativo 2025 x 2026 de Consultivos."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

import production
from components.comparativo_consultivo import (
    _sintese_executiva_consultivo,
    calcular_comparativo_consultivo,
)

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class ComparativoConsultivoCalculoTests(unittest.TestCase):
    """Valida regras de Consultivos, Mix (Mesh/TV/Virtua), datas DD/MM/YYYY e coortes."""

    def _sample_consultivo(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                # Out/2025 - Ana (ATIVO, Z640001): 12 consultivos, 32 produtos (bate meta >=30!)
                {
                    "DATA": "02/10/2025",
                    "LOGIN NETSALES": "Z640001",
                    "VENDEDOR": "Ana Souza",
                    "Técnico": "Ana Souza",
                    "Monitor": "Edson",
                    "Base": "NET-ABCDM",
                    "U.N.": "ABCDM-TOTALE",
                    "Situação": "ATIVO",
                    "TIPO SERVIÇO": "SERVIÇOS AVANÇADOS",
                    "Qtde. Cons.": 12,
                    "Qtde. Prod.": 32,
                    "Qtde. Mesh": 20,
                    "Qtde. TV": 4,
                    "Qtde. Virtua": 8,
                },
                # Out/2025 - Tiago (DESLIGADO, Z649999): 5 consultivos, 8 produtos
                {
                    "DATA": "2025-10-08",
                    "LOGIN NETSALES": "Z649999",
                    "VENDEDOR": "Tiago Mendes",
                    "Técnico": "Tiago Mendes",
                    "Monitor": "Adriano",
                    "Base": "NET-GUARULHOS",
                    "U.N.": "GRS-TOTALE",
                    "Situação": "DESLIGADO",
                    "TIPO SERVIÇO": "1 GIGA (FIBRA)",
                    "Qtde. Cons.": 5,
                    "Qtde. Prod.": 8,
                    "Qtde. Mesh": 0,
                    "Qtde. TV": 0,
                    "Qtde. Virtua": 8,
                },
                # Dez/2025 - Ana (fora da interseção quando 2026 só tem Outubro): 4 consultivos, 6 produtos
                {
                    "DATA": "15/12/2025",
                    "LOGIN NETSALES": "Z640001",
                    "VENDEDOR": "Ana Souza",
                    "Técnico": "Ana Souza",
                    "Monitor": "Edson",
                    "Base": "NET-ABCDM",
                    "U.N.": "ABCDM-TOTALE",
                    "Situação": "ATIVO",
                    "TIPO SERVIÇO": "CLARO TV+ BOX",
                    "Qtde. Cons.": 4,
                    "Qtde. Prod.": 6,
                    "Qtde. Mesh": 0,
                    "Qtde. TV": 6,
                    "Qtde. Virtua": 0,
                },
                # Out/2026 - Ana (mesmo login Z640001 com grafia abreviada): 18 consultivos, 45 produtos
                {
                    "DATA": "05/10/2026",
                    "LOGIN NETSALES": "z640001",
                    "VENDEDOR": "ANA S.",
                    "Técnico": "Ana Souza",
                    "Monitor": "Edson",
                    "Base": "NET-ABCDM",
                    "U.N.": "ABCDM-TOTALE",
                    "Situação": "ATIVO",
                    "TIPO SERVIÇO": "CLARO TV+ BOX & 600 MEGA (FIBRA)",
                    "Qtde. Cons.": 18,
                    "Qtde. Prod.": 45,
                    "Qtde. Mesh": 30,
                    "Qtde. TV": 9,
                    "Qtde. Virtua": 6,
                },
                # Out/2026 - Bia (nova em 2026, ATIVO): 6 consultivos, 15 produtos
                {
                    "DATA": "2026-10-12",
                    "LOGIN NETSALES": "Z640002",
                    "VENDEDOR": "Bia Lima",
                    "Técnico": "Bia Lima",
                    "Monitor": "Elisangela",
                    "Base": "NET-LESTE",
                    "U.N.": "SPO-TOTALLESTE",
                    "Situação": "ATIVO",
                    "TIPO SERVIÇO": "SERVIÇOS AVANÇADOS",
                    "Qtde. Cons.": 6,
                    "Qtde. Prod.": 15,
                    "Qtde. Mesh": 12,
                    "Qtde. TV": 0,
                    "Qtde. Virtua": 3,
                },
            ]
        )

    def test_modo_equivalente_datas_dd_mm_yyyy_e_mix_produtos(self) -> None:
        resumo = calcular_comparativo_consultivo(
            self._sample_consultivo(),
            modo_meses="equivalente",
            escopo_equipe="todos",
        )
        # Apenas Outubro (mês 10) está presente em ambos os anos; Dez/2025 fica fora do equivalente.
        self.assertEqual(resumo.meses_disponiveis_base, [10, 12])
        self.assertEqual(resumo.meses_disponiveis_comp, [10])
        self.assertEqual(resumo.meses_considerados, [10])
        self.assertFalse(resumo.fallback_sem_intersecao)

        # Garante datas estritamente em DD/MM/YYYY sem inversão MM/DD/YYYY em dia <= 12.
        self.assertEqual(resumo.data_min_base, "02/10/2025")
        self.assertEqual(resumo.data_max_base, "08/10/2025")
        self.assertEqual(resumo.data_min_comp, "05/10/2026")
        self.assertEqual(resumo.data_max_comp, "12/10/2026")

        # Out/2025: 12 + 5 = 17 consultivos; 32 + 8 = 40 produtos (conv. 2,35).
        self.assertEqual(resumo.consultivos_base, 17)
        self.assertEqual(resumo.produtos_base, 40)
        self.assertAlmostEqual(resumo.conversao_base, 2.35, places=2)

        # Out/2026: 18 + 6 = 24 consultivos; 45 + 15 = 60 produtos (conv. 2,50).
        self.assertEqual(resumo.consultivos_comp, 24)
        self.assertEqual(resumo.produtos_comp, 60)
        self.assertEqual(resumo.delta_consultivos, 7)
        self.assertEqual(resumo.delta_produtos, 20)
        self.assertAlmostEqual(resumo.conversao_comp, 2.50, places=2)

        # Mix de produtos: Mesh salta de 20 (50,0%) para 42 (70,0%) => +20,0 p.p.
        mesh_row = resumo.mix_produtos[resumo.mix_produtos["Produto"] == "Mesh"].iloc[0]
        self.assertEqual(int(mesh_row["Qtde 2025"]), 20)
        self.assertEqual(int(mesh_row["Qtde 2026"]), 42)
        self.assertAlmostEqual(float(mesh_row["Δ Share (p.p.)"]), 20.0, places=1)

        # Taxa de meta mensal por técnico (>= 30 produtos): 1/2 (50%) em Out/25 e 1/2 (50%) em Out/26.
        self.assertAlmostEqual(resumo.taxa_meta_tecnico_base, 50.0, places=1)
        self.assertAlmostEqual(resumo.taxa_meta_tecnico_comp, 50.0, places=1)

    def test_escopos_ativos_e_mesma_equipe_unificam_por_login(self) -> None:
        ativos = calcular_comparativo_consultivo(
            self._sample_consultivo(),
            modo_meses="equivalente",
            escopo_equipe="ativos",
        )
        # Tiago (DESLIGADO) sai de 2025; Ana permanece em 2025 (12 cons) e Ana+Bia em 2026 (24 cons).
        self.assertEqual(ativos.consultivos_base, 12)
        self.assertEqual(ativos.consultivos_comp, 24)

        mesma_eq = calcular_comparativo_consultivo(
            self._sample_consultivo(),
            modo_meses="equivalente",
            escopo_equipe="mesma_equipe",
        )
        # Mesmo com grafia 'Ana Souza' vs 'ANA S.', o login Z640001 conecta as duas pontas!
        self.assertEqual(mesma_eq.equipes_comuns, 1)
        self.assertEqual(mesma_eq.consultivos_base, 12)
        self.assertEqual(mesma_eq.consultivos_comp, 18)
        self.assertEqual(mesma_eq.produtos_base, 32)
        self.assertEqual(mesma_eq.produtos_comp, 45)

    def test_cenario_apenas_2026_aciona_fallback_informativo_sem_erro(self) -> None:
        so_2026 = self._sample_consultivo()[
            self._sample_consultivo()["DATA"].str.contains("2026")
        ].copy()
        resumo = calcular_comparativo_consultivo(so_2026, modo_meses="equivalente")
        self.assertTrue(resumo.fallback_sem_intersecao)
        self.assertEqual(resumo.modo_efetivo, "ano_completo")
        self.assertEqual(resumo.consultivos_base, 0)
        self.assertEqual(resumo.consultivos_comp, 24)
        texto, tipo = _sintese_executiva_consultivo(resumo)
        self.assertEqual(tipo, "info")
        self.assertIn("Histórico Consultivo", texto)

    def test_rotacao_login_entre_2025_e_2026_unifica_mesmo_tecnico(self) -> None:
        roster = pd.DataFrame(
            [
                {
                    "technician": "EDER SALES MONTEIRO",
                    "login": "Z699964",
                    "monitor": "EDSON MARCO PINHEIRO",
                    "base": "NET-ABCDM",
                    "un": "ABCDM-TOTALE",
                    "status": "ATIVO",
                    "source_tab": production.ROSTER_ACTIVE_TAB,
                }
            ]
        )
        df = pd.DataFrame(
            [
                {
                    "DATA": "10/01/2025",
                    "LOGIN NETSALES": "Z517209",
                    "VENDEDOR": "EDER SALES MONTEIRO",
                    "Qtde. Cons.": 6,
                    "Qtde. Prod.": 10,
                    "Qtde. Mesh": 6,
                    "Qtde. TV": 2,
                    "Qtde. Virtua": 2,
                    "TIPO SERVIÇO": "Internet + TV",
                },
                {
                    "DATA": "12/01/2026",
                    "LOGIN NETSALES": "Z699964",
                    "VENDEDOR": "EDER SALES MONTEIRO",
                    "Qtde. Cons.": 9,
                    "Qtde. Prod.": 15,
                    "Qtde. Mesh": 9,
                    "Qtde. TV": 3,
                    "Qtde. Virtua": 3,
                    "TIPO SERVIÇO": "Internet + TV",
                },
            ]
        )
        resumo = calcular_comparativo_consultivo(
            df,
            roster=roster,
            modo_meses="equivalente",
            escopo_equipe="mesma_equipe",
        )
        self.assertEqual(resumo.consultivos_base, 6)
        self.assertEqual(resumo.consultivos_comp, 9)
        self.assertEqual(len(resumo.por_vendedor), 1)
        self.assertEqual(resumo.por_vendedor.iloc[0]["Login"], "Z699964")
        self.assertEqual(resumo.por_vendedor.iloc[0]["Base"], "NET-ABCDM")


class ComparativoConsultivoUiTests(unittest.TestCase):
    """Valida navegação interativa, gráficos, tabelas e atalhos no Streamlit."""

    def test_pagina_consultivo_2025_2026_e_atalhos_cruzados(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "ui_comp_consultivo.db"
            with (
                mock.patch.object(production, "DB_PATH", db_file),
                mock.patch.dict(os.environ, {"SHOW_DEMO_DATA": "1"}, clear=False),
            ):
                app = AppTest.from_file(_APP_PATH).run(timeout=30)
                self.assertFalse(app.exception)

                # Abre Consultivo operacional e clica no atalho para Consultivo 2025 x 2026.
                app.radio(key="navigation").set_value("Consultivo").run(timeout=30)
                self.assertFalse(app.exception)
                app.button(key="atalho_comp_consultivo").click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(
                    app.radio(key="navigation").value, "Consultivo 2025 x 2026"
                )

                # Verifica gráficos Plotly, tabelas e downloads CSV.
                self.assertGreaterEqual(len(app.get("plotly_chart")), 6)
                tabelas = [
                    cast("pd.DataFrame", cast("Any", item).value)
                    for item in app.get("dataframe")
                ]
                self.assertTrue(
                    any(
                        "Cons. 2025" in t.columns and "Prod. 2026" in t.columns
                        for t in tabelas
                    )
                )
                self.assertTrue(any("Δ Share (p.p.)" in t.columns for t in tabelas))
                self.assertTrue(
                    any(
                        "Baixar comparativo mensal de Consultivos"
                        in str(cast("Any", item).label)
                        for item in app.get("download_button")
                    )
                )

                # Alterna escopo de equipes e modo de meses sem exceções.
                app.selectbox(key="comp_cons_escopo_equipe").set_value(
                    "mesma_equipe"
                ).run(timeout=30)
                self.assertFalse(app.exception)
                app.selectbox(key="comp_cons_modo_meses").set_value("ano_completo").run(
                    timeout=30
                )
                self.assertFalse(app.exception)

                # Testa atalho cruzado para o Comparativo de Contratos e O.S.
                app.button(key="comp_cons_ir_contratos").click().run(timeout=30)
                self.assertFalse(app.exception)
                self.assertEqual(
                    app.radio(key="navigation").value, "Comparativo 2025 x 2026"
                )

    def test_auto_sync_carrega_bases_2025_em_sessao_aberta(self) -> None:
        import drive_import

        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "ui_autosync_2025.db"
            csv_2026 = (
                "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;PLANO TV;PLANO INTERNET;OBSERVACAO\n"
                "10/01/2026;Z641759;ALEX BERNARDES DA SILVA;1120001;-;SERVIÇOS AVANÇADOS;2599990001\n"
            ).encode("utf-8-sig")
            csv_2025 = (
                "DATA;LOGIN NETSALES;VENDEDOR;CÓDIGO CONTATO;PLANO TV;PLANO INTERNET;OBSERVACAO\n"
                '15/01/2025;Z641759;ALEX BERNARDES DA SILVA;1080001;-;SERVIÇOS AVANÇADOS;"O.S: 2524680364; 2524680353\n'
            ).encode("cp1252")

            with (
                mock.patch.object(production, "DB_PATH", db_file),
                mock.patch.dict(os.environ, {"SHOW_DEMO_DATA": "0"}, clear=False),
            ):
                production.init_database()
                recs_26, _ = production.process_consultivo_upload(
                    "numeros-tabulacao-2026-02-02 [f2026].csv", csv_2026
                )
                production.sync_consultivo_drive_records(
                    recs_26,
                    {"f2026"},
                    {"f2026"},
                    folder_id=production.DEFAULT_CONSULTIVO_FOLDER_ID,
                    file_fingerprints={
                        "f2026": f"numeros-tabulacao-2026-02-02.csv|text/csv|2026-02-02|md5a|100|{drive_import.CONSULTIVO_PARSER_VERSION}"
                    },
                )

                # Sessão inicia sem credenciais do Drive (apenas 2026 no SQLite)
                app = AppTest.from_file(_APP_PATH).run(timeout=30)
                self.assertFalse(app.exception)

                # Agora a pasta Histórico Consultivo no Drive recebe a base de 2025
                fake_drive_files = [
                    {
                        "id": "f2026",
                        "name": "numeros-tabulacao-2026-02-02.csv",
                        "mimeType": "text/csv",
                        "modifiedTime": "2026-02-02",
                        "md5Checksum": "md5a",
                        "size": "100",
                    },
                    {
                        "id": "f2025",
                        "name": "numeros-tabulacao-2026-11-11-09-20-55.csv",
                        "mimeType": "text/csv",
                        "modifiedTime": "2026-11-11T12:20:55Z",
                        "md5Checksum": "md5b",
                        "size": str(len(csv_2025)),
                    },
                ]
                fake_sa = {
                    "type": "service_account",
                    "client_email": "bot@test.iam.gserviceaccount.com",
                    "private_key": "dummy",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
                with (
                    mock.patch.dict(
                        os.environ,
                        {
                            "GOOGLE_SERVICE_ACCOUNT_JSON": __import__("json").dumps(
                                fake_sa
                            )
                        },
                        clear=False,
                    ),
                    mock.patch.object(
                        drive_import, "create_drive_session"
                    ) as mock_sess,
                    mock.patch.object(
                        drive_import, "list_folder_files", return_value=fake_drive_files
                    ),
                    mock.patch.object(
                        drive_import,
                        "download_file",
                        return_value=(
                            "numeros-tabulacao-2026-11-11-09-20-55 [f2025].csv",
                            csv_2025,
                        ),
                    ),
                ):
                    mock_sess.return_value.credentials = None
                    app.radio(key="navigation").set_value("Consultivo 2025 x 2026").run(
                        timeout=30
                    )
                    self.assertFalse(app.exception)

                    # Verifica que a base 2025 foi sincronizada e contabilizada automaticamente!
                    snap_df, _ = production.load_consultivo_snapshot()
                    anos = set(snap_df["DATA"].dt.year.dropna().astype(int).tolist())
                    self.assertEqual(anos, {2025, 2026})
                    self.assertTrue(
                        any(b.key == "comp_cons_btn_sync_drive" for b in app.button)
                    )


if __name__ == "__main__":
    unittest.main()
