"""Inicialização e roteamento do histórico de produção.

Os elementos visuais ficam em ``components/`` e as regras de negócio em
``production.py``. Este arquivo apenas conecta dados, navegação e páginas.
"""

import streamlit as st

from components.data_import import render_import, template_file
from components.filters import apply_filters
from components.history import render_history
from components.layout import (
    apply_styles,
    render_demo_banner,
    render_empty_state,
    render_footer,
    render_page_header,
    render_sidebar,
)
from components.overview import render_overview
from components.technicians import render_technicians
from production import create_demonstration, database_stats, init_database, load_records

st.set_page_config(
    page_title="Histórico de produção | Totale",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_styles()

PAGE_TITLES = {
    "Visão geral": (
        "Histórico de produção",
        "Acompanhe a evolução e os resultados da equipe técnica.",
    ),
    "Histórico": (
        "Histórico de produção",
        "Detalhamento mensal da produção por técnico.",
    ),
    "Técnicos": (
        "Produção por técnico",
        "Analise a evolução individual e compare com a equipe.",
    ),
    "Importar dados": (
        "Base de produção",
        "Importação, validação e gestão das planilhas.",
    ),
}

init_database()
create_demonstration()
records = load_records()
stats = database_stats()
is_demo = bool(stats["records"] and stats["demo_rows"] == stats["records"])

navigation = render_sidebar()
title, subtitle = PAGE_TITLES[navigation]
render_page_header(title, subtitle, stats)

if is_demo:
    render_demo_banner()

if navigation == "Importar dados":
    render_import(is_demo)
elif records.empty:
    render_empty_state()
    st.download_button(
        "Baixar planilha modelo",
        data=template_file(),
        file_name="modelo_producao.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    filtered, technicians, months = apply_filters(records)
    if filtered.empty:
        st.info("Não há produção para os filtros selecionados. Ajuste o período ou os técnicos.")
    elif navigation == "Visão geral":
        render_overview(filtered, records, technicians, months)
    elif navigation == "Histórico":
        render_history(filtered)
    elif navigation == "Técnicos":
        render_technicians(filtered)

render_footer()
