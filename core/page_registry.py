"""Registro declarativo de módulos com carregamento sob demanda (lazy import) e slugs URL."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any


@dataclass(frozen=True)
class PageSpec:
    """Metadados e política de carregamento de um módulo do painel."""

    key: str
    slug: str
    sidebar_label: str
    title: str
    subtitle: str
    badge: str
    groups: tuple[str, ...]
    module_path: str | None = None
    callable_name: str | None = None
    needs_production: bool = True
    needs_consultivo: bool = False
    needs_roster: bool = False
    uses_materialized_monthly: bool = False
    custom_hero: bool = False


PAGE_SPECS: tuple[PageSpec, ...] = (
    PageSpec(
        key="Visão geral",
        slug="visao-geral",
        sidebar_label=":material/dashboard:  Visão Executiva · Produção",
        title="Visão Executiva · Produção Operacional",
        subtitle="Monitoramento consolidado de pontuação técnica (Prod + Gpon), produtividade e evolução das equipes.",
        badge="TOTALE · GESTÃO OPERACIONAL",
        groups=("Executivo",),
        uses_materialized_monthly=True,
    ),
    PageSpec(
        key="Modo Reunião",
        slug="modo-reuniao",
        sidebar_label=":material/present_to_all:  Modo Reunião · Briefing Executivo",
        title="Modo Reunião · Briefing Executivo Semanal",
        subtitle="Resumo executivo em 1 página com destaques, alertas críticos, comparativo WoW/MoM por Base, governança e exportação pronta para PDF/Excel.",
        badge="TOTALE · BRIEFING EXECUTIVO",
        groups=("Executivo",),
        module_path="components.modo_reuniao",
        callable_name="render_modo_reuniao",
        needs_consultivo=True,
        needs_roster=True,
        uses_materialized_monthly=True,
    ),
    PageSpec(
        key="Visão 360°",
        slug="visao-360",
        sidebar_label=":material/hub:  Visão 360° · Prod × Consultivo",
        title="Visão 360° Operacional × Comercial",
        subtitle="Cruzamento integrado entre Produção Técnica (Prod + Gpon, O.S. e Contratos) e Performance Consultiva (NetSales) por Técnico, Monitor, Base e U.N.",
        badge="TOTALE · VISÃO 360°",
        groups=("Executivo", "Comercial"),
        module_path="components.visao_360",
        callable_name="render_visao_360",
        needs_consultivo=True,
        needs_roster=True,
    ),
    PageSpec(
        key="Radar de Alertas",
        slug="radar-alertas",
        sidebar_label=":material/notifications_active:  Radar de Alertas",
        title="Radar de Alertas & Gestão à Vista",
        subtitle="Sinalizações priorizadas de oportunidades de virada de faixa, quedas MoM, ativos sem apontamento, lacunas consultivas e governança.",
        badge="TOTALE · GESTÃO À VISTA",
        groups=("Executivo",),
        module_path="components.radar_alertas",
        callable_name="render_radar_alertas",
        needs_consultivo=True,
        needs_roster=True,
    ),
    PageSpec(
        key="Scorecard Supervisão",
        slug="scorecard-supervisao",
        sidebar_label=":material/leaderboard:  Scorecard · Monitor & Base",
        title="Scorecard de Supervisão · Monitor, Base e U.N.",
        subtitle="Avaliação consolidada de span of control, cobertura produtiva, dispersão interna, participação em Faixas 4–5 e conversão comercial.",
        badge="TOTALE · SCORECARD DE SUPERVISÃO",
        groups=("Executivo",),
        module_path="components.scorecard_supervisao",
        callable_name="render_scorecard_supervisao",
        needs_consultivo=True,
        needs_roster=True,
    ),
    PageSpec(
        key="Comparativo 2025 x 2026",
        slug="comparativo-2025-2026",
        sidebar_label=":material/compare_arrows:  Produção 2025 × 2026",
        title="Comparativo Interanual 2025 × 2026 · Produção, Contratos e O.S.",
        subtitle="Análise interanual de pontuação, contratos distintos, ordens de serviço (Prod), giro O.S./contrato e evolução por equipe.",
        badge="TOTALE · GESTÃO OPERACIONAL",
        groups=("Executivo",),
        module_path="components.comparativo_anos",
        callable_name="render_comparativo_anos",
        needs_consultivo=True,
        needs_roster=True,
        uses_materialized_monthly=True,
        custom_hero=True,
    ),
    PageSpec(
        key="Consultivo 2025 x 2026",
        slug="consultivo-2025-2026",
        sidebar_label=":material/trending_up:  Consultivo 2025 × 2026",
        title="Comparativo Interanual 2025 × 2026 · Performance Consultiva",
        subtitle="Análise interanual de consultivos realizados, mix comercial (Mesh, TV Box, Virtua), conversão e metas por equipe.",
        badge="TOTALE · GESTÃO OPERACIONAL",
        groups=("Comercial",),
        module_path="components.comparativo_consultivo",
        callable_name="render_comparativo_consultivo",
        needs_production=False,
        needs_consultivo=True,
        needs_roster=True,
        uses_materialized_monthly=True,
        custom_hero=True,
    ),
    PageSpec(
        key="Consultivo",
        slug="consultivo",
        sidebar_label=":material/support_agent:  Performance Consultiva",
        title="Performance Consultiva & Mix Comercial",
        subtitle="Indicadores consolidados de consultivos realizados, funil NetSales, mix de planos e vínculo com o quadro ativo.",
        badge="TOTALE · GESTÃO OPERACIONAL",
        groups=("Comercial",),
        module_path="components.consultivo",
        callable_name="render_consultivo",
        needs_production=False,
        needs_consultivo=True,
        needs_roster=True,
        custom_hero=True,
    ),
    PageSpec(
        key="Projetos",
        slug="projetos",
        sidebar_label=":material/account_tree:  Gestão por Projeto",
        title="Gestão Operacional por Projeto",
        subtitle="Comparativo executivo de pontuação, ordens de serviço e participação percentual por frente de projeto.",
        badge="TOTALE · GESTÃO POR PROJETO",
        groups=("Operação",),
        module_path="components.visoes_dashboards",
        callable_name="render_projetos",
    ),
    PageSpec(
        key="Quantidade de O.S.",
        slug="quantidade-os",
        sidebar_label=":material/assignment:  Ordens de Serviço (O.S.)",
        title="Gestão de Ordens de Serviço (O.S.)",
        subtitle="Acompanhamento de ordens de serviço produtivas (aba Prod) por competência, projeto e técnico.",
        badge="TOTALE · ORDENS DE SERVIÇO",
        groups=("Operação",),
        module_path="components.prod_os",
        callable_name="render_prod_orders",
    ),
    PageSpec(
        key="Contratos",
        slug="contratos",
        sidebar_label=":material/description:  Gestão de Contratos",
        title="Gestão & Eficiência de Contratos",
        subtitle="Monitoramento de contratos distintos atendidos por competência, técnico e faixa de eficiência operacional.",
        badge="TOTALE · GESTÃO DE CONTRATOS",
        groups=("Operação",),
        module_path="components.contratos",
        callable_name="render_contratos",
    ),
    PageSpec(
        key="Produtividade unitária",
        slug="produtividade-unitaria",
        sidebar_label=":material/speed:  Produtividade Unitária",
        title="Produtividade Unitária & Densidade Técnica",
        subtitle="Relação entre pontos por O.S., pontos por contrato e posicionamento volume × complexidade da equipe.",
        badge="TOTALE · PERFORMANCE & PRODUTIVIDADE",
        groups=("Operação",),
        module_path="components.produtividade_unitaria",
        callable_name="render_produtividade_unitaria",
    ),
    PageSpec(
        key="Qualidade & Ritmo",
        slug="qualidade-ritmo",
        sidebar_label=":material/verified:  Qualidade, Reincidência & Ritmo",
        title="Qualidade, Reincidência & Ritmo Diário",
        subtitle="Auditoria de reincidência por contrato/O.S., cadência por dia da semana (Seg–Sáb) e projeção de fechamento mensal.",
        badge="TOTALE · QUALIDADE & RITMO DIÁRIO",
        groups=("Operação",),
        module_path="components.qualidade_ritmo",
        callable_name="render_qualidade_ritmo",
    ),
    PageSpec(
        key="Regularidade",
        slug="regularidade",
        sidebar_label=":material/calendar_month:  Regularidade & Sazonalidade",
        title="Regularidade Operacional & Sazonalidade",
        subtitle="Análise estatística de médias, medianas, coeficiente de variação, lacunas e mapa de calor mensal por técnico ou projeto.",
        badge="TOTALE · REGULARIDADE & SAZONALIDADE",
        groups=("Operação",),
        module_path="components.visoes_dashboards",
        callable_name="render_regularidade_producao",
    ),
    PageSpec(
        key="Eficiência",
        slug="eficiencia",
        sidebar_label=":material/bolt:  Matriz de Eficiência",
        title="Matriz de Eficiência Mensal por Técnico",
        subtitle="Classificação mensal de faixas de entrega e predominância histórica de performance da equipe.",
        badge="TOTALE · MATRIZ DE EFICIÊNCIA",
        groups=("Operação",),
        module_path="components.eficiencia",
        callable_name="render_eficiencia",
    ),
    PageSpec(
        key="Técnicos",
        slug="tecnicos",
        sidebar_label=":material/person:  Desempenho Individual",
        title="Desempenho Individual de Técnicos",
        subtitle="Dossiê individual técnico + consultivo, melhor competência e comparação direta lado a lado.",
        badge="TOTALE · DESEMPENHO INDIVIDUAL",
        groups=("Pessoas & Dados",),
        needs_consultivo=True,
    ),
    PageSpec(
        key="Turnover & Ramp-up",
        slug="turnover-rampup",
        sidebar_label=":material/group_remove:  Turnover & Curva de Ramp-up",
        title="Turnover, Capacidade Perdida & Curva de Ramp-up",
        subtitle="Análise de desligamentos, motivos, perda de capacidade produtiva mensal e curva de maturação de novos técnicos.",
        badge="TOTALE · RETENÇÃO & MATURAÇÃO",
        groups=("Pessoas & Dados",),
        module_path="components.turnover_rampup",
        callable_name="render_turnover_rampup",
        needs_roster=True,
    ),
    PageSpec(
        key="Quadro de técnicos",
        slug="quadro-tecnicos",
        sidebar_label=":material/groups:  Quadro Cadastral (Ativos)",
        title="Quadro Cadastral & Conciliação de Ativos",
        subtitle="Conciliação executiva entre o cadastro oficial (lista_ativos / desligados) e entregas por Monitor, U.N. e Base.",
        badge="TOTALE · GOVERNANÇA CADASTRAL",
        groups=("Pessoas & Dados",),
        module_path="components.quadro_tecnicos",
        callable_name="render_quadro_tecnicos",
        needs_roster=True,
    ),
    PageSpec(
        key="Saúde dos dados",
        slug="saude-dos-dados",
        sidebar_label=":material/monitor_heart:  Governança & Dados",
        title="Governança de Dados & Auditoria de Importações",
        subtitle="Rastreabilidade de cobertura, lotes sincronizados no Google Drive, tabelas materializadas, De-Para e backup SQLite.",
        badge="TOTALE · GOVERNANÇA DE DADOS",
        groups=("Pessoas & Dados",),
        module_path="components.visoes_dashboards",
        callable_name="render_saude_dados",
        needs_consultivo=True,
        needs_roster=True,
        uses_materialized_monthly=True,
    ),
)

PAGE_SPEC_BY_KEY: dict[str, PageSpec] = {spec.key: spec for spec in PAGE_SPECS}
PAGE_KEY_BY_SLUG: dict[str, str] = {spec.slug: spec.key for spec in PAGE_SPECS}

NAV_GROUP_ORDER: tuple[str, ...] = (
    "Todos",
    "Executivo",
    "Operação",
    "Comercial",
    "Pessoas & Dados",
)


def build_nav_labels() -> dict[str, str]:
    """Mapa ``chave_pagina -> rótulo exibido na sidebar``."""
    return {spec.key: spec.sidebar_label for spec in PAGE_SPECS}


def build_nav_groups() -> dict[str, list[str]]:
    """Agrupamentos temáticos usados no seletor da sidebar."""
    groups: dict[str, list[str]] = {"Todos": [spec.key for spec in PAGE_SPECS]}
    for group_name in NAV_GROUP_ORDER[1:]:
        groups[group_name] = [
            spec.key for spec in PAGE_SPECS if group_name in spec.groups
        ]
    return groups


def resolve_page_key(raw_value: str | None, *, default: str = "Visão geral") -> str:
    """Resolve nome canônico ou slug URL (ex.: ``modo-reuniao``) para chave de página."""
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return default
    if cleaned in PAGE_SPEC_BY_KEY:
        return cleaned
    slug_key = PAGE_KEY_BY_SLUG.get(cleaned.lower())
    if slug_key:
        return slug_key
    return default


def load_page_callable(page_key: str) -> Any:
    """Importa sob demanda (lazy import) o renderer associado à página informada."""
    spec = PAGE_SPEC_BY_KEY.get(page_key)
    if spec is None or not spec.module_path or not spec.callable_name:
        return None
    module = importlib.import_module(spec.module_path)
    return getattr(module, spec.callable_name)
