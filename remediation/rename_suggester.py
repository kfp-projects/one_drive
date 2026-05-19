"""
Sugestor de renomes para arquivos com "nomes descritivos longos".

Lê os arquivos marcados como nome_descritivo_longo=True no scan mais recente,
chama Gemini 2.5 Flash-Lite (sem thinking) para reescrever o nome em formato
Title_Case_Com_Underscore preservando substantivos centrais, e devolve um
dicionário estruturado por arquivo.

Princípio: a IA SUGERE; a aprovação é humana. Esse módulo nunca toca disco.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from google import genai
from google.genai import types

from config import config


GEMINI_MODEL = "gemini-2.5-flash-lite"
RENAME_CACHE_FILE = os.path.join(config.OUTPUT_DIR, "rename_cache.json")

# SYSTEM_PROMPT v2 — 2026-05-19
# Mudança em relação à v1: regra 5 agora usa ESPAÇOS naturais entre palavras
# (em vez de underscore). OneDrive/SharePoint suporta espaços e nomes ficam
# mais legíveis. Cache antigo (underscore) foi movido pra .legacy_underscore.json.
SYSTEM_PROMPT = """Você é um agente de renomeação de arquivos corporativos. Sua função é reescrever nomes de arquivos que estão em formato de frase descritiva, transformando-os em nomes curtos, claros e padronizados.

REGRAS:

1. PRESERVAR SIGNIFICADO: O nome novo deve manter o conceito central do nome original.

2. REMOVER PALAVRAS DE CONEXÃO: descartar "de, do, da, dos, das, que, para, como, em, com, e, o, a, os, as, no, na" e similares.

3. REMOVER PALAVRAS VAZIAS: "como fica", "informações sobre", "documento referente a", "questões relacionadas a" — descartar.

4. PRESERVAR INFORMAÇÃO ESPECÍFICA: nomes próprios (pessoas, empresas, clientes), datas, números de processo, códigos. NUNCA descartar.

5. FORMATO DE SAÍDA: Title Case com espaços naturais entre palavras. Manter extensão original.
   - Usar espaço simples (" ") entre palavras, NUNCA underscore.
   - Capitalizar a primeira letra de cada palavra significativa.
   - Siglas permanecem em maiúsculo (KFP, AL, NF, CNPJ, RH).
   - Hífen é permitido em compostos naturais (KFP-AL, home-office) se já existir no original.
   - Não usar dois espaços seguidos. Colapsar múltiplos espaços em um único.
   - Não começar nem terminar com espaço.

6. TAMANHO ALVO: entre 20 e 50 caracteres no nome final (sem contar extensão). Se não conseguir ficar abaixo de 50, priorizar preservação de informação sobre tamanho.

7. SE EM DÚVIDA SOBRE O QUE PRESERVAR: preservar mais informação.

EXEMPLOS:

EXEMPLO 1:
Original: "Como fica os acessos aos números que fazem parte da do grupo da empresa.docx"
Sugerido: "Acessos Numeros Grupo Empresa.docx"
Motivo: Removidas palavras de conexão e pergunta retórica; preservados os 4 substantivos centrais; espaços naturais.

EXEMPLO 2:
Original: "Contrato Joao Silva 2024 prestacao de servicos contabeis mensais.pdf"
Sugerido: "Contrato Joao Silva 2024 Servicos Contabeis.pdf"
Motivo: Preservado nome do cliente, ano e tipo de serviço; espaços mantidos como separador natural.

EXEMPLO 3:
Original: "Documento referente a questao do pagamento atrasado do cliente XPTO.docx"
Sugerido: "Pagamento Atrasado Cliente XPTO.docx"
Motivo: Removidas frases vazias; preservado nome do cliente em sigla; sem underscores.

EXEMPLO 4:
Original: "Email enviado pela diretoria sobre as novas regras de home office em 2024.pdf"
Sugerido: "Diretoria Regras Home Office 2024.pdf"
Motivo: Removido verbo e preposições; preservados autor, tema e ano.

EXEMPLO 5:
Original: "03 - AR NOTA FISCAL KFP AL (2018, 19, 20 e 21) com 12,5%.xlsx"
Sugerido: "AR Nota Fiscal KFP-AL 2018 2019 2020 2021 12,5%.xlsx"
Motivo: Removido prefixo numérico isolado ("03 -") e palavra de conexão ("com"); anos abreviados (19, 20, 21) expandidos para forma completa; sigla composta KFP-AL preservada com hífen; percentual mantido como informação relevante.

Confiança:
- Alta: nome original tem estrutura clara, substantivos identificáveis sem ambiguidade.
- Media: alguma ambiguidade sobre o que é central vs periférico.
- Baixa: nome original é muito vago ou pode ter múltiplas interpretações válidas.

Responda SEMPRE em JSON estrito no formato:
{
  "nome_original": "...",
  "nome_sugerido": "...",
  "confianca": "Alta" | "Media" | "Baixa",
  "motivo": "explicação curta de uma frase",
  "informacao_preservada": ["substantivo1", "substantivo2"],
  "informacao_descartada": ["palavra1", "palavra2"]
}
"""


# ---------------------------------------------------------------------------
# Cache (mesmo padrão do image_cleaner: chave = nome.lower()|tamanho_em_bytes)
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()


def load_cache() -> dict:
    try:
        with open(RENAME_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(RENAME_CACHE_FILE), exist_ok=True)
        with open(RENAME_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def cache_key_for_path(path_str: str) -> Optional[str]:
    try:
        p = Path(path_str)
        if not p.exists():
            return None
        return f"{p.name.lower()}|{p.stat().st_size}"
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Chamada à IA
# ---------------------------------------------------------------------------

def suggest_one(client: genai.Client, original_name: str, max_attempts: int = 2) -> dict:
    """Pede uma sugestão de renome ao Flash-Lite. Retorna o dict do schema."""
    user_text = f"Reescreva este nome de arquivo: {original_name}"
    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[user_text],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            text = response.text
            if not text:
                raise ValueError("Resposta vazia do Gemini.")
            data = json.loads(text)
            # Normalização: garante campos esperados
            return {
                "nome_original": data.get("nome_original") or original_name,
                "nome_sugerido": (data.get("nome_sugerido") or "").strip(),
                "confianca": (data.get("confianca") or "Media").strip().capitalize(),
                "motivo": (data.get("motivo") or "")[:200],
                "informacao_preservada": data.get("informacao_preservada") or [],
                "informacao_descartada": data.get("informacao_descartada") or [],
            }
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
    raise last_err  # type: ignore


# ---------------------------------------------------------------------------
# Construção da lista de candidatos a partir do scan
# ---------------------------------------------------------------------------

def load_descriptive_files_from_latest_report() -> list[dict]:
    """Lê o report JSON mais recente e devolve só os com nome_descritivo_longo=True."""
    if not os.path.isdir(config.REPORTS_DIR):
        return []
    json_files = [f for f in os.listdir(config.REPORTS_DIR) if f.endswith(".json")]
    if not json_files:
        return []
    latest = max(
        json_files,
        key=lambda x: os.path.getctime(os.path.join(config.REPORTS_DIR, x)),
    )
    with open(os.path.join(config.REPORTS_DIR, latest), "r", encoding="utf-8") as f:
        data = json.load(f)
    records = data.get("issues", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    return [r for r in records if r.get("nome_descritivo_longo")]


# ---------------------------------------------------------------------------
# Worker que processa em paralelo (com cache + cost tracking)
# ---------------------------------------------------------------------------

class SuggestState:
    """Estado mutável do worker, lido pelo endpoint /status."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.total = 0
        self.done = 0
        self.error: Optional[str] = None
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.results: list[dict] = []
        self.cache_hits = 0
        self.api_calls = 0
        self.mode = ""  # "sample" ou "all"

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "total": self.total,
                "done": self.done,
                "percent": (self.done / self.total * 100) if self.total else 0,
                "error": self.error,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "cache_hits": self.cache_hits,
                "api_calls": self.api_calls,
                "mode": self.mode,
            }


def run_worker(state: SuggestState, api_key: str, files: list[dict], mode: str) -> None:
    """Executa o lote de sugestões. Atualiza state em tempo real."""
    from datetime import datetime
    try:
        client = genai.Client(api_key=api_key)
        cache = load_cache()

        def process(rec: dict) -> Optional[dict]:
            orig_name = rec.get("original_name") or ""
            full_path = rec.get("full_path") or ""
            if not orig_name:
                return None
            ck = cache_key_for_path(full_path)
            if ck and ck in cache:
                cached = cache[ck]
                with state.lock:
                    state.cache_hits += 1
                return {
                    **cached,
                    "full_path": full_path,
                    "original_name": orig_name,
                    "status": "pendente",
                    "edited": False,
                    "from_cache": True,
                }
            try:
                sugg = suggest_one(client, orig_name)
                with state.lock:
                    state.api_calls += 1
                if ck:
                    with _cache_lock:
                        cache[ck] = sugg
                return {
                    **sugg,
                    "full_path": full_path,
                    "original_name": orig_name,
                    "status": "pendente",
                    "edited": False,
                    "from_cache": False,
                }
            except Exception as e:
                return {
                    "nome_original": orig_name,
                    "nome_sugerido": orig_name,
                    "confianca": "Baixa",
                    "motivo": f"Falha na IA: {type(e).__name__}",
                    "informacao_preservada": [],
                    "informacao_descartada": [],
                    "full_path": full_path,
                    "original_name": orig_name,
                    "status": "pendente",
                    "edited": False,
                    "from_cache": False,
                    "error": True,
                }

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(process, r) for r in files]
            for fut in as_completed(futures):
                result = fut.result()
                with state.lock:
                    if result:
                        state.results.append(result)
                    state.done += 1

        save_cache(cache)
        with state.lock:
            state.running = False
            state.completed_at = datetime.now().isoformat()
    except Exception as e:
        with state.lock:
            state.running = False
            state.error = f"{type(e).__name__}: {e}"
            state.completed_at = datetime.now().isoformat()


def select_sample(files: list[dict], n: int = 50) -> list[dict]:
    """Sorteia até n arquivos do lote."""
    if len(files) <= n:
        return list(files)
    return random.sample(files, n)
