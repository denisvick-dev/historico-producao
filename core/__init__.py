"""Camada modular interna do Painel Totale Gestão Operacional.

Separa conexão/schema SQLite (``core.db``), normalização e validação
(``core.normalization``), agregações e métricas (``core.metrics``),
tabelas materializadas e pushdown SQL (``core.summaries``), presets de
filtros persistidos (``core.presets``) e registro declarativo de módulos
com carregamento sob demanda (``core.page_registry``).
"""

from __future__ import annotations
