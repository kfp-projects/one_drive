# Organiza — Saneamento de Documentos para OneDrive

Ferramenta **local** que escaneia uma pasta sincronizada do OneDrive/SharePoint,
detecta problemas de conformidade (nomes/caminhos longos, caracteres proibidos,
nomes reservados) e ajuda a corrigir **renomeando com IA** sob aprovação humana,
com rollback.

## Stack

- **Backend:** Python + FastAPI (`api.py`, `main.py`, `scanner/`, `remediation/`, `analytics/`)
- **Frontend:** React + Vite + Tailwind (`web/`), buildado para `web/dist`
- **IA:** Google Gemini 2.5 Flash-Lite (sugestões de renome)

## Pré-requisitos

- Python 3.11+ com as deps de `requirements.txt`
- Node 18+ (para buildar o frontend)
- `.env` na raiz com `GEMINI_API_KEY=...`

## Como rodar

```bash
# 1. Backend (deps)
pip install -r requirements.txt

# 2. Frontend (build — gera web/dist que o FastAPI serve)
cd web && npm install && npm run build && cd ..

# 3. Servidor (serve API + UI na mesma porta)
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Abra **http://127.0.0.1:8000**.

### Desenvolvimento do frontend (hot reload)

```bash
cd web && npm run dev      # http://localhost:5173, com proxy /api -> :8000
```

## Fluxo

1. **Escanear** — varre a árvore (suporte a caminho longo `\\?\`, pula
   `rules/exclusions.json`, respeita `rules/frozen_items.json`), analisa
   conformidade OneDrive e gera relatório + analytics.
2. **Visão geral** — problemas agrupados por tipo.
3. **Renomeações IA** — candidatos de nome descritivo longo → Gemini sugere nome
   curto e único → detecção de colisão → você aprova → aplica no disco (mais
   fundo primeiro) → salva rollback em `outputs/remediation/`.
4. **Analytics** — profundidade, duplicatas, categorias, padrões.

## Configuração

- `rules/onedrive_rules.json` — limites OneDrive. **`cloud_url_overhead`** ajusta
  o limite efetivo de caminho (o OneDrive mede a URL da nuvem, ~49 chars mais
  longa que o caminho local; por isso o limite real é ~351, não 400).
- `rules/exclusions.json` — pastas (e conteúdo) totalmente fora do processo.
- `rules/frozen_items.json` — arquivos/pastas compartilhados que **nunca** são
  renomeados (aparecem como "Bloqueado").

## Rollback

Cada aplicação de renome gera `outputs/remediation/rollback_renames_*.csv`.
Ferramentas em `tools/` consolidam/reconstroem o histórico de rollback.
A limpeza do scan **nunca** apaga arquivos `rollback_*`.

## Testes

```bash
python -m unittest discover -s tests -p "test_*.py"
```
