FROM python:3.12-slim

LABEL org.opencontainers.image.title="Totale · Inteligência & Gestão Operacional" \
      org.opencontainers.image.description="Plataforma corporativa de Inteligência & Gestão Operacional da Totale (Produção Técnica, O.S., Contratos, Performance Consultiva e Quadro Ativo)" \
      org.opencontainers.image.vendor="Totale" \
      org.opencontainers.image.source="https://github.com/denisvick-dev/totale-gestao-operacional"

WORKDIR /app

# Dependências do sistema (necessárias para alguns pacotes Python)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Health check para orquestradores (Docker, Kubernetes, etc.)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "streamlit_app.py", "--server.address", "0.0.0.0", "--server.headless", "true", "--server.port", "8501"]
