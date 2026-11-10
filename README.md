<p align="left">
  <img src="assets/novo-logo-totale.png" alt="Logo Totale" width="220">
</p>

# Histórico de produção — Totale

Painel em Streamlit para acompanhar a produção dos técnicos ao longo do tempo. A regra central do sistema é:

> **Pontos Totais = Pontos na aba `Prod` + Pontos na aba `Gpon`**

## Funcionalidades

- Visão geral com Pontos Totais, Prod, Gpon e média por técnico.
- **Resumo executivo** com comparação contra competências anteriores, distribuição por técnico e variações individuais.
- **Produção por projeto** com ranking, evolução mensal, participação, O.S. e detalhamento por técnico.
- **Regularidade da produção** com média e mediana mensal, coeficiente de variação, destaques de oscilação e competências sem registros por técnico.
- **Sazonalidade** com mapa de calor de Pontos Totais por competência e técnico ou projeto, além de tabela exportável em CSV.
- Página **Quantidade de O.S.** com evolução por competência e ranking dos 15 técnicos com mais ordens (cada linha válida da aba `Prod` conta como uma O.S.).
- Página **Contratos** com duas sub-abas: **Quantidade de contratos** (indicadores, evolução mensal, ranking e matriz por técnico com meses com produção, média mensal e exportação CSV) e **Eficiência de contratos** (classificação mensal dos contratos nas Faixas 1 a 5 de pontuação, filtros por técnico e faixa predominante, distribuição e evolução mensal das faixas, matriz de frequência por contrato e detalhamento mensal exportáveis em CSV). A contagem de quantidade considera contratos distintos por técnico e competência em todas as origens filtradas; a média mensal divide o total pelos meses com ao menos um contrato válido (e, na linha Total geral, usa os meses com contratos de qualquer técnico).
- Página **Produtividade unitária** cruzando volume e complexidade: indicadores de **Pontos por O.S. (`Prod`)** e **Pontos por Contrato**, evolução mensal do ticket médio de pontos, gráfico de dispersão em 4 quadrantes (*Volume × Pontos unitários*), rankings Top 15 e tabela consolidada com exportação CSV.
- Página **Quadro de técnicos** interligada à planilha oficial [`lista_ativos`](https://docs.google.com/spreadsheets/d/1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg) (abas `lista_ativos` e `desligados`), conciliando **RE**, **Login**, **Situação**, **Monitor**, **U.N.** e **Base** com os pontos (`Prod + Gpon`), O.S. e contratos no período.
- **Saúde dos dados** com cobertura de projetos, dados de demonstração, status de sincronização, histórico de arquivos importados com o contador de contratos distintos de cada arquivo e detalhamento dos registros com a coluna **Qtde_Contrato**, exportável em CSV.
- Filtros compartilhados por **Situação cadastral** (padrão restrito a `ATIVO`), **Monitor**, **Base**, período, projeto e técnico; a página de técnicos exibe matrícula/RE, login, monitor e base no perfil individual.
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

O projeto requer **Python 3.12**. Use o mesmo interpretador para instalar dependências e iniciar o Streamlit.

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

**Linux/macOS:**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
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
| `ROSTER_SHEET_ID` | Não | `1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg` | ID ou URL da planilha cadastral (`lista_ativos`) |
| `ROSTER_PUBLIC_SYNC` | Não | `0` | Define como `1` para sincronizar `lista_ativos` via link público mesmo sem conta de serviço |
| `SHOW_DEMO_DATA` | Não | `1` | Define como `0` para desativar dados de demonstração |

## Sincronização automática do Google Drive

Habilite a Google Drive API, compartilhe a pasta de produção e a planilha cadastral `lista_ativos` com a conta de serviço e configure suas credenciais em `.streamlit/secrets.toml` (não versione esse arquivo):

```toml
# Opcional: sobrescreve os IDs padrão da pasta e da planilha cadastral
drive_folder_id = "id_da_pasta"
roster_sheet_id = "1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg"

[gcp_service_account]
type = "service_account"
project_id = "seu-projeto"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "conta-de-servico@seu-projeto.iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"

```

Os arquivos Excel devem conter as abas `Prod` e/ou `Gpon`; arquivos CSV são lidos como `Prod` por padrão.
Para reduzir o tempo das sincronizações seguintes, os metadados dos arquivos são comparados e somente arquivos novos ou alterados são baixados e processados. Arquivos sem metadados suficientes são reprocessados; alterações nas opções de importação também invalidam a comparação. Falhas individuais preservam os registros anteriores, e listagens incompletas interrompem a sincronização antes de qualquer exclusão. Erros temporários de conexão, HTTP 429 e erros 5xx recebem até três tentativas; erros permanentes são informados imediatamente. O download e processamento são paralelos (até 8 arquivos), com reutilização da conexão e do token por worker. Os logs incluem a duração da listagem e o tempo total da importação para facilitar o diagnóstico de lentidão.

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

## Desenvolvimento e verificações

Após instalar `requirements.txt` no ambiente virtual, instale as ferramentas de desenvolvimento:

```bash
python -m pip install ruff mypy
python scripts/check.py              # lint, tipos, testes e compilação
python scripts/check.py lint         # ou: types, tests, compile
```

O script usa o mesmo interpretador Python e os mesmos comandos do CI. Os testes
podem ser executados diretamente com `python -m unittest discover -s tests -v`.
Para medir as operações de dados com uma amostra sintética, sem acessar o banco:

```bash
python scripts/benchmark_data.py --rows 200000
```

Os tempos dependem do ambiente e da distribuição dos dados; compare execuções
na mesma máquina e não use o resultado como limite de aprovação do CI.

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

## Organização e fluxo de dados

- `drive_import.py` lista e processa arquivos do Drive; `production.py` concentra
  importação, normalização, persistência SQLite e agregações independentes da UI.
- `streamlit_app.py` monta a navegação e os filtros compartilhados. Os módulos de
  `components/` renderizam os painéis e consomem os dados filtrados. Os painéis
  de contratos e O.S. compartilham elementos visuais em `painel_quantidades.py`,
  sem depender um do outro.
- A consulta do dashboard usa cache de 60 segundos; os carregamentos de registros
  e do dashboard compartilham a mesma consulta e preparação dos dados. A contagem
  por arquivo usa os flags `Qtde_Contrato` quando presentes e contratos distintos
  como fallback. Não confundir com os totais por técnico e mês da aba Contratos.
- O Docker usa `.dockerignore` para não incluir banco local, credenciais ou
  dependências de desenvolvimento no contexto da imagem. Monte o banco em volume
  e forneça os segredos pelo mecanismo da plataforma, fora do repositório.

## Estrutura do projeto

```
historico-producao/
├── .github/workflows/ci.yml      # Pipeline de CI/CD
├── .dockerignore                 # Exclusões do contexto Docker
├── Dockerfile                    # Imagem para deploy em contêiner
├── mypy.ini                      # Configuração de type checking
├── requirements.txt              # Dependências Python
├── README.md                     # Este documento
├── assets/
│   └── novo-logo-totale.png      # Logotipo oficial da Totale
├── streamlit_app.py              # Ponto de entrada da aplicação
├── production.py                 # Regras de negócio e persistência (SQLite)
├── drive_import.py               # Sincronização com Google Drive
├── scripts/                      # Verificações locais/CI e benchmark sintético
├── components/                   # Design System e componentes UI
│   ├── __init__.py
│   ├── componentes.py            # Design System base (cores, fontes, KPI, heróis)
│   ├── contratos.py              # Quantidade de contratos por técnico e competência
│   ├── css_global.py             # CSS global dos componentes nativos
│   ├── eficiencia.py             # Eficiência por técnico e por contrato
│   ├── painel_quantidades.py     # Componentes compartilhados dos painéis O.S. e contratos
│   ├── prod_os.py                # Página de quantidade de O.S.
│   ├── produtividade_unitaria.py # Página de produtividade unitária (pontos por O.S. e contrato)
│   ├── quadro_tecnicos.py        # Página de conciliação do cadastro lista_ativos/desligados
│   ├── sidebar.py                # Sidebar corporativa e temas
│   └── visoes_dashboards.py      # Projetos, resumo executivo e saúde da base
└── tests/
    ├── test_contratos.py         # Importação e persistência de contratos
    ├── test_css_global.py        # Testes de fonte em dataframes
    ├── test_data_optimization.py # Normalização e carregamento compartilhado
    ├── test_drive_import.py      # Testes de importação do Drive
    ├── test_eficiencia.py        # Eficiência por técnico e por contrato
    ├── test_prod_os.py           # Testes da página de O.S.
    ├── test_production.py        # Testes de regras de negócio
    ├── test_produtividade_unitaria.py # Testes da página de produtividade unitária
    ├── test_roster_integration.py # Testes da integração com lista_ativos e Quadro de técnicos
    ├── test_streamlit_app.py     # Testes de integração da UI
    └── test_visoes_dashboards.py # Testes das visões e saúde da base
```

## Troubleshooting

| Problema | Causa provável | Solução |
| --- | --- | --- |
| `pip install` falha | Python abaixo de 3.12 ou ambiente virtual usando outro interpretador | Use Python 3.12, recrie `.venv` e execute `python -m pip install -r requirements.txt` com o mesmo Python do Streamlit |
| Erro ao abrir XLSX: `openpyxl` parcialmente inicializado | Pacote incompleto ou conflito local de importação | Reinstale com `python -m pip install --force-reinstall --no-cache-dir openpyxl==3.1.5` no `.venv` do app e verifique se o projeto não contém `openpyxl.py` nem pasta `openpyxl` |
| Sem dados no painel | Banco vazio ou sem sincronização | Verifique `PRODUCAO_DB_PATH` e credenciais do Drive |
| Erro de autenticação Drive | Credenciais inválidas ou pasta não compartilhada | Confirme `.streamlit/secrets.toml` e compartilhamento da pasta |
| Health check falha | App ainda inicializando | Aguarde o start-period do Docker (40s) |
