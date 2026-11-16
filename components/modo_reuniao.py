"""Modo Reunião — Briefing Executivo Semanal em 1 página com exportação HTML/PDF e Excel.

Consolida em uma única visão orientada a reunião operacional:
- KPIs executivos de Produção + Consultivo + Qualidade (com deltas)
- Narrativa executiva gerada automaticamente sobre os números do período
- Top 3 Destaques Positivos (pontuação, score 360° e aceleração)
- Top 3 Alertas Críticos (priorizados do Radar de Alertas)
- Comparativo WoW (7d × 7d anteriores) e MoM (mês atual × mês anterior) por Base
- Pendências de Governança de Dados (ativos sem produção, não cadastrados, contratos sem ID)
- Série mensal consolidada a partir das tabelas materializadas
- Exportação em documento HTML5 autocontido com layout ``@media print`` pronto para PDF
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_drilldown_tecnico,
    render_kpi,
    render_section_header,
)
from components.pacote_executivo import gerar_pacote_executivo_xlsx
from components.qualidade_ritmo import calcular_reincidencia_contratos
from components.radar_alertas import calcular_radar_alertas
from components.visao_360 import calcular_visao_360
from production import (
    PROD,
    format_points,
    month_label,
    normalize_text,
    summarize,
    summarize_os,
)


@dataclass
class BriefingReuniao:
    """Payload consolidado para tela de 1 página e relatório HTML/PDF."""

    periodo_label: str
    gerado_em: str
    pontos_totais: float
    pontos_delta_pct: float | None
    os_totais: int
    contratos_totais: int
    tecnicos_ativos_periodo: int
    pontos_por_os: float
    consultivos_totais: int
    produtos_totais: int
    conversao_consultiva_pct: float
    taxa_reincidencia_pct: float
    total_alertas_criticos: int
    total_alertas_atencao: int
    narrativa_bullets: list[str] = field(default_factory=list)
    top_destaques: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_alertas: pd.DataFrame = field(default_factory=pd.DataFrame)
    comparativo_wow_bases: pd.DataFrame = field(default_factory=pd.DataFrame)
    comparativo_mom_bases: pd.DataFrame = field(default_factory=pd.DataFrame)
    wow_label: str = ""
    mom_label: str = ""
    pendencias_governanca: list[dict[str, str]] = field(default_factory=list)
    serie_mensal: pd.DataFrame = field(default_factory=pd.DataFrame)
    tecnicos_disponiveis: list[str] = field(default_factory=list)


def _format_pct_br(value: float | None, *, signed: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value:.1f}%".replace(".", ",")


def _comparar_bases_janelas(
    records: pd.DataFrame,
    atual_mask: pd.Series,
    anterior_mask: pd.Series,
) -> pd.DataFrame:
    """Agrega e compara Pontos, O.S. e Técnicos por Base entre duas janelas (vetorizado)."""
    cols = [
        "Base",
        "Pontos Atual",
        "Pontos Anterior",
        "Variação (pts)",
        "Variação (%)",
        "O.S. Atual",
        "Técnicos Ativos",
        "Status",
    ]
    if records.empty:
        return pd.DataFrame(columns=cols)

    base_col = (
        records["base"]
        .fillna("Sem base")
        .astype(str)
        .str.strip()
        .replace("", "Sem base")
        if "base" in records.columns
        else pd.Series("Operação Geral", index=records.index)
    )
    work = pd.DataFrame(
        {
            "Base": base_col,
            "points": pd.to_numeric(records["points"], errors="coerce").fillna(0.0),
            "is_prod": records["source_sheet"].eq(PROD).astype("int32"),
            "technician": records["technician"].astype(str),
        },
        index=records.index,
    )

    df_atual = work.loc[atual_mask]
    df_ant = work.loc[anterior_mask]
    if df_atual.empty and df_ant.empty:
        return pd.DataFrame(columns=cols)

    agg_atual = (
        df_atual.groupby("Base", as_index=False).agg(
            pontos_atual=("points", "sum"),
            os_atual=("is_prod", "sum"),
            tecnicos_ativos=("technician", "nunique"),
        )
        if not df_atual.empty
        else pd.DataFrame(
            columns=["Base", "pontos_atual", "os_atual", "tecnicos_ativos"]
        )
    )
    agg_ant = (
        df_ant.groupby("Base", as_index=False).agg(pontos_ant=("points", "sum"))
        if not df_ant.empty
        else pd.DataFrame(columns=["Base", "pontos_ant"])
    )

    merged = pd.merge(agg_atual, agg_ant, on="Base", how="outer")
    merged["pontos_atual"] = merged["pontos_atual"].fillna(0.0)
    merged["pontos_ant"] = merged["pontos_ant"].fillna(0.0)
    merged["os_atual"] = merged["os_atual"].fillna(0).astype(int)
    merged["tecnicos_ativos"] = merged["tecnicos_ativos"].fillna(0).astype(int)
    merged["var_pts"] = merged["pontos_atual"] - merged["pontos_ant"]
    merged["var_pct"] = (
        merged["var_pts"]
        .div(merged["pontos_ant"].where(merged["pontos_ant"].gt(0)))
        .mul(100.0)
    )

    status = pd.Series("Estável", index=merged.index, dtype="object")
    status = status.mask(
        merged["pontos_ant"].le(0) & merged["pontos_atual"].gt(0), "Nova janela"
    )
    status = status.mask(
        merged["pontos_atual"].le(0) & merged["pontos_ant"].gt(0), "Sem apontamento"
    )
    status = status.mask(merged["var_pct"].ge(3.0), "Alta")
    status = status.mask(merged["var_pct"].le(-3.0), "Queda")

    result = pd.DataFrame(
        {
            "Base": merged["Base"],
            "Pontos Atual": merged["pontos_atual"].round(2),
            "Pontos Anterior": merged["pontos_ant"].round(2),
            "Variação (pts)": merged["var_pts"].round(2),
            "Variação (%)": merged["var_pct"].round(1),
            "O.S. Atual": merged["os_atual"],
            "Técnicos Ativos": merged["tecnicos_ativos"],
            "Status": status,
        }
    )
    return result.sort_values("Pontos Atual", ascending=False).reset_index(drop=True)


def _construir_serie_mensal_briefing(
    records: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None,
    monthly_prod_summary: pd.DataFrame | None,
    monthly_cons_summary: pd.DataFrame | None,
) -> pd.DataFrame:
    """Usa tabelas materializadas quando disponíveis; fallback para agregação em memória."""
    if monthly_prod_summary is not None and not monthly_prod_summary.empty:
        prod_m = (
            monthly_prod_summary.groupby("period", as_index=False)
            .agg(
                pontos_totais=("points_total", "sum"),
                os_totais=("os_count", "sum"),
                tecnicos=("technician", "nunique"),
            )
            .sort_values("period")
        )
    elif not records.empty:
        s_pts = summarize(records, "period")
        s_os = summarize_os(records, "period")
        s_tec = records.groupby("period", as_index=False).agg(
            tecnicos=("technician", "nunique")
        )
        prod_m = (
            s_pts.merge(s_os, on="period", how="left")
            .merge(s_tec, on="period", how="left")
            .rename(columns={"points_total": "pontos_totais", "os_count": "os_totais"})
            .sort_values("period")
        )
        prod_m["os_totais"] = prod_m["os_totais"].fillna(0).astype(int)
    else:
        return pd.DataFrame(
            columns=[
                "period",
                "Competência",
                "Pontos Totais",
                "O.S. (Prod)",
                "Consultivos",
                "Técnicos",
            ]
        )

    if monthly_cons_summary is not None and not monthly_cons_summary.empty:
        cons_m = monthly_cons_summary.groupby("period", as_index=False).agg(
            consultivos=("qtde_consultivo", "sum")
        )
    elif consultivo_frame is not None and not consultivo_frame.empty:
        c_col = (
            "QTDE_CONSULTIVO"
            if "QTDE_CONSULTIVO" in consultivo_frame.columns
            else "Qtde. Cons."
        )
        if "period" in consultivo_frame.columns and c_col in consultivo_frame.columns:
            cons_m = (
                consultivo_frame.assign(
                    period=pd.to_datetime(consultivo_frame["period"], errors="coerce")
                )
                .dropna(subset=["period"])
                .groupby("period", as_index=False)
                .agg(consultivos=(c_col, "sum"))
            )
        else:
            cons_m = pd.DataFrame(columns=["period", "consultivos"])
    else:
        cons_m = pd.DataFrame(columns=["period", "consultivos"])

    merged = prod_m.merge(cons_m, on="period", how="left")
    merged["consultivos"] = merged["consultivos"].fillna(0).astype(int)
    merged["Competência"] = merged["period"].map(month_label)
    return (
        pd.DataFrame(
            {
                "period": merged["period"],
                "Competência": merged["Competência"],
                "Pontos Totais": merged["pontos_totais"].round(2),
                "O.S. (Prod)": merged["os_totais"].astype(int),
                "Consultivos": merged["consultivos"].astype(int),
                "Técnicos": merged["tecnicos"].fillna(0).astype(int),
            }
        )
        .tail(12)
        .reset_index(drop=True)
    )


def montar_briefing_reuniao(
    records: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    *,
    periodo_label: str = "Período selecionado",
    monthly_prod_summary: pd.DataFrame | None = None,
    monthly_cons_summary: pd.DataFrame | None = None,
) -> BriefingReuniao:
    """Calcula todos os blocos do Modo Reunião (1 página) de forma pura e testável."""
    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")
    if records is None or records.empty:
        return BriefingReuniao(
            periodo_label=periodo_label,
            gerado_em=gerado_em,
            pontos_totais=0.0,
            pontos_delta_pct=None,
            os_totais=0,
            contratos_totais=0,
            tecnicos_ativos_periodo=0,
            pontos_por_os=0.0,
            consultivos_totais=0,
            produtos_totais=0,
            conversao_consultiva_pct=0.0,
            taxa_reincidencia_pct=0.0,
            total_alertas_criticos=0,
            total_alertas_atencao=0,
            narrativa_bullets=[
                "Sem registros de produção no recorte atual para geração do briefing."
            ],
        )

    work = records.copy()
    work["reference_date"] = pd.to_datetime(work["reference_date"], errors="coerce")
    work = work.dropna(subset=["reference_date"])
    if "period" not in work.columns:
        work["period"] = work["reference_date"].dt.to_period("M").dt.to_timestamp()

    v360 = calcular_visao_360(work, consultivo_frame, roster_frame)
    radar = calcular_radar_alertas(work, consultivo_frame, roster_frame)
    reinc = calcular_reincidencia_contratos(work, janela_dias=30)

    pontos_totais = float(v360.pontos_totais)
    os_totais = int(v360.os_totais)
    contratos_totais = int(v360.contratos_totais)
    tecnicos_ativos = int(work["technician"].nunique())
    pontos_por_os = round(pontos_totais / os_totais, 2) if os_totais > 0 else 0.0

    # --- WoW (últimos 7 dias vs 7 dias anteriores) ---
    max_dt = work["reference_date"].max()
    wow_start = max_dt - pd.Timedelta(days=6)
    wow_prev_end = wow_start - pd.Timedelta(days=1)
    wow_prev_start = wow_prev_end - pd.Timedelta(days=6)
    wow_atual_mask = work["reference_date"].between(wow_start, max_dt)
    wow_prev_mask = work["reference_date"].between(wow_prev_start, wow_prev_end)
    wow_bases = _comparar_bases_janelas(work, wow_atual_mask, wow_prev_mask)
    wow_label = (
        f"{wow_start.strftime('%d/%m')}–{max_dt.strftime('%d/%m/%Y')} "
        f"vs {wow_prev_start.strftime('%d/%m')}–{wow_prev_end.strftime('%d/%m/%Y')}"
    )

    # --- MoM (última competência vs competência imediatamente anterior) ---
    periods_sorted = sorted(work["period"].dropna().unique())
    pontos_delta_pct: float | None = None
    mom_label = "Competência única no recorte"
    if len(periods_sorted) >= 2:
        p_atual = pd.Timestamp(periods_sorted[-1])
        p_ant = pd.Timestamp(periods_sorted[-2])
        mom_atual_mask = work["period"].eq(p_atual)
        mom_prev_mask = work["period"].eq(p_ant)
        mom_bases = _comparar_bases_janelas(work, mom_atual_mask, mom_prev_mask)
        pts_atual_m = float(work.loc[mom_atual_mask, "points"].sum())
        pts_ant_m = float(work.loc[mom_prev_mask, "points"].sum())
        if pts_ant_m > 0:
            pontos_delta_pct = (pts_atual_m - pts_ant_m) / pts_ant_m * 100.0
        mom_label = f"{month_label(p_atual)} vs {month_label(p_ant)}"
    else:
        p_only = pd.Timestamp(periods_sorted[-1]) if periods_sorted else max_dt
        mom_bases = _comparar_bases_janelas(
            work,
            work["period"].eq(p_only),
            pd.Series(False, index=work.index),
        )
        mom_label = f"{month_label(p_only)} (sem mês anterior no recorte)"

    # --- Top 3 Destaques Positivos ---
    if not v360.por_tecnico.empty:
        dest_src = v360.por_tecnico.sort_values(
            ["Score 360°", "Pontos Totais"], ascending=[False, False]
        ).head(3)
        top_destaques = pd.DataFrame(
            {
                "Técnico": dest_src["Técnico"].astype(str),
                "Base": dest_src["Base"].astype(str),
                "Monitor": dest_src["Monitor"].astype(str),
                "Pontos Totais": dest_src["Pontos Totais"].round(2),
                "Consultivos": dest_src["Consultivos"].astype(int),
                "Score 360°": dest_src["Score 360°"].round(1),
                "Quadrante": dest_src["Quadrante 360°"].astype(str),
            }
        ).reset_index(drop=True)
    else:
        top_destaques = pd.DataFrame(
            columns=[
                "Técnico",
                "Base",
                "Monitor",
                "Pontos Totais",
                "Consultivos",
                "Score 360°",
                "Quadrante",
            ]
        )

    # --- Top 3 Alertas Críticos ---
    if not radar.alertas.empty:
        sev_rank = {"Crítico": 0, "Atenção": 1, "Oportunidade": 2}
        al_sorted = (
            radar.alertas.assign(
                _ord=radar.alertas["Severidade"].map(sev_rank).fillna(9)
            )
            .sort_values(["_ord", "Categoria", "Técnico"])
            .drop(columns=["_ord"])
            .head(3)
            .reset_index(drop=True)
        )
        top_alertas = al_sorted[
            [
                "Severidade",
                "Categoria",
                "Técnico",
                "Base",
                "Indicador",
                "Detalhe",
                "Ação Recomendada",
            ]
        ]
    else:
        top_alertas = pd.DataFrame(
            columns=[
                "Severidade",
                "Categoria",
                "Técnico",
                "Base",
                "Indicador",
                "Detalhe",
                "Ação Recomendada",
            ]
        )

    # --- Pendências de Governança ---
    pendencias: list[dict[str, str]] = []
    if roster_frame is not None and not roster_frame.empty:
        ativos_roster = roster_frame[
            roster_frame["status"].astype(str).str.upper().eq("ATIVO")
        ]
        keys_prod = {normalize_text(t) for t in work["technician"].dropna().unique()}
        ativos_sem_prod = int(
            sum(
                1
                for k in ativos_roster["technician_key"].dropna().unique()
                if str(k) not in keys_prod
            )
        )
        pendencias.append(
            {
                "item": "Técnicos ATIVOS sem produção no recorte",
                "valor": str(ativos_sem_prod),
                "nivel": "critico"
                if ativos_sem_prod >= 5
                else ("atencao" if ativos_sem_prod > 0 else "ok"),
                "acao": "Validar férias, afastamentos ou desligamentos pendentes no cadastro.",
            }
        )
    if "roster_status" in work.columns:
        nao_cad = int(
            work.loc[
                work["roster_status"].isin(["Sem cadastro", "Não cadastrado"]),
                "technician",
            ].nunique()
        )
        pendencias.append(
            {
                "item": "Técnicos produzindo sem vínculo cadastral",
                "valor": str(nao_cad),
                "nivel": "atencao" if nao_cad > 0 else "ok",
                "acao": "Criar regra De-Para na aba Saúde dos dados ou atualizar lista_ativos.",
            }
        )
    if "contract" in work.columns:
        sem_contrato_pct = float(work["contract"].eq("Sem contrato").mean() * 100.0)
        pendencias.append(
            {
                "item": "Registros sem identificador de contrato",
                "valor": f"{sem_contrato_pct:.1f}%".replace(".", ","),
                "nivel": "critico"
                if sem_contrato_pct >= 25.0
                else ("atencao" if sem_contrato_pct >= 10.0 else "ok"),
                "acao": "Auditar cabeçalho da coluna Contrato nos lotes recentes.",
            }
        )
    pendencias.append(
        {
            "item": "Reincidência de contratos (janela 30 dias)",
            "valor": f"{reinc.taxa_reincidencia_pct:.1f}%".replace(".", ","),
            "nivel": "critico"
            if reinc.taxa_reincidencia_pct >= 20.0
            else ("atencao" if reinc.taxa_reincidencia_pct >= 10.0 else "ok"),
            "acao": "Priorizar revisão de qualidade nos contratos reincidentes.",
        }
    )

    # --- Narrativa Executiva Automática ---
    narrativa: list[str] = []
    delta_txt = (
        f" ({_format_pct_br(pontos_delta_pct)} vs competência anterior)"
        if pontos_delta_pct is not None
        else ""
    )
    narrativa.append(
        f"A operação entregou {format_points(pontos_totais)} pontos{delta_txt}, "
        f"com {formatar_numero_br(os_totais)} O.S. produtivas ({format_points(pontos_por_os)} pts/O.S.) "
        f"e {formatar_numero_br(contratos_totais)} contratos distintos atendidos por {tecnicos_ativos} técnicos."
    )
    if v360.consultivos_totais > 0:
        narrativa.append(
            f"No frente comercial (NetSales), foram {formatar_numero_br(v360.consultivos_totais)} consultivos "
            f"e {formatar_numero_br(v360.produtos_totais)} produtos vendidos "
            f"(conversão média de {v360.conversao_pct:.1f}% e {v360.elite_count} técnico(s) no quadrante Elite 360°).".replace(
                ".", ","
            )
        )
    if not top_destaques.empty:
        lider = top_destaques.iloc[0]
        narrativa.append(
            f"Destaque do período: {lider['Técnico']} ({lider['Base']}) liderando o Score 360° "
            f"com {lider['Score 360°']:.1f} pts de índice e {format_points(lider['Pontos Totais'])} pontos técnicos."
        )
    if not mom_bases.empty and mom_bases["Variação (%)"].notna().any():
        melhor_b = (
            mom_bases.dropna(subset=["Variação (%)"])
            .sort_values("Variação (%)", ascending=False)
            .iloc[0]
        )
        pior_b = (
            mom_bases.dropna(subset=["Variação (%)"])
            .sort_values("Variação (%)", ascending=True)
            .iloc[0]
        )
        narrativa.append(
            f"Comparativo MoM por Base ({mom_label}): maior avanço em {melhor_b['Base']} "
            f"({_format_pct_br(float(melhor_b['Variação (%)']))}) e maior atenção em {pior_b['Base']} "
            f"({_format_pct_br(float(pior_b['Variação (%)']))})."
        )
    narrativa.append(
        f"Radar de Alertas aponta {radar.criticos} alerta(s) crítico(s) e {radar.atencao} ponto(s) de atenção; "
        f"reincidência 30d em {reinc.taxa_reincidencia_pct:.1f}%.".replace(".", ",")
    )

    serie_mensal = _construir_serie_mensal_briefing(
        work, consultivo_frame, monthly_prod_summary, monthly_cons_summary
    )
    tecnicos_disp = sorted(work["technician"].dropna().astype(str).unique().tolist())

    return BriefingReuniao(
        periodo_label=periodo_label,
        gerado_em=gerado_em,
        pontos_totais=pontos_totais,
        pontos_delta_pct=pontos_delta_pct,
        os_totais=os_totais,
        contratos_totais=contratos_totais,
        tecnicos_ativos_periodo=tecnicos_ativos,
        pontos_por_os=pontos_por_os,
        consultivos_totais=int(v360.consultivos_totais),
        produtos_totais=int(v360.produtos_totais),
        conversao_consultiva_pct=float(v360.conversao_pct),
        taxa_reincidencia_pct=float(reinc.taxa_reincidencia_pct),
        total_alertas_criticos=int(radar.criticos),
        total_alertas_atencao=int(radar.atencao),
        narrativa_bullets=narrativa,
        top_destaques=top_destaques,
        top_alertas=top_alertas,
        comparativo_wow_bases=wow_bases,
        comparativo_mom_bases=mom_bases,
        wow_label=wow_label,
        mom_label=mom_label,
        pendencias_governanca=pendencias,
        serie_mensal=serie_mensal,
        tecnicos_disponiveis=tecnicos_disp,
    )


def _df_to_html_rows(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return f'<tr><td colspan="{len(columns)}" style="text-align:center;color:#64748B;padding:12px;">Sem dados no recorte.</td></tr>'
    rows_html: list[str] = []
    for row in frame[columns].itertuples(index=False, name=None):
        cells = "".join(
            f"<td>{html.escape('—' if pd.isna(val) else str(val))}</td>" for val in row
        )
        rows_html.append(f"<tr>{cells}</tr>")
    return "".join(rows_html)


def gerar_briefing_html(briefing: BriefingReuniao) -> bytes:
    """Gera documento HTML5 corporativo pronto para impressão/PDF (``@media print``)."""
    esc = html.escape
    bullets_html = "".join(f"<li>{esc(b)}</li>" for b in briefing.narrativa_bullets)

    dest_df = briefing.top_destaques.copy()
    if not dest_df.empty:
        dest_df["Pontos Totais"] = dest_df["Pontos Totais"].map(format_points)
        dest_df["Score 360°"] = dest_df["Score 360°"].map(
            lambda v: f"{float(v):.1f}".replace(".", ",")
        )
    dest_cols = [
        "Técnico",
        "Base",
        "Monitor",
        "Pontos Totais",
        "Consultivos",
        "Score 360°",
        "Quadrante",
    ]
    dest_rows = (
        _df_to_html_rows(dest_df, dest_cols)
        if not dest_df.empty
        else _df_to_html_rows(pd.DataFrame(), dest_cols)
    )

    al_cols = [
        "Severidade",
        "Categoria",
        "Técnico",
        "Base",
        "Detalhe",
        "Ação Recomendada",
    ]
    al_rows = (
        _df_to_html_rows(briefing.top_alertas, al_cols)
        if not briefing.top_alertas.empty
        else _df_to_html_rows(pd.DataFrame(), al_cols)
    )

    mom_df = briefing.comparativo_mom_bases.copy()
    if not mom_df.empty:
        mom_df["Pontos Atual"] = mom_df["Pontos Atual"].map(format_points)
        mom_df["Pontos Anterior"] = mom_df["Pontos Anterior"].map(format_points)
        mom_df["Variação (%)"] = mom_df["Variação (%)"].map(
            lambda v: _format_pct_br(None if pd.isna(v) else float(v))
        )
    base_cols = [
        "Base",
        "Pontos Atual",
        "Pontos Anterior",
        "Variação (%)",
        "O.S. Atual",
        "Técnicos Ativos",
        "Status",
    ]
    mom_rows = (
        _df_to_html_rows(mom_df, base_cols)
        if not mom_df.empty
        else _df_to_html_rows(pd.DataFrame(), base_cols)
    )

    gov_items = "".join(
        f'<div class="gov-item gov-{esc(p["nivel"])}">'
        f'<div><strong>{esc(p["item"])}</strong><div class="gov-acao">{esc(p["acao"])}</div></div>'
        f'<div class="gov-val">{esc(p["valor"])}</div></div>'
        for p in briefing.pendencias_governanca
    )

    doc = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Totale · Briefing Executivo — {esc(briefing.periodo_label)}</title>
<style>
  @page {{ size: A4 portrait; margin: 12mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: #0F172A; background: #F8FAFC; margin: 0; padding: 24px; line-height: 1.45;
  }}
  .sheet {{
    max-width: 980px; margin: 0 auto; background: #FFFFFF; border: 1px solid #E2E8F0;
    border-radius: 14px; padding: 28px 32px; box-shadow: 0 8px 24px rgba(1,40,105,0.06);
  }}
  .header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    border-bottom: 3px solid #012869; padding-bottom: 14px; margin-bottom: 18px;
  }}
  .badge {{
    display: inline-block; background: #012869; color: #FFFFFF; font-size: 10px;
    letter-spacing: 0.08em; font-weight: 700; padding: 3px 9px; border-radius: 999px;
    text-transform: uppercase; margin-bottom: 6px;
  }}
  h1 {{ margin: 0; font-size: 22px; color: #012869; }}
  .meta {{ text-align: right; font-size: 12px; color: #475569; }}
  .kpi-grid {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 18px;
  }}
  .kpi {{
    border: 1px solid #E2E8F0; border-top: 3px solid #012869; border-radius: 10px;
    padding: 10px 12px; background: #F8FAFC;
  }}
  .kpi.accent {{ border-top-color: #B85A3A; }}
  .kpi-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: #64748B; font-weight: 700; }}
  .kpi-val {{ font-size: 20px; font-weight: 800; color: #012869; margin: 3px 0; }}
  .kpi-sub {{ font-size: 11px; color: #475569; }}
  h2 {{
    font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #012869;
    margin: 20px 0 8px; padding-left: 8px; border-left: 4px solid #B85A3A;
  }}
  ul.narrativa {{ margin: 0 0 14px; padding-left: 18px; font-size: 13px; color: #1E293B; }}
  ul.narrativa li {{ margin-bottom: 5px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 12px; }}
  th {{
    background: #012869; color: #FFFFFF; text-align: left; padding: 7px 8px;
    font-size: 11px; font-weight: 600;
  }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #E2E8F0; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #F8FAFC; }}
  .gov-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }}
  .gov-item {{
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
    padding: 9px 12px; border-radius: 8px; border: 1px solid #E2E8F0; font-size: 12px;
  }}
  .gov-ok {{ border-left: 4px solid #16A34A; background: #F0FDF4; }}
  .gov-atencao {{ border-left: 4px solid #D97706; background: #FFFBEB; }}
  .gov-critico {{ border-left: 4px solid #DC2626; background: #FEF2F2; }}
  .gov-acao {{ font-size: 11px; color: #475569; margin-top: 2px; }}
  .gov-val {{ font-size: 16px; font-weight: 800; color: #0F172A; white-space: nowrap; }}
  .footer {{
    margin-top: 20px; padding-top: 10px; border-top: 1px solid #E2E8F0;
    font-size: 11px; color: #64748B; display: flex; justify-content: space-between;
  }}
  @media print {{
    body {{ background: #FFFFFF; padding: 0; }}
    .sheet {{ border: none; box-shadow: none; padding: 0; max-width: 100%; }}
    .no-print {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="header">
      <div>
        <span class="badge">Totale · Briefing Executivo Semanal</span>
        <h1>Resumo Operacional &amp; Comercial</h1>
      </div>
      <div class="meta">
        <div><strong>Recorte:</strong> {esc(briefing.periodo_label)}</div>
        <div><strong>Gerado em:</strong> {esc(briefing.gerado_em)}</div>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi-label">Pontos Totais</div>
        <div class="kpi-val">{esc(format_points(briefing.pontos_totais))}</div>
        <div class="kpi-sub">MoM: {esc(_format_pct_br(briefing.pontos_delta_pct))} · {briefing.tecnicos_ativos_periodo} técnicos</div>
      </div>
      <div class="kpi">
        <div class="kpi-label">O.S. &amp; Contratos</div>
        <div class="kpi-val">{esc(formatar_numero_br(briefing.os_totais))}</div>
        <div class="kpi-sub">{esc(formatar_numero_br(briefing.contratos_totais))} contratos · {esc(format_points(briefing.pontos_por_os))} pts/O.S.</div>
      </div>
      <div class="kpi accent">
        <div class="kpi-label">Consultivo (NetSales)</div>
        <div class="kpi-val">{esc(formatar_numero_br(briefing.consultivos_totais))}</div>
        <div class="kpi-sub">{esc(formatar_numero_br(briefing.produtos_totais))} produtos · conv. {briefing.conversao_consultiva_pct:.1f}%</div>
      </div>
      <div class="kpi accent">
        <div class="kpi-label">Qualidade &amp; Alertas</div>
        <div class="kpi-val">{briefing.total_alertas_criticos} crítico(s)</div>
        <div class="kpi-sub">{briefing.total_alertas_atencao} atenção · reinc. 30d {briefing.taxa_reincidencia_pct:.1f}%</div>
      </div>
    </div>

    <h2>Síntese Executiva</h2>
    <ul class="narrativa">{bullets_html}</ul>

    <h2>Top 3 Destaques Positivos (Score 360°)</h2>
    <table>
      <thead><tr>{"".join(f"<th>{esc(c)}</th>" for c in dest_cols)}</tr></thead>
      <tbody>{dest_rows}</tbody>
    </table>

    <h2>Top 3 Alertas Críticos &amp; Ações Recomendadas</h2>
    <table>
      <thead><tr>{"".join(f"<th>{esc(c)}</th>" for c in al_cols)}</tr></thead>
      <tbody>{al_rows}</tbody>
    </table>

    <h2>Desempenho por Base — MoM ({esc(briefing.mom_label)})</h2>
    <table>
      <thead><tr>{"".join(f"<th>{esc(c)}</th>" for c in base_cols)}</tr></thead>
      <tbody>{mom_rows}</tbody>
    </table>

    <h2>Pendências de Governança</h2>
    <div class="gov-grid">{gov_items}</div>

    <div class="footer">
      <span>Totale · Inteligência &amp; Gestão Operacional</span>
      <span>Dica: use Ctrl+P → Salvar como PDF para compartilhar</span>
    </div>
  </div>
</body>
</html>
"""
    return doc.encode("utf-8")


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _montar_briefing_cached(
    records: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None,
    roster_frame: pd.DataFrame | None,
    periodo_label: str,
    monthly_prod_summary: pd.DataFrame | None,
    monthly_cons_summary: pd.DataFrame | None,
) -> BriefingReuniao:
    return montar_briefing_reuniao(
        records,
        consultivo_frame,
        roster_frame,
        periodo_label=periodo_label,
        monthly_prod_summary=monthly_prod_summary,
        monthly_cons_summary=monthly_cons_summary,
    )


@st.fragment
def _render_fragment_bases_comparativo(briefing: BriefingReuniao) -> None:
    """Alterna entre WoW (7d×7d) e MoM por Base sem rerodagem da página inteira."""
    modo = st.radio(
        "Janela comparativa por Base",
        options=["MoM (Competência)", "WoW (Últimos 7d × 7d ant.)"],
        horizontal=True,
        key="reuniao_base_comp_modo",
    )
    if modo.startswith("WoW"):
        st.caption(f"Janela WoW: {briefing.wow_label}")
        tabela = briefing.comparativo_wow_bases
    else:
        st.caption(f"Janela MoM: {briefing.mom_label}")
        tabela = briefing.comparativo_mom_bases

    if tabela.empty:
        st.info("Sem base suficiente para comparação na janela selecionada.")
        return

    c_chart, c_tbl = st.columns([1.05, 1.35], gap="medium")
    with c_chart:
        fig = go.Figure()
        fig.add_bar(
            x=tabela["Base"],
            y=tabela["Pontos Anterior"],
            name="Janela anterior",
            marker_color="#CBD5E1",
        )
        fig.add_bar(
            x=tabela["Base"],
            y=tabela["Pontos Atual"],
            name="Janela atual",
            marker_color=Cores.PRIMARIA,
        )
        fig.update_layout(
            barmode="group",
            title=dict(
                text="Pontos por Base (Atual × Anterior)",
                font=dict(size=14, color=Cores.PRIMARIA),
            ),
            height=310,
            margin=dict(l=18, r=18, t=42, b=28),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family=Fontes.TEXTO, color=Cores.TEXTO),
            legend=dict(
                orientation="h", yanchor="bottom", y=-0.22, x=0.5, xanchor="center"
            ),
            yaxis=dict(gridcolor=Cores.BORDA),
        )
        st.plotly_chart(fig, width="stretch")
    with c_tbl:
        st.dataframe(
            tabela,
            width="stretch",
            hide_index=True,
            column_config={
                "Pontos Atual": st.column_config.NumberColumn(format="%.2f"),
                "Pontos Anterior": st.column_config.NumberColumn(format="%.2f"),
                "Variação (pts)": st.column_config.NumberColumn(format="%+.2f"),
                "Variação (%)": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )


def render_modo_reuniao(
    records: pd.DataFrame,
    *,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    periodo_label: str = "Período selecionado",
    monthly_prod_summary: pd.DataFrame | None = None,
    monthly_cons_summary: pd.DataFrame | None = None,
) -> None:
    """Renderiza a página executiva de 1 página pronta para reunião semanal."""
    if records is None or records.empty:
        st.info("Não há dados de produção no recorte para montar o Briefing Executivo.")
        return

    briefing = _montar_briefing_cached(
        records,
        consultivo_frame,
        roster_frame,
        periodo_label,
        monthly_prod_summary,
        monthly_cons_summary,
    )

    # Barra de exportação no topo (HTML/PDF + Excel Executivo 5 abas)
    exp_col1, exp_col2, exp_col3 = st.columns(
        [1.4, 1.4, 2.2], vertical_alignment="center"
    )
    html_bytes = gerar_briefing_html(briefing)
    with exp_col1:
        st.download_button(
            "📄 Exportar Briefing HTML / PDF",
            data=html_bytes,
            file_name=f"totale_briefing_executivo_{pd.Timestamp.now().strftime('%Y%m%d')}.html",
            mime="text/html",
            key="reuniao_export_html_btn",
            type="primary",
            use_container_width=True,
        )
    with exp_col2:
        xlsx_bytes = gerar_pacote_executivo_xlsx(
            records,
            consultivo_frame,
            roster_frame,
            periodo_label=periodo_label,
        )
        st.download_button(
            "📊 Exportar Pacote Executivo (.xlsx)",
            data=xlsx_bytes,
            file_name=f"totale_pacote_executivo_{pd.Timestamp.now().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="reuniao_export_xlsx_btn",
            use_container_width=True,
        )
    with exp_col3:
        st.caption(
            f"Recorte: **{briefing.periodo_label}** · Gerado em {briefing.gerado_em} · "
            "Abra o HTML exportado e pressione Ctrl+P para salvar em PDF."
        )

    # 1. KPIs consolidados (1 linha)
    k1, k2, k3, k4 = st.columns(4)
    render_kpi(
        k1,
        "PONTOS TOTAIS",
        format_points(briefing.pontos_totais),
        f"MoM {_format_pct_br(briefing.pontos_delta_pct)} · {briefing.tecnicos_ativos_periodo} técnicos",
        tema="azul",
        icone="⚡",
    )
    render_kpi(
        k2,
        "O.S. & CONTRATOS",
        formatar_numero_br(briefing.os_totais),
        f"{formatar_numero_br(briefing.contratos_totais)} contratos · {format_points(briefing.pontos_por_os)} pts/O.S.",
        tema="verde",
        icone="📋",
    )
    render_kpi(
        k3,
        "CONSULTIVO (NETSALES)",
        formatar_numero_br(briefing.consultivos_totais),
        f"{formatar_numero_br(briefing.produtos_totais)} prod. · conv. {briefing.conversao_consultiva_pct:.1f}%".replace(
            ".", ","
        ),
        tema="laranja",
        icone="🎯",
    )
    render_kpi(
        k4,
        "ALERTAS & QUALIDADE",
        f"{briefing.total_alertas_criticos} crítico(s)",
        f"{briefing.total_alertas_atencao} atenção · reinc. 30d {briefing.taxa_reincidencia_pct:.1f}%".replace(
            ".", ","
        ),
        tema="vermelho" if briefing.total_alertas_criticos > 0 else "roxo",
        icone="🚨",
    )

    # 2. Narrativa Executiva Automática
    render_section_header(
        "Síntese Executiva da Reunião",
        "Leitura automática dos principais vetores da semana/competência",
    )
    bullets_html = "".join(
        f"<li style='margin-bottom:6px;'>{html.escape(b)}</li>"
        for b in briefing.narrativa_bullets
    )
    st.markdown(
        f"""
        <div style="background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid {Cores.SECUNDARIA};
                    border-radius:12px;padding:14px 18px;margin-bottom:14px;font-family:{Fontes.TEXTO};">
            <ul style="margin:0;padding-left:18px;color:#1E293B;font-size:14px;line-height:1.55;">
                {bullets_html}
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 3. Top 3 Destaques Positivos x Top 3 Alertas Críticos (lado a lado)
    col_dest, col_al = st.columns(2, gap="medium")
    with col_dest:
        render_section_header(
            "Top 3 Destaques Positivos",
            "Líderes em Score 360° e entrega técnica no recorte",
        )
        if briefing.top_destaques.empty:
            st.info("Sem destaques disponíveis no recorte.")
        else:
            st.dataframe(
                briefing.top_destaques,
                width="stretch",
                hide_index=True,
                column_config={
                    "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
                    "Score 360°": st.column_config.NumberColumn(format="%.1f"),
                },
            )
    with col_al:
        render_section_header(
            "Top 3 Alertas Críticos",
            "Prioridades imediatas de ação para a liderança",
        )
        if briefing.top_alertas.empty:
            st.success("Nenhum alerta crítico identificado neste recorte.")
        else:
            st.dataframe(
                briefing.top_alertas[
                    [
                        "Severidade",
                        "Categoria",
                        "Técnico",
                        "Base",
                        "Detalhe",
                        "Ação Recomendada",
                    ]
                ],
                width="stretch",
                hide_index=True,
            )

    # 4. Comparativo WoW / MoM por Base (fragmento isolado)
    render_section_header(
        "Comparativo por Base (MoM / WoW)",
        "Evolução entre janelas consecutivas com destaque de altas e quedas",
    )
    _render_fragment_bases_comparativo(briefing)

    # 5. Série Mensal Consolidada (alimentada pelas tabelas materializadas) + Governança
    col_serie, col_gov = st.columns([1.35, 1.0], gap="medium")
    with col_serie:
        render_section_header(
            "Tendência Mensal Consolidada",
            "Pontos Totais e Consultivos nos últimos 12 meses (leitura materializada)",
        )
        if briefing.serie_mensal.empty:
            st.info("Série mensal indisponível.")
        else:
            fig_m = go.Figure()
            fig_m.add_bar(
                x=briefing.serie_mensal["Competência"],
                y=briefing.serie_mensal["Pontos Totais"],
                name="Pontos Totais",
                marker_color=Cores.PRIMARIA,
            )
            if briefing.serie_mensal["Consultivos"].sum() > 0:
                fig_m.add_scatter(
                    x=briefing.serie_mensal["Competência"],
                    y=briefing.serie_mensal["Consultivos"],
                    name="Consultivos",
                    yaxis="y2",
                    mode="lines+markers",
                    line=dict(color=Cores.SECUNDARIA, width=2.5),
                )
                fig_m.update_layout(
                    yaxis2=dict(
                        title="Consultivos",
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    )
                )
            fig_m.update_layout(
                title=dict(
                    text="Produção × Consultivo por Competência",
                    font=dict(size=14, color=Cores.PRIMARIA),
                ),
                height=300,
                margin=dict(l=18, r=18, t=42, b=28),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(family=Fontes.TEXTO, color=Cores.TEXTO),
                legend=dict(
                    orientation="h", yanchor="bottom", y=-0.24, x=0.5, xanchor="center"
                ),
                yaxis=dict(gridcolor=Cores.BORDA),
            )
            st.plotly_chart(fig_m, width="stretch")

    with col_gov:
        render_section_header(
            "Checklist de Governança",
            "Pendências cadastrais, contratuais e de qualidade para saneamento",
        )
        cor_nivel = {
            "ok": ("#16A34A", "#F0FDF4"),
            "atencao": ("#D97706", "#FFFBEB"),
            "critico": ("#DC2626", "#FEF2F2"),
        }
        for pend in briefing.pendencias_governanca:
            borda, fundo = cor_nivel.get(pend["nivel"], ("#64748B", "#F8FAFC"))
            st.markdown(
                f"""
                <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;
                            padding:10px 12px;margin-bottom:8px;border-radius:10px;
                            border:1px solid #E2E8F0;border-left:4px solid {borda};background:{fundo};">
                    <div>
                        <div style="font-weight:700;font-size:13px;color:#0F172A;">{html.escape(pend["item"])}</div>
                        <div style="font-size:11.5px;color:#475569;margin-top:2px;">{html.escape(pend["acao"])}</div>
                    </div>
                    <div style="font-weight:800;font-size:16px;color:#0F172A;white-space:nowrap;">
                        {html.escape(pend["valor"])}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # 6. Drill-down direto para dossiê do técnico
    render_drilldown_tecnico(
        briefing.tecnicos_disponiveis,
        key_prefix="reuniao_drill",
        rotulo_select="Abrir dossiê 1:1 de um técnico citado na reunião",
    )
