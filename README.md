# Histórico de produção — Totale

Painel em Streamlit para acompanhar a produção dos técnicos ao longo do tempo. A regra central do sistema é:

> **Pontos Totais = Pontos na aba `Prod` + Pontos na aba `Gpon`**

## Funcionalidades

- Visão geral com Pontos Totais, Prod, Gpon e média por técnico.
- Página **Quantidade de O.S.** com evolução por competência e ranking dos 15 técnicos com mais ordens (cada linha válida da aba `Prod` conta como uma O.S.).
- Ticker animado com indicadores atualizados conforme os filtros na visão geral e na quantidade de O.S.
- Filtros compartilhados por período, projeto e técnico; a página de técnicos permite escolher o projeto e o perfil individual.
- Evolução mensal e ranking da equipe.
- Histórico mensal detalhado, mapa de produção e exportação em CSV.
- Perfil individual com melhor competência e comparação com a média da equipe.
- Persistência local em SQLite.
- Dados de demonstração identificados.

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

## Como executar

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```


O painel relê a base SQLite automaticamente a cada 30 segundos. Com as credenciais configuradas, o app também sincroniza a pasta de produção do Google Drive ao abrir uma nova sessão, baixando e processando arquivos em paralelo (até oito por vez); não há etapa manual de importação na interface. Arquivos processados substituem sua versão anterior, arquivos removidos da pasta saem do histórico e arquivos que não puderem ser lidos mantêm os dados locais existentes.

### Sincronização automática do Google Drive

Habilite a Google Drive API, compartilhe a pasta de produção com a conta de serviço e configure suas credenciais em `.streamlit/secrets.toml` (não versione esse arquivo):

```toml
[gcp_service_account]
type = "service_account"
project_id = "seu-projeto"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "conta-de-servico@seu-projeto.iam.gserviceaccount.com"
client_id = "..."
token_uri = "https://oauth2.googleapis.com/token"
```

Os arquivos Excel devem conter as abas `Prod` e/ou `Gpon`; arquivos CSV são lidos como `Prod` por padrão.

### Persistência

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

Os testes cobrem a fórmula de consolidação, conversão de pontos e datas, importação de Excel/CSV e prevenção de duplicidades.
