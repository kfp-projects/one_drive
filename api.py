from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
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

from main import run_pipeline
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

_scan_state = {
    "running": False,
    "phase": None,
    "files": 0,
    "folders": 0,
    "error": None,
    "done": False,
}
_scan_lock = threading.Lock()


@app.post("/api/scan")
def api_scan(request: ScanRequest):
    if not os.path.exists(request.path):
        raise HTTPException(status_code=400, detail="Caminho não existe")
    with _scan_lock:
        if _scan_state["running"]:
            raise HTTPException(409, detail="Já existe um scan em andamento.")
        _scan_state.update({"running": True, "phase": "Iniciando", "files": 0,
                            "folders": 0, "error": None, "done": False})

    # Thread referencia o mesmo dict de progresso pra status ao vivo.
    progress = {"phase": "Iniciando", "files": 0, "folders": 0}

    def worker():
        try:
            run_pipeline(request.path, progress=progress)
            with _scan_lock:
                _scan_state.update({"running": False, "done": True, "phase": "Concluído",
                                    "files": progress.get("files", 0),
                                    "folders": progress.get("folders", 0)})
        except Exception as e:
            with _scan_lock:
                _scan_state.update({"running": False, "error": str(e), "phase": "Erro"})

    # Atualizador: copia o progress vivo pro state a cada poll (via status).
    _scan_state["_progress_ref"] = progress
    threading.Thread(target=worker, daemon=True).start()
    return {"status": "started"}


@app.get("/api/scan/status")
def api_scan_status():
    with _scan_lock:
        ref = _scan_state.get("_progress_ref")
        if _scan_state["running"] and isinstance(ref, dict):
            _scan_state["files"] = ref.get("files", 0)
            _scan_state["folders"] = ref.get("folders", 0)
            _scan_state["phase"] = ref.get("phase", _scan_state["phase"])
        return {k: v for k, v in _scan_state.items() if k != "_progress_ref"}

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
    rollback_rows = []

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
        # Caminho longo NÃO é corrigido por regra (truncaria o nome). Vai pra IA,
        # que encurta o nome com sentido. Pulamos aqui.
        if "PATH_TOO_LONG" in (record.get("detected_problems", "") or ""):
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
            rollback_rows.append({
                "original_path": str(src),
                "new_path": str(dst),
                "original_name": src.name,
                "new_name": dst.name,
            })
        except Exception as e:
            errors.append(f"{src.name}: {type(e).__name__}")

    # Manifesto de rollback (mesmo formato do rename IA; nunca apagado no scan).
    rollback_path = None
    if rollback_rows:
        os.makedirs(config.REMEDIATION_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rollback_path = os.path.join(config.REMEDIATION_DIR, f"rollback_renames_{ts}.csv")
        try:
            with open(rollback_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["original_path", "new_path", "original_name", "new_name"])
                w.writeheader()
                w.writerows(rollback_rows)
        except Exception as e:
            errors.append(f"rollback manifest: {type(e).__name__}")

    return {
        "renamed": renamed,
        "skipped_blocked": skipped_blocked,
        "skipped_unchanged": skipped_unchanged,
        "skipped_missing": skipped_missing,
        "errors_count": len(errors),
        "errors_sample": errors[:10],
        "rollback_manifest": rollback_path,
    }



# =============================================================================
# Sugestões de renome para "nomes descritivos longos" via Gemini Flash-Lite
# =============================================================================

from remediation.rename_suggester import (
    SuggestState, run_worker as run_rename_worker,
    select_sample as rename_select_sample,
    load_descriptive_files_from_latest_report,
    annotate_collisions,
    resolve_collisions_worker,
)
from remediation.onedrive_compliance import analyze as onedrive_analyze

_rename_state = SuggestState()


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
    all_files = load_descriptive_files_from_latest_report()
    sample = rename_select_sample(all_files, n=50)
    return _start_rename_worker(sample, mode="sample")


@app.post("/api/rename/suggest-all")
def rename_suggest_all():
    """Gera sugestões para TODOS os arquivos descritivos do último scan."""
    all_files = load_descriptive_files_from_latest_report()
    return _start_rename_worker(all_files, mode="all")


@app.get("/api/rename/status")
def rename_status():
    return _rename_state.snapshot()


# --- Desambiguação de colisões (passe que dá contexto de "irmãos" à IA) ------

_disambig_state = SuggestState()


@app.post("/api/rename/resolve-collisions")
def rename_resolve_collisions():
    """Reescreve os grupos que colidem com nomes distintos (IA vê o grupo todo)."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(400, detail="GEMINI_API_KEY não configurada no .env")

    with _rename_state.lock:
        results = _rename_state.results  # mesma lista — atualizada in place
    annotate_collisions(results)
    n_colisao = sum(1 for r in results if r.get("collision"))
    if n_colisao == 0:
        return {"status": "noop", "detail": "Nenhuma colisão a resolver."}

    with _disambig_state.lock:
        if _disambig_state.running:
            raise HTTPException(409, detail="Já existe uma resolução de colisões em andamento.")
        _disambig_state.running = True
        _disambig_state.total = 0
        _disambig_state.done = 0
        _disambig_state.error = None
        _disambig_state.api_calls = 0
        _disambig_state.started_at = datetime.now().isoformat()
        _disambig_state.completed_at = None

    threading.Thread(
        target=resolve_collisions_worker,
        args=(_disambig_state, api_key, results),
        daemon=True,
    ).start()
    return {"status": "started", "collisions": n_colisao}


@app.get("/api/rename/resolve-status")
def rename_resolve_status():
    snap = _disambig_state.snapshot()
    with _rename_state.lock:
        snap["remaining_collisions"] = sum(
            1 for r in _rename_state.results if r.get("collision")
        )
    return snap


@app.get("/api/rename/results")
def rename_results():
    """Devolve todos os resultados acumulados (amostra ou lote completo)."""
    with _rename_state.lock:
        results = list(_rename_state.results)
    # Marca colisões (mesma pasta + mesmo nome sugerido) pra a UI avisar.
    annotate_collisions(results)
    summary = {"pendente": 0, "aprovada": 0, "recusada": 0}
    collisions = 0
    for r in results:
        summary[r.get("status", "pendente")] = summary.get(r.get("status", "pendente"), 0) + 1
        if r.get("collision"):
            collisions += 1
    return {
        "results": results,
        "summary": summary,
        "total": len(results),
        "collisions": collisions,
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

    # ORDEM CRÍTICA: renomear do mais PROFUNDO pro mais RASO (filhos antes dos
    # pais). Se uma pasta fosse renomeada antes dos arquivos/subpastas dentro
    # dela, o caminho guardado dos filhos ficaria inválido e a renomeação deles
    # falharia. Ordenar por número de separadores no caminho (desc) garante que
    # todo conteúdo é renomeado antes do diretório que o contém.
    def _depth(r: dict) -> int:
        p = r.get("full_path", "") or ""
        return p.replace("/", "\\").count("\\")
    approved.sort(key=_depth, reverse=True)

    # Pré-cálculo de colisões: 2+ aprovados (não compartilhados) que cairiam no
    # MESMO nome final dentro da MESMA pasta. Esses NÃO são aplicados — em vez
    # de renomear pra "X (1)/X (2)" arbitrário (que apagaria a distinção
    # original), bloqueamos e devolvemos pra ajuste manual.
    target_counts: dict[tuple, int] = {}
    for r in approved:
        if r.get("is_shared"):
            continue
        src = Path(r.get("full_path", ""))
        new_name = (r.get("nome_sugerido") or "").strip()
        if not new_name:
            continue
        key = (str(src.parent).lower(), new_name.lower())
        target_counts[key] = target_counts.get(key, 0) + 1

    os.makedirs(config.REMEDIATION_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rollback_path = os.path.join(config.REMEDIATION_DIR, f"rollback_renames_{timestamp}.csv")

    renamed = 0
    skipped_missing = 0
    skipped_shared = 0
    skipped_collision = 0
    errors: list[str] = []
    collisions: list[str] = []
    rollback_rows: list[dict] = []

    for r in approved:
        # Trava de segurança: nunca renomear item compartilhado/bloqueado.
        if r.get("is_shared"):
            skipped_shared += 1
            continue
        src = Path(r.get("full_path", ""))
        new_name = (r.get("nome_sugerido") or "").strip()
        if not src.exists():
            skipped_missing += 1
            continue
        if not new_name or new_name == src.name:
            continue
        # Colisão entre aprovados: pula e reporta, não inventa sufixo.
        key = (str(src.parent).lower(), new_name.lower())
        if target_counts.get(key, 0) > 1:
            skipped_collision += 1
            collisions.append(f"{src.name} → {new_name}")
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
        "skipped_shared": skipped_shared,
        "skipped_collision": skipped_collision,
        "collisions_sample": collisions[:10],
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

@app.get("/api/analytics/latest")
def get_latest_analytics():
    """Devolve o JSON de inteligência analítica do último scan."""
    ad = config.ANALYTICS_DIR
    if not os.path.isdir(ad):
        return {"status": "no_analytics"}
    files = [f for f in os.listdir(ad) if f.startswith("analytics_") and f.endswith(".json")]
    if not files:
        return {"status": "no_analytics"}
    latest = max(files, key=lambda x: os.path.getctime(os.path.join(ad, x)))
    with open(os.path.join(ad, latest), "r", encoding="utf-8") as f:
        data = json.load(f)
    return {"status": "success", "data": data}


# =============================================================================
# Navegador de pastas + gestão de exclusões (pra escolher caminho e excluir
# pastas pela UI em vez de editar JSON na mão).
# =============================================================================

@app.get("/api/folders")
def list_folders(path: str = ""):
    """Lista subpastas de `path`. Sem path, devolve drives + pasta do usuário."""
    import string
    if not path:
        home = os.path.expanduser("~")
        starts = [{"name": "🏠 " + home, "path": home}]
        for d in string.ascii_uppercase:
            drive = f"{d}:\\"
            if os.path.isdir(drive):
                starts.append({"name": drive, "path": drive})
        return {"path": "", "parent": None, "folders": starts}

    if not os.path.isdir(path):
        raise HTTPException(400, detail="Pasta não existe")
    folders = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir():
                        folders.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
    except PermissionError:
        raise HTTPException(403, detail="Sem permissão para listar esta pasta")
    folders.sort(key=lambda x: x["name"].lower())
    parent = os.path.dirname(path.rstrip("\\/")) or None
    if parent == path:
        parent = None
    return {"path": path, "parent": parent, "folders": folders[:1000]}


def _read_exclusions() -> dict:
    try:
        with open(config.EXCLUSIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


@app.get("/api/exclusions")
def get_exclusions():
    d = _read_exclusions()
    return {
        "excluded_folder_paths": d.get("excluded_folder_paths", []),
        "excluded_folder_names": d.get("excluded_folder_names", []),
    }


class ExclusionsUpdate(BaseModel):
    excluded_folder_paths: list[str] = []
    excluded_folder_names: list[str] = []


@app.post("/api/exclusions")
def set_exclusions(req: ExclusionsUpdate):
    d = _read_exclusions()  # preserva _doc/_como_usar
    # dedup preservando ordem
    d["excluded_folder_paths"] = list(dict.fromkeys(req.excluded_folder_paths))
    d["excluded_folder_names"] = list(dict.fromkeys(req.excluded_folder_names))
    os.makedirs(os.path.dirname(config.EXCLUSIONS_PATH), exist_ok=True)
    with open(config.EXCLUSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    return {
        "status": "ok",
        "excluded_folder_paths": d["excluded_folder_paths"],
        "excluded_folder_names": d["excluded_folder_names"],
    }


_BASE = os.path.dirname(os.path.abspath(__file__))
# UI nova: build do React/Vite em web/dist.
FRONTEND_DIR = os.path.join(_BASE, "web", "dist")

_NEED_BUILD_HTML = (
    "<html><body style='font-family:system-ui;max-width:640px;margin:60px auto;"
    "padding:0 20px;color:#0f172a'><h1>Organiza</h1><p>O frontend ainda não foi "
    "buildado.</p><pre style='background:#f1f5f9;padding:14px;border-radius:8px'>"
    "cd web\nnpm install\nnpm run build</pre><p>Depois recarregue esta página."
    "</p></body></html>"
)


@app.get("/")
def serve_index():
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return HTMLResponse(_NEED_BUILD_HTML)


@app.get("/{filename:path}")
def serve_frontend_file(filename: str):
    if filename.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    full_path = os.path.join(FRONTEND_DIR, filename)
    if os.path.isfile(full_path):
        return FileResponse(full_path)
    # SPA fallback: rotas desconhecidas voltam pro index (ou aviso de build).
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.isfile(index):
        return FileResponse(index)
    return HTMLResponse(_NEED_BUILD_HTML)
