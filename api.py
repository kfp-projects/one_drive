from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import csv
import os
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Carrega .env antes de qualquer leitura de os.getenv()
from dotenv import load_dotenv
load_dotenv()

from main import run_pipeline, execute_media_move
from config import config

app = FastAPI(title="Organiza API")

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_REPORT_RECORDS = 20000
REPORT_KEEP_FIELDS = {
    "original_name", "full_path", "extension", "is_dir", "is_shared",
    "detected_problems", "suggested_name", "risk_level", "classification",
    "action_required", "confidence_score", "naming_reason", "semantic_summary"
}
RISK_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}

class ScanRequest(BaseModel):
    path: str

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/scan")
def api_scan(request: ScanRequest):
    if not os.path.exists(request.path):
        raise HTTPException(status_code=400, detail="Path does not exist")

    try:
        results = run_pipeline(request.path)
        return {"status": "success", "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/execute")
def api_execute(request: ScanRequest):
    if config.DRY_RUN:
        raise HTTPException(status_code=400, detail="Cannot execute in DRY_RUN mode")
    try:
        execute_media_move(request.path)
        return {"status": "success", "message": "Media files moved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Classificação IA (Gemini) dos arquivos de mídia identificados
# Roda em background com progresso polled via /classify/status.
# =============================================================================

_classify_state = {
    "running": False,
    "total": 0,
    "done": 0,
    "started_at": None,
    "completed_at": None,
    "error": None,
    "results": [],  # acumula classificações
    "cache_hits": 0,
    "api_calls": 0,
}
_classify_lock = threading.Lock()

# Cache persistente de classificações (chave: nome|tamanho_em_bytes).
# Permite reuso entre execuções e entre cópias do mesmo arquivo em paths
# diferentes (ex: testar localmente uma cópia da pasta OneDrive).
CLASSIFY_CACHE_FILE = os.path.join(config.OUTPUT_DIR, "classify_cache.json")


def _load_classify_cache() -> dict:
    try:
        with open(CLASSIFY_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_classify_cache(cache: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CLASSIFY_CACHE_FILE), exist_ok=True)
        with open(CLASSIFY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _cache_key_for_path(path_str: str) -> str | None:
    try:
        p = Path(path_str)
        if not p.exists():
            return None
        return f"{p.name.lower()}|{p.stat().st_size}"
    except OSError:
        return None


def _build_media_list_from_manifest() -> list[dict]:
    """Lê o manifesto CSV mais recente e devolve só os IMAGENS que ainda existem."""
    if not os.path.isdir(config.REMEDIATION_DIR):
        return []
    manifests = sorted(
        [f for f in os.listdir(config.REMEDIATION_DIR)
         if f.startswith("media_offload_manifest_") and f.endswith(".csv")],
        key=lambda f: os.path.getctime(os.path.join(config.REMEDIATION_DIR, f)),
        reverse=True,
    )
    if not manifests:
        return []

    # Importa só aqui pra não criar dependência hard se a lib não estiver instalada
    try:
        from image_cleaner import IMAGE_EXTENSIONS
    except Exception:
        IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".heic"}

    out = []
    with open(os.path.join(config.REMEDIATION_DIR, manifests[0]), "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = (row.get("original_path") or "").strip()
            if not src or not os.path.exists(src):
                continue
            ext = os.path.splitext(src)[1].lower()
            if ext not in IMAGE_EXTENSIONS:
                continue
            out.append({
                "path": src,
                "source_folder": row.get("source_folder", ""),
            })
    return out


def _classify_worker(api_key: str, items: list[dict]) -> None:
    """Worker em thread separada — paraleliza chamadas Gemini com pool.
    Checa cache (nome|tamanho) antes de cada chamada à API."""
    try:
        from google import genai
        from image_cleaner import (
            classify_with_retry, make_thumbnail,
            detect_folder_category, THUMBNAIL_SIZE,
        )

        client = genai.Client(api_key=api_key)
        cache = _load_classify_cache()
        cache_lock = threading.Lock()

        def classify_one(item):
            try:
                path = Path(item["path"])
                if not path.exists():
                    return None

                # Tenta cache primeiro — economiza chamada de API se o mesmo
                # arquivo (por nome+tamanho) já foi classificado antes.
                ck = _cache_key_for_path(str(path))
                if ck and ck in cache:
                    cached = cache[ck]
                    with _classify_lock:
                        _classify_state["cache_hits"] += 1
                    return {
                        "path": str(path),
                        "name": path.name,
                        "decisao": cached["decisao"],
                        "confianca": cached.get("confianca", 0),
                        "motivo": cached.get("motivo", ""),
                        "categoria_detectada": cached.get("categoria_detectada", ""),
                        "source_folder": item.get("source_folder", ""),
                        "from_cache": True,
                    }

                thumb = make_thumbnail(path, THUMBNAIL_SIZE)
                if thumb is None:
                    return None
                category = detect_folder_category(path)
                data = classify_with_retry(client, thumb, str(path), category, max_attempts=2)
                result = {
                    "path": str(path),
                    "name": path.name,
                    "decisao": str(data.get("decisao", "")).upper(),
                    "confianca": int(data.get("confianca", 0)),
                    "motivo": (data.get("motivo") or "")[:100],
                    "categoria_detectada": data.get("categoria_detectada", "") or "",
                    "source_folder": item.get("source_folder", ""),
                    "from_cache": False,
                }
                with _classify_lock:
                    _classify_state["api_calls"] += 1
                if ck:
                    with cache_lock:
                        cache[ck] = {
                            "decisao": result["decisao"],
                            "confianca": result["confianca"],
                            "motivo": result["motivo"],
                            "categoria_detectada": result["categoria_detectada"],
                        }
                return result
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(classify_one, it) for it in items]
            for fut in as_completed(futures):
                result = fut.result()
                with _classify_lock:
                    if result:
                        _classify_state["results"].append(result)
                    _classify_state["done"] += 1

        # Salva cache atualizado no disco
        _save_classify_cache(cache)

        with _classify_lock:
            _classify_state["running"] = False
            _classify_state["completed_at"] = datetime.now().isoformat()
    except Exception as e:
        with _classify_lock:
            _classify_state["running"] = False
            _classify_state["error"] = f"{type(e).__name__}: {e}"
            _classify_state["completed_at"] = datetime.now().isoformat()


@app.post("/api/classify/start")
def classify_start():
    """Inicia a classificação IA dos arquivos de mídia do último scan."""
    with _classify_lock:
        if _classify_state["running"]:
            raise HTTPException(409, detail="Classificação já em andamento")

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(400, detail="GEMINI_API_KEY não configurada no .env")

    items = _build_media_list_from_manifest()
    if not items:
        raise HTTPException(400, detail="Nenhuma imagem para classificar. Rode um scan primeiro.")

    # Antes de descartar resultados em memória, salva no cache (por nome+tamanho)
    # pra reuso na próxima execução — inclui o caso "copiei a pasta pra testar".
    with _classify_lock:
        existing = list(_classify_state.get("results") or [])
    if existing:
        cache = _load_classify_cache()
        for r in existing:
            ck = _cache_key_for_path(r.get("path", ""))
            if ck:
                cache[ck] = {
                    "decisao": r["decisao"],
                    "confianca": r.get("confianca", 0),
                    "motivo": r.get("motivo", ""),
                    "categoria_detectada": r.get("categoria_detectada", ""),
                }
        _save_classify_cache(cache)

    with _classify_lock:
        _classify_state["running"] = True
        _classify_state["total"] = len(items)
        _classify_state["done"] = 0
        _classify_state["results"] = []
        _classify_state["started_at"] = datetime.now().isoformat()
        _classify_state["completed_at"] = None
        _classify_state["error"] = None
        _classify_state["cache_hits"] = 0
        _classify_state["api_calls"] = 0

    threading.Thread(
        target=_classify_worker, args=(api_key, items), daemon=True
    ).start()

    return {"status": "started", "total": len(items)}


@app.get("/api/classify/status")
def classify_status():
    """Polled pelo frontend pra atualizar a barra de progresso."""
    with _classify_lock:
        total = _classify_state["total"]
        done = _classify_state["done"]
        return {
            "running": _classify_state["running"],
            "total": total,
            "done": done,
            "percent": (done / total * 100) if total else 0,
            "error": _classify_state["error"],
            "started_at": _classify_state["started_at"],
            "completed_at": _classify_state["completed_at"],
            "cache_hits": _classify_state.get("cache_hits", 0),
            "api_calls": _classify_state.get("api_calls", 0),
        }


@app.get("/api/classify/results")
def classify_results():
    """Retorna os IRRELEVANTES já classificados (ordenados por confiança desc)."""
    with _classify_lock:
        results = list(_classify_state["results"])
        running = _classify_state["running"]

    irrelevant = sorted(
        [r for r in results if r.get("decisao") == "IRRELEVANTE"],
        key=lambda r: r.get("confianca", 0),
        reverse=True,
    )
    relevant_count = sum(1 for r in results if r.get("decisao") == "RELEVANTE")

    return {
        "running": running,
        "total_classified": len(results),
        "irrelevant_count": len(irrelevant),
        "relevant_count": relevant_count,
        "irrelevant": irrelevant,
    }


def _derive_scan_root() -> str | None:
    """Deriva o caminho raiz do último scan a partir do manifesto."""
    if not os.path.isdir(config.REMEDIATION_DIR):
        return None
    manifests = sorted(
        [f for f in os.listdir(config.REMEDIATION_DIR)
         if f.startswith("media_offload_manifest_") and f.endswith(".csv")],
        key=lambda f: os.path.getctime(os.path.join(config.REMEDIATION_DIR, f)),
        reverse=True,
    )
    if not manifests:
        return None
    latest = os.path.join(config.REMEDIATION_DIR, manifests[0])
    try:
        with open(latest, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                np = row.get("new_path", "")
                if "_ARQUIVOS_PESADOS_MEDIA" in np:
                    # new_path tem formato: <root>/_ARQUIVOS_PESADOS_MEDIA/...
                    idx = np.index("_ARQUIVOS_PESADOS_MEDIA")
                    return np[:idx].rstrip("\\/")
    except Exception:
        pass
    return None


@app.post("/api/move-irrelevant-to-image-trash")
def api_move_irrelevant_to_image_trash():
    """
    Move os arquivos classificados como IRRELEVANTE pela IA para
    <raiz_do_scan>/backup de imagens/, preservando a estrutura de subpastas.
    Operação real (não simulação). Reversível (arquivos só são MOVIDOS).
    """
    with _classify_lock:
        results = list(_classify_state["results"])

    irrelevant = [r for r in results if r.get("decisao") == "IRRELEVANTE"]
    if not irrelevant:
        raise HTTPException(400, detail="Nenhum item irrelevante para mover. Rode a classificação primeiro.")

    root_str = _derive_scan_root()
    if not root_str:
        raise HTTPException(400, detail="Não consegui derivar a raiz do scan. Rode um scan primeiro.")

    root = Path(root_str).resolve()
    if not root.exists():
        raise HTTPException(400, detail=f"Raiz do scan não existe: {root}")

    trash_dir = root / "backup de imagens"
    trash_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    skipped_missing = 0
    errors = []

    for r in irrelevant:
        src = Path(r.get("path", ""))
        if not src.exists():
            skipped_missing += 1
            continue
        try:
            rel = src.relative_to(root)
        except ValueError:
            rel = Path(src.name)
        dst = trash_dir / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                stem, suffix = dst.stem, dst.suffix
                i = 1
                while (dst.parent / f"{stem} ({i}){suffix}").exists():
                    i += 1
                dst = dst.parent / f"{stem} ({i}){suffix}"
            shutil.move(str(src), str(dst))
            moved += 1
        except Exception as e:
            errors.append(f"{src.name}: {type(e).__name__}")

    return {
        "moved": moved,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "destination": str(trash_dir),
    }


@app.post("/api/move-all-audio-to-trash")
def api_move_all_audio_to_trash():
    """
    Move TODOS os arquivos de áudio identificados no último scan para
    <raiz_do_scan>/backup de audios/, preservando a estrutura de subpastas.
    SEM análise por IA — todos vão. Operação real, reversível.
    """
    if not os.path.isdir(config.REMEDIATION_DIR):
        raise HTTPException(400, detail="Nenhum scan encontrado. Rode um scan primeiro.")

    manifests = sorted(
        [f for f in os.listdir(config.REMEDIATION_DIR)
         if f.startswith("media_offload_manifest_") and f.endswith(".csv")],
        key=lambda f: os.path.getctime(os.path.join(config.REMEDIATION_DIR, f)),
        reverse=True,
    )
    if not manifests:
        raise HTTPException(400, detail="Nenhum plano de mídia encontrado.")

    root_str = _derive_scan_root()
    if not root_str:
        raise HTTPException(400, detail="Não consegui derivar a raiz do scan.")

    root = Path(root_str).resolve()
    if not root.exists():
        raise HTTPException(400, detail=f"Raiz do scan não existe: {root}")

    trash_dir = root / "backup de audios"
    trash_dir.mkdir(parents=True, exist_ok=True)

    AUDIO_EXTS = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"}

    moved = 0
    skipped_missing = 0
    errors = []

    latest_path = os.path.join(config.REMEDIATION_DIR, manifests[0])
    with open(latest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src_str = (row.get("original_path") or "").strip()
            if not src_str:
                continue
            src = Path(src_str)
            ext = src.suffix.lower()
            if ext not in AUDIO_EXTS:
                continue
            if not src.exists():
                skipped_missing += 1
                continue
            try:
                rel = src.relative_to(root)
            except ValueError:
                rel = Path(src.name)
            dst = trash_dir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    stem, suffix = dst.stem, dst.suffix
                    i = 1
                    while (dst.parent / f"{stem} ({i}){suffix}").exists():
                        i += 1
                    dst = dst.parent / f"{stem} ({i}){suffix}"
                shutil.move(str(src), str(dst))
                moved += 1
            except Exception as e:
                errors.append(f"{src.name}: {type(e).__name__}")

    return {
        "moved": moved,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "destination": str(trash_dir),
    }


@app.post("/api/apply-renames")
def api_apply_renames():
    """
    Aplica as renomeações sugeridas pelo scanner OneDrive lendo o JSON do
    último scan. Renomeia tudo que tem sugestão diferente do original e não
    está bloqueado (is_shared). Operação real, irreversível sem rollback.
    """
    if not os.path.isdir(config.REPORTS_DIR):
        raise HTTPException(400, detail="Nenhum scan encontrado.")

    json_files = [f for f in os.listdir(config.REPORTS_DIR) if f.endswith(".json")]
    if not json_files:
        raise HTTPException(400, detail="Nenhum relatório encontrado.")

    latest = max(json_files, key=lambda x: os.path.getctime(os.path.join(config.REPORTS_DIR, x)))
    with open(os.path.join(config.REPORTS_DIR, latest), "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        records = data.get("issues", [])
    elif isinstance(data, list):
        records = data
    else:
        records = []

    renamed = 0
    skipped_blocked = 0
    skipped_unchanged = 0
    skipped_missing = 0
    errors = []

    # Ordena por profundidade descendente: renomeia arquivos antes de pastas
    # pra não invalidar caminhos de filhos quando pai é renomeado.
    records_sorted = sorted(
        records,
        key=lambda r: (r.get("full_path") or "").count(os.sep),
        reverse=True,
    )

    for record in records_sorted:
        if record.get("is_shared"):
            skipped_blocked += 1
            continue
        action = record.get("action_required", "")
        if action not in ("AUTO_RENAME", "SUGGEST_RENAME", "SUGGEST_RENAME_CAUTION", "RENAME"):
            continue

        orig_path = record.get("full_path", "")
        suggested = record.get("suggested_name", "")
        original_name = record.get("original_name", "")

        if not suggested or suggested == original_name:
            skipped_unchanged += 1
            continue

        src = Path(orig_path)
        if not src.exists():
            skipped_missing += 1
            continue

        dst = src.parent / suggested
        try:
            if dst.exists() and dst != src:
                stem = Path(suggested).stem
                ext = Path(suggested).suffix
                i = 1
                while (src.parent / f"{stem} ({i}){ext}").exists():
                    i += 1
                dst = src.parent / f"{stem} ({i}){ext}"
            os.rename(str(src), str(dst))
            renamed += 1
        except Exception as e:
            errors.append(f"{src.name}: {type(e).__name__}")

    return {
        "renamed": renamed,
        "skipped_blocked": skipped_blocked,
        "skipped_unchanged": skipped_unchanged,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
    }


@app.post("/api/move-media-to-trash")
def api_move_to_trash():
    """
    Move os arquivos de mídia do último plano para a lixeira (pasta especial).
    Operação reversível — nada é deletado. Bypassa DRY_RUN porque é segura.
    Lê o manifesto CSV gerado pelo último scan.
    """
    if not os.path.isdir(config.REMEDIATION_DIR):
        raise HTTPException(
            status_code=400,
            detail="Nenhuma varredura encontrada. Rode um scan primeiro.",
        )

    manifests = sorted(
        [
            f for f in os.listdir(config.REMEDIATION_DIR)
            if f.startswith("media_offload_manifest_") and f.endswith(".csv")
        ],
        key=lambda f: os.path.getctime(os.path.join(config.REMEDIATION_DIR, f)),
        reverse=True,
    )
    if not manifests:
        raise HTTPException(
            status_code=400,
            detail="Nenhum plano de mídia encontrado. Rode um scan primeiro.",
        )

    latest_path = os.path.join(config.REMEDIATION_DIR, manifests[0])
    moved = 0
    skipped_missing = 0
    errors = []

    with open(latest_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = (row.get("original_path") or "").strip()
            dst = (row.get("new_path") or "").strip()
            if not src or not dst:
                continue
            if not os.path.exists(src):
                skipped_missing += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # Se já existe no destino (re-execução), gera sufixo numérico
                if os.path.exists(dst):
                    base, ext = os.path.splitext(dst)
                    i = 1
                    while os.path.exists(f"{base} ({i}){ext}"):
                        i += 1
                    dst = f"{base} ({i}){ext}"
                shutil.move(src, dst)
                moved += 1
            except Exception as e:
                errors.append(f"{os.path.basename(src)}: {type(e).__name__}")

    return {
        "status": "success",
        "moved": moved,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "manifest_used": manifests[0],
    }

# =============================================================================
# Sugestões de renome para "nomes descritivos longos" via Gemini Flash-Lite
# =============================================================================

from remediation.rename_suggester import (
    SuggestState, run_worker as run_rename_worker,
    select_sample as rename_select_sample,
    load_descriptive_files_from_latest_report,
)
from remediation.onedrive_compliance import analyze as onedrive_analyze

_rename_state = SuggestState()


def _ensure_no_classify_running() -> None:
    """Bloqueio mútuo: classificação de imagens e sugestão de renome dividem
    a mesma cota da API Gemini. Roda só um por vez."""
    with _classify_lock:
        if _classify_state.get("running"):
            raise HTTPException(
                409,
                detail="Aguarde a classificação de imagens terminar antes de gerar sugestões de renomeação.",
            )


def _start_rename_worker(files: list[dict], mode: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(400, detail="GEMINI_API_KEY não configurada no .env")
    if not files:
        raise HTTPException(400, detail="Nenhum arquivo descritivo encontrado. Rode um scan primeiro.")

    with _rename_state.lock:
        if _rename_state.running:
            raise HTTPException(409, detail="Já existe uma geração de sugestões em andamento.")
        _rename_state.running = True
        _rename_state.total = len(files)
        _rename_state.done = 0
        _rename_state.results = []
        _rename_state.started_at = datetime.now().isoformat()
        _rename_state.completed_at = None
        _rename_state.error = None
        _rename_state.cache_hits = 0
        _rename_state.api_calls = 0
        _rename_state.mode = mode

    threading.Thread(
        target=run_rename_worker,
        args=(_rename_state, api_key, files, mode),
        daemon=True,
    ).start()

    return {"status": "started", "total": len(files), "mode": mode}


@app.post("/api/rename/suggest-sample")
def rename_suggest_sample():
    """Gera sugestões para uma amostra aleatória de 50 arquivos descritivos."""
    _ensure_no_classify_running()
    all_files = load_descriptive_files_from_latest_report()
    sample = rename_select_sample(all_files, n=50)
    return _start_rename_worker(sample, mode="sample")


@app.post("/api/rename/suggest-all")
def rename_suggest_all():
    """Gera sugestões para TODOS os arquivos descritivos do último scan."""
    _ensure_no_classify_running()
    all_files = load_descriptive_files_from_latest_report()
    return _start_rename_worker(all_files, mode="all")


@app.get("/api/rename/status")
def rename_status():
    return _rename_state.snapshot()


@app.get("/api/rename/results")
def rename_results():
    """Devolve todos os resultados acumulados (amostra ou lote completo)."""
    with _rename_state.lock:
        results = list(_rename_state.results)
    summary = {"pendente": 0, "aprovada": 0, "recusada": 0}
    for r in results:
        summary[r.get("status", "pendente")] = summary.get(r.get("status", "pendente"), 0) + 1
    return {
        "results": results,
        "summary": summary,
        "total": len(results),
    }


class RenameUpdate(BaseModel):
    full_path: str
    nome_sugerido: str | None = None


@app.post("/api/rename/approve")
def rename_approve(req: RenameUpdate):
    return _update_rename_status(req.full_path, "aprovada")


@app.post("/api/rename/reject")
def rename_reject(req: RenameUpdate):
    return _update_rename_status(req.full_path, "recusada")


@app.post("/api/rename/edit")
def rename_edit(req: RenameUpdate):
    """Edita manualmente o nome sugerido. Valida contra regras OneDrive."""
    new_name = (req.nome_sugerido or "").strip()
    if not new_name:
        raise HTTPException(400, detail="nome_sugerido vazio.")

    # Valida contra regras OneDrive — usa o caminho pai pra montar o caminho final
    parent_dir = os.path.dirname(req.full_path)
    candidate_path = os.path.join(parent_dir, new_name)
    check = onedrive_analyze(new_name, candidate_path)
    violations = check.get("violacoes_detectadas") or []
    if violations:
        raise HTTPException(
            400,
            detail=f"Nome editado viola regras OneDrive: {', '.join(violations)}. {check.get('motivo', '')}",
        )

    with _rename_state.lock:
        for r in _rename_state.results:
            if r.get("full_path") == req.full_path:
                r["nome_sugerido"] = new_name
                r["edited"] = True
                return {"status": "ok", "result": r}
    raise HTTPException(404, detail="Arquivo não encontrado nos resultados.")


def _update_rename_status(full_path: str, new_status: str) -> dict:
    with _rename_state.lock:
        for r in _rename_state.results:
            if r.get("full_path") == full_path:
                r["status"] = new_status
                return {"status": "ok", "result": r}
    raise HTTPException(404, detail="Arquivo não encontrado nos resultados.")


@app.post("/api/rename/apply")
def rename_apply():
    """Aplica as renomeações APROVADAS no disco e cria manifest de rollback."""
    with _rename_state.lock:
        approved = [r for r in _rename_state.results if r.get("status") == "aprovada"]

    if not approved:
        raise HTTPException(400, detail="Nenhuma sugestão aprovada para aplicar.")

    os.makedirs(config.REMEDIATION_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_path = os.path.join(config.REMEDIATION_DIR, f"rollback_renames_{timestamp}.csv")

    renamed = 0
    skipped_missing = 0
    errors: list[str] = []
    rollback_rows: list[dict] = []

    for r in approved:
        src = Path(r.get("full_path", ""))
        new_name = (r.get("nome_sugerido") or "").strip()
        if not src.exists():
            skipped_missing += 1
            continue
        if not new_name or new_name == src.name:
            continue
        dst = src.parent / new_name
        try:
            if dst.exists() and dst != src:
                stem, suffix = Path(new_name).stem, Path(new_name).suffix
                i = 1
                while (src.parent / f"{stem} ({i}){suffix}").exists():
                    i += 1
                dst = src.parent / f"{stem} ({i}){suffix}"
            os.rename(str(src), str(dst))
            renamed += 1
            rollback_rows.append({
                "original_path": str(src),
                "new_path": str(dst),
                "original_name": src.name,
                "new_name": dst.name,
            })
        except Exception as e:
            errors.append(f"{src.name}: {type(e).__name__}")

    # Manifest de rollback em CSV (simétrico ao media_offload_manifest)
    if rollback_rows:
        try:
            with open(rollback_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["original_path", "new_path", "original_name", "new_name"],
                )
                writer.writeheader()
                writer.writerows(rollback_rows)
        except Exception as e:
            errors.append(f"rollback manifest: {type(e).__name__}")

    return {
        "renamed": renamed,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "rollback_manifest": rollback_path if rollback_rows else None,
    }


@app.get("/api/reports/latest")
def get_latest_report():
    if not os.path.exists(config.REPORTS_DIR):
        return {"status": "no_reports"}

    json_files = [f for f in os.listdir(config.REPORTS_DIR) if f.endswith('.json')]
    if not json_files:
        return {"status": "no_reports"}

    latest_file = max(json_files, key=lambda x: os.path.getctime(os.path.join(config.REPORTS_DIR, x)))

    with open(os.path.join(config.REPORTS_DIR, latest_file), 'r', encoding='utf-8') as f:
        data = json.load(f)

    media_breakdown = {}
    media_files = []
    if isinstance(data, dict):
        issues = data.get("issues", [])
        media_breakdown = data.get("media_breakdown", {})
        media_files = data.get("media_files", [])
    elif isinstance(data, list):
        issues = data
    else:
        issues = []

    total = len(issues)
    issues.sort(key=lambda r: RISK_ORDER.get((r.get("risk_level") or "LOW").upper(), 5))
    capped = issues[:MAX_REPORT_RECORDS]
    slim = [{k: r[k] for k in REPORT_KEEP_FIELDS if k in r} for r in capped]

    return {
        "status": "success",
        "data": {
            "issues": slim,
            "total_count": total,
            "returned_count": len(slim),
            "truncated": total > MAX_REPORT_RECORDS,
            "media_breakdown": media_breakdown,
            "media_files": media_files
        }
    }

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")

if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")

    @app.get("/{filename:path}")
    def serve_frontend_file(filename: str):
        if filename.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        full_path = os.path.join(FRONTEND_DIR, filename)
        if os.path.isfile(full_path):
            return FileResponse(full_path)
        raise HTTPException(status_code=404, detail="Not Found")
