"""Componentes de importação e manutenção da base."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from production import (
    DEMO_SOURCE,
    GPON,
    PROD,
    clear_database,
    clear_demonstration,
    database_stats,
    import_batches,
    process_upload,
    save_records,
)

from .layout import section_heading

DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq"


def template_file() -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(columns=["Data", "Técnico", "Pontos"]).to_excel(
            writer, sheet_name=PROD, index=False
        )
        pd.DataFrame(columns=["Data", "Técnico", "Pontos"]).to_excel(
            writer, sheet_name=GPON, index=False
        )
    return output.getvalue()


def render_import(is_demo: bool) -> None:
    section_heading("Importar e gerenciar dados", "Atualize o histórico com as planilhas de produção da equipe")
    feedback = st.session_state.pop("import_feedback", None)
    if feedback:
        if feedback["type"] == "success":
            st.success(feedback["message"])
        else:
            st.warning(feedback["message"])
        for issue in feedback.get("issues", []):
            st.caption(issue)

    upload_col, help_col = st.columns([1.65, 1])
    with upload_col:
        with st.container(border=True):
            st.markdown("**1. Selecione os arquivos**")
            st.markdown(
                '<div class="small-muted">Envie um ou mais arquivos. Ao reenviar um arquivo com o mesmo nome, seus registros serão substituídos sem duplicar o histórico.</div>',
                unsafe_allow_html=True,
            )
            files = st.file_uploader(
                "Planilhas de produção",
                type=["xlsx", "xls", "csv"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            option_col, date_col = st.columns(2)
            with option_col:
                csv_origin = st.selectbox(
                    "Origem para arquivos CSV",
                    [PROD, GPON],
                    help="Arquivos Excel usam automaticamente o nome das abas.",
                )
            with date_col:
                default_date = st.date_input(
                    "Competência padrão (opcional)",
                    value=None,
                    help="Usada somente quando o arquivo não tiver coluna de data/competência.",
                )
            if st.button(
                "Processar e importar",
                type="primary",
                disabled=not files,
                width="stretch",
            ):
                all_records = []
                issues = []
                successful_files = 0
                for uploaded in files:
                    try:
                        records, file_issues = process_upload(
                            uploaded.name,
                            uploaded.getvalue(),
                            csv_origin=csv_origin,
                            default_date=default_date,
                        )
                        if records:
                            all_records.extend(records)
                            successful_files += 1
                        issues.extend(f"{uploaded.name} · {issue}" for issue in file_issues[:20])
                    except ValueError as error:
                        issues.append(f"{uploaded.name} · {error}")
                if all_records:
                    count = save_records(all_records)
                    message = (
                        f"{count} registros importados de {successful_files} arquivo(s). "
                        "O histórico já foi atualizado."
                    )
                    if is_demo:
                        message += " Os dados de demonstração foram removidos."
                    st.session_state["import_feedback"] = {
                        "type": "success",
                        "message": message,
                        "issues": issues[:40],
                    }
                    st.rerun()
                else:
                    st.session_state["import_feedback"] = {
                        "type": "warning",
                        "message": "Nenhum registro válido foi importado. Revise os avisos abaixo.",
                        "issues": issues[:40],
                    }
                    st.rerun()

    with help_col:
        with st.container(border=True):
            st.markdown("**2. Confira o formato**")
            st.markdown(
                """
                <div class="small-muted">
                Cada arquivo Excel deve conter as abas <b>Prod</b> e/ou <b>Gpon</b>, com:
                <ul>
                    <li><b>Técnico:</b> nome do colaborador</li>
                    <li><b>Pontos:</b> valor produzido</li>
                    <li><b>Data:</b> dia ou competência mensal</li>
                </ul>
                Também reconhecemos Competência, Mês, Colaborador e Pontuação.
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="formula"><b>Pontos Totais = Pontos em Prod + Pontos em Gpon</b></div>',
                unsafe_allow_html=True,
            )
            st.download_button(
                "Baixar planilha modelo",
                data=template_file(),
                file_name="modelo_producao.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.link_button("Abrir pasta no Google Drive", DRIVE_FOLDER_URL, width="stretch")

    section_heading("Arquivos na base", "Reenvios com o mesmo nome substituem apenas a origem correspondente")
    batches = import_batches()
    if not batches.empty:
        batches = batches.rename(
            columns={
                "source_file": "Arquivo",
                "origins": "Abas",
                "rows_count": "Registros",
                "points": "Soma de pontos",
                "imported_at": "Importado em",
            }
        )
        batches["Arquivo"] = batches["Arquivo"].replace(DEMO_SOURCE, "Base de demonstração")
        batches["Importado em"] = pd.to_datetime(batches["Importado em"]).dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(batches, width="stretch", hide_index=True)

    stats = database_stats()
    first_date = pd.Timestamp(stats["first_date"]).strftime("%d/%m/%Y") if stats["first_date"] else "—"
    last_date = pd.Timestamp(stats["last_date"]).strftime("%d/%m/%Y") if stats["last_date"] else "—"
    st.markdown(
        f'<div class="small-muted">A base contém <b>{stats["records"]}</b> linhas de {stats["technicians"]} técnicos, com produção entre <b>{first_date}</b> e <b>{last_date}</b>.</div>',
        unsafe_allow_html=True,
    )

    with st.expander("Limpar dados"):
        if is_demo:
            st.markdown("Remova a demonstração para começar com uma base vazia.")
            if st.button("Remover dados de demonstração"):
                clear_demonstration()
                st.session_state.pop("period_filter", None)
                st.rerun()
        st.warning("A limpeza completa apaga todos os registros importados. Essa ação não pode ser desfeita.")
        confirmation = st.checkbox("Confirmo que desejo apagar toda a base de produção")
        if st.button("Apagar toda a base", disabled=not confirmation):
            clear_database()
            for key in ("period_filter", "technician_filter", "custom_start", "custom_end"):
                st.session_state.pop(key, None)
            st.rerun()
