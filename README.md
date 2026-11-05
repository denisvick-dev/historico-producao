# Histórico de produção — Totale

Painel em Streamlit para acompanhar a produção dos técnicos ao longo do tempo. A regra central do sistema é:

> **Pontos Totais = Pontos na aba `Prod` + Pontos na aba `Gpon`**

## Funcionalidades

- Visão geral com Pontos Totais, Prod, Gpon e média por técnico.
- **Resumo executivo** com comparação contra competências anteriores, distribuição por técnico e variações individuais.
- **Produção por projeto** com ranking, evolução mensal, participação, O.S. e detalhamento por técnico.
- Página **Quantidade de O.S.** com evolução por competência e ranking dos 15 técnicos com mais ordens (cada linha válida da aba `Prod` conta como uma O.S.).
- **Saúde dos dados** com cobertura de projetos, dados de demonstração, status de sincronização e histórico de arquivos importados.
- Filtros compartilhados por período, projeto e técnico; a página de técnicos permite escolher o projeto e o perfil individual.
- Evolução mensal e ranking da equipe.
- Histórico mensal detalhado e exportação em CSV.
- Perfil individual com melhor competência e comparação com a média da equipe.
- Persistência local em SQLite.
- Dados de demonstração identificados.
- Sincronização automática com Google Drive via conta de serviço.
- Logs estruturados em JSON para observabilidade.
- Health check para orquestradores (Docker, Kubernetes).
- CI/CD com GitHub Actions (testes, lint, type check).

## Formato das planilhas

Arquivos Excel devem ter uma aba chamada **Prod** e/ou **Gpon**. Cada aba precisa conter:

| Coluna | Obrigatória | Exemplo |
| --- | --- | --- |
| Data / Competência | Sim* | `03/11/2026` ou `11/2026` |
| Técnico | Sim | `André Santos` |
| Projeto | Não | `Rede Metropolitana` |
| Pontos | Sim | `125,50` |

\* Quando não houver data, a rotina de sincronização pode usar o ano/mês informado no nome do arquivo (por exemplo, `producao_2026-11.xlsx`).

A rotina de sincronização reconhece variações como `Colaborador`, `Funcionário`, `Nome`, `Projeto`, `Pontuação`, `Mês/Ano` e `Período`. Sem coluna ou valor preenchido, o registro fica classificado como **Sem projeto**. Para arquivos CSV, a origem deve ser indicada como `Prod` ou `Gpon`; são aceitos separadores vírgula ou ponto e vírgula e codificações UTF-8 ou Latin-1.

### Exemplo de arquivo CSV

```csv
Técnico;Pontos;Competência;Projeto
André Santos;125,50;11/2026;Rede Metropolitana
Bruno Oliveira;98,30;11/2026;Fibra Norte
```

## Como executar

### Localmente

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### Com Docker

```bash
docker build -t historico-producao .
docker run -p 8501:8501 \
  -e PRODUCAO_DB_PATH=/data/producao.db \
  -v $(pwd)/data:/data \
  historico-producao
```

O painel estará disponível em `http://localhost:8501`.

## Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `PRODUCAO_DB_PATH` | Não | `data/producao.db` | Caminho do banco SQLite |
| `DRIVE_FOLDER_ID` | Não | `1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq` | ID da pasta no Google Drive |
| `SHOW_DEMO_DATA` | Não | `1` | Define como `0` para desativar dados de demonstração |

## Sincronização automática do Google Drive

Habilite a Google Drive API, compartilhe a pasta de produção com a conta de serviço e configure suas credenciais em `.streamlit/secrets.toml` (não versione esse arquivo):

```toml
[gcp_service_account]
type = "service_account"
project_id = "seu-projeto"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "conta-de-servico@seu-projeto.iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"

[drive_folder_id]
# Opcional: sobrescreve o ID padrão da pasta
```

Os arquivos Excel devem conter as abas `Prod` e/ou `Gpon`; arquivos CSV são lidos como `Prod` por padrão.

## Persistência

Os registros ficam em `data/producao.db`, ignorado pelo Git. Em hospedagens com disco temporário, configure um volume persistente para preservar os dados entre reinicializações.

Para iniciar sem dados de demonstração:

```bash
SHOW_DEMO_DATA=0 streamlit run streamlit_app.py
```

Para usar outro local de banco:

```bash
PRODUCAO_DB_PATH=/caminho/producao.db streamlit run streamlit_app.py
```

## Testes

```bash
python -m unittest discover -s tests -v
```

Os testes cobrem:
- Fórmula de consolidação (Prod + Gpon)
- Conversão de pontos (formato brasileiro e internacional)
- Conversão de datas (completo, mensal, nome do arquivo)
- Importação de Excel/CSV com aliases de colunas
- Prevenção de duplicidades na reimportação
- Sincronização do Drive (substituição e remoção de arquivos)
- Fonte Inter em dataframes (corpo e cabeçalhos)

## CI/CD

O repositório usa GitHub Actions (`.github/workflows/ci.yml`) para executar em cada push/PR:

1. **Lint** com `ruff` (verificação de estilo e formatação)
2. **Type checking** com `mypy`
3. **Testes** com `unittest`
4. **Compilação** com `py_compile`

## Estrutura do projeto

```
historico-producao/
├── .github/workflows/ci.yml      # Pipeline de CI/CD
├── Dockerfile                    # Imagem para deploy em contêiner
├── mypy.ini                      # Configuração de type checking
├── requirements.txt              # Dependências Python
├── README.md                     # Este documento
├── streamlit_app.py              # Ponto de entrada da aplicação
├── production.py                 # Regras de negócio e persistência (SQLite)
├── drive_import.py               # Sincronização com Google Drive
├── components/                   # Design System e componentes UI
│   ├── __init__.py
│   ├── componentes.py            # Design System base (cores, fontes, KPI, heróis)
│   ├── css_global.py             # CSS global dos componentes nativos
│   ├── css_paginas.py            # CSS compartilhado de páginas
│   ├── criterios.py              # Detecção e classificação de colunas
│   ├── dashboard_kit.py          # Kit de dashboards (CSS v2, KPI, filtros)
│   ├── dashboards.py
│   ├── graficos.py               # Fábrica de gráficos Plotly
│   ├── kpi_cards.py              # Cartões de KPI avançados
│   ├── layout_pagina.py          # Hierarquia de leitura das páginas
│   ├── metricas_executivas.py    # Cálculos de tendências executivas
│   ├── prod_os.py                # Página de quantidade de O.S.
│   ├── saude_dados.py            # Avaliação de frescor e consistência
│   ├── sidebar.py                # Sidebar corporativa
│   └── visoes_dashboards.py      # Projetos, resumo executivo e saúde da base
└── tests/
    ├── test_css_global.py        # Testes de fonte em dataframes
    ├── test_drive_import.py      # Testes de importação do Drive
    ├── test_prod_os.py           # Testes da página de O.S.
    ├── test_production.py        # Testes de regras de negócio
    ├── test_streamlit_app.py     # Testes de integração da UI
    └── test_visoes_dashboards.py # Testes das novas visões
```

## Troubleshooting

| Problema | Causa provável | Solução |
| --- | --- | --- |
| `pip install` falha | `requirements.txt` com encoding inválido | Verifique que o arquivo está em UTF-8 |
| Sem dados no painel | Banco vazio ou sem sincronização | Verifique `PRODUCAO_DB_PATH` e credenciais do Drive |
| Erro de autenticação Drive | Credenciais inválidas ou pasta não compartilhada | Confirme `.streamlit/secrets.toml` e compartilhamento da pasta |
| Health check falha | App ainda inicializando | Aguarde o start-period do Docker (40s) |
