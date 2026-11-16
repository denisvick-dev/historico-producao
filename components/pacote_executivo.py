"""Exportador executivo multi-aba (.xlsx) para diretoria e supervisão."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from components.qualidade_ritmo import calcular_reincidencia_contratos
from components.radar_alertas import calcular_radar_alertas
from components.scorecard_supervisao import calcular_scorecard_supervisao
from components.visao_360 import calcular_visao_360

_NAVY_FILL = PatternFill(start_color="012869", end_color="012869", fill_type="solid")
_ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
_WHITE_FILL = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
_HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
_TITLE_FONT = Font(name="Calibri", size=14, bold=True, color="012869")
_SUBTITLE_FONT = Font(name="Calibri", size=10, italic=True, color="475569")
_BODY_FONT = Font(name="Calibri", size=10, color="0F172A")
_THIN_BORDER = Border(
    left=Side(style="thin", color="E2E8F0"),
    right=Side(style="thin", color="E2E8F0"),
    top=Side(style="thin", color="E2E8F0"),
    bottom=Side(style="thin", color="CBD5E1"),
)


def _limpar_valor_excel(val: Any) -> Any:
    if val is None:
        return ""
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return ""
        return val.strftime("%Y-%m-%d")
    if isinstance(val, float) and pd.isna(val):
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return val


def _escrever_tabela_sheet(
    ws: Any,
    titulo: str,
    subtitulo: str,
    df: pd.DataFrame,
    *,
    colunas_percent: set[str] | None = None,
    colunas_int: set[str] | None = None,
    colunas_float: set[str] | None = None,
) -> None:
    colunas_percent = colunas_percent or set()
    colunas_int = colunas_int or set()
    colunas_float = colunas_float or set()

    ws["A1"] = titulo
    ws["A1"].font = _TITLE_FONT
    ws["A2"] = subtitulo
    ws["A2"].font = _SUBTITLE_FONT

    start_row = 4
    if df is None or df.empty:
        ws.cell(
            row=start_row, column=1, value="Sem dados disponíveis no recorte."
        ).font = _SUBTITLE_FONT
        ws.column_dimensions["A"].width = 40
        return

    cols = list(df.columns)
    for col_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=str(col_name))
        cell.fill = _NAVY_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = _THIN_BORDER
    ws.row_dimensions[start_row].height = 24

    col_arrays = [df.iloc[:, i].tolist() for i in range(len(cols))]
    max_widths = [max(len(str(c)) + 4, 12) for c in cols]

    for row_offset, row_vals in enumerate(zip(*col_arrays, strict=False), start=1):
        excel_row = start_row + row_offset
        fill = _ZEBRA_FILL if row_offset % 2 == 0 else _WHITE_FILL
        for col_idx, (col_name, raw_val) in enumerate(
            zip(cols, row_vals, strict=False), start=1
        ):
            val = _limpar_valor_excel(raw_val)
            cell = ws.cell(row=excel_row, column=col_idx, value=val)
            cell.font = _BODY_FONT
            cell.fill = fill
            cell.border = _THIN_BORDER
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if col_name in colunas_percent:
                    cell.number_format = "0.0"
                elif col_name in colunas_int:
                    cell.number_format = "#,##0"
                elif col_name in colunas_float:
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")
            max_widths[col_idx - 1] = min(
                max(max_widths[col_idx - 1], len(str(val)) + 3), 48
            )

    for col_idx, width in enumerate(max_widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = f"A{start_row + 1}"
    ws.auto_filter.ref = (
        f"A{start_row}:{get_column_letter(len(cols))}{start_row + len(df)}"
    )


def gerar_pacote_executivo_xlsx(
    frame_prod: pd.DataFrame,
    frame_cons: pd.DataFrame | None = None,
    roster: pd.DataFrame | None = None,
    *,
    periodo_label: str = "Histórico completo",
    filtros_resumo: str = "Sem restrições adicionais",
) -> bytes:
    """Gera arquivo .xlsx executivo com 5 abas consolidadas para diretoria."""
    cons_df = frame_cons if frame_cons is not None else pd.DataFrame()
    roster_df = roster if roster is not None else pd.DataFrame()

    resumo_360 = calcular_visao_360(frame_prod, cons_df, roster_df)
    resumo_alertas = calcular_radar_alertas(frame_prod, cons_df, roster_df)
    scorecard_df = calcular_scorecard_supervisao(
        frame_prod, cons_df, roster_df, dimensao="Monitor"
    )
    reinc = calcular_reincidencia_contratos(frame_prod)

    wb = Workbook()
    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── Aba 1: Resumo Executivo ───────────────────────────────────────────
    ws_resumo: Any = wb.active
    assert ws_resumo is not None
    ws_resumo.title = "Resumo Executivo"
    kpis_rows = [
        ("Pontos Totais (Prod + Gpon)", round(resumo_360.pontos_totais, 2), "pts"),
        ("Ordens de Serviço (O.S. Prod)", int(resumo_360.os_totais), "O.S."),
        ("Contratos Atendidos", int(resumo_360.contratos_totais), "contratos"),
        ("Técnicos no Recorte 360°", int(resumo_360.total_tecnicos), "técnicos"),
        ("Técnicos Elite 360°", int(resumo_360.elite_count), "técnicos"),
        ("Consultivos Realizados", int(resumo_360.consultivos_totais), "consultivos"),
        ("Produtos Comercializados", int(resumo_360.produtos_totais), "produtos"),
        ("Conversão Comercial (%)", round(resumo_360.conversao_pct, 2), "%"),
        ("Penetração Comercial (%)", round(resumo_360.penetracao_pct, 2), "%"),
        (
            "Taxa de Reincidência de Contratos (%)",
            round(reinc.taxa_reincidencia_pct, 2),
            "%",
        ),
        (
            "Eventos de Reincidência Detectados",
            int(reinc.eventos_reincidencia),
            "eventos",
        ),
        ("Alertas Operacionais Ativos", int(resumo_alertas.total_alertas), "alertas"),
        ("Alertas Críticos", int(resumo_alertas.criticos), "alertas"),
    ]
    resumo_kpi_df = pd.DataFrame(kpis_rows, columns=["Indicador", "Valor", "Unidade"])
    _escrever_tabela_sheet(
        ws_resumo,
        "Painel Totale · Pacote Executivo Consolidado",
        f"Recorte: {periodo_label} | Filtros: {filtros_resumo} | Gerado em {gerado_em}",
        resumo_kpi_df,
        colunas_float={"Valor"},
    )
    ws_resumo.column_dimensions["A"].width = 42
    ws_resumo.column_dimensions["B"].width = 18
    ws_resumo.column_dimensions["C"].width = 16

    # ── Aba 2: Visão 360° por Técnico ────────────────────────────────────
    ws_360 = wb.create_sheet(title="Visao 360")
    _escrever_tabela_sheet(
        ws_360,
        "Visão 360° · Produção Técnica × Performance Consultiva",
        f"Consolidado por técnico ({periodo_label})",
        resumo_360.por_tecnico,
        colunas_float={
            "Pontos Prod",
            "Pontos Gpon",
            "Pontos Totais",
            "Pontos / O.S.",
            "Score 360°",
        },
        colunas_int={
            "O.S. (Prod)",
            "Contratos",
            "Consultivos",
            "Produtos",
            "Mesh",
            "TV Box",
            "Virtua",
            "Contratos em Comum",
        },
        colunas_percent={"Conversão (%)", "Penetração Consultiva (%)"},
    )

    # ── Aba 3: Radar de Alertas ──────────────────────────────────────────
    ws_alertas = wb.create_sheet(title="Alertas")
    _escrever_tabela_sheet(
        ws_alertas,
        "Radar de Alertas & Gestão à Vista",
        f"Sinalizações priorizadas ({periodo_label} · Ref.: {resumo_alertas.competencia_referencia})",
        resumo_alertas.alertas,
    )

    # ── Aba 4: Scorecard Supervisão ──────────────────────────────────────
    ws_sup = wb.create_sheet(title="Supervisao")
    _escrever_tabela_sheet(
        ws_sup,
        "Scorecard de Supervisão por Monitor",
        f"Governança de equipe e performance combinada ({periodo_label})",
        scorecard_df,
        colunas_float={
            "Pontos Totais",
            "Média / Técnico",
            "Desvio-Padrão",
            "Índice Supervisão",
        },
        colunas_int={
            "Headcount Ativo",
            "Ativos Produzindo",
            "O.S. (Prod)",
            "Contratos",
            "Consultivos",
            "Produtos",
        },
        colunas_percent={"Cobertura (%)", "% Faixas 4–5", "Conversão (%)"},
    )

    # ── Aba 5: Série Mensal ──────────────────────────────────────────────
    ws_mensal = wb.create_sheet(title="Mensal")
    mensal_export = resumo_360.evolucao_mensal.copy()
    if "period" in mensal_export.columns:
        mensal_export = mensal_export.drop(columns=["period"])
    _escrever_tabela_sheet(
        ws_mensal,
        "Evolução Mensal Consolidada",
        f"Série temporal produção + consultivo ({periodo_label})",
        mensal_export,
        colunas_float={"Pontos Totais"},
        colunas_int={"O.S. (Prod)", "Contratos", "Consultivos", "Produtos"},
        colunas_percent={"Conversão (%)", "Penetração Consultiva (%)"},
    )

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
