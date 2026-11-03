# Histórico de produção — Totale

Painel em Streamlit para acompanhar a produção dos técnicos ao longo do tempo. A regra central do sistema é:

> **Pontos Totais = Pontos na aba `Prod` + Pontos na aba `Gpon`**

## Funcionalidades

- Visão geral com Pontos Totais, Prod, Gpon e média por técnico.
- Evolução mensal e ranking da equipe.
- Histórico mensal detalhado, mapa de produção e exportação em CSV.
- Perfil individual com melhor competência e comparação com a média da equipe.
- Importação de vários arquivos `.xlsx`, `.xls` e `.csv`.
- Persistência local em SQLite e substituição sem duplicidade ao reenviar um arquivo.
- Dados de demonstração identificados, removidos automaticamente na primeira importação real.

## Formato das planilhas

Arquivos Excel devem ter uma aba chamada **Prod** e/ou **Gpon**. Cada aba precisa conter:

| Coluna | Obrigatória | Exemplo |
| --- | --- | --- |
| Data / Competência | Sim* | `03/11/2026` ou `11/2026` |
| Técnico | Sim | `André Santos` |
| Pontos | Sim | `125,50` |

\* Quando não houver data, é possível selecionar uma competência padrão na tela de importação ou informar ano/mês no nome do arquivo (por exemplo, `producao_2026-11.xlsx`).

O importador também reconhece variações como `Colaborador`, `Funcionário`, `Nome`, `Pontuação`, `Mês/Ano` e `Período`. Valores vazios e erros de conversão são informados por linha, sem interromper os demais registros válidos.

Para arquivos CSV, selecione na interface se a origem é **Prod** ou **Gpon**. O CSV pode usar vírgula ou ponto e vírgula e codificação UTF-8 ou Latin-1.

## Como executar

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Abra o endereço exibido pelo Streamlit. Na opção **Importar dados**, baixe a planilha modelo ou envie os arquivos baixados da [pasta de produção no Google Drive](https://drive.google.com/drive/folders/1P0ComfPrfZiq-bHfOi8fWJeAE4GAEkBq).

### Persistência

Os registros ficam em `data/producao.db`, ignorado pelo Git. Em hospedagens com disco temporário, configure um volume persistente ou envie os arquivos novamente após uma reinicialização.

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
