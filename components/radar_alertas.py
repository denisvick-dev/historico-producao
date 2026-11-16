"""Radar de Alertas & Gestão à Vista — sinalizações acionáveis para supervisão."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components.componentes import (
    Cores,
    Fontes,
    formatar_numero_br,
    render_drilldown_tecnico,
    render_insight,
    render_kpi_card,
    render_section_header,
    render_ticker,
)
from components.consultivo import (
    normalizar_coluna_data_consultivo,
    sanitizar_csv_exportacao,
)
from components.visoes_dashboards import resumir_regularidade
from production import (
    clean_code,
    format_points,
    month_label,
    normalize_text,
    summarize,
)

CHART_CONFIG = {"displayModeBar": False, "responsive": True}

SEVERIDADE_ORDEM = ("Crítico", "Atenção", "Oportunidade")
SEVERIDADE_PESO = {"Crítico": 1, "Atenção": 2, "Oportunidade": 3}
CORES_SEVERIDADE: dict[str, tuple[str, str, str]] = {
    "Crítico": ("#DC2626", "#FEF2F2", "#B91C1C"),
    "Atenção": ("#D97706", "#FFFBEB", "#B45309"),
    "Oportunidade": ("#059669", "#ECFDF5", "#047857"),
}

LIMIARES_FAIXA: tuple[tuple[float, float, str], ...] = (
    (275.0, 300.0, "Faixa 2 (300 pts)"),
    (335.0, 350.0, "Faixa 3 (350 pts)"),
    (360.0, 375.0, "Faixa 4 (375 pts)"),
    (385.0, 400.0, "Faixa 5 (400 pts)"),
)


@dataclass(frozen=True)
class ResumoAlertas:
    """Resultado consolidado do Radar de Alertas Operacionais."""

    alertas: pd.DataFrame
    por_monitor: pd.DataFrame
    por_categoria: pd.DataFrame
    total_alertas: int
    criticos: int
    atencao: int
    oportunidades: int
    competencia_referencia: str


def _garantir_periodo(frame: pd.DataFrame) -> pd.Series:
    col = "period" if "period" in frame.columns else "reference_date"
    if pd.api.types.is_datetime64_any_dtype(frame[col]):
        dt = frame[col]
    else:
        dt = pd.to_datetime(frame[col], errors="coerce")
    return pd.Series(dt.dt.to_period("M").dt.to_timestamp(), index=frame.index)


def _mapa_meta_tecnico(
    production_frame: pd.DataFrame,
    roster_frame: pd.DataFrame | None,
) -> dict[str, dict[str, str]]:
    meta: dict[str, dict[str, str]] = {}
    if not production_frame.empty and "technician" in production_frame.columns:
        for row in production_frame.drop_duplicates("technician").itertuples(
            index=False
        ):
            nome = str(getattr(row, "technician", "") or "").strip()
            key = normalize_text(nome)
            if not key:
                continue
            meta[key] = {
                "technician": nome,
                "monitor": str(getattr(row, "monitor", "Sem monitor") or "Sem monitor"),
                "base": str(getattr(row, "base", "Sem base") or "Sem base"),
                "un": str(getattr(row, "un", "Sem U.N.") or "Sem U.N."),
                "login": clean_code(getattr(row, "login", "")).upper(),
                "status": str(
                    getattr(row, "roster_status", "Sem cadastro") or "Sem cadastro"
                ),
            }
    if roster_frame is not None and not roster_frame.empty:
        for row in roster_frame.itertuples(index=False):
            nome = str(getattr(row, "technician", "") or "").strip()
            key = str(
                getattr(row, "technician_key", "") or ""
            ).strip() or normalize_text(nome)
            if not key:
                continue
            meta[key] = {
                "technician": nome or meta.get(key, {}).get("technician", key),
                "monitor": str(getattr(row, "monitor", "Sem monitor") or "Sem monitor"),
                "base": str(getattr(row, "base", "Sem base") or "Sem base"),
                "un": str(getattr(row, "un", "Sem U.N.") or "Sem U.N."),
                "login": clean_code(getattr(row, "login", "")).upper(),
                "status": str(getattr(row, "status", "ATIVO") or "ATIVO"),
            }
    return meta


def calcular_radar_alertas(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    *,
    limite_queda_pct: float = -20.0,
) -> ResumoAlertas:
    """Identifica alertas priorizados de produção, faixas, consultivo e governança."""
    colunas = [
        "Severidade",
        "Categoria",
        "Técnico",
        "Monitor",
        "Base",
        "U.N.",
        "Indicador",
        "Detalhe",
        "Ação Recomendada",
    ]
    if production_frame.empty and (roster_frame is None or roster_frame.empty):
        vazio = pd.DataFrame(columns=colunas)
        return ResumoAlertas(
            alertas=vazio,
            por_monitor=pd.DataFrame(columns=["Monitor", *SEVERIDADE_ORDEM, "Total"]),
            por_categoria=pd.DataFrame(
                columns=["Categoria", "Severidade", "Quantidade"]
            ),
            total_alertas=0,
            criticos=0,
            atencao=0,
            oportunidades=0,
            competencia_referencia="Sem dados",
        )

    meta = _mapa_meta_tecnico(production_frame, roster_frame)
    registros_alerta: list[dict[str, Any]] = []
    competencia_ref_label = "Sem competência"

    if not production_frame.empty and "technician" in production_frame.columns:
        work = production_frame.copy()
        work["period"] = _garantir_periodo(work)
        work = work.dropna(subset=["period"])

        if not work.empty:
            ultima_comp = work["period"].max()
            competencia_ref_label = month_label(ultima_comp)
            anterior_comp = ultima_comp - pd.DateOffset(months=1)

            atual_df = summarize(work[work["period"].eq(ultima_comp)], "technician")
            anterior_df = summarize(
                work[work["period"].eq(anterior_comp)], "technician"
            )
            anterior_map = (
                dict(
                    zip(
                        anterior_df["technician"],
                        anterior_df["points_total"],
                        strict=False,
                    )
                )
                if not anterior_df.empty
                else {}
            )

            ativos_ultima_keys: set[str] = set()
            for row in atual_df.itertuples(index=False):
                nome = str(row.technician)
                pts = float(cast(Any, row.points_total))
                key = normalize_text(nome)
                ativos_ultima_keys.add(key)
                info = meta.get(
                    key,
                    {
                        "monitor": "Sem monitor",
                        "base": "Sem base",
                        "un": "Sem U.N.",
                    },
                )

                # 1) Oportunidade: zona limiar de virada de faixa
                for piso, teto, nome_faixa in LIMIARES_FAIXA:
                    if piso <= pts < teto:
                        faltam = round(teto - pts, 2)
                        registros_alerta.append(
                            {
                                "Severidade": "Oportunidade",
                                "Categoria": "Zona Limiar de Faixa",
                                "Técnico": nome,
                                "Monitor": info["monitor"],
                                "Base": info["base"],
                                "U.N.": info["un"],
                                "Indicador": f"{format_points(pts)} pts ({competencia_ref_label})",
                                "Detalhe": (
                                    f"Faltam apenas {format_points(faltam)} pts para atingir {nome_faixa}."
                                ),
                                "Ação Recomendada": (
                                    f"Priorizar fechamento de O.S./Gpon para garantir {nome_faixa}."
                                ),
                            }
                        )
                        break

                # 2) Crítico: queda brusca MoM
                pts_ant = float(anterior_map.get(nome, 0.0))
                if pts_ant >= 100.0:
                    var_pct = (pts / pts_ant - 1.0) * 100.0
                    if var_pct <= limite_queda_pct:
                        diff_pts = pts - pts_ant
                        registros_alerta.append(
                            {
                                "Severidade": "Crítico",
                                "Categoria": "Queda Brusca MoM",
                                "Técnico": nome,
                                "Monitor": info["monitor"],
                                "Base": info["base"],
                                "U.N.": info["un"],
                                "Indicador": f"{var_pct:+.1f}%".replace(".", ","),
                                "Detalhe": (
                                    f"Caiu de {format_points(pts_ant)} pts ({month_label(anterior_comp)}) "
                                    f"para {format_points(pts)} pts ({competencia_ref_label}) "
                                    f"[{format_points(diff_pts)} pts]."
                                ),
                                "Ação Recomendada": (
                                    "Alinhar causa com o Monitor (escala, rota, ausência ou bloqueio de O.S.)."
                                ),
                            }
                        )

            # 3) Crítico: técnico ATIVO no cadastro sem produção na última competência
            if roster_frame is not None and not roster_frame.empty:
                ativos_roster = roster_frame[roster_frame["status"].eq("ATIVO")]
                for row in ativos_roster.itertuples(index=False):
                    nome = str(getattr(row, "technician", "") or "").strip()
                    key = str(
                        getattr(row, "technician_key", "") or ""
                    ).strip() or normalize_text(nome)
                    if key and key not in ativos_ultima_keys:
                        registros_alerta.append(
                            {
                                "Severidade": "Crítico",
                                "Categoria": "Ativo Sem Produção",
                                "Técnico": nome,
                                "Monitor": str(
                                    getattr(row, "monitor", "Sem monitor")
                                    or "Sem monitor"
                                ),
                                "Base": str(
                                    getattr(row, "base", "Sem base") or "Sem base"
                                ),
                                "U.N.": str(
                                    getattr(row, "un", "Sem U.N.") or "Sem U.N."
                                ),
                                "Indicador": f"0,00 pts ({competencia_ref_label})",
                                "Detalhe": (
                                    f"Consta como ATIVO em lista_ativos, mas não possui apontamentos em {competencia_ref_label}."
                                ),
                                "Ação Recomendada": (
                                    "Validar status cadastral (férias/afastamento) ou ausência de apontamento."
                                ),
                            }
                        )

            # 4) Atenção: técnico em campo sem consultivos na competência mais recente
            if consultivo_frame is not None and not consultivo_frame.empty:
                cons = normalizar_coluna_data_consultivo(consultivo_frame)
                if "DATA" in cons.columns and cons["DATA"].notna().any():
                    cons_periods = cons["DATA"].dt.to_period("M").dt.to_timestamp()
                    cons_mes = cons[cons_periods.eq(ultima_comp)]
                    if not cons_mes.empty:
                        q_col = (
                            "Qtde. Cons."
                            if "Qtde. Cons." in cons_mes.columns
                            else "QTDE_CONSULTIVO"
                        )
                        cons_pos = cons_mes[
                            pd.to_numeric(cons_mes[q_col], errors="coerce").fillna(0)
                            > 0
                        ]
                        com_cons_keys: set[str] = set()
                        com_cons_logins: set[str] = set()
                        for col_n in ("Técnico", "VENDEDOR"):
                            if col_n in cons_pos.columns:
                                com_cons_keys.update(
                                    cons_pos[col_n]
                                    .astype(str)
                                    .map(normalize_text)
                                    .tolist()
                                )
                        if "LOGIN NETSALES" in cons_pos.columns:
                            com_cons_logins.update(
                                cons_pos["LOGIN NETSALES"]
                                .astype(str)
                                .map(clean_code)
                                .str.upper()
                                .tolist()
                            )

                        for row in atual_df.itertuples(index=False):
                            nome = str(row.technician)
                            key = normalize_text(nome)
                            info = meta.get(key, {})
                            login_tec = info.get("login", "")
                            if key not in com_cons_keys and (
                                not login_tec or login_tec not in com_cons_logins
                            ):
                                registros_alerta.append(
                                    {
                                        "Severidade": "Atenção",
                                        "Categoria": "Em Campo Sem Consultivo",
                                        "Técnico": nome,
                                        "Monitor": info.get("monitor", "Sem monitor"),
                                        "Base": info.get("base", "Sem base"),
                                        "U.N.": info.get("un", "Sem U.N."),
                                        "Indicador": f"{format_points(float(cast(Any, row.points_total)))} pts · 0 cons.",
                                        "Detalhe": (
                                            f"Produziu em campo em {competencia_ref_label}, mas sem registros consultivos no NetSales."
                                        ),
                                        "Ação Recomendada": (
                                            "Reforçar abordagem consultiva em campo e validar login NetSales."
                                        ),
                                    }
                                )

            # 5) Atenção: alta oscilação histórica (CV >= 30%)
            reg = resumir_regularidade(work)
            if not reg.empty:
                alta_osc = reg[reg["regularity"].eq("Alta oscilação")]
                for row in alta_osc.itertuples(index=False):
                    nome = str(row.technician)
                    key = normalize_text(nome)
                    info = meta.get(key, {})
                    cv = float(getattr(row, "coefficient_variation_pct", 0.0) or 0.0)
                    meses_ativos_cv = int(cast(Any, row.active_months))
                    registros_alerta.append(
                        {
                            "Severidade": "Atenção",
                            "Categoria": "Alta Oscilação (CV)",
                            "Técnico": nome,
                            "Monitor": info.get("monitor", "Sem monitor"),
                            "Base": info.get("base", "Sem base"),
                            "U.N.": info.get("un", "Sem U.N."),
                            "Indicador": f"CV {cv:.1f}%".replace(".", ","),
                            "Detalhe": (
                                f"Coeficiente de variação elevado em {meses_ativos_cv} meses ativos."
                            ),
                            "Ação Recomendada": (
                                "Acompanhar constância semanal para estabilizar entregas mensais."
                            ),
                        }
                    )

            # 6) Atenção: produção de técnico não cadastrado em lista_ativos
            if (
                "roster_status" in work.columns
                and work["roster_status"].ne("Sem cadastro").any()
            ):
                nao_cad = work[work["roster_status"].eq("Não cadastrado")]
                if not nao_cad.empty:
                    por_nc = summarize(nao_cad, "technician")
                    for row in por_nc.itertuples(index=False):
                        nome = str(row.technician)
                        pts_nc = float(cast(Any, row.points_total))
                        registros_alerta.append(
                            {
                                "Severidade": "Atenção",
                                "Categoria": "Produção Sem Cadastro",
                                "Técnico": nome,
                                "Monitor": "Sem monitor",
                                "Base": "Sem base",
                                "U.N.": "Sem U.N.",
                                "Indicador": f"{format_points(pts_nc)} pts",
                                "Detalhe": (
                                    "Técnico com apontamento de produção sem correspondência em lista_ativos."
                                ),
                                "Ação Recomendada": (
                                    "Revisar grafia do nome ou incluir colaborador na planilha lista_ativos."
                                ),
                            }
                        )

    if not registros_alerta:
        vazio = pd.DataFrame(columns=colunas)
        return ResumoAlertas(
            alertas=vazio,
            por_monitor=pd.DataFrame(columns=["Monitor", *SEVERIDADE_ORDEM, "Total"]),
            por_categoria=pd.DataFrame(
                columns=["Categoria", "Severidade", "Quantidade"]
            ),
            total_alertas=0,
            criticos=0,
            atencao=0,
            oportunidades=0,
            competencia_referencia=competencia_ref_label,
        )

    df_alertas = pd.DataFrame(registros_alerta)
    df_alertas["_peso"] = df_alertas["Severidade"].map(SEVERIDADE_PESO).fillna(9)
    df_alertas = (
        df_alertas.sort_values(["_peso", "Categoria", "Técnico"])
        .drop(columns=["_peso"])
        .reset_index(drop=True)[colunas]
    )

    por_monitor = pd.crosstab(df_alertas["Monitor"], df_alertas["Severidade"]).reindex(
        columns=list(SEVERIDADE_ORDEM), fill_value=0
    )
    por_monitor["Total"] = por_monitor.sum(axis=1)
    por_monitor = por_monitor.sort_values(
        ["Crítico", "Total"], ascending=[False, False]
    ).reset_index()

    por_categoria = cast(
        pd.DataFrame,
        df_alertas.groupby(["Categoria", "Severidade"], as_index=False)
        .size()
        .rename(columns={"size": "Quantidade"})
        .sort_values("Quantidade", ascending=False)
        .reset_index(drop=True),
    )

    return ResumoAlertas(
        alertas=df_alertas,
        por_monitor=por_monitor,
        por_categoria=por_categoria,
        total_alertas=len(df_alertas),
        criticos=int(df_alertas["Severidade"].eq("Crítico").sum()),
        atencao=int(df_alertas["Severidade"].eq("Atenção").sum()),
        oportunidades=int(df_alertas["Severidade"].eq("Oportunidade").sum()),
        competencia_referencia=competencia_ref_label,
    )


def _estilo_severidade(valor: object) -> str:
    cores = CORES_SEVERIDADE.get(str(valor))
    if cores is None:
        return ""
    _, bg, fg = cores
    return f"background-color: {bg}; color: {fg}; font-weight: 700;"


def _layout_radar(fig: go.Figure, altura: int = 360) -> go.Figure:
    fig.update_layout(
        height=altura,
        margin=dict(l=10, r=16, t=24, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=Fontes.TEXTO, color=Cores.TEXTO_3, size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hoverlabel=dict(bgcolor="white", font_color=Cores.TEXTO),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor=Cores.BORDA, zeroline=False)
    return fig


@st.cache_data(ttl=1800, max_entries=16, show_spinner=False)
def _calcular_radar_alertas_cached(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
    *,
    limite_queda_pct: float = -20.0,
) -> ResumoAlertas:
    return calcular_radar_alertas(
        production_frame,
        consultivo_frame,
        roster_frame,
        limite_queda_pct=limite_queda_pct,
    )


def render_radar_alertas(
    production_frame: pd.DataFrame,
    consultivo_frame: pd.DataFrame | None = None,
    roster_frame: pd.DataFrame | None = None,
) -> None:
    """Renderiza o painel acionável de Radar de Alertas & Gestão à Vista."""

    @st.fragment
    def _render_radar_body() -> None:
        with st.container(border=True):
            c_cfg = st.columns([1.5, 2.5])
            with c_cfg[0]:
                limite_queda = float(
                    st.slider(
                        "Sensibilidade de Queda MoM (%)",
                        min_value=-50,
                        max_value=-5,
                        value=-20,
                        step=5,
                        key="radar_limite_queda",
                    )
                )
            with c_cfg[1]:
                st.caption(
                    "O Radar analisa automaticamente a competência mais recente do recorte para detectar "
                    "oportunidades de virada de faixa, quedas MoM, ativos sem apontamento, lacunas no "
                    "Consultivo, alta oscilação histórica e inconsistências cadastrais."
                )

        resumo = _calcular_radar_alertas_cached(
            production_frame,
            consultivo_frame,
            roster_frame,
            limite_queda_pct=limite_queda,
        )

        render_ticker(
            [
                ("Competência de referência", resumo.competencia_referencia),
                ("Total de alertas", formatar_numero_br(resumo.total_alertas)),
                ("Críticos", formatar_numero_br(resumo.criticos)),
                ("Atenção", formatar_numero_br(resumo.atencao)),
                ("Oportunidades de Faixa", formatar_numero_br(resumo.oportunidades)),
            ],
            label="Radar de Alertas & Gestão à Vista",
        )

        k = st.columns(4)
        with k[0]:
            render_kpi_card(
                "TOTAL DE SINALIZAÇÕES",
                formatar_numero_br(resumo.total_alertas),
                f"Referência: {resumo.competencia_referencia}",
                "🚨",
                "kpi-card--azul",
            )
        with k[1]:
            render_kpi_card(
                "ALERTAS CRÍTICOS",
                formatar_numero_br(resumo.criticos),
                "Queda brusca MoM ou ativo sem produção",
                "🔴",
                "kpi-card--vermelho",
            )
        with k[2]:
            render_kpi_card(
                "PONTOS DE ATENÇÃO",
                formatar_numero_br(resumo.atencao),
                "Sem consultivo, alta oscilação ou sem cadastro",
                "🟠",
                "kpi-card--laranja",
            )
        with k[3]:
            render_kpi_card(
                "OPORTUNIDADES DE FAIXA",
                formatar_numero_br(resumo.oportunidades),
                "Técnicos próximos de virar de faixa no mês",
                "🟢",
                "kpi-card--verde",
            )

        if resumo.alertas.empty:
            render_insight(
                "Nenhum alerta operacional disparado para os critérios e filtros atuais.",
                tipo="ok",
            )
            return

        with st.container(border=True):
            f = st.columns([1.2, 1.4, 1.3, 1.1])
            with f[0]:
                sel_sev = st.multiselect(
                    "Severidade",
                    options=list(SEVERIDADE_ORDEM),
                    default=[],
                    placeholder="Todas",
                    key="radar_filtro_sev",
                )
            with f[1]:
                sel_cat = st.multiselect(
                    "Categoria",
                    options=sorted(resumo.alertas["Categoria"].unique().tolist()),
                    default=[],
                    placeholder="Todas",
                    key="radar_filtro_cat",
                )
            with f[2]:
                sel_mon = st.multiselect(
                    "Monitor",
                    options=sorted(resumo.alertas["Monitor"].unique().tolist()),
                    default=[],
                    placeholder="Todos",
                    key="radar_filtro_mon",
                )
            with f[3]:
                sel_base = st.multiselect(
                    "Base",
                    options=sorted(resumo.alertas["Base"].unique().tolist()),
                    default=[],
                    placeholder="Todas",
                    key="radar_filtro_base",
                )

        df_view = resumo.alertas
        if sel_sev:
            df_view = df_view[df_view["Severidade"].isin(sel_sev)]
        if sel_cat:
            df_view = df_view[df_view["Categoria"].isin(sel_cat)]
        if sel_mon:
            df_view = df_view[df_view["Monitor"].isin(sel_mon)]
        if sel_base:
            df_view = df_view[df_view["Base"].isin(sel_base)]

        g1, g2 = st.columns([1.2, 1.0])
        with g1, st.container(border=True):
            render_section_header(
                "Concentração de Alertas por Monitor",
                subtitulo="Empilhamento por severidade para priorização da supervisão",
                icone="👥",
            )
            top_mon = resumo.por_monitor.head(12).sort_values("Total", ascending=True)
            fig_mon = go.Figure()
            for sev in SEVERIDADE_ORDEM:
                fig_mon.add_bar(
                    y=top_mon["Monitor"],
                    x=top_mon[sev],
                    orientation="h",
                    name=sev,
                    marker_color=CORES_SEVERIDADE[sev][0],
                    hovertemplate=f"<b>%{{y}}</b><br>{sev}: %{{x}}<extra></extra>",
                )
            fig_mon.update_layout(barmode="stack")
            st.plotly_chart(
                _layout_radar(
                    fig_mon, altura=max(320, min(520, 120 + len(top_mon) * 28))
                ),
                width="stretch",
                config=CHART_CONFIG,
                key="radar_chart_monitor",
            )

        with g2, st.container(border=True):
            render_section_header(
                "Alertas por Categoria",
                subtitulo="Principais ofensores e oportunidades no recorte",
                icone="📊",
            )
            cat_ord = resumo.por_categoria.sort_values("Quantidade", ascending=True)
            fig_cat = go.Figure(
                go.Bar(
                    y=cat_ord["Categoria"],
                    x=cat_ord["Quantidade"],
                    orientation="h",
                    marker_color=[
                        CORES_SEVERIDADE[str(s)][0] for s in cat_ord["Severidade"]
                    ],
                    text=cat_ord["Quantidade"],
                    textposition="outside",
                    hovertemplate="<b>%{y}</b><br>Alertas: %{x}<extra></extra>",
                )
            )
            max_q = int(cat_ord["Quantidade"].max()) if not cat_ord.empty else 1
            fig_cat.update_xaxes(range=[0, max_q * 1.25])
            st.plotly_chart(
                _layout_radar(fig_cat, altura=340),
                width="stretch",
                config=CHART_CONFIG,
                key="radar_chart_categoria",
            )

        render_section_header(
            "Fila Priorizada de Ação Operacional",
            subtitulo=f"{len(df_view)} sinalização(ões) no filtro atual",
            icone="✅",
        )
        if df_view.empty:
            render_insight(
                "Nenhum alerta corresponde aos filtros selecionados.", tipo="info"
            )
        else:
            st.dataframe(
                df_view.style.map(_estilo_severidade, subset=["Severidade"]),
                width="stretch",
                hide_index=True,
                column_config={
                    "Severidade": st.column_config.TextColumn(width="small"),
                    "Categoria": st.column_config.TextColumn(width="medium"),
                    "Técnico": st.column_config.TextColumn(width="medium"),
                    "Detalhe": st.column_config.TextColumn(width="large"),
                    "Ação Recomendada": st.column_config.TextColumn(width="large"),
                },
            )
            if "Técnico" in df_view.columns:
                render_drilldown_tecnico(
                    df_view["Técnico"].tolist(),
                    key_prefix="radar",
                )
            st.download_button(
                "Baixar fila de alertas em CSV",
                data=sanitizar_csv_exportacao(df_view),
                file_name="totale_radar_alertas.csv",
                mime="text/csv",
                key="radar_download_csv",
            )

    _render_radar_body()


__all__ = [
    "CORES_SEVERIDADE",
    "ResumoAlertas",
    "SEVERIDADE_ORDEM",
    "calcular_radar_alertas",
    "render_radar_alertas",
]
