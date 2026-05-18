# Organiza — Manual de Contexto para Modelos Futuros

> Documento de handoff. Se você é um modelo (Claude, Gemini, GPT, qualquer um)
> herdando esse codebase, leia até o fim antes de mexer em qualquer coisa. As
> decisões aqui foram tomadas em iterações com o usuário e várias delas têm
> rationale que não fica óbvio só lendo código.

---

## 1. TL;DR (30 segundos)

**Organiza** é uma ferramenta híbrida web + CLI pra saneamento de uma pasta
OneDrive corporativa (KFP Distribuidora Ltda, distribuidora de combustível
no Nordeste do Brasil).

Faz três coisas, todas com **operações reversíveis** (move, nunca deleta):

1. **Scan de conformidade OneDrive** → varre milhares de arquivos, identifica
   nomes que violam regras oficiais OneDrive/SharePoint (regras A-F definidas
   abaixo), sugere correções determinísticas, aplica renomeações em lote.
2. **Classificação de imagens via IA** → manda thumbnails das imagens
   identificadas pra Gemini 2.5 Flash com thinking, recebe RELEVANTE/IRRELEVANTE,
   move só as IRRELEVANTES pra uma pasta de backup na raiz.
3. **Backup de áudios** → move todos os áudios identificados pra outra pasta
   de backup, sem IA (todo áudio numa pasta corporativa é provavelmente
   gravação de reunião/whatsapp pessoal — bonificação assumida).

Backend: Python 3.13 + FastAPI. Frontend: HTML/CSS/JS vanilla (sem framework).
CLI auxiliar: `image_cleaner.py`. Armazenamento: filesystem local + JSONs em
`outputs/`.

---

## 2. Cliente e Contexto de Negócio

**Cliente:** KFP Distribuidora Ltda — distribuidora de combustível, Nordeste do
Brasil. Parceiros mencionados em prompts: Petrobras, Plus, Ipiranga, Shell, BR.
Documentos operacionais típicos: NF-e de combustível, alvarás ANP, contratos
de revenda, fotos de frota (caminhão-tanque, bomba, posto, tanque), prints de
ERP/SAP.

**Pasta-alvo principal:** `E:\OneDrive - Kfp Distribuidora Ltda\` (~175k arquivos
no scan inicial, ~1612 imagens identificadas como mídia corporativa pelo critério
de extensão+pasta-fonte).

**Pastas "compartilhadas" / frozen:** lista em [rules/frozen_items.json](rules/frozen_items.json).
Pastas como `Comercial`, `Diretoria`, `RH`, `Filiais`, etc. NÃO podem ter o
nome alterado (são acessadas por múltiplos usuários, mudar nome quebra links e
permissões). Arquivos **dentro** delas e subpastas internas **podem** ser
renomeados normalmente — só o nome da raiz frozen é protegido.

---

## 3. Arquitetura

```
                          ┌─────────────────────┐
                          │  Frontend (vanilla) │
                          │  index.html + app.js│
                          └──────────┬──────────┘
                                     │ HTTP/JSON
                                     ▼
                          ┌─────────────────────┐
                          │   FastAPI (api.py)  │  ◄── porta 8000
                          └─────┬──────────┬────┘
                                │          │
                  ┌─────────────┘          └──────────────┐
                  ▼                                       ▼
       ┌──────────────────┐                  ┌───────────────────────┐
       │  Scanner Module  │                  │  Remediação / Compli- │
       │  scanner/*.py    │                  │  ance / Move logic    │
       │                  │                  │  remediation/*.py     │
       │  - walk filesys  │                  │                       │
       │  - gera manifest │                  │  - onedrive_compliance│
       │  - delega regra  │                  │  - apply-renames      │
       └────────┬─────────┘                  │  - move-*-to-trash    │
                │                            └─────────┬─────────────┘
                ▼                                      │
       ┌─────────────────┐                             │
       │ outputs/        │ ◄───── lê                   │
       │ - reports/*.json│        ┌────────────────────┘
       │ - reports/*.csv │        │
       │ - remediation/  │        ▼
       │   manifest_*.csv│   ┌──────────────────────┐
       │ - analytics/    │   │  Gemini 2.5 Flash    │
       │ - classify_     │◄──┤  (chamado via worker │
       │   cache.json    │   │   em background)     │
       └─────────────────┘   └──────────────────────┘
```

**CLI standalone** `image_cleaner.py` faz o mesmo fluxo de classificação IA
mas sem servidor — útil pra rodar em qualquer máquina sem subir o backend.
Compartilha funções (`make_thumbnail`, `classify_with_retry`, `detect_folder_category`,
`SYSTEM_PROMPT`) com o backend via import — **única fonte de verdade**.

---

## 4. Mapa de Arquivos

```
One_drive/
├── api.py                    # FastAPI + endpoints + worker IA
├── main.py                   # CLI entry (run_pipeline)
├── config.py                 # constantes (limites OneDrive, paths)
├── image_cleaner.py          # CLI standalone + funções compartilhadas + SYSTEM_PROMPT
├── requirements.txt
├── .env / .env.example       # GEMINI_API_KEY, ROOT_FOLDER_PATH, etc.
├── README.md                 # doc original do projeto (pt-BR, voltado pra usuário leigo)
├── Gemini.md                 # ESSE documento — handoff pra modelos
│
├── scanner/                  # camada de varredura
│   ├── scanner.py            # ScannerService — walk + análise por arquivo
│   ├── pipeline.py           # delegador fino p/ remediation.onedrive_compliance
│   └── classifier.py         # classificação estrutural (CACHE/TEMPORARY/etc.)
│
├── remediation/              # camada de regras e correção
│   ├── onedrive_compliance.py # ★ regras A-F, função analyze() central
│   ├── media_manager.py      # plano de offload de mídia (legado, ainda usado)
│   ├── batch_planner.py
│   ├── rollback_manager.py
│   └── rename_simulator.py
│
├── services/
│   └── semantic_naming_engine.py # legado de naming, hoje atalho pro compliance
│
├── analytics/                # métricas e dashboards (não alterado pela reforma)
│   └── reports_dashboard.py
│
├── frontend/
│   ├── index.html            # SPA single-file
│   ├── app.js                # toda lógica do client
│   └── styles.css
│
├── rules/                    # ★ regras versionadas em JSON
│   ├── onedrive_rules.json   # limites 255/400, chars proibidos, reserved, ext composta
│   ├── frozen_items.json     # pastas/arquivos compartilhados não-alteráveis
│   ├── corporate_naming_style.json  # estilo legado (não usado após reforma)
│   ├── abbreviations.json
│   ├── forbidden_chars.json
│   ├── reserved_words.json
│   └── ignored_paths.json
│
├── tests/
│   └── test_onedrive_compliance.py  # 12 testes cobrindo A-F
│
├── utils/
│   ├── logger.py
│   └── cleanup.py
│
└── outputs/                  # gerado em runtime
    ├── reports/              # JSON+CSV do scan
    ├── remediation/          # planos de movimentação (manifest, batches, rollback)
    ├── analytics/            # métricas em JSON+TXT+CSV
    └── classify_cache.json   # cache nome+tamanho → decisão IA (persistente)
```

**Arquivos com gravidade alta** (cuidado ao mexer):
- `remediation/onedrive_compliance.py` — coração das regras
- `image_cleaner.py` — contém `SYSTEM_PROMPT` (fonte única, ver §8)
- `scanner/scanner.py` — só edita se souber o que está fazendo (eu já bend
  the rule do usuário aqui mais de uma vez; faça o mesmo só se justificável)
- `config.py` — mudanças afetam tudo

---

## 5. Endpoints HTTP

Inventário completo de [api.py](api.py):

| Método | Path                                   | O que faz                                                          |
|--------|----------------------------------------|--------------------------------------------------------------------|
| GET    | `/api/health`                          | Smoke test                                                         |
| POST   | `/api/scan`                            | Roda scan completo (síncrono, pode demorar minutos)                |
| POST   | `/api/execute`                         | **Legado** — move média via DRY_RUN (ainda existe, mas frontend não chama mais) |
| POST   | `/api/classify/start`                  | Inicia worker IA em background (4 threads paralelas)               |
| GET    | `/api/classify/status`                 | Polled pelo frontend, retorna `{running, done, total, cache_hits, api_calls}` |
| GET    | `/api/classify/results`                | Retorna lista IRRELEVANTES ordenadas por confiança                 |
| POST   | `/api/move-irrelevant-to-image-trash`  | Move IRRELEVANTES pra `<root>/backup de imagens/`                  |
| POST   | `/api/move-all-audio-to-trash`         | Move TODOS áudios pra `<root>/backup de audios/`                   |
| POST   | `/api/apply-renames`                   | Aplica renomeações OneDrive do último relatório                    |
| POST   | `/api/move-media-to-trash`             | **Legado** — move via manifest pra `_ARQUIVOS_PESADOS_MEDIA`       |
| GET    | `/api/reports/latest`                  | Retorna até 20k registros do último relatório (truncado por risco) |
| GET    | `/`                                    | Serve `index.html`                                                 |
| GET    | `/{filename:path}`                     | Serve assets estáticos do frontend                                 |

**Middleware:** `GZipMiddleware` (min 1000 bytes) — relatórios JSON podem
ter ~150MB sem compressão, comprimem ~10x.

---

## 6. Workflows do Usuário

### Workflow 1 — Conformidade OneDrive (renomear arquivos)

1. Dashboard → digita caminho → "Iniciar Scan"
2. Backend roda `ScannerService.scan_directory()`, gera JSON+CSV em
   `outputs/reports/`
3. Frontend carrega o relatório em "Arquivos Escaneados" (paginado, 30 pastas
   por vez)
4. Usuário revisa sugestões, opcionalmente filtra por tipo de violação
5. Botão **"Aplicar Renomeações"** → `POST /api/apply-renames` → backend
   renomeia em ordem (descendente por profundidade — filhos antes de pais)

### Workflow 2 — Mover imagens irrelevantes (com IA)

1. Após scan, aba **Remediação** → botão **"Mover Imagens (IA filtra)"**
2. Confirmação com estimativa de tempo/custo
3. Modal de progresso abre, polled a cada 2s
4. Backend dispara worker de 4 threads paralelas. Cada uma:
   - Verifica cache (`outputs/classify_cache.json` por `filename|size`)
   - Cache hit → reusa decisão (zero custo)
   - Cache miss → gera thumbnail 512×512 JPEG → chama Gemini → salva cache
5. Quando termina, abre modal com lista filtrada (só IRRELEVANTES)
6. Confirma → `POST /api/move-irrelevant-to-image-trash` → move
   preservando estrutura

### Workflow 3 — Backup de áudios (sem IA)

1. Aba Remediação → botão **"Mover TODOS os Áudios"**
2. Modal mostra lista de todos os áudios identificados
3. Confirma → `POST /api/move-all-audio-to-trash` → move todos pra
   `<root>/backup de audios/`

### Workflow 4 — Reverter movimentação (CLI)

```bash
python image_cleaner.py --restore
```
Lê o último relatório em `_image_cleanup_reports/`, devolve cada arquivo
pra origem. Funciona só pro CLI `image_cleaner.py`, não pros endpoints
web. (Pro web, a "reversão" é manual: arrasta do `backup de imagens/` de volta.)

---

## 7. Regras OneDrive — A até F

Fonte única: [rules/onedrive_rules.json](rules/onedrive_rules.json).
Lógica em [remediation/onedrive_compliance.py](remediation/onedrive_compliance.py),
função `analyze(name, full_path)`.

| Código | Violação                       | Limite/Padrão                                | Correção                                     | Risco/Confiança |
|--------|--------------------------------|----------------------------------------------|----------------------------------------------|-----------------|
| **A**  | Nome > 255 chars               | 255 (margem segurança = 5)                   | Trunca preservando começo + extensão         | Médio / 95%     |
| **B**  | Caminho > 400 chars            | 400 (margem segurança = 5)                   | Encurta nome; se < 10 chars úteis, manter    | Médio ou Alto / 95% ou 80% |
| **C**  | Caractere proibido             | `" * : < > ? / \ \| #`                       | Substitui por `_`, colapsa consecutivos      | Baixo / 100%    |
| **D**  | Nome reservado                 | `CON, PRN, AUX, NUL, COM0-9, LPT0-9, ~$*, _vti_*, desktop.ini, .lock` | Adiciona sufixo `_arquivo` antes da extensão | Baixo / 100%    |
| **E**  | Borda inválida                 | Começa/termina com espaço, ponto ou til      | `strip(' .~')` no nome base                  | Baixo / 100%    |
| **F**  | Dupla extensão suspeita        | `arquivo.xl.xlsx`, `foto.jpg.exe` — 2 últimos segmentos curtos alfanuméricos | Remove extensão interna (preserva externa)   | Baixo / 100%    |

**Whitelist da regra F:** `.tar.gz`, `.tar.bz2`, `.tar.xz`, `.tar.zst` —
extensões compostas legítimas.

**Ordem de correção:** **C → F → D → E → A → B**. F vem antes de D porque
remover extensão interna pode revelar nome reservado (ex: `CON.xl.txt` →
`CON.txt` → vira `CON_arquivo.txt`).

**Ação resultante:**
- Risco Baixo + 100% confiança → `AUTO_RENAME` ("Renomear Automaticamente")
- Risco Médio → `SUGGEST_RENAME`
- Risco Alto → `SUGGEST_RENAME_CAUTION`
- Sem violação → `NONE` (frontend mostra "Manter Original" no popover)
- Item `is_shared` → `BLOCKED` (ignora qualquer regra, retorna nome original)

**Detecções que foram REMOVIDAS na reforma** (anteriormente faziam parte do scanner):
- `EXCESSIVE_DEPTH` — não é regra OneDrive, virou só estat informativo
- `POSSIBLE_DUPLICATE` — não é regra OneDrive
- `SUBOPTIMAL_NAME` (cosmético) — explicitamente removido por pedido do usuário
- `NAME_COLLISION_RESOLVED` — virou efeito colateral do shutil.move com sufixo

---

## 8. Classificação por IA — SYSTEM_PROMPT v2

**Arquivo:** [image_cleaner.py:82-148](image_cleaner.py#L82). Comentário no
topo declara `v2 — 2026-05-14`.

**Modelo:** `gemini-2.5-flash` (via SDK `google-genai`, NÃO o legado
`google-generativeai`).

**Config:**
- `thinking_budget=-1` (dinâmico — modelo decide quanto pensar por imagem)
- `temperature=0.1` (determinístico mas evita loop em multimodal)
- `response_mime_type="application/json"` (modo JSON forçado)

**Estrutura do prompt (ordem em que o modelo lê):**

1. **Papel + KFP** — auditor digital de distribuidora de combustível
2. **Protocolo de Reconsideração** — se confiança < 75%, listar 2 sinais
   pró-RELEVANTE + 2 pró-IRRELEVANTE, pesar evidência concreta, se ainda
   < 75% → classificar RELEVANTE
3. **Contexto KFP** — ANP, Petrobras/Plus/Ipiranga/Shell/BR, frota tanque
4. **Listas RELEVANTE/IRRELEVANTE**
5. **5 Regras Duras** — selfie→IRR, CNPJ/NF→REL, frota→REL, ERP→REL, festa→IRR
6. **Sinais de Conteúdo Pessoal** — 11 sinais a procurar ATIVAMENTE
7. **Regra de Uso (a)/(b)** — single signal forte OR combinação de 2+ sutis
8. **6 Exemplos few-shot** com regra que dispara cada
9. **Precedência:** regras + exemplos > caminho da pasta
10. **Esclarecimento sobre viés:** não use "em dúvida → RELEVANTE" como atalho
11. **Justificativa obrigatória com evidência concreta** (motivo PROIBIDO vs EXIGIDO)
12. **Schema JSON** de saída

**Schema da resposta:**
```json
{
  "decisao": "RELEVANTE" | "IRRELEVANTE",
  "confianca": <0-100>,
  "motivo": "<até 100 chars, com evidência visual citada se IRRELEVANTE>",
  "categoria_detectada": "<descrição curta do conteúdo>"
}
```

**Cache de classificação:** chave `filename.lower()|size_em_bytes`. Persistido em
`outputs/classify_cache.json`. Atravessa restarts do uvicorn. Funciona pra
cópias do mesmo arquivo em paths diferentes (use case: testar em cópia local
sem repagar Gemini).

**Custo estimado (1612 imagens):** ~$4-6 USD com thinking ativo. Cache hit
posterior = grátis.

---

## 9. Decisões de Design — Log de Rejeições

Esse projeto foi iterado em ciclos com o usuário. Várias coisas foram
propostas e rejeitadas. Documento aqui pra você não reinventá-las:

### REJEITADO: Sugestões cosméticas de nome

A versão pré-reforma sugeria title case, removia stop words, abreviava palavras
("Documento de Compensação" → "Doc Compensacao"). O usuário **rejeitou
explicitamente** com a especificação:

> "Se um arquivo está em conformidade com as regras do OneDrive/SharePoint,
> NÃO TOCAR. O sistema só sugere renomeação quando o arquivo viola uma regra
> técnica concreta. Padronização estética não é objetivo deste módulo."

Resultado: arquivos como `CONTROLE SUPERMERCADO EXTRA.xl.xlsx` (que ANTES
viraria `Controle Supermercado Extra.xl.xlsx`) hoje só viram alvo se
violarem regra concreta — e nesse caso só pela regra F (dupla extensão).

**Se você for tentado a adicionar transformações cosméticas, NÃO ADICIONE.**
O usuário vai te corrigir.

### REJEITADO: Detecção de double-extension via heurística "letra+letra"

Cogitei detectar duplas extensões via padrão genérico tipo "ponto seguido de 1-2
caracteres". Rejeitado por gerar muitos falsos positivos. A escolha final foi
"2 últimos segmentos curtos alfanuméricos" com whitelist explícita pra
`.tar.gz` e família.

### REJEITADO: Detectar "all caps" como violação

O usuário foi explícito: "vamos adicionar apenas essa regra F, a outra não".
ALL CAPS é cosmético, OneDrive aceita, não viola nada técnico.

### REJEITADO: Segundo pass com Gemini Pro pra casos de baixa confiança

Cogitei rotear imagens com confiança 50-85% pro modelo Pro. Rejeitado pelo
usuário (e com razão): calibração de confiança em LLMs multimodais é
notoriamente ruim. Confiança 90% pode estar tão errada quanto 70%. O critério
correto pra segundo pass seria observação empírica de padrões de falha, não
banda de confiança numérica.

### REJEITADO: Aumentar thumbnail pra 768 ou 1024

Cogitei justificando "documentos precisam de mais resolução pra IA ler texto".
O usuário rebateu: o que importa é o sinal binário "tem ou não tem texto
denso" — que aparece em 512×512. Ler conteúdo do texto não é necessário pra
decidir relevância. **Mantido em 512×512.**

### REJEITADO: Viés duplicado "<60% → RELEVANTE" + "em dúvida → RELEVANTE"

Quando propus esses dois juntos, o usuário apontou que empilhar bias duas
vezes mata o módulo (quase nada vira IRRELEVANTE). Resultado: o prompt v2
tem só **um** caminho de viés conservador — via Protocolo de Reconsideração
< 75% (regra ativa, não default passivo).

### REJEITADO: Renomear corrige profundidade excessiva

O usuário perguntou por que 4792 "Profundidade Excessiva" ainda apareciam
após aplicar renomeações. Resposta: depth da estrutura ≠ length do nome.
Renomear muda nome, não muda quantos níveis de pasta o arquivo está. Esse
métrico hoje é só informativo, não acionável.

---

## 10. Configuração

### `.env` (não commitado, fonte: `.env.example`)

| Var                       | Default                                | Uso                                            |
|---------------------------|----------------------------------------|------------------------------------------------|
| `GEMINI_API_KEY`          | -                                      | https://aistudio.google.com/apikey             |
| `ROOT_FOLDER_PATH`        | -                                      | Pasta-alvo (usado pelo CLI image_cleaner)      |
| `QUARANTINE_FOLDER`       | `./_QUARENTENA_IMAGENS`                 | Destino do CLI image_cleaner                   |
| `IMAGE_EXTENSIONS`        | `.jpg,.jpeg,.png,.gif,.bmp,.webp,.tiff,.heic` | Extensões consideradas imagem            |
| `THUMBNAIL_SIZE`          | `512`                                  | Tamanho do thumbnail enviado pro Gemini        |
| `AUTO_MOVE_THRESHOLD`     | `90`                                   | Conf. mínima pro modo `--auto` do CLI          |
| `RUN_MODE`                | `dry_run`                              | Modo default do CLI (dry_run\|review\|auto)    |
| `MIN_FILE_SIZE_BYTES`     | `8192`                                 | Abaixo disso, CLI pula (assume ícone/sprite)   |

### [config.py](config.py)

Limites OneDrive, paths de output, listas de extensões ignoradas e
**pastas ignoradas** (importante — inclui as pastas de backup criadas pelo
próprio sistema pra não re-varrer o que já foi movido).

### Pastas ignoradas pelo scanner

```python
IGNORED_FOLDERS = {
    '.git', 'node_modules', '__pycache__', '.venv', 'venv',
    '_ARQUIVOS_PESADOS_MEDIA',  # legado (media offload antigo)
    'backup de imagens',         # destino das IRRELEVANTES da IA
    'backup de audios',          # destino dos áudios
}
```

Comparação **case-insensitive** — pega `Backup de Imagens`, `BACKUP...`, etc.

---

## 11. Como Rodar

**Instalar deps:**
```bash
pip install -r requirements.txt
# pillow-heif é opcional (falha de build no Windows é OK)
```

**Subir backend:**
```bash
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```
Abre frontend em http://127.0.0.1:8000/ (FastAPI serve index.html).

**CLI standalone (imagens):**
```bash
python image_cleaner.py --dry-run    # só lista, com confirmação simulada
python image_cleaner.py --review     # confirma e move
python image_cleaner.py --auto       # automático acima do threshold
python image_cleaner.py --restore    # devolve do quarentine pro original
```

**Rodar testes:**
```bash
python -m unittest tests.test_onedrive_compliance -v
```
12 testes cobrindo regras A-F. Devem todos passar.

---

## 12. Gotchas e Coisas Não-Óbvias

### O usuário tem opinião forte sobre "fazer só o que foi pedido"

- Não adicione features que ele não pediu
- Não refatore "preventivamente" 
- Não adicione comentários desnecessários (regra mantida em todo o codebase)
- Se ele rejeitou algo no passado (ver §9), não traga de volta sem justificativa nova
- Ele aprecia **pushback técnico fundamentado**, não bajulação. Se ele propõe
  algo questionável, debata. Se for bom mesmo, ele aceita

### A linguagem é português brasileiro casual

Mensagens de erro, prompts, motivos, banners — tudo em pt-BR. Mantenha tom
direto e informal nas respostas ao usuário (ele responde nesse tom). Não use
"caro usuário" ou linguagem corporativa. Não use emojis a menos que ele use
primeiro.

### Estado do classifier vive em memória do uvicorn

`_classify_state` em [api.py](api.py) é um dict global protegido por `threading.Lock`.
Restart do uvicorn = estado perdido. O **cache em disco** (`outputs/classify_cache.json`)
sobrevive — então re-execuções aproveitam decisões anteriores via filename+size.

### A análise estática do IDE não acha módulos do scanner

Mensagem comum:
```
Cannot find module `scanner.pipeline`
```
**False positive.** O runtime funciona porque Python adiciona cwd ao path.
Ignore esses warnings.

### Frontend usa URL relativa OU absoluta dependendo de onde foi servido

`app.js` linha 1: `const API_BASE = (location.protocol === 'http:' || 'https:') ? '' : 'http://127.0.0.1:8000'`.
Permite abrir `index.html` direto via `file://` pra desenvolvimento, mas
preferível abrir via `http://127.0.0.1:8000/` (sem CORS, mesma origem).

### Pastas frozen NÃO propagam pra filhos

`is_shared` é marcado por **item**. `Comercial/` é frozen mas `Comercial/relatorio.pdf`
NÃO é. Foi decisão explícita do usuário.

### Cache de classificação é por nome+tamanho, NÃO por path

Funciona em cópias do mesmo arquivo em paths diferentes (use case real:
testar localmente em `C:\test\` uma cópia do `E:\OneDrive\`).

### Performance do frontend com relatórios grandes

Já otimizado pra ~50k registros. Truques aplicados:
- Backend trunca relatório em 20k items ordenados por risco (`api.py:get_latest_report`)
- GZip middleware (~10x compressão)
- Pré-indexação no JS após load (Sets pra busca O(1))
- Paginação por grupos de pasta (30 por vez + "Mostrar mais")
- Conteúdo das pastas é renderizado **lazy** ao expandir
- Toggle é DOM-local (não re-renderiza tudo)
- Delegação de eventos no document (1 listener vs N por célula)
- Filtros com debounce 150ms

Se você for adicionar features que afetam a lista grande, **pense na performance
antes** — o usuário tem um relatório real de 175k arquivos.

### O modo simulação foi removido do frontend, não do backend

Os endpoints `/api/move-*-to-trash` movem de verdade. O frontend antigo
tinha modo "simulação" mas hoje tudo é real (com confirmação dupla via
`confirm()` antes do POST).

---

## 13. Estado Atual (snapshot)

- ✅ Scan OneDrive compliance funcionando (regras A-F)
- ✅ Renomeação em lote funcionando (botão "Aplicar Renomeações")
- ✅ Classificação IA Gemini funcionando + cache persistente
- ✅ Mover imagens irrelevantes pra `backup de imagens` (real, não simulado)
- ✅ Mover todos os áudios pra `backup de audios` (real)
- ✅ Restore via CLI image_cleaner
- ✅ 12 testes passando em `tests/test_onedrive_compliance.py`
- ✅ Pastas backup ignoradas em scans subsequentes
- ✅ Frozen items respeitados (não renomeados)
- ✅ SYSTEM_PROMPT v2 com protocolo de reconsideração

**Coisas que NÃO existem (intencionalmente):**
- ❌ Move automático sem confirmação humana
- ❌ Sugestões cosméticas (title case, abreviações)
- ❌ Detecção de "all caps" como violação
- ❌ Restore via web UI (só CLI)
- ❌ Histórico de operações em DB (filesystem é o histórico)
- ❌ Auth / multi-user (single-user assumido)

---

## 14. Instruções pra Modelos Futuros

### Antes de mexer em algo

1. **Leia este doc inteiro.** Pelo menos uma vez.
2. **Leia o arquivo que você vai editar.** Não confie em memória/grep
   superficial.
3. **Roda os testes existentes** antes de qualquer mudança grande:
   `python -m unittest tests.test_onedrive_compliance -v`

### Quando o usuário propõe algo

1. **Pense antes de aceitar.** Ele aprecia pushback fundamentado.
2. **Não bajule.** Se a ideia é boa, diga concretamente o que é bom. Se tem
   problema, diga concretamente o problema. Sugestões alternativas se houver.
3. **Cite §9 desse doc** quando reconhecer uma rejeição antiga sendo
   re-proposta. Não force a barra — pode ser que o contexto mudou.
4. **Confirme antes de aplicar** mudanças não-triviais. Mostre o diff
   conceitual primeiro.

### Quando você for editar

1. **Mudanças cirúrgicas, não rewrites.** Não troque tudo "pra ficar mais limpo".
2. **Mantenha pt-BR** em strings de UI, motivos, banners.
3. **Não adicione comentários explicando o que o código faz.** Só explique
   WHY se não for óbvio.
4. **Atualize testes** se mudar regras de compliance.
5. **Atualize ESTE documento** se mudar arquitetura, endpoints novos,
   decisões que outros modelos precisarão saber.

### Quando você for mexer no SYSTEM_PROMPT

1. Incrementa a versão no comentário do topo (v2 → v3 → ...).
2. Lista as mudanças no comentário.
3. Aplica os critérios de validação se possível (taxa IRRELEVANTE ±5pp
   após mudança — sinal de calibração ruim).
4. **Não adicione viés que se acumule.** Releia §9 — "Viés Duplicado".

### Quando você for mexer em regras OneDrive

1. Edita [rules/onedrive_rules.json](rules/onedrive_rules.json) primeiro
   (fonte única).
2. Atualiza [remediation/onedrive_compliance.py](remediation/onedrive_compliance.py)
   se for adicionar nova regra (`_detect_violations`, `_fix_*`, `_motivo`).
3. Adiciona ao mapping em [scanner/pipeline.py](scanner/pipeline.py)
   `VIOLATION_CODES`.
4. Adiciona stat counter em [scanner/scanner.py](scanner/scanner.py).
5. Atualiza filter dropdown em [frontend/index.html](frontend/index.html).
6. Atualiza `parseViolations` + `issueLabel` em [frontend/app.js](frontend/app.js).
7. Adiciona badge CSS em [frontend/styles.css](frontend/styles.css).
8. Adiciona test case em [tests/test_onedrive_compliance.py](tests/test_onedrive_compliance.py).
9. **Roda os testes.** Se passar, deploy. Se falhar, conserta antes.

### Quando algo der errado

1. Backend não sobe → confere `python -c "import ast; ast.parse(open('api.py').read())"`
2. Frontend não atualiza → Ctrl+F5 limpa cache do JS
3. Classificação trava → confere `_classify_state` via `GET /api/classify/status`
4. Arquivo "sumiu" → procura em `<root>/backup de imagens/` ou `<root>/backup de audios/`
5. Renomeação inesperada → confere o último JSON em `outputs/reports/` pelo nome original

---

## 15. Versão Deste Documento

- **v1 — 2026-05-14:** documento inicial criado por Claude (Anthropic) durante
  sessão de iteração com o usuário. Reflete estado do projeto após reforma de
  conformidade OneDrive + IA classification + Mover endpoints reais.

Se você (modelo futuro) atualizar este doc, incrementa a versão e adiciona
nota do que mudou.
