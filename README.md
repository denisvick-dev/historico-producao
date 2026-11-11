<p align="left">
  <img src="assets/novo-logo-totale.png" alt="Logo Totale" width="220">
</p>

# Totale · Inteligência & Gestão Operacional

Plataforma corporativa em Streamlit dedicada ao acompanhamento executivo e analítico das operações de campo e performance comercial da **Totale**, consolidando **Produção Técnica (`Prod + Gpon`)**, **Ordens de Serviço (O.S.)**, **Contratos**, **Performance Consultiva (`NetSales`)**, **Comparativos Interanuais (`2025 × 2026`)** e **Governança Cadastral (`lista_ativos`)**.

> **Regra de Consolidação Operacional:**  
> **`Pontos Totais = Pontos na aba Prod + Pontos na aba Gpon`**

---

## Módulos Executivos

### 1. Produção & Produtividade Técnica
- **Visão Executiva · Produção**: indicadores consolidados de Pontos Totais, participação percentual `Prod` / `Gpon`, média por técnico ativo, cards de Delta (`Δ`) com destaque percentual contra o período anterior, evolução mensal e ranking da operação.
- **Gestão por Projeto**: ranking de projetos, evolução mensal, participação percentual, volume de O.S. e detalhamento por técnico.
- **Ordens de Serviço (O.S.)**: evolução mensal por competência e ranking Top 15 de técnicos (cada registro válido da aba `Prod` corresponde a uma O.S.).
- **Gestão & Eficiência de Contratos**:
  - *Quantidade de Contratos*: contratos distintos por técnico e competência, média mensal nos meses ativos e matriz exportável em CSV.
  - *Eficiência de Contratos*: classificação mensal nas Faixas 1 a 5 de pontuação, filtros por técnico e faixa predominante, evolução das faixas e matriz de frequência por contrato.
- **Produtividade Unitária**: indicadores de **Pontos por O.S. (`Prod`)** e **Pontos por Contrato**, evolução do ticket médio de pontos e dispersão estratégica em 4 quadrantes (*Volume × Complexidade*).
- **Regularidade Operacional & Sazonalidade**: média, mediana, coeficiente de variação, lacunas de produção e mapa de calor mensal por técnico ou projeto.
- **Matriz de Eficiência & Desempenho Individual**: predominância mensal de faixas e dossiê individual do técnico frente à média da operação.

### 2. Performance Consultiva & Mix Comercial
- **Performance Consultiva (`Consultivo`)**: sincronizado com a pasta oficial [`Histórico Consultivo`](https://drive.google.com/drive/folders/1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2) no Google Drive e conciliado com `lista_ativos` via `LOGIN NETSALES` e `VENDEDOR`. Apresenta KPIs executivos com participação percentual em destaque, mix comercial (**Mesh**, **TV Box** e **Virtua**), projeção de fechamento mensal (Seg–Sáb), cards de Delta contra a janela anterior, ranking por **Monitor** ou **Técnico**, equipes sem vendas, meta diária por Monitor e exportação CSV protegida.

### 3. Inteligência Comparativa Interanual (`2025 × 2026`)
- **Produção `2025 × 2026` (`Comparativo Interanual · Produção, Contratos e O.S.`)**: análise lado a lado entre anos (recorte equivalente dos mesmos meses, ano completo ou seleção manual) e escopos de equipe (*Operação completa*, *Apenas ativos atuais* ou *Mesma equipe nos 2 anos*), com **Cards de Delta (`Δ`) e Spotlight Percentual (`VARIAÇÃO %`)**, comparativos mensais com rótulos percentuais, curvas acumuladas YTD, giro `O.S./Contrato` e cruzamento executivo com Consultivo.
- **Consultivo `2025 × 2026` (`Comparativo Interanual · Performance Consultiva & Mix`)**: evolução interanual de atendimentos consultivos, produtos comercializados, taxa de conversão (`Produtos/Consultivo`) e deslocamento de mix em pontos percentuais (`Δ Mix p.p.`) para Mesh, TV Box e Virtua por Base, Monitor e Técnico.

### 4. Governança Cadastral & Dados
- **Quadro Cadastral (`lista_ativos`)**: conciliação direta com a planilha oficial [`lista_ativos`](https://docs.google.com/spreadsheets/d/1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg) (abas `lista_ativos` e `desligados`), unificando **RE**, **Login**, **Situação**, **Monitor**, **U.N.** e **Base** aos indicadores operacionais e comerciais.
- **Governança & Dados**: rastreabilidade de cobertura de projetos, status de sincronização incremental, auditoria de arquivos importados com contador `Qtde_Contrato` e exportação CSV.
- **Observabilidade & Infraestrutura**: persistência local em SQLite, logs estruturados em JSON (`structlog`), health check nativo para contêineres e pipeline automatizado de qualidade via GitHub Actions.

---

## Formato das Bases de Entrada

Os arquivos Excel de Produção devem possuir as abas **`Prod`** e/ou **`Gpon`**, contendo:

| Coluna | Obrigatória | Exemplo |
| --- | --- | --- |
| Data / Competência | Sim* | `03/11/2026` ou `11/2026` |
| Técnico | Sim | `André Santos` |
| Projeto | Não | `Rede Metropolitana` |
| Pontos | Sim | `125,50` |

\* Na ausência de coluna de data, a rotina de importação infere ano/mês a partir do nome do arquivo (ex.: `producao_2026-11.xlsx` ou nomes de competência por extenso).

A ingestão reconhece automaticamente aliases como `Colaborador`, `Funcionário`, `Nome`, `Nome Equipe`, `Projeto`, `Pontuação`, `Mês/Ano` e `Período`. Registros sem projeto recebem a classificação **Sem projeto**. Arquivos CSV aceitam delimitadores `,` ou `;` e codificações `UTF-8` ou `Latin-1`.

### Exemplo de arquivo CSV

```csv
Técnico;Pontos;Competência;Projeto
André Santos;125,50;11/2026;Rede Metropolitana
Bruno Oliveira;98,30;11/2026;Fibra Norte
```

---

## Execução do Ambiente

### Localmente

O ambiente de produção e CI utiliza **Python 3.12**:

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

**Linux / macOS:**

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run streamlit_app.py
```

### Contêiner Docker

```bash
docker build -t totale-gestao-operacional .
docker run -p 8501:8501 \
  -e PRODUCAO_DB_PATH=/data/producao.db \
  -v $(pwd)/data:/data \
  totale-gestao-operacional
```

Acesse a aplicação em `http://localhost:8501`.

---

## Variáveis de Ambiente

| Variável | Obrigatória | Padrão | Descrição |
| --- | --- | --- | --- |
| `PRODUCAO_DB_PATH` | Não | `data/producao.db` | Caminho do banco SQLite local |
| `DRIVE_FOLDER_ID` | Não | `1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq` | ID da pasta de Produção no Google Drive |
| `CONSULTIVO_FOLDER_ID` | Não | `1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2` | ID ou URL da pasta `Histórico Consultivo` no Google Drive |
| `ROSTER_SHEET_ID` | Não | `1LQKDcLshC6XSXLBVWaEYSpxrro6uydyU9pwDLc38pEg` | ID ou URL da planilha cadastral (`lista_ativos`) |
| `ROSTER_PUBLIC_SYNC` | Não | `0` | Define como `1` para sincronizar `lista_ativos` via link público sem conta de serviço |
| `SHOW_DEMO_DATA` | Não | `1` | Define como `0` para iniciar sem registros demonstrativos |

---

## Integração com Google Drive

Habilite a **Google Drive API**, compartilhe as pastas operacionais e a planilha `lista_ativos` com a conta de serviço e configure `.streamlit/secrets.toml` (arquivo ignorado pelo controle de versão):

```toml
# Opcional: sobrescreve os IDs padrão das fontes oficiais
drive_folder_id = "id_da_pasta"
consultivo_folder_id = "1xMwEgPm9udFoGobv9cCUoMmuoxuFiPB2"
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

A sincronização percorre pastas e subpastas anuais (`2025`, `2026`, etc.), comparando *fingerprints* de metadados para baixar apenas arquivos novos ou modificados em paralelo (até 8 workers com retentativa automática para falhas transitórias HTTP 429/5xx).

---

## Persistência de Dados

Os registros são armazenados em `data/producao.db` (ignorado pelo Git). Em ambientes em nuvem com sistema de arquivos efêmero, monte um volume persistente em `/data`:

```bash
SHOW_DEMO_DATA=0 PRODUCAO_DB_PATH=/caminho/producao.db streamlit run streamlit_app.py
```

---

## Qualidade de Código & Verificações (CI/CD)

Após instalar `requirements.txt`, instale as ferramentas de verificação estática e execute a suíte completa:

```bash
python -m pip install ruff mypy
python scripts/check.py              # lint, tipagem estática, testes e compilação
python scripts/check.py lint         # ou: types, tests, compile
python scripts/benchmark_data.py --rows 200000
```

O pipeline `.github/workflows/ci.yml` valida automaticamente a cada push ou Pull Request:
1. **Lint & Formatação** (`ruff check` e `ruff format --check`)
2. **Tipagem Estática** (`mypy`)
3. **Suíte de Testes Unitários e de Interface (`AppTest`)** (`unittest discover -s tests -v`)
4. **Compilação de Bytecode** (`py_compile`)

---

## Arquitetura do Repositório

```text
totale-gestao-operacional/
├── .github/workflows/ci.yml           # Pipeline corporativo de Qualidade & CI
├── .dockerignore                      # Exclusões de contexto de build Docker
├── Dockerfile                         # Imagem de produção com metadados OCI e healthcheck
├── pyproject.toml                     # Metadados corporativos do projeto (PEP 621)
├── mypy.ini                           # Configuração de verificação estática de tipos
├── requirements.txt                   # Dependências fixadas da aplicação
├── README.md                          # Documentação institucional e técnica
├── assets/
│   └── novo-logo-totale.png           # Identidade visual oficial da Totale
├── streamlit_app.py                   # Ponto de entrada, roteamento executivo e filtros globais
├── production.py                      # Regras de negócio, ETL, conciliação e persistência SQLite
├── drive_import.py                    # Conector paralelo e resiliente com Google Drive
├── scripts/
│   ├── check.py                       # Orquestrador unificado de lint, tipos, testes e compilação
│   └── benchmark_data.py              # Benchmark sintético de agregações em memória
├── components/                        # Design System Corporativo Totale e módulos visuais
│   ├── __init__.py
│   ├── componentes.py                 # Design System base (paleta, KPIs, Cards de Delta, heróis)
│   ├── sidebar.py                     # Barra lateral executiva, telemetria e seletor de temas
│   ├── css_global.py                  # Estilização global de tabelas e componentes nativos
│   ├── comparativo_anos.py            # Inteligência Interanual 2025 × 2026 (Produção, O.S. e Contratos)
│   ├── comparativo_consultivo.py      # Inteligência Interanual 2025 × 2026 (Consultivos e Mix)
│   ├── consultivo.py                  # Módulo operacional de Performance Consultiva & Mix Comercial
│   ├── contratos.py                   # Gestão de quantidade de contratos por competência
│   ├── eficiencia.py                  # Matriz de eficiência por técnico e por contrato
│   ├── painel_quantidades.py          # Visuais compartilhados entre O.S. e Contratos
│   ├── prod_os.py                     # Módulo de Ordens de Serviço (aba Prod)
│   ├── produtividade_unitaria.py      # Densidade de pontos por O.S., contrato e quadrantes
│   ├── quadro_tecnicos.py             # Conciliação cadastral (lista_ativos e desligados)
│   └── visoes_dashboards.py           # Gestão por projeto, regularidade e governança de dados
└── tests/                             # Suíte automatizada (regras de negócio + integração AppTest)
    ├── test_comparativo_anos.py
    ├── test_comparativo_consultivo.py
    ├── test_consultivo.py
    ├── test_contratos.py
    ├── test_css_global.py
    ├── test_data_optimization.py
    ├── test_drive_import.py
    ├── test_eficiencia.py
    ├── test_prod_os.py
    ├── test_production.py
    ├── test_produtividade_unitaria.py
    ├── test_roster_integration.py
    ├── test_streamlit_app.py
    └── test_visoes_dashboards.py
```

---

## Solução de Problemas (Troubleshooting)

| Sintoma | Causa Provável | Ação Recomendada |
| --- | --- | --- |
| Falha em `pip install -r requirements.txt` | Versão do Python inferior a 3.12 ou conflito de ambiente virtual | Crie o `.venv` com Python 3.12 e instale via `.venv/bin/python -m pip install -r requirements.txt` |
| Erro `openpyxl` parcialmente inicializado | Instalação corrompida ou sombreamento de nome de módulo | Reinstale com `python -m pip install --force-reinstall --no-cache-dir openpyxl==3.1.5` |
| Painel sem registros reais | Banco local vazio ou credenciais ausentes | Verifique `PRODUCAO_DB_PATH` e acione **Atualizar dados** na barra lateral |
| Erro de autenticação no Google Drive | Credenciais inválidas ou pastas não compartilhadas | Revise `.streamlit/secrets.toml` e compartilhe as pastas com o `client_email` da conta de serviço |
| Healthcheck do contêiner pendente | Aplicação ainda em inicialização | Aguarde a janela de `start-period` configurada no `Dockerfile` (`40s`) |
