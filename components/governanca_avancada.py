"""Painel de Governança Avançada: De-Para, Tabelas Materializadas e Backup WAL-Safe."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import tempfile
from typing import Any, cast

import pandas as pd
import streamlit as st

from components.componentes import (
    formatar_numero_br,
    render_kpi,
    render_section_header,
)
from production import (
    backup_database,
    delete_technician_alias,
    load_sidebar_pulse_summary,
    load_technician_aliases,
    refresh_monthly_summaries,
    save_technician_alias,
)


def render_governanca_avancada(
    records: pd.DataFrame,
    roster: pd.DataFrame,
    *,
    on_invalidate_caches: Callable[[], None] | None = None,
) -> None:
    """Renderiza De-Para de técnicos/logins, status das tabelas materializadas e backup."""
    # 1. Status das Tabelas Materializadas Mensais & Índices Compostos (Item 2.1)
    render_section_header(
        "Tabelas Materializadas Mensais & Pushdown SQL",
        "Camada pré-agregada (summary_production_monthly / summary_consultivo_monthly) e índices compostos.",
    )
    pulse = load_sidebar_pulse_summary()
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        render_kpi(
            m1,
            "STATUS MATERIALIZAÇÃO",
            "Ativa" if pulse.get("materialized") else "Sob demanda",
            f"Atualizada em {pulse.get('refreshed_at') or '—'}",
            tema="verde" if pulse.get("materialized") else "laranja",
            icone="⚡",
        )
        render_kpi(
            m2,
            "LINHAS RESUMO PRODUÇÃO",
            formatar_numero_br(pulse.get("summary_prod_rows", 0)),
            f"Compila {formatar_numero_br(pulse.get('records', 0))} registros brutos",
            tema="azul",
            icone="📊",
        )
        render_kpi(
            m3,
            "LINHAS RESUMO CONSULTIVO",
            formatar_numero_br(pulse.get("summary_cons_rows", 0)),
            f"{formatar_numero_br(pulse.get('consultivos_total', 0))} consultivos agregados",
            tema="roxo",
            icone="🎯",
        )
        render_kpi(
            m4,
            "COMPETÊNCIAS INDEXADAS",
            f"{int(pulse.get('months_count', 0))} meses",
            "Índices compostos data × origem/login ativos",
            tema="azul",
            icone="🗂️",
        )
        if st.button(
            "Recalcular tabelas materializadas",
            key="gov_refresh_materialized_btn",
            icon=":material/sync:",
        ):
            refresh_monthly_summaries()
            if on_invalidate_caches is not None:
                on_invalidate_caches()
            st.success("Tabelas materializadas mensais recalculadas com sucesso.")
            st.rerun()

    # 2. De-Para de Técnicos & Logins NetSales
    render_section_header(
        "De-Para de Técnicos & Logins NetSales",
        "Corrija nomes divergentes ou logins antigos sem alterar as planilhas de origem.",
    )
    with st.container(border=True):
        aliases_df = load_technician_aliases()
        nomes_canonicos: set[str] = set()
        if not roster.empty and "technician" in roster.columns:
            nomes_canonicos.update(
                str(n).strip()
                for n in roster["technician"].dropna().unique()
                if str(n).strip()
            )
        if not records.empty and "technician" in records.columns:
            nomes_canonicos.update(
                str(n).strip()
                for n in records["technician"].dropna().unique()
                if str(n).strip()
            )
        opcoes_canonicas = sorted(nomes_canonicos)

        c1, c2, c3, c4 = st.columns([0.9, 1.3, 1.5, 1.1])
        with c1:
            alias_tipo = st.selectbox(
                "Tipo de de-para",
                options=["name", "login"],
                format_func=lambda v: (
                    "Nome divergente" if v == "name" else "Login NetSales"
                ),
                key="gov_alias_type",
            )
        with c2:
            alias_origem = st.text_input(
                "Valor na planilha (origem)",
                placeholder="Ex.: JOAO SILVA ou Z649999",
                key="gov_alias_source",
            )
        with c3:
            if opcoes_canonicas:
                alias_destino = st.selectbox(
                    "Técnico canônico (destino)",
                    options=opcoes_canonicas,
                    key="gov_alias_target_sel",
                )
            else:
                alias_destino = st.text_input(
                    "Técnico canônico (destino)",
                    placeholder="Nome oficial no cadastro",
                    key="gov_alias_target_txt",
                )
        with c4:
            alias_nota = st.text_input(
                "Observação",
                placeholder="Opcional",
                key="gov_alias_notes",
            )

        if st.button(
            "Salvar regra De-Para",
            key="gov_alias_save_btn",
            type="primary",
            icon=":material/link:",
        ):
            if alias_origem.strip() and str(alias_destino or "").strip():
                saved_ok = save_technician_alias(
                    cast(Any, alias_tipo),
                    alias_origem.strip(),
                    str(alias_destino).strip(),
                    notes=alias_nota.strip(),
                )
                if saved_ok:
                    if on_invalidate_caches is not None:
                        on_invalidate_caches()
                    st.success("Regra De-Para salva e caches recarregados.")
                    st.rerun()
            else:
                st.warning("Informe o valor de origem e o técnico canônico de destino.")

        if aliases_df.empty:
            st.caption("Nenhuma regra De-Para cadastrada até o momento.")
        else:
            st.dataframe(aliases_df, width="stretch", hide_index=True)
            rem_c1, rem_c2 = st.columns([2.5, 1.0], vertical_alignment="bottom")
            with rem_c1:
                id_opcoes = aliases_df["id"].astype(int).tolist()
                rotulos_id = {
                    int(r_id): f"#{int(r_id)} · [{r_tipo}] {r_src} → {r_dst}"
                    for r_id, r_tipo, r_src, r_dst in zip(
                        aliases_df["id"].tolist(),
                        aliases_df["alias_type"].tolist(),
                        aliases_df["source_value"].tolist(),
                        aliases_df["canonical_technician"].tolist(),
                        strict=False,
                    )
                }
                alias_rem = st.selectbox(
                    "Remover regra existente",
                    options=id_opcoes,
                    format_func=lambda i: rotulos_id.get(int(i), str(i)),
                    key="gov_alias_delete_select",
                )
            with rem_c2:
                if st.button(
                    "Remover regra",
                    key="gov_alias_delete_btn",
                    use_container_width=True,
                ):
                    delete_technician_alias(int(alias_rem))
                    if on_invalidate_caches is not None:
                        on_invalidate_caches()
                    st.success("Regra removida com sucesso.")
                    st.rerun()

    # 3. Backup Seguro WAL-Safe
    render_section_header(
        "Backup Seguro do Banco SQLite (WAL-Safe)",
        "Gera uma cópia consistente via API nativa sqlite3.backup() com PRAGMA optimize.",
    )
    with st.container(border=True):
        b_col1, b_col2 = st.columns([1.4, 2.6], vertical_alignment="center")
        with b_col1:
            if st.button(
                "Gerar snapshot de backup (.db)",
                key="gov_generate_backup_btn",
                icon=":material/backup:",
                use_container_width=True,
            ):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    snap_path = backup_database(Path(tmp_dir) / "totale_backup.db")
                    if snap_path and snap_path.exists():
                        st.session_state["_gov_backup_bytes"] = snap_path.read_bytes()
                        st.session_state["_gov_backup_name"] = (
                            f"totale_producao_backup_{pd.Timestamp.now().strftime('%Y%m%d_%H%M')}.db"
                        )
        with b_col2:
            if st.session_state.get("_gov_backup_bytes"):
                st.download_button(
                    "⬇️ Baixar backup SQLite (.db)",
                    data=st.session_state["_gov_backup_bytes"],
                    file_name=str(
                        st.session_state.get("_gov_backup_name", "totale_backup.db")
                    ),
                    mime="application/x-sqlite3",
                    key="gov_download_backup_btn",
                )
            else:
                st.caption(
                    "Clique em 'Gerar snapshot de backup (.db)' para criar uma cópia íntegra pronta para download."
                )
