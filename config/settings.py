"""Configurações centrais do portal."""

from __future__ import annotations

import os

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

VERSAO_PORTAL_PADRAO = "3.7.0"
AMBIENTE_PORTAL_PADRAO = "Produção"


def _obter_configuracao(chave: str) -> str | None:
    """Lê uma configuração dos secrets do Streamlit e, em seguida, do ambiente."""
    try:
        valor = st.secrets.get(chave)
    except (KeyError, StreamlitSecretNotFoundError, AttributeError):
        valor = None

    if valor is None or not str(valor).strip():
        valor = os.getenv(chave)

    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip()


def obter_versao_portal() -> str | None:
    """Retorna a versão configurada em ``TOTALE_VERSAO``, se houver."""
    return _obter_configuracao("TOTALE_VERSAO")


def obter_ambiente_portal() -> str | None:
    """Retorna o ambiente configurado em ``TOTALE_AMBIENTE``, se houver."""
    return _obter_configuracao("TOTALE_AMBIENTE")


VERSAO_PORTAL = obter_versao_portal() or VERSAO_PORTAL_PADRAO
AMBIENTE_PORTAL = obter_ambiente_portal() or AMBIENTE_PORTAL_PADRAO

__all__ = [
    "AMBIENTE_PORTAL",
    "AMBIENTE_PORTAL_PADRAO",
    "VERSAO_PORTAL",
    "VERSAO_PORTAL_PADRAO",
    "obter_ambiente_portal",
    "obter_versao_portal",
]
