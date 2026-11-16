# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Totale · Inteligência & Gestão Operacional" \
      org.opencontainers.image.description="Plataforma corporativa de Inteligência & Gestão Operacional da Totale (Produção Técnica, O.S., Contratos, Performance Consultiva e Quadro Ativo)" \
      org.opencontainers.image.vendor="Totale" \
      org.opencontainers.image.source="https://github.com/denisvick-dev/totale-gestao-operacional"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash --uid 10001 appuser

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY --chown=appuser:appuser . .
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

EXPOSE 8501

# Health check para orquestradores (Docker, Kubernetes, etc.)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.headless", "true", "--server.port", "8501"]
