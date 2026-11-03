"""Avaliações reproduzíveis de frescor e consistência estrutural das fontes."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd

EstadoSaude = Literal["ok", "alerta", "critico"]
FUSO_BR = ZoneInfo("America/Sao_Paulo")


def avaliar_frescor(
    ultimo_sucesso: datetime | None,
    sucesso_na_tentativa_atual: bool,
    *,
    agora: datetime | None = None,
) -> tuple[EstadoSaude, str]:
    if ultimo_sucesso is None:
        return "critico", "Sem sincronização bem-sucedida nesta sessão"

    referencia = agora or datetime.now(FUSO_BR)
    sucesso = ultimo_sucesso
    if sucesso.tzinfo is None:
        sucesso = sucesso.replace(tzinfo=FUSO_BR)
    if referencia.tzinfo is None:
        referencia = referencia.replace(tzinfo=FUSO_BR)
    idade_min = max(0.0, (referencia - sucesso).total_seconds() / 60.0)
    idade = f"último sucesso há {idade_min:.0f} min"
    if idade_min <= 15 and sucesso_na_tentativa_atual:
        return "ok", f"Atualizada · {idade}"
    if idade_min <= 60:
        aviso = " · tentativa mais recente falhou" if not sucesso_na_tentativa_atual else ""
        return "alerta", f"Atenção · {idade}{aviso}"
    return "critico", f"Desatualizada · {idade}"


def avaliar_consistencia(df: pd.DataFrame | None) -> tuple[EstadoSaude, str]:
    if df is None or df.empty:
        return "critico", "Sem registros carregados"

    vazias = [
        coluna
        for coluna in df.columns
        if df[coluna].isna().all() or df[coluna].astype("string").str.strip().eq("").all()
    ]
    duplicadas = int(df.duplicated().sum())
    if duplicadas or vazias:
        detalhes: list[str] = []
        if duplicadas:
            detalhes.append(f"{duplicadas:,} linhas duplicadas".replace(",", "."))
        if vazias:
            detalhes.append(f"{len(vazias)} coluna(s) sem valores")
        return "alerta", " · ".join(detalhes)
    return "ok", f"Estrutura íntegra · {len(df):,} linhas".replace(",", ".")
