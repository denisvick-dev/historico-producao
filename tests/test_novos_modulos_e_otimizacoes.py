from __future__ import annotations

from datetime import date
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from components.componentes import CSSInjector
from components.consultivo import preparar_funil_netsales
from components.eficiencia import calcular_eficiencia
from components.qualidade_ritmo import (
    calcular_reincidencia_contratos,
    calcular_ritmo_diario_producao,
)
from components.radar_alertas import calcular_radar_alertas
from components.scorecard_supervisao import calcular_scorecard_supervisao
from components.turnover_rampup import calcular_curva_rampup, calcular_turnover
from components.visao_360 import calcular_visao_360, resumo_consultivo_tecnico
import production

_APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


class Visao360Tests(unittest.TestCase):
    """Testes unitários da Visão 360° Operacional × Comercial."""

    def test_calcular_visao_360_cruzamento_quadrantes_e_agregacoes(self) -> None:
        prod = pd.DataFrame(
            [
                # Ana: alta produção + alto consultivo -> Elite 360°
                {
                    "reference_date": pd.Timestamp("2026-09-10"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "points": 300.0,
                    "source_sheet": "Prod",
                    "contract": "1001",
                    "monitor": "Carlos",
                    "base": "Base Sul",
                    "un": "SP-SUL",
                    "roster_status": "ATIVO",
                    "login": "T1001",
                },
                {
                    "reference_date": pd.Timestamp("2026-09-12"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "points": 150.0,
                    "source_sheet": "Gpon",
                    "contract": "1002",
                    "monitor": "Carlos",
                    "base": "Base Sul",
                    "un": "SP-SUL",
                    "roster_status": "ATIVO",
                    "login": "T1001",
                },
                # Bruno: alta produção + baixo consultivo -> Forte Operacional
                {
                    "reference_date": pd.Timestamp("2026-09-10"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Bruno Lima",
                    "points": 420.0,
                    "source_sheet": "Prod",
                    "contract": "2001",
                    "monitor": "Carlos",
                    "base": "Base Sul",
                    "un": "SP-SUL",
                    "roster_status": "ATIVO",
                    "login": "T1002",
                },
                # Carla: baixa produção + alto consultivo -> Forte Comercial
                {
                    "reference_date": pd.Timestamp("2026-09-11"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Carla Souza",
                    "points": 180.0,
                    "source_sheet": "Prod",
                    "contract": "3001",
                    "monitor": "Marcos",
                    "base": "Base Norte",
                    "un": "SP-NORTE",
                    "roster_status": "ATIVO",
                    "login": "T1003",
                },
                # Diego: baixa produção + zero consultivo -> Em Desenvolvimento
                {
                    "reference_date": pd.Timestamp("2026-09-15"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Diego Rocha",
                    "points": 120.0,
                    "source_sheet": "Prod",
                    "contract": "4001",
                    "monitor": "Marcos",
                    "base": "Base Norte",
                    "un": "SP-NORTE",
                    "roster_status": "ATIVO",
                    "login": "T1004",
                },
            ]
        )
        cons = pd.DataFrame(
            [
                {
                    "DATA": pd.Timestamp("2026-09-10"),
                    "VENDEDOR": "Ana Silva",
                    "LOGIN NETSALES": "T1001",
                    "CONTRATO": "1001",
                    "Qtde. Cons.": 6,
                    "Qtde. Prod.": 9,
                    "Qtde. Mesh": 4,
                    "Qtde. TV": 3,
                    "Qtde. Virtua": 2,
                    "MONITOR": "Carlos",
                    "BASE": "Base Sul",
                    "UN": "SP-SUL",
                },
                {
                    "DATA": pd.Timestamp("2026-09-11"),
                    "VENDEDOR": "Carla Souza",
                    "LOGIN NETSALES": "T1003",
                    "CONTRATO": "3001",
                    "Qtde. Cons.": 8,
                    "Qtde. Prod.": 10,
                    "Qtde. Mesh": 5,
                    "Qtde. TV": 3,
                    "Qtde. Virtua": 2,
                    "MONITOR": "Marcos",
                    "BASE": "Base Norte",
                    "UN": "SP-NORTE",
                },
                {
                    "DATA": pd.Timestamp("2026-09-14"),
                    "VENDEDOR": "Bruno Lima",
                    "LOGIN NETSALES": "T1002",
                    "CONTRATO": "2001",
                    "Qtde. Cons.": 1,
                    "Qtde. Prod.": 1,
                    "Qtde. Mesh": 1,
                    "Qtde. TV": 0,
                    "Qtde. Virtua": 0,
                    "MONITOR": "Carlos",
                    "BASE": "Base Sul",
                    "UN": "SP-SUL",
                },
            ]
        )
        res = calcular_visao_360(prod, cons)
        self.assertEqual(res.total_tecnicos, 4)
        self.assertAlmostEqual(res.pontos_totais, 1170.0)
        self.assertEqual(res.consultivos_totais, 15)
        self.assertEqual(res.produtos_totais, 20)
        self.assertEqual(res.contratos_comum, 3)

        quads = dict(
            zip(
                res.por_tecnico["Técnico"],
                res.por_tecnico["Quadrante 360°"],
                strict=False,
            )
        )
        self.assertEqual(quads["Ana Silva"], "Elite 360°")
        self.assertEqual(quads["Bruno Lima"], "Forte Técnico · Potencial Comercial")
        self.assertEqual(quads["Carla Souza"], "Forte Comercial · Potencial Técnico")
        self.assertEqual(quads["Diego Rocha"], "Atenção Prioritária")
        self.assertFalse(res.por_monitor.empty)
        self.assertFalse(res.por_base.empty)
        self.assertFalse(res.por_un.empty)
        self.assertEqual(len(res.evolucao_mensal), 1)

        ind = resumo_consultivo_tecnico(cons, "Ana Silva", login="T1001")
        self.assertEqual(ind["consultivos"], 6)
        self.assertEqual(ind["produtos"], 9)
        self.assertEqual(ind["mesh"], 4)
        self.assertAlmostEqual(ind["conversao_pct"], 150.0)


class RadarAlertasTests(unittest.TestCase):
    """Testes unitários das 6 regras do Radar de Alertas."""

    def test_dispara_todos_os_seis_tipos_de_alerta(self) -> None:
        prod = pd.DataFrame(
            [
                # Ana: 285 pts no último mês (Zona Limiar 275-299.99) + sem consultivo
                {
                    "reference_date": pd.Timestamp("2026-08-10"),
                    "period": pd.Timestamp("2026-08-01"),
                    "technician": "Ana Silva",
                    "points": 300.0,
                    "source_sheet": "Prod",
                    "contract": "1001",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "roster_status": "ATIVO",
                    "login": "L1",
                },
                {
                    "reference_date": pd.Timestamp("2026-09-10"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "points": 285.0,
                    "source_sheet": "Prod",
                    "contract": "1002",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "roster_status": "ATIVO",
                    "login": "L1",
                },
                # Bruno: queda brusca MoM (-90%) e alta oscilação (CV > 50%)
                {
                    "reference_date": pd.Timestamp("2026-07-10"),
                    "period": pd.Timestamp("2026-07-01"),
                    "technician": "Bruno Lima",
                    "points": 600.0,
                    "source_sheet": "Prod",
                    "contract": "2001",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "roster_status": "ATIVO",
                    "login": "L2",
                },
                {
                    "reference_date": pd.Timestamp("2026-08-10"),
                    "period": pd.Timestamp("2026-08-01"),
                    "technician": "Bruno Lima",
                    "points": 500.0,
                    "source_sheet": "Prod",
                    "contract": "2002",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "roster_status": "ATIVO",
                    "login": "L2",
                },
                {
                    "reference_date": pd.Timestamp("2026-09-10"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Bruno Lima",
                    "points": 50.0,
                    "source_sheet": "Prod",
                    "contract": "2003",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "roster_status": "ATIVO",
                    "login": "L2",
                },
                # Extra não cadastrado
                {
                    "reference_date": pd.Timestamp("2026-09-12"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Visitante Sem Cadastro",
                    "points": 100.0,
                    "source_sheet": "Prod",
                    "contract": "9001",
                    "monitor": "Sem monitor",
                    "base": "Sem base",
                    "un": "Sem U.N.",
                    "roster_status": "Não cadastrado",
                    "login": "",
                },
            ]
        )
        roster = pd.DataFrame(
            [
                {
                    "technician_key": production.normalize_text("Ana Silva"),
                    "technician_name": "Ana Silva",
                    "status": "ATIVO",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "login": "L1",
                },
                {
                    "technician_key": production.normalize_text("Bruno Lima"),
                    "technician_name": "Bruno Lima",
                    "status": "ATIVO",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                    "login": "L2",
                },
                {
                    "technician_key": production.normalize_text("Carlos Parado"),
                    "technician_name": "Carlos Parado",
                    "status": "ATIVO",
                    "monitor": "Marcos",
                    "base": "Norte",
                    "un": "SP",
                    "login": "L3",
                },
            ]
        )
        cons = pd.DataFrame(
            [
                {
                    "DATA": pd.Timestamp("2026-09-11"),
                    "VENDEDOR": "Bruno Lima",
                    "LOGIN NETSALES": "L2",
                    "Qtde. Cons.": 2,
                    "Qtde. Prod.": 2,
                }
            ]
        )
        res = calcular_radar_alertas(prod, consultivo_frame=cons, roster_frame=roster)
        categorias = set(res.alertas["Categoria"].tolist())
        self.assertIn("Zona Limiar de Faixa", categorias)
        self.assertIn("Queda Brusca MoM", categorias)
        self.assertIn("Ativo Sem Produção", categorias)
        self.assertIn("Em Campo Sem Consultivo", categorias)
        self.assertIn("Alta Oscilação (CV)", categorias)
        self.assertIn("Produção Sem Cadastro", categorias)
        self.assertGreaterEqual(res.criticos, 2)
        self.assertGreaterEqual(res.oportunidades, 1)


class FunilNetSalesTests(unittest.TestCase):
    """Testes do Funil NetSales & Mix de Planos em components/consultivo.py."""

    def test_preparar_funil_netsales_filtra_sinteticos_e_calcula_taxas(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "STATUS NETSALES": "Instalado",
                    "TIPO DE TABULAÇÃO": "Venda Consultiva",
                    "PLANO INTERNET": "Claro Virtua 500M",
                    "PLANO TV": "Claro TV+ Box",
                    "TIPO SERVIÇO": "VT / Reparo",
                    "Qtde. Cons.": 1,
                    "Qtde. Prod.": 2,
                },
                {
                    "STATUS NETSALES": "Cancelado",
                    "TIPO DE TABULAÇÃO": "Sem Interesse",
                    "PLANO INTERNET": "NA",
                    "PLANO TV": "NA",
                    "TIPO SERVIÇO": "Instalação",
                    "Qtde. Cons.": 1,
                    "Qtde. Prod.": 0,
                },
                {
                    "STATUS NETSALES": "SEM MOVIMENTAÇÃO",
                    "TIPO DE TABULAÇÃO": "SEM MOVIMENTAÇÃO",
                    "PLANO INTERNET": "NA",
                    "PLANO TV": "NA",
                    "TIPO SERVIÇO": "SEM MOVIMENTAÇÃO",
                    "Qtde. Cons.": 0,
                    "Qtde. Prod.": 0,
                },
            ]
        )
        funil = preparar_funil_netsales(df)
        self.assertEqual(int(funil["status"]["Registros"].sum()), 2)
        self.assertEqual(int(funil["tabulacao"]["Registros"].sum()), 2)
        self.assertEqual(len(funil["planos"]), 2)
        self.assertEqual(len(funil["servicos"]), 2)
        inst = funil["status"][funil["status"]["Status NetSales"].eq("Instalado")].iloc[
            0
        ]
        self.assertAlmostEqual(float(inst["Conversão (%)"]), 200.0)


class ScorecardQualidadeTurnoverTests(unittest.TestCase):
    """Testes dos módulos da Fase 3 (Scorecard, Qualidade/Ritmo, Turnover/Ramp-up)."""

    def test_scorecard_supervisao_calcula_cobertura_f45_e_indice(self) -> None:
        prod = pd.DataFrame(
            [
                {
                    "reference_date": pd.Timestamp("2026-09-10"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "points": 420.0,
                    "source_sheet": "Prod",
                    "contract": "1001",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                },
                {
                    "reference_date": pd.Timestamp("2026-09-12"),
                    "period": pd.Timestamp("2026-09-01"),
                    "technician": "Bruno Lima",
                    "points": 310.0,
                    "source_sheet": "Prod",
                    "contract": "1002",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                },
            ]
        )
        roster = pd.DataFrame(
            [
                {
                    "technician_key": "ana silva",
                    "status": "ATIVO",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                },
                {
                    "technician_key": "bruno lima",
                    "status": "ATIVO",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                },
                {
                    "technician_key": "terceiro ativo",
                    "status": "ATIVO",
                    "monitor": "Carlos",
                    "base": "Sul",
                    "un": "SP",
                },
            ]
        )
        cons = pd.DataFrame(
            [
                {
                    "DATA": pd.Timestamp("2026-09-10"),
                    "MONITOR": "Carlos",
                    "BASE": "Sul",
                    "UN": "SP",
                    "Qtde. Cons.": 5,
                    "Qtde. Prod.": 6,
                }
            ]
        )
        sc = calcular_scorecard_supervisao(
            prod, consultivo_frame=cons, roster_frame=roster, dimensao="Monitor"
        )
        self.assertEqual(len(sc), 1)
        row = sc.iloc[0]
        self.assertEqual(int(row["Headcount Ativo"]), 3)
        self.assertEqual(int(row["Ativos Produzindo"]), 2)
        self.assertAlmostEqual(float(row["Cobertura (%)"]), 66.666, places=1)
        self.assertAlmostEqual(float(row["% Faixas 4–5"]), 50.0)
        self.assertGreater(float(row["Índice Supervisão"]), 0.0)

    def test_reincidencia_ignora_mesmo_dia_e_detecta_retorno_na_janela(self) -> None:
        prod = pd.DataFrame(
            [
                # Mesmo dia Prod + Gpon para o contrato 5001 -> apenas 1 visita
                {
                    "reference_date": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "project": "Fibra",
                    "contract": "5001",
                    "wo": "WO-1",
                    "points": 100.0,
                    "source_sheet": "Prod",
                    "monitor": "Carlos",
                    "base": "Sul",
                },
                {
                    "reference_date": pd.Timestamp("2026-09-01"),
                    "technician": "Ana Silva",
                    "project": "Fibra",
                    "contract": "5001",
                    "wo": "WO-1",
                    "points": 50.0,
                    "source_sheet": "Gpon",
                    "monitor": "Carlos",
                    "base": "Sul",
                },
                # Retorno em 5 dias -> reincidência atribuída à Ana Silva
                {
                    "reference_date": pd.Timestamp("2026-09-06"),
                    "technician": "Bruno Lima",
                    "project": "Fibra",
                    "contract": "5001",
                    "wo": "WO-2",
                    "points": 80.0,
                    "source_sheet": "Prod",
                    "monitor": "Carlos",
                    "base": "Sul",
                },
                # Contrato único sem retorno
                {
                    "reference_date": pd.Timestamp("2026-09-02"),
                    "technician": "Ana Silva",
                    "project": "Fibra",
                    "contract": "5002",
                    "wo": "WO-3",
                    "points": 90.0,
                    "source_sheet": "Prod",
                    "monitor": "Carlos",
                    "base": "Sul",
                },
            ]
        )
        reinc = calcular_reincidencia_contratos(prod, janela_dias=15)
        self.assertEqual(reinc.contratos_validos, 2)
        self.assertEqual(reinc.contratos_reincidentes, 1)
        self.assertEqual(reinc.eventos_reincidencia, 1)
        self.assertAlmostEqual(reinc.taxa_reincidencia_pct, 50.0)
        self.assertEqual(reinc.eventos.iloc[0]["Técnico Origem"], "Ana Silva")
        self.assertEqual(int(reinc.eventos.iloc[0]["Intervalo (dias)"]), 5)

        ritmo_andamento = calcular_ritmo_diario_producao(prod, hoje=date(2026, 9, 10))
        self.assertFalse(ritmo_andamento.por_dia_semana.empty)
        self.assertGreater(
            ritmo_andamento.pontos_projetados, ritmo_andamento.pontos_realizados
        )
        ritmo_encerrado = calcular_ritmo_diario_producao(prod, hoje=date(2026, 11, 16))
        self.assertAlmostEqual(
            ritmo_encerrado.pontos_projetados, ritmo_encerrado.pontos_realizados
        )

    def test_turnover_e_curva_rampup(self) -> None:
        roster = pd.DataFrame(
            [
                {
                    "technician_key": "ana silva",
                    "technician_name": "Ana Silva",
                    "status": "ATIVO",
                    "base": "Sul",
                    "monitor": "Carlos",
                    "un": "SP",
                    "termination_date": "",
                    "termination_reason": "",
                },
                {
                    "technician_key": "ex tecnico",
                    "technician_name": "Ex Técnico",
                    "status": "DESLIGADO",
                    "base": "Sul",
                    "monitor": "Carlos",
                    "un": "SP",
                    "termination_date": "2026-08-20",
                    "termination_reason": "Pedido de demissão",
                },
            ]
        )
        prod = pd.DataFrame(
            [
                {
                    "reference_date": pd.Timestamp("2026-06-15"),
                    "period": pd.Timestamp("2026-06-01"),
                    "technician": "Ex Técnico",
                    "points": 320.0,
                    "source_sheet": "Prod",
                },
                {
                    "reference_date": pd.Timestamp("2026-07-15"),
                    "period": pd.Timestamp("2026-07-01"),
                    "technician": "Ex Técnico",
                    "points": 360.0,
                    "source_sheet": "Prod",
                },
                {
                    "reference_date": pd.Timestamp("2026-07-15"),
                    "period": pd.Timestamp("2026-07-01"),
                    "technician": "Ana Silva",
                    "points": 210.0,
                    "source_sheet": "Prod",
                },
                {
                    "reference_date": pd.Timestamp("2026-08-15"),
                    "period": pd.Timestamp("2026-08-01"),
                    "technician": "Ana Silva",
                    "points": 330.0,
                    "source_sheet": "Prod",
                },
            ]
        )
        turn = calcular_turnover(roster, prod)
        self.assertEqual(turn.total_ativos, 1)
        self.assertEqual(turn.total_desligados, 1)
        self.assertAlmostEqual(turn.taxa_turnover_pct, 50.0)
        self.assertAlmostEqual(turn.capacidade_perdida_mensal, 340.0)
        self.assertEqual(turn.motivo_principal, "Pedido de demissão")

        ramp = calcular_curva_rampup(prod, meta_pontos=300.0)
        self.assertEqual(ramp.meta_pontos, 300.0)
        self.assertGreater(ramp.media_mes_1, 0.0)
        self.assertEqual(len(ramp.curva_maturacao), 2)


class OtimizacoesInfraestruturaTests(unittest.TestCase):
    """Valida correções de stats/files, SQLite PRAGMAs, eficiência vetorizada e CSS idempotente."""

    def test_database_stats_e_snapshot_retornam_files_e_months_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stats_check.db"
            old_db = production.DB_PATH
            try:
                production.DB_PATH = db_path
                production._INITIALIZED_DBS.clear()
                production.create_demonstration()
                stats = production.database_stats()
                self.assertGreater(stats["files"], 0)
                self.assertGreater(stats["months_count"], 0)
                self.assertGreater(stats["roster_active"], 0)

                _, snap_stats = production.load_dashboard_snapshot()
                self.assertEqual(snap_stats["files"], stats["files"])
                self.assertEqual(snap_stats["months_count"], stats["months_count"])

                with production.connect() as conn:
                    mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0])
                    self.assertEqual(mode.lower(), "wal")
            finally:
                production.DB_PATH = old_db

    def test_eficiencia_vetorizada_preserva_empates(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-01-01"),
                    "points": 310.0,
                },  # Faixa 2
                {
                    "technician": "Ana",
                    "period": pd.Timestamp("2026-02-01"),
                    "points": 360.0,
                },  # Faixa 3
            ]
        )
        _, resumo = calcular_eficiencia(df)
        self.assertEqual(len(resumo), 1)
        self.assertEqual(resumo.iloc[0]["Faixa mais frequente"], "Faixa 2 / Faixa 3")

    def test_css_injector_idempotente_por_tema(self) -> None:
        fake_state: dict[str, object] = {}
        with (
            patch("components.componentes.st.session_state", fake_state),
            patch("components.componentes._safe_render_html") as mock_html,
            patch("components.componentes._injetar_js") as mock_js,
        ):
            CSSInjector.injetar(tema_sidebar="azul")
            self.assertEqual(mock_html.call_count, 1)
            self.assertEqual(mock_js.call_count, 1)
            # Segunda chamada com mesmo tema não reinjeta nada
            CSSInjector.injetar(tema_sidebar="azul")
            self.assertEqual(mock_html.call_count, 1)
            self.assertEqual(mock_js.call_count, 1)
            # Troca de tema volta a injetar
            CSSInjector.injetar(tema_sidebar="claro")
            self.assertEqual(mock_html.call_count, 2)
            self.assertEqual(mock_js.call_count, 2)
            # forcar=True força nova injeção
            CSSInjector.injetar(tema_sidebar="claro", forcar=True)
            self.assertEqual(mock_html.call_count, 3)
            self.assertEqual(mock_js.call_count, 3)


class NovosModulosUiAppTests(unittest.TestCase):
    """Testes AppTest de ponta a ponta para todas as novas páginas e melhorias na UI."""

    def test_todas_novas_paginas_e_enriquecimentos_renderizam_sem_excecao(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "novos_modulos_ui.db"
            old_db = production.DB_PATH
            old_env = os.environ.get("PRODUCAO_DB_PATH")
            try:
                production.DB_PATH = db_path
                production._INITIALIZED_DBS.clear()
                os.environ["PRODUCAO_DB_PATH"] = str(db_path)

                app = AppTest.from_file(_APP_PATH).run(timeout=30)
                self.assertFalse(app.exception)

                # Filtro global U.N. + botão Limpar presentes na Visão geral
                ms_keys = {w.key for w in app.multiselect}
                btn_keys = {w.key for w in app.button}
                self.assertIn("un_filter", ms_keys)
                self.assertIn("clear_global_filters_button", btn_keys)

                # Todas as 5 novas páginas + páginas enriquecidas abrem sem exceção
                for pagina in (
                    "Visão 360°",
                    "Radar de Alertas",
                    "Scorecard Supervisão",
                    "Qualidade & Ritmo",
                    "Turnover & Ramp-up",
                    "Regularidade",
                    "Técnicos",
                    "Consultivo",
                ):
                    with self.subTest(pagina=pagina):
                        app.radio(key="navigation").set_value(pagina).run(timeout=30)
                        self.assertFalse(app.exception)

                # Confirma 4ª aba do Funil NetSales presente na página Consultivo
                titulos_abas = [tab.label for tab in app.tabs]
                self.assertTrue(
                    any("Funil NetSales" in t for t in titulos_abas),
                    f"Esperava aba Funil NetSales em {titulos_abas}",
                )
            finally:
                production.DB_PATH = old_db
                if old_env is None:
                    os.environ.pop("PRODUCAO_DB_PATH", None)
                else:
                    os.environ["PRODUCAO_DB_PATH"] = old_env


if __name__ == "__main__":
    unittest.main()
