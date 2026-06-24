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
import re
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

# Versão do prompt. Mudou o prompt => cache antigo é invalidado automaticamente
# (suas sugestões foram geradas com regras diferentes e não devem ser reusadas).
PROMPT_VERSION = "v3-2026-06-22-agressivo"

# SYSTEM_PROMPT v3 — 2026-06-22
# Mudança em relação à v2: encurtamento AGRESSIVO. Alvo caiu de 20-50 para
# 15-30 chars. Mantém no máximo ~4 palavras significativas + códigos/datas/
# siglas obrigatórios. Descarta tipos-de-documento genéricos quando há um
# assunto claro. Cache v2 invalidado por PROMPT_VERSION.
SYSTEM_PROMPT = """Você é um agente de renomeação de arquivos corporativos. Sua função é reescrever nomes longos e descritivos transformando-os em nomes CURTOS, claros e padronizados. Priorize brevidade: nomes enxutos são o objetivo principal.

REGRAS:

1. SEJA AGRESSIVO NO CORTE: o nome final deve ser o MAIS CURTO possível que ainda identifique o documento sem ambiguidade. Menos é mais. Na dúvida entre duas palavras, fique com a mais informativa e descarte a outra.

2. REMOVER PALAVRAS DE CONEXÃO: descartar "de, do, da, dos, das, que, para, como, em, com, e, o, a, os, as, no, na" e similares.

3. REMOVER PALAVRAS VAZIAS E REDUNDANTES: "como fica", "informações sobre", "documento referente a", "questões relacionadas a", "termo de", "relativo a". Também descartar tipos-de-documento genéricos ("documento", "arquivo", "planilha") QUANDO o assunto já estiver claro. Manter o tipo só quando ele for a informação central (ex.: "Contrato", "NF-e").

4. PRESERVAR INFORMAÇÃO ESPECÍFICA (NUNCA DESCARTAR): nomes próprios (pessoas, empresas, clientes), datas, números de processo, CNPJ, códigos, percentuais, siglas e localização (estado/filial). Essa informação é o que distingue um arquivo de outro parecido — ela tem prioridade sobre a brevidade.

5. FORMATO DE SAÍDA: Title Case com espaços naturais entre palavras. Manter extensão original.
   - Usar espaço simples (" ") entre palavras, NUNCA underscore.
   - Capitalizar a primeira letra de cada palavra significativa.
   - Siglas permanecem em maiúsculo (KFP, AL, NF, CNPJ, RH).
   - Hífen é permitido em compostos naturais (KFP-AL, home-office) se já existir no original.
   - Não usar dois espaços seguidos. Colapsar múltiplos espaços em um único.
   - Não começar nem terminar com espaço.

6. TAMANHO ALVO: entre 15 e 30 caracteres no nome final (sem contar extensão). Mire em no máximo ~4 palavras significativas. Só ultrapasse 30 se for estritamente necessário pra preservar a informação específica da regra 4 (nome próprio + data + código, por exemplo).

7. SE EM DÚVIDA: corte mais — desde que a informação específica da regra 4 permaneça intacta.

EXEMPLOS:

EXEMPLO 1:
Original: "Como fica os acessos aos números que fazem parte da do grupo da empresa.docx"
Sugerido: "Acessos Grupo Empresa.docx"
Motivo: Cortado ao essencial; 3 palavras-chave bastam pra identificar.

EXEMPLO 2:
Original: "Contrato Joao Silva 2024 prestacao de servicos contabeis mensais.pdf"
Sugerido: "Contrato Joao Silva 2024.pdf"
Motivo: Preservado tipo central, cliente e ano; descrição do serviço cortada por brevidade.

EXEMPLO 3:
Original: "Termo de Término do Contrato de Experiência Antecipado Guilherme Pereira (RS) KFP SUL.docx"
Sugerido: "Termino Contrato Guilherme RS KFP.docx"
Motivo: Removido "Termo de", "Experiência" e "Antecipado"; preservados pessoa, estado e sigla.

EXEMPLO 4:
Original: "Email enviado pela diretoria sobre as novas regras de home office em 2024.pdf"
Sugerido: "Regras Home Office 2024.pdf"
Motivo: Cortado autor e verbo; tema + ano bastam.

EXEMPLO 5:
Original: "03 - AR NOTA FISCAL KFP AL (2018, 19, 20 e 21) com 12,5%.xlsx"
Sugerido: "AR NF KFP-AL 2018-2021 12,5%.xlsx"
Motivo: Prefixo solto removido; "Nota Fiscal" abreviada para NF; anos em intervalo; sigla, estado e percentual preservados (informação específica).

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


_VERSION_KEY = "__prompt_version__"


def load_cache() -> dict:
    """Carrega o cache. Se a versão do prompt mudou, ignora o cache inteiro
    (as sugestões antigas foram geradas com regras diferentes)."""
    try:
        with open(RENAME_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get(_VERSION_KEY) != PROMPT_VERSION:
            return {_VERSION_KEY: PROMPT_VERSION}
        return data
    except Exception:
        return {_VERSION_KEY: PROMPT_VERSION}


def save_cache(cache: dict) -> None:
    try:
        cache[_VERSION_KEY] = PROMPT_VERSION
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
# Preservação de sufixo de duplicata: " (1)", " (2)" no fim do nome.
# A regra 5 do prompt manda descartar números soltos, mas o sufixo de
# duplicata carrega INFORMAÇÃO (distingue cópias do mesmo documento). Sem
# isso, "X (1).pdf" e "X (2).pdf" colidiriam para o mesmo nome sugerido.
# ---------------------------------------------------------------------------

_DUP_SUFFIX_RE = re.compile(r"\s*\((\d+)\)\s*$")


def preservar_sufixo_duplicata(original_name: str, suggested_name: str) -> str:
    """Se o nome original termina com '(N)', garante que o sugerido também."""
    if not suggested_name:
        return suggested_name
    orig_stem, _ = os.path.splitext(original_name or "")
    m = _DUP_SUFFIX_RE.search(orig_stem)
    if not m:
        return suggested_name
    sugg_stem, sugg_ext = os.path.splitext(suggested_name)
    # Já tem algum '(N)' no fim? Não duplica.
    if _DUP_SUFFIX_RE.search(sugg_stem):
        return suggested_name
    return f"{sugg_stem.rstrip()} ({m.group(1)}){sugg_ext}"


# ---------------------------------------------------------------------------
# Chamada à IA
# ---------------------------------------------------------------------------

def suggest_one(client: genai.Client, original_name: str, max_attempts: int = 2,
                is_dir: bool = False) -> dict:
    """Pede uma sugestão de renome ao Flash-Lite. Retorna o dict do schema."""
    if is_dir:
        user_text = (
            "Reescreva este nome de PASTA (diretório, NÃO tem extensão de "
            f"arquivo — não adicione nenhuma): {original_name}"
        )
    else:
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
            nome_sugerido = (data.get("nome_sugerido") or "").strip()
            # Pasta não tem extensão: se a IA inventou uma (".docx" etc.),
            # remove. Heurística simples: tira o último sufixo .xxx curto.
            if is_dir:
                base, ext = os.path.splitext(nome_sugerido)
                if ext and len(ext) <= 6:
                    nome_sugerido = base
            # Normalização: garante campos esperados
            return {
                "nome_original": data.get("nome_original") or original_name,
                "nome_sugerido": nome_sugerido,
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
    # Candidatos da IA: nomes descritivos longos OU caminho longo (a IA encurta
    # o nome, o que encurta o caminho — correção inteligente em vez de truncar).
    # Itens compartilhados (frozen) nunca entram.
    return [
        r for r in records
        if (r.get("nome_descritivo_longo")
            or "PATH_TOO_LONG" in (r.get("detected_problems", "") or ""))
        and not r.get("is_shared")
    ]


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
            is_shared = bool(rec.get("is_shared"))
            is_dir = bool(rec.get("is_dir"))
            if not orig_name:
                return None
            # Defesa em profundidade: itens compartilhados/bloqueados NUNCA
            # devem virar candidatos. A seleção já filtra, mas reforçamos aqui.
            if is_shared:
                return None
            ck = cache_key_for_path(full_path)
            if ck and ck in cache:
                cached = cache[ck]
                with state.lock:
                    state.cache_hits += 1
                result = {
                    **cached,
                    "full_path": full_path,
                    "original_name": orig_name,
                    "is_shared": is_shared,
                    "is_dir": is_dir,
                    "status": "pendente",
                    "edited": False,
                    "from_cache": True,
                }
                result["nome_sugerido"] = preservar_sufixo_duplicata(
                    orig_name, result.get("nome_sugerido", "")
                )
                return result
            try:
                sugg = suggest_one(client, orig_name, is_dir=is_dir)
                with state.lock:
                    state.api_calls += 1
                if ck:
                    with _cache_lock:
                        cache[ck] = sugg
                result = {
                    **sugg,
                    "full_path": full_path,
                    "original_name": orig_name,
                    "is_shared": is_shared,
                    "is_dir": is_dir,
                    "status": "pendente",
                    "edited": False,
                    "from_cache": False,
                }
                result["nome_sugerido"] = preservar_sufixo_duplicata(
                    orig_name, result.get("nome_sugerido", "")
                )
                return result
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
                    "is_shared": is_shared,
                    "is_dir": is_dir,
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


# ---------------------------------------------------------------------------
# Desambiguação: resolve colisões mandando o GRUPO inteiro pra IA de uma vez,
# pedindo nomes distintos que preservem o diferenciador (mês, número, cópia).
# É o que faltava no fluxo original — a IA via cada arquivo isolado e não tinha
# como saber que um "irmão" ia receber o mesmo nome.
# ---------------------------------------------------------------------------

DISAMBIG_PROMPT = """Você recebe uma lista de arquivos da MESMA pasta que receberam nomes sugeridos IGUAIS ou quase iguais — eles colidiriam no disco. Sua tarefa é reescrever cada um com um nome CURTO e ÚNICO dentro do grupo.

REGRAS (em ordem de prioridade):

1. UNICIDADE: cada nome final DEVE ser diferente de todos os outros do grupo. Essa é a prioridade máxima — nunca repita.

2. PRESERVAR O DIFERENCIADOR: identifique o que distingue um arquivo do outro no nome ORIGINAL — mês (Janeiro, Fevereiro... ou Jan, Fev), ano, número sequencial, "Copia"/"Cópia N", "Parte N", sigla, etc. — e MANTENHA isso no nome novo. É justamente o que tinha sido cortado e causou a colisão.

3. ESTILO: Title Case com espaços, siglas em maiúsculo (KFP, NF, AL, PE), manter a extensão original. Sem underscore.

4. CURTO, mas a UNICIDADE vence a brevidade: pode passar de 30 chars se for preciso pra diferenciar.

5. Preservar nomes próprios, datas, códigos e percentuais.

Responda SEMPRE em JSON estrito, incluindo TODOS os itens recebidos:
{"itens": [{"nome_original": "...", "nome_sugerido": "..."}, ...]}
"""


def _forcar_unicidade(items: list[dict]) -> None:
    """Último recurso determinístico: se a IA ainda deixou nomes iguais no
    grupo, adiciona ' (2)', ' (3)'… preservando a extensão. Muta os items."""
    vistos: dict[str, int] = {}
    for it in items:
        nome = it.get("nome_sugerido") or ""
        chave = nome.lower()
        if chave not in vistos:
            vistos[chave] = 1
        else:
            vistos[chave] += 1
            stem, ext = os.path.splitext(nome)
            it["nome_sugerido"] = f"{stem.rstrip()} ({vistos[chave]}){ext}"


def disambiguate_group(client: genai.Client, items: list[dict],
                       max_attempts: int = 2) -> dict[str, str]:
    """Recebe os items de um grupo que colide e devolve {nome_original: novo}.

    Faz UMA chamada à IA com todos os nomes juntos. Em falha, devolve {} e o
    chamador mantém os nomes atuais (continuam marcados como colisão).
    """
    originais = [it.get("original_name", "") for it in items]
    linhas = "\n".join(f"{i+1}. {o}" for i, o in enumerate(originais))
    user_text = (
        f"Pasta: {os.path.dirname(items[0].get('full_path', ''))}\n"
        f"São {len(originais)} arquivos que colidiriam. Nomes ORIGINAIS:\n{linhas}\n\n"
        "Reescreva cada um com nome curto e ÚNICO, preservando o que os diferencia."
    )
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[user_text],
                config=types.GenerateContentConfig(
                    system_instruction=DISAMBIG_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            data = json.loads(response.text or "{}")
            mapa: dict[str, str] = {}
            for entry in data.get("itens", []):
                orig = (entry.get("nome_original") or "").strip()
                novo = (entry.get("nome_sugerido") or "").strip()
                if orig and novo:
                    mapa[orig] = novo
            if mapa:
                return mapa
        except Exception:
            if attempt < max_attempts:
                time.sleep(2 ** attempt)
    return {}


def resolve_collisions_worker(state: "SuggestState", api_key: str,
                              results: list[dict]) -> None:
    """Resolve TODOS os grupos que colidem, em paralelo. Atualiza results in
    place (nome_sugerido + flags) e re-anota colisões ao final."""
    from datetime import datetime
    try:
        annotate_collisions(results)
        # Agrupa colidentes por (pasta, nome_sugerido)
        grupos: dict[tuple, list[dict]] = {}
        for r in results:
            if r.get("collision"):
                folder = os.path.dirname(r.get("full_path", "") or "")
                name = (r.get("nome_sugerido") or "").strip().lower()
                grupos.setdefault((folder.lower(), name), []).append(r)

        with state.lock:
            state.total = len(grupos)
            state.done = 0

        client = genai.Client(api_key=api_key)

        def process(group_items: list[dict]) -> None:
            mapa = disambiguate_group(client, group_items)
            for it in group_items:
                novo = mapa.get(it.get("original_name", ""))
                if novo:
                    novo = preservar_sufixo_duplicata(it.get("original_name", ""), novo)
                    it["nome_sugerido"] = novo
                    it["edited"] = True
                    it["disambiguated"] = True
            # Garante unicidade dentro do grupo mesmo se a IA falhar
            _forcar_unicidade(group_items)
            with state.lock:
                state.done += 1
                state.api_calls += 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(process, g) for g in grupos.values()]
            for _ in as_completed(futures):
                pass

        # Re-anota: o que ainda colidir (raro) continua marcado
        annotate_collisions(results)
        with state.lock:
            state.running = False
            state.completed_at = datetime.now().isoformat()
    except Exception as e:
        with state.lock:
            state.running = False
            state.error = f"{type(e).__name__}: {e}"
            state.completed_at = datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Detector de colisão: dois arquivos da MESMA pasta com o MESMO nome sugerido.
# É o risco central de encurtar nomes parecidos — a parte que os distinguia
# pode sumir. Marcamos esses casos pra que a UI avise e a aplicação bloqueie.
# ---------------------------------------------------------------------------

def annotate_collisions(results: list[dict]) -> list[dict]:
    """Adiciona 'collision' (bool) e 'collision_count' a cada resultado.

    Colisão = mesma pasta + mesmo nome_sugerido (case-insensitive) em 2+ itens.
    Muta e devolve a própria lista.
    """
    groups: dict[tuple, list[dict]] = {}
    for r in results:
        folder = os.path.dirname(r.get("full_path", "") or "")
        name = (r.get("nome_sugerido") or "").strip().lower()
        if not name:
            r["collision"] = False
            r["collision_count"] = 0
            continue
        groups.setdefault((folder.lower(), name), []).append(r)
    for grp in groups.values():
        collide = len(grp) > 1
        for r in grp:
            r["collision"] = collide
            r["collision_count"] = len(grp) if collide else 0
    return results
