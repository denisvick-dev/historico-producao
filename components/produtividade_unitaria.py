"""Painel de produtividade unitária: pontos por O.S. (Prod) e por contrato.

Cruza volume de atendimentos e complexidade (pontuação unitária) respeitando as
regras oficiais do sistema:

- **Pontos por O.S. (Prod)** = ``Pontos na aba Prod ÷ Quantidade de linhas Prod``.
- **Pontos por Contrato** = ``Pontos em registros com contrato válido ÷ Contratos
  distintos por técnico e competência`` (mesmo denominador da aba *Contratos*).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Literal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from pandas.io.formats.style import Styler

from components.componentes import Cores, formatar_numero_br, render_ticker
from components.painel_quantidades import (
    AZUL_TOTALE,
    CHART_CONFIG,
    LARANJA_TOTALE,
    chart_layout as _chart_layout,
    csv_download as _csv_download,
    section_heading as _section_heading,
)
from production import (
    GPON,
    PROD,
    clean_contract,
    format_points,
    is_valid_contract,
    month_label,
)

PerfilQuadrante = Literal[
    "Alto volume e pontuação",
    "Alta pontuação",
    "Alto giro",
    "Em desenvolvimento",
    "Sem O.S.",
    "Sem contratos",
]

REGRA_PRODUTIVIDADE = (
    "Pontos por O.S. divide apenas os pontos da aba Prod pelas linhas válidas de Prod. "
    "Pontos por contrato divide os pontos (Prod + Gpon) dos registros com contrato válido "
    "pela soma de contratos distintos por técnico e competência."
)

_CORES_PERFIL: dict[str, str] = {
    "Alto volume e pontuação": "#047857",
    "Alta pontuação": AZUL_TOTALE,
    "Alto giro": LARANJA_TOTALE,
    "Em desenvolvimento": "#64748B",
}

_ESTILOS_PERFIL: dict[str, str] = {
    "Alto volume e pontuação": "background-color: #DCFCE7; color: #166534; font-weight: 600;",
    "Alta pontuação": "background-color: #E8EEF8; color: #012869; font-weight: 600;",
    "Alto giro": "background-color: #FFF7ED; color: #9A3412; font-weight: 600;",
    "Em desenvolvimento": "background-color: #F1F5F9; color: #475569; font-weight: 600;",
    "Sem O.S.": "background-color: #F8FAFC; color: #94A3B8;",
    "Sem contratos": "background-color: #F8FAFC; color: #94A3B8;",
    "Média da equipe": "background-color: #E8EEF8; color: #012869; font-weight: 700;",
}


@dataclass(frozen=True)
class ResumoProdutividade:
    """Resultado consolidado da análise de produtividade unitária."""

    mensal: pd.DataFrame
    por_tecnico: pd.DataFrame
    tabela_exibicao: pd.DataFrame
    total_points: float
    total_points_prod: float
    total_os: int
    team_points_per_os: float
    total_contracts: int
    total_points_with_contract: float
    team_points_per_contract: float
    records_without_contract: int
    excluded_incomplete_rows: int


def classificar_quadrantes(
    volumes: pd.Series,
    unitarios: pd.Series,
    *,
    rotulo_inativo: Literal["Sem O.S.", "Sem contratos"],
) -> pd.Series:
    """Classifica cada técnico em 4 quadrantes usando as medianas dos ativos."""
    resultado = pd.Series(rotulo_inativo, index=volumes.index, dtype="object")
    ativos = volumes.gt(0)
    if not ativos.any():
        return resultado

    mediana_vol = float(volumes.loc[ativos].median())
    mediana_unit = float(unitarios.loc[ativos].median())

    for idx in volumes.loc[ativos].index:
        alto_vol = float(volumes.loc[idx]) >= mediana_vol
        alto_unit = float(unitarios.loc[idx]) >= mediana_unit
        if alto_vol and alto_unit:
            resultado.loc[idx] = "Alto volume e pontuação"
        elif alto_unit:
            resultado.loc[idx] = "Alta pontuação"
        elif alto_vol:
            resultado.loc[idx] = "Alto giro"
        else:
            resultado.loc[idx] = "Em desenvolvimento"
    return resultado


def _vazio() -> ResumoProdutividade:
    mensal_vazio = pd.DataFrame(
        columns=[
            "period",
            "points_total",
            "points_prod",
            "os_count",
            "points_per_os",
            "contracts_count",
            "points_with_contract",
            "points_per_contract",
        ]
    )
    tecnico_vazio = pd.DataFrame(
        columns=[
            "technician",
            "points_total",
            "points_prod",
            "os_count",
            "points_per_os",
            "contracts_count",
            "points_with_contract",
            "points_per_contract",
            "profile_os",
            "profile_contract",
        ]
    )
    tabela_vazia = pd.DataFrame(
        columns=[
            "Técnico",
            "Perfil (O.S.)",
            "O.S. (Prod)",
            "Pontos Prod",
            "Pontos / O.S.",
            "Contratos",
            "Pontos em contratos",
            "Pontos / Contrato",
            "Pontos Totais",
        ]
    )
    return ResumoProdutividade(
        mensal=mensal_vazio,
        por_tecnico=tecnico_vazio,
        tabela_exibicao=tabela_vazia,
        total_points=0.0,
        total_points_prod=0.0,
        total_os=0,
        team_points_per_os=0.0,
        total_contracts=0,
        total_points_with_contract=0.0,
        team_points_per_contract=0.0,
        records_without_contract=0,
        excluded_incomplete_rows=0,
    )


def resumir_produtividade_unitaria(frame: pd.DataFrame) -> ResumoProdutividade:
    """Calcula séries mensais, indicadores por técnico, quadrantes e tabela final."""
    if frame.empty:
        return _vazio()

    n = len(frame)
    if "technician" in frame:
        tecnicos = frame["technician"].astype("string").str.strip()
    else:
        tecnicos = pd.Series(pd.NA, index=frame.index, dtype="string")

    datas: pd.Series = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    if "period" in frame:
        datas = pd.Series(
            pd.to_datetime(frame["period"], errors="coerce", format="mixed"),
            index=frame.index,
        )
    if "reference_date" in frame:
        datas = datas.fillna(
            pd.Series(
                pd.to_datetime(
                    frame["reference_date"], errors="coerce", format="mixed"
                ),
                index=frame.index,
            )
        )
    competencias: pd.Series = pd.Series(
        datas.dt.to_period("M").dt.to_timestamp(), index=frame.index
    )

    incompletos = (
        tecnicos.isna()
        | tecnicos.str.casefold().isin(
            ["", "sem técnico", "sem tecnico", "none", "nan", "null"]
        )
        | competencias.isna()
    )
    excluidos_incompletos = int(incompletos.sum())
    if incompletos.all():
        vazio = _vazio()
        return ResumoProdutividade(
            **{
                **vazio.__dict__,
                "excluded_incomplete_rows": excluidos_incompletos,
            }
        )

    mask_ok = ~incompletos
    pontos = (
        pd.to_numeric(frame.loc[mask_ok, "points"], errors="coerce").fillna(0.0)
        if "points" in frame
        else pd.Series(0.0, index=frame.index[mask_ok], dtype="float64")
    )
    origens = (
        frame.loc[mask_ok, "source_sheet"].astype("string").fillna(PROD)
        if "source_sheet" in frame
        else pd.Series(PROD, index=frame.index[mask_ok], dtype="string")
    )
    eh_prod = origens.eq(PROD)
    eh_gpon = origens.eq(GPON)
    # Preserva apenas registros de origens conhecidas (Prod e Gpon).
    pontos_validos = pontos.where(eh_prod | eh_gpon, 0.0)

    if "contract" in frame:
        contratos_raw = frame.loc[mask_ok, "contract"].astype("string")
        unicos = contratos_raw.dropna().unique()
        mapa_limpo = {valor: clean_contract(valor) for valor in unicos}
        contratos_limpos = contratos_raw.map(mapa_limpo)
        unicos_limpos = contratos_limpos.dropna().unique()
        mapa_valido = {valor: is_valid_contract(valor) for valor in unicos_limpos}
        contrato_valido = contratos_limpos.map(mapa_valido).fillna(False).astype(bool)
    else:
        contratos_limpos = pd.Series(None, index=frame.index[mask_ok], dtype="object")
        contrato_valido = pd.Series(False, index=frame.index[mask_ok], dtype="bool")

    sem_contrato = int((~contrato_valido).sum())

    work = pd.DataFrame(
        {
            "technician": tecnicos.loc[mask_ok].astype(str),
            "period": competencias.loc[mask_ok],
            "points": pontos_validos.astype(float),
            "points_prod": pontos_validos.where(eh_prod, 0.0).astype(float),
            "is_os": eh_prod.astype(int),
            "contract": contratos_limpos,
            "valid_contract": contrato_valido,
            "points_with_contract": pontos_validos.where(contrato_valido, 0.0).astype(
                float
            ),
        },
        index=frame.index[mask_ok],
    )

    if work.empty or n == 0:
        return _vazio()

    # Contratos distintos por (técnico, competência), idêntico a components/contratos.py
    contratos_unicos = work.loc[
        work["valid_contract"], ["technician", "period", "contract"]
    ].drop_duplicates(["technician", "period", "contract"])
    contratos_por_mes = (
        contratos_unicos.groupby("period").size().rename("contracts_count")
        if not contratos_unicos.empty
        else pd.Series(dtype="int64", name="contracts_count")
    )
    contratos_por_tecnico = (
        contratos_unicos.groupby("technician").size().rename("contracts_count")
        if not contratos_unicos.empty
        else pd.Series(dtype="int64", name="contracts_count")
    )

    # Agregação mensal
    mensal = (
        work.groupby("period", as_index=False)
        .agg(
            points_total=("points", "sum"),
            points_prod=("points_prod", "sum"),
            os_count=("is_os", "sum"),
            points_with_contract=("points_with_contract", "sum"),
        )
        .sort_values("period", ascending=True)
        .reset_index(drop=True)
    )
    mensal["os_count"] = mensal["os_count"].astype(int)
    mensal["contracts_count"] = (
        mensal["period"].map(contratos_por_mes).fillna(0).astype(int)
    )
    mensal["points_per_os"] = (
        mensal["points_prod"].div(mensal["os_count"].where(mensal["os_count"].gt(0)))
    ).fillna(0.0)
    mensal["points_per_contract"] = (
        mensal["points_with_contract"].div(
            mensal["contracts_count"].where(mensal["contracts_count"].gt(0))
        )
    ).fillna(0.0)
    mensal = mensal[
        [
            "period",
            "points_total",
            "points_prod",
            "os_count",
            "points_per_os",
            "contracts_count",
            "points_with_contract",
            "points_per_contract",
        ]
    ]

    # Agregação por técnico
    por_tecnico = (
        work.groupby("technician", as_index=False)
        .agg(
            points_total=("points", "sum"),
            points_prod=("points_prod", "sum"),
            os_count=("is_os", "sum"),
            points_with_contract=("points_with_contract", "sum"),
        )
        .reset_index(drop=True)
    )
    por_tecnico["os_count"] = por_tecnico["os_count"].astype(int)
    por_tecnico["contracts_count"] = (
        por_tecnico["technician"].map(contratos_por_tecnico).fillna(0).astype(int)
    )
    por_tecnico["points_per_os"] = (
        por_tecnico["points_prod"].div(
            por_tecnico["os_count"].where(por_tecnico["os_count"].gt(0))
        )
    ).fillna(0.0)
    por_tecnico["points_per_contract"] = (
        por_tecnico["points_with_contract"].div(
            por_tecnico["contracts_count"].where(por_tecnico["contracts_count"].gt(0))
        )
    ).fillna(0.0)
    por_tecnico["profile_os"] = classificar_quadrantes(
        por_tecnico["os_count"],
        por_tecnico["points_per_os"],
        rotulo_inativo="Sem O.S.",
    )
    por_tecnico["profile_contract"] = classificar_quadrantes(
        por_tecnico["contracts_count"],
        por_tecnico["points_per_contract"],
        rotulo_inativo="Sem contratos",
    )
    por_tecnico = por_tecnico.sort_values(
        by=["points_per_os", "points_per_contract", "points_total", "technician"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)

    total_points = float(work["points"].sum())
    total_points_prod = float(work["points_prod"].sum())
    total_os = int(work["is_os"].sum())
    team_points_per_os = total_points_prod / total_os if total_os > 0 else 0.0

    total_contracts = int(por_tecnico["contracts_count"].sum())
    total_points_with_contract = float(work["points_with_contract"].sum())
    team_points_per_contract = (
        total_points_with_contract / total_contracts if total_contracts > 0 else 0.0
    )

    tabela = pd.DataFrame(
        {
            "Técnico": por_tecnico["technician"],
            "Perfil (O.S.)": por_tecnico["profile_os"],
            "O.S. (Prod)": por_tecnico["os_count"],
            "Pontos Prod": por_tecnico["points_prod"],
            "Pontos / O.S.": por_tecnico["points_per_os"],
            "Contratos": por_tecnico["contracts_count"],
            "Pontos em contratos": por_tecnico["points_with_contract"],
            "Pontos / Contrato": por_tecnico["points_per_contract"],
            "Pontos Totais": por_tecnico["points_total"],
        }
    )
    linha_total = pd.DataFrame(
        [
            {
                "Técnico": "Total geral",
                "Perfil (O.S.)": "Média da equipe",
                "O.S. (Prod)": total_os,
                "Pontos Prod": total_points_prod,
                "Pontos / O.S.": team_points_per_os,
                "Contratos": total_contracts,
                "Pontos em contratos": total_points_with_contract,
                "Pontos / Contrato": team_points_per_contract,
                "Pontos Totais": total_points,
            }
        ]
    )
    tabela_exibicao = pd.concat([tabela, linha_total], ignore_index=True)

    return ResumoProdutividade(
        mensal=mensal,
        por_tecnico=por_tecnico,
        tabela_exibicao=tabela_exibicao,
        total_points=total_points,
        total_points_prod=total_points_prod,
        total_os=total_os,
        team_points_per_os=team_points_per_os,
        total_contracts=total_contracts,
        total_points_with_contract=total_points_with_contract,
        team_points_per_contract=team_points_per_contract,
        records_without_contract=sem_contrato,
        excluded_incomplete_rows=excluidos_incompletos,
    )


def _render_kpi_card_colorido(
    label: str,
    value: str,
    note: str,
    symbol: str,
    color_class: str,
) -> None:
    label_safe = html.escape(label)
    value_safe = html.escape(value)
    note_safe = html.escape(note)
    symbol_safe = html.escape(symbol)
    st.markdown(
        f"""
        <div class="kpi-card {color_class}">
            <div class="kpi-top"><span class="kpi-label">{label_safe}</span><span class="kpi-dot">{symbol_safe}</span></div>
            <div class="kpi-value">{value_safe}</div>
            <div class="kpi-note">{note_safe}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _grafico_evolucao_unitaria(mensal: pd.DataFrame) -> go.Figure:
    labels = mensal["period"].map(month_label).tolist()
    fig = go.Figure()
    if mensal["os_count"].gt(0).any():
        fig.add_bar(
            x=labels,
            y=mensal["points_per_os"],
            name="Pontos / O.S. (Prod)",
            marker_color=AZUL_TOTALE,
            text=[format_points(v) for v in mensal["points_per_os"]],
            textposition="outside",
            textfont={"size": 10, "color": AZUL_TOTALE},
            cliponaxis=False,
            customdata=mensal["os_count"],
            hovertemplate=(
                "<b>%{x}</b><br>Pontos / O.S.: %{y:,.2f}"
                "<br>O.S. no mês: %{customdata:,.0f}<extra></extra>"
            ),
        )
    if mensal["contracts_count"].gt(0).any():
        fig.add_scatter(
            x=labels,
            y=mensal["points_per_contract"],
            name="Pontos / Contrato",
            mode="lines+markers",
            line={"color": LARANJA_TOTALE, "width": 3},
            marker={"size": 7, "color": LARANJA_TOTALE},
            customdata=mensal["contracts_count"],
            hovertemplate=(
                "<b>%{x}</b><br>Pontos / Contrato: %{y:,.2f}"
                "<br>Contratos no mês: %{customdata:,.0f}<extra></extra>"
            ),
        )
    maximo = float(
        max(
            mensal["points_per_os"].max() if not mensal.empty else 0.0,
            mensal["points_per_contract"].max() if not mensal.empty else 0.0,
        )
    )
    _chart_layout(fig, height=340)
    fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
        margin={"l": 8, "r": 12, "t": 34, "b": 8},
    )
    fig.update_yaxes(
        range=[0, maximo * 1.25 if maximo > 0 else 1],
        title="Pontos médios",
    )
    return fig


def _intervalo_eixo(serie: pd.Series) -> list[float]:
    minimo = float(serie.min())
    maximo = float(serie.max())
    if minimo == maximo:
        base = maximo if maximo > 0 else 1.0
        return [max(0.0, base * 0.7), base * 1.3]
    margem = (maximo - minimo) * 0.15
    return [max(0.0, minimo - margem), maximo + margem]


def _grafico_quadrantes(
    por_tecnico: pd.DataFrame,
    *,
    modo: Literal["os", "contrato"],
) -> go.Figure:
    if modo == "os":
        col_vol = "os_count"
        col_unit = "points_per_os"
        col_pts = "points_prod"
        col_perfil = "profile_os"
        titulo_x = "Quantidade de O.S. (Prod)"
        titulo_y = "Pontos por O.S."
        rotulo_vol = "O.S."
    else:
        col_vol = "contracts_count"
        col_unit = "points_per_contract"
        col_pts = "points_with_contract"
        col_perfil = "profile_contract"
        titulo_x = "Contratos atendidos"
        titulo_y = "Pontos por Contrato"
        rotulo_vol = "Contratos"

    ativos = por_tecnico[por_tecnico[col_vol].gt(0)].copy()
    fig = go.Figure()
    if ativos.empty:
        _chart_layout(fig, height=340)
        return fig

    max_pts = float(ativos[col_pts].max())
    tamanhos = (
        ativos[col_pts]
        .div(max_pts if max_pts > 0 else 1.0)
        .mul(22.0)
        .add(11.0)
        .clip(11.0, 33.0)
    )
    ativos = ativos.assign(_bubble_size=tamanhos)

    mediana_vol = float(ativos[col_vol].median())
    mediana_unit = float(ativos[col_unit].median())

    for perfil, cor in _CORES_PERFIL.items():
        grupo = ativos[ativos[col_perfil].eq(perfil)]
        if grupo.empty:
            continue
        fig.add_scatter(
            x=grupo[col_vol],
            y=grupo[col_unit],
            mode="markers",
            name=perfil,
            marker={
                "size": grupo["_bubble_size"],
                "color": cor,
                "opacity": 0.85,
                "line": {"width": 1.5, "color": "#FFFFFF"},
            },
            customdata=grupo[["technician", col_pts, col_perfil]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Perfil: %{customdata[2]}<br>"
                f"{rotulo_vol}: %{{x:,.0f}}<br>"
                f"{titulo_y}: %{{y:,.2f}}<br>"
                "Pontos acumulados: %{customdata[1]:,.2f}<extra></extra>"
            ),
        )

    fig.add_vline(
        x=mediana_vol,
        line_dash="dash",
        line_color=Cores.BORDA,
        annotation_text=f"Mediana {formatar_numero_br(mediana_vol, 1)}",
        annotation_position="top right",
        annotation_font={"size": 10, "color": Cores.TEXTO_3},
    )
    fig.add_hline(
        y=mediana_unit,
        line_dash="dash",
        line_color=Cores.BORDA,
        annotation_text=f"Mediana {format_points(mediana_unit)}",
        annotation_position="bottom right",
        annotation_font={"size": 10, "color": Cores.TEXTO_3},
    )

    _chart_layout(fig, height=340)
    fig.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 10},
        },
        margin={"l": 8, "r": 16, "t": 34, "b": 8},
    )
    fig.update_xaxes(
        title=titulo_x,
        range=_intervalo_eixo(ativos[col_vol]),
        showgrid=True,
        gridcolor="#eef2f7",
        fixedrange=False,
    )
    fig.update_yaxes(
        title=titulo_y,
        range=_intervalo_eixo(ativos[col_unit]),
        fixedrange=False,
    )
    return fig


def _grafico_ranking_unitario(
    por_tecnico: pd.DataFrame,
    *,
    col_valor: str,
    col_volume: str,
    media_equipe: float,
    cor_barra: str,
    cor_linha: str,
    rotulo_unidade: str,
) -> go.Figure:
    ativos = (
        por_tecnico[por_tecnico[col_volume].gt(0)]
        .sort_values(by=[col_valor, "technician"], ascending=[False, True])
        .head(15)
        .iloc[::-1]
    )
    fig = go.Figure()
    if ativos.empty:
        _chart_layout(fig, height=320)
        return fig

    fig.add_bar(
        x=ativos[col_valor],
        y=ativos["technician"],
        orientation="h",
        marker_color=cor_barra,
        text=[format_points(v) for v in ativos[col_valor]],
        textposition="outside",
        cliponaxis=False,
        customdata=ativos[col_volume],
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Média: %{x:,.2f} pontos<br>"
            f"Volume: %{{customdata:,.0f}} {rotulo_unidade}<extra></extra>"
        ),
    )
    if media_equipe > 0:
        fig.add_vline(
            x=media_equipe,
            line_dash="dash",
            line_color=cor_linha,
            line_width=2,
            annotation_text=f"Equipe: {format_points(media_equipe)}",
            annotation_position="bottom right",
            annotation_font={"size": 10, "color": cor_linha},
        )
    maximo = max(float(ativos[col_valor].max()), media_equipe)
    _chart_layout(fig, height=max(320, len(ativos) * 28 + 70))
    fig.update_layout(margin={"l": 8, "r": 58, "t": 15, "b": 18})
    fig.update_xaxes(
        range=[0, maximo * 1.24 if maximo > 0 else 1],
        showgrid=False,
        showticklabels=False,
    )
    return fig


def _estilo_linha_tabela(linha: pd.Series) -> pd.Series:
    estilos = pd.Series("", index=linha.index, dtype="object")
    if linha.get("Técnico") == "Total geral":
        estilos.loc[:] = "background-color: #E8EEF8; color: #012869; font-weight: 700;"
        return estilos

    perfil = str(linha.get("Perfil (O.S.)", ""))
    estilos.loc["Perfil (O.S.)"] = _ESTILOS_PERFIL.get(perfil, "")
    estilos.loc["Pontos / O.S."] = (
        "background-color: #F4F7FC; color: #012869; font-weight: 600;"
    )
    estilos.loc["Pontos / Contrato"] = (
        "background-color: #FFF7ED; color: #9A3412; font-weight: 600;"
    )
    return estilos


def _estilizar_tabela(tabela: pd.DataFrame) -> pd.DataFrame | Styler:
    limite = int(pd.get_option("styler.render.max_elements"))
    if tabela.size > min(10_000, limite):
        return tabela
    return tabela.style.apply(_estilo_linha_tabela, axis=1)


def render_produtividade_unitaria(filtered: pd.DataFrame) -> None:
    """Renderiza a aba dedicada de Produtividade Unitária (O.S. e Contratos)."""
    resumo = resumir_produtividade_unitaria(filtered)
    if resumo.mensal.empty or (resumo.total_os == 0 and resumo.total_contracts == 0):
        render_ticker(
            [("Produtividade unitária", "Sem O.S. ou contratos válidos no recorte")],
            label="Indicadores de produtividade unitária",
        )
        st.info(
            "Não há ordens de serviço da aba Prod nem contratos válidos para "
            "calcular a produtividade unitária nos filtros selecionados."
        )
        if resumo.records_without_contract or resumo.excluded_incomplete_rows:
            st.caption(
                f"Registros desconsiderados: {formatar_numero_br(resumo.records_without_contract)} "
                f"sem contrato válido e {formatar_numero_br(resumo.excluded_incomplete_rows)} "
                "sem técnico ou data válida."
            )
        return

    ativos_os = resumo.por_tecnico[resumo.por_tecnico["os_count"].gt(0)].sort_values(
        by=["points_per_os", "os_count", "technician"], ascending=[False, False, True]
    )
    ativos_ct = resumo.por_tecnico[
        resumo.por_tecnico["contracts_count"].gt(0)
    ].sort_values(
        by=["points_per_contract", "contracts_count", "technician"],
        ascending=[False, False, True],
    )

    ultimo_mes = resumo.mensal.iloc[-1]
    ticker_items: list[tuple[str, str]] = [
        (
            "Pontos / O.S. (Prod)",
            format_points(resumo.team_points_per_os)
            if resumo.total_os > 0
            else "Sem O.S.",
        ),
        (
            "Pontos / Contrato",
            format_points(resumo.team_points_per_contract)
            if resumo.total_contracts > 0
            else "Sem contratos",
        ),
        (
            "Competência mais recente",
            f"{month_label(ultimo_mes['period'])} · "
            f"{format_points(ultimo_mes['points_per_os'])} pts/O.S. · "
            f"{format_points(ultimo_mes['points_per_contract'])} pts/contrato",
        ),
    ]
    if not ativos_os.empty:
        lider_os = ativos_os.iloc[0]
        ticker_items.append(
            (
                "Destaque Pontos / O.S.",
                f"{lider_os['technician']} · {format_points(lider_os['points_per_os'])} pts",
            )
        )
    if not ativos_ct.empty:
        lider_ct = ativos_ct.iloc[0]
        ticker_items.append(
            (
                "Destaque Pontos / Contrato",
                f"{lider_ct['technician']} · {format_points(lider_ct['points_per_contract'])} pts",
            )
        )
    render_ticker(ticker_items, label="Indicadores de produtividade unitária")

    cards = st.columns(4)
    with cards[0]:
        _render_kpi_card_colorido(
            "PONTOS POR O.S. (PROD)",
            format_points(resumo.team_points_per_os) if resumo.total_os > 0 else "—",
            (
                f"{format_points(resumo.total_points_prod)} pts em "
                f"{formatar_numero_br(resumo.total_os)} O.S."
                if resumo.total_os > 0
                else "Nenhuma O.S. da aba Prod no recorte"
            ),
            "O.S.",
            "kpi-card--azul",
        )
    with cards[1]:
        _render_kpi_card_colorido(
            "PONTOS POR CONTRATO",
            (
                format_points(resumo.team_points_per_contract)
                if resumo.total_contracts > 0
                else "—"
            ),
            (
                f"{format_points(resumo.total_points_with_contract)} pts em "
                f"{formatar_numero_br(resumo.total_contracts)} contratos"
                if resumo.total_contracts > 0
                else "Nenhum contrato válido no recorte"
            ),
            "CT",
            "kpi-card--laranja",
        )
    with cards[2]:
        if not ativos_os.empty:
            top_os = ativos_os.iloc[0]
            _render_kpi_card_colorido(
                "DESTAQUE · PONTOS / O.S.",
                format_points(top_os["points_per_os"]),
                f"{top_os['technician']} · {formatar_numero_br(top_os['os_count'])} O.S.",
                "↑",
                "kpi-card--verde",
            )
        else:
            _render_kpi_card_colorido(
                "DESTAQUE · PONTOS / O.S.",
                "—",
                "Sem registros da aba Prod",
                "↑",
                "kpi-card--verde",
            )
    with cards[3]:
        if not ativos_ct.empty:
            top_ct = ativos_ct.iloc[0]
            _render_kpi_card_colorido(
                "DESTAQUE · PONTOS / CONTRATO",
                format_points(top_ct["points_per_contract"]),
                (
                    f"{top_ct['technician']} · "
                    f"{formatar_numero_br(top_ct['contracts_count'])} contratos"
                ),
                "★",
                "kpi-card--roxo",
            )
        else:
            _render_kpi_card_colorido(
                "DESTAQUE · PONTOS / CONTRATO",
                "—",
                "Sem contratos válidos",
                "★",
                "kpi-card--roxo",
            )

    _section_heading(
        "Volume × complexidade dos atendimentos",
        REGRA_PRODUTIVIDADE,
    )
    if resumo.records_without_contract or resumo.excluded_incomplete_rows:
        partes: list[str] = []
        if resumo.records_without_contract:
            partes.append(
                f"{formatar_numero_br(resumo.records_without_contract)} sem contrato válido "
                "(fora da média por contrato)"
            )
        if resumo.excluded_incomplete_rows:
            partes.append(
                f"{formatar_numero_br(resumo.excluded_incomplete_rows)} sem técnico ou data válida"
            )
        st.caption(f"Observação sobre os registros: {' e '.join(partes)}.")

    opcoes_quadrante: list[str] = []
    if resumo.total_os > 0:
        opcoes_quadrante.append("Por O.S. (Prod)")
    if resumo.total_contracts > 0:
        opcoes_quadrante.append("Por Contrato")

    escolha = opcoes_quadrante[0]
    if len(opcoes_quadrante) > 1:
        selecionado = st.radio(
            "Dimensão dos quadrantes",
            opcoes_quadrante,
            horizontal=True,
            key="unit_productivity_quadrant_mode",
        )
        escolha = str(selecionado or opcoes_quadrante[0])
    modo_quadrante: Literal["os", "contrato"] = (
        "contrato" if escolha == "Por Contrato" else "os"
    )

    col_evolucao, col_quadrantes = st.columns([1.05, 1.15])
    with col_evolucao, st.container(border=True):
        st.markdown("**Evolução mensal do ticket médio de pontos**")
        st.plotly_chart(
            _grafico_evolucao_unitaria(resumo.mensal),
            width="stretch",
            config=CHART_CONFIG,
        )
    with col_quadrantes, st.container(border=True):
        subtitulo_quad = (
            "Quadrantes por O.S. (Prod)"
            if modo_quadrante == "os"
            else "Quadrantes por Contrato"
        )
        st.markdown(f"**{subtitulo_quad} · Volume × Pontos unitários**")
        st.plotly_chart(
            _grafico_quadrantes(resumo.por_tecnico, modo=modo_quadrante),
            width="stretch",
            config=CHART_CONFIG,
        )

    _section_heading(
        "Ranking de produtividade unitária · Top 15",
        "Pontuação média por atendimento comparada com a média ponderada da equipe.",
    )
    col_rank_os, col_rank_ct = st.columns(2)
    with col_rank_os, st.container(border=True):
        st.markdown("**Pontos por O.S. (Prod) · Top 15**")
        if resumo.total_os > 0:
            st.plotly_chart(
                _grafico_ranking_unitario(
                    resumo.por_tecnico,
                    col_valor="points_per_os",
                    col_volume="os_count",
                    media_equipe=resumo.team_points_per_os,
                    cor_barra=AZUL_TOTALE,
                    cor_linha=LARANJA_TOTALE,
                    rotulo_unidade="O.S.",
                ),
                width="stretch",
                config=CHART_CONFIG,
            )
        else:
            st.info("Não há O.S. da aba Prod no recorte selecionado.")
    with col_rank_ct, st.container(border=True):
        st.markdown("**Pontos por Contrato · Top 15**")
        if resumo.total_contracts > 0:
            st.plotly_chart(
                _grafico_ranking_unitario(
                    resumo.por_tecnico,
                    col_valor="points_per_contract",
                    col_volume="contracts_count",
                    media_equipe=resumo.team_points_per_contract,
                    cor_barra=LARANJA_TOTALE,
                    cor_linha=AZUL_TOTALE,
                    rotulo_unidade="contratos",
                ),
                width="stretch",
                config=CHART_CONFIG,
            )
        else:
            st.info("Não há contratos válidos no recorte selecionado.")

    _section_heading(
        "Produtividade unitária por técnico",
        "A linha Total geral apresenta a média ponderada da equipe (total de pontos ÷ total de atendimentos).",
    )
    st.caption(
        "Perfis nos quadrantes (em relação às medianas da equipe ativa): "
        "Alto volume e pontuação · Alta pontuação · Alto giro · Em desenvolvimento."
    )
    st.dataframe(
        _estilizar_tabela(resumo.tabela_exibicao),
        width="stretch",
        hide_index=True,
        alt="Produtividade unitária em pontos por O.S. e pontos por contrato por técnico",
        column_config={
            "Técnico": st.column_config.TextColumn(width="medium"),
            "Perfil (O.S.)": st.column_config.TextColumn(width="medium"),
            "O.S. (Prod)": st.column_config.NumberColumn(format="%d"),
            "Pontos Prod": st.column_config.NumberColumn(format="%.2f"),
            "Pontos / O.S.": st.column_config.NumberColumn(format="%.2f"),
            "Contratos": st.column_config.NumberColumn(format="%d"),
            "Pontos em contratos": st.column_config.NumberColumn(format="%.2f"),
            "Pontos / Contrato": st.column_config.NumberColumn(format="%.2f"),
            "Pontos Totais": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    st.download_button(
        "Baixar produtividade unitária em CSV",
        data=_csv_download(resumo.tabela_exibicao),
        file_name="produtividade_unitaria.csv",
        mime="text/csv",
        key="download_produtividade_unitaria",
    )


__all__ = [
    "PerfilQuadrante",
    "REGRA_PRODUTIVIDADE",
    "ResumoProdutividade",
    "classificar_quadrantes",
    "render_produtividade_unitaria",
    "resumir_produtividade_unitaria",
]
