"""components/graficos.py
=========================
Tokens de identidade visual TOTALE.

Versão: 1.0.0
Autor: TOTALE Tecnologia

Módulo slim: hospeda as cores oficiais da marca (**Azul ``#012869``** e
**Laranja ``#F37C04``**) consumidas pelos componentes de UI. A fábrica de
gráficos Plotly Express (24 tipos) foi removida: nenhuma página a consumia —
os gráficos do app são renderizados diretamente com Streamlit/Plotly nas
vistas, e os tokens daqui garantem a coesão visual entre eles.

Como usar::

    from components.graficos import AZUL_TOTALE, LARANJA_TOTALE
"""

from __future__ import annotations

# ====================================================
# 🎨 IDENTIDADE VISUAL TOTALE
# ====================================================
AZUL_TOTALE = "#012869"
AZUL_CLARO = "#0A48AA"
AZUL_ESCURO = "#011838"
LARANJA_TOTALE = "#F37C04"
LARANJA_CLARO = "#FF9D45"
LARANJA_ESCURO = "#C2410C"
