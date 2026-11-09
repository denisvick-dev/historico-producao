"""
components/__init__.py
======================
Pacote de componentes reutilizáveis do portal TOTALE.

Submódulos de UI, importados sob demanda via ``__getattr__`` (PEP 562) para
não importar Streamlit/Plotly em quem usa o pacote apenas por conveniência:

=================================  ==========================================================
Módulo                             Responsabilidade
=================================  ==========================================================
``componentes``                    Design System base (cores, fontes, KPI, heróis, tabelas)
``kpi_cards``                      Cartões de KPI avançados — substituto do ``st.metric``
``graficos``                       Tokens de identidade visual (cores TOTALE)
``css_global``                     CSS global dos componentes nativos (uma injeção por sessão)
``layout_pagina``                  Hierarquia de leitura das páginas (seções, filtros, rodapé)
``sidebar``                        Sidebar corporativa e temas
=================================  ==========================================================
"""

from typing import TYPE_CHECKING, Any

#: Submódulos do Design System expostos como atributos do pacote (lazy).
_MODULOS_DESIGN_SYSTEM = (
    "componentes",
    "css_global",
    "graficos",
    "kpi_cards",
    "layout_pagina",
    "sidebar",
)

if TYPE_CHECKING:  # apenas para ferramentas estáticas; não importa em runtime
    from . import (  # noqa: F401
        componentes,
        css_global,
        graficos,
        kpi_cards,
        layout_pagina,
        sidebar,
    )


def __getattr__(nome: str) -> Any:
    """Importa os módulos de UI sob demanda (PEP 562)."""
    if nome in _MODULOS_DESIGN_SYSTEM:
        from importlib import import_module

        return import_module(f"{__name__}.{nome}")
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")


def __dir__() -> list[str]:
    return sorted([*globals().keys(), *_MODULOS_DESIGN_SYSTEM])


__all__ = [
    *_MODULOS_DESIGN_SYSTEM,
]
