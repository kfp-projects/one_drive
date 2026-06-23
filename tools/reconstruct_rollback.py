"""
Reconstrói um rollback a partir do rename_cache.json (que sobreviveu ao
cleanup) + varredura do disco atual.

O cache guarda, por arquivo: nome_original, nome_sugerido e o tamanho (na
chave 'nome.lower()|tamanho'). Como renomear NÃO muda o tamanho, casamos os
arquivos atuais (nome_sugerido + tamanho) de volta ao nome_original.

Cobre as renomeações simples. NÃO cobre as desambiguadas (nome final não está
no cache) — essas ficam de fora e são listadas no fim.

Saída: outputs/remediation/rollback_reconstructed_<ts>.csv
  current_path, original_name, suggested_name

Uso: python tools/reconstruct_rollback.py
"""
import os, csv, json, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

ROOT = r"C:\Users\kfpno\OneDrive - Kfp Distribuidora Ltda"
CACHE = os.path.join(config.OUTPUT_DIR, "rename_cache.json")


def load_exclusions():
    try:
        d = json.load(open(config.EXCLUSIONS_PATH, encoding="utf-8"))
        names = {x.lower() for x in d.get("excluded_folder_names", []) if x}
        paths = [os.path.normcase(os.path.normpath(x)) for x in d.get("excluded_folder_paths", []) if x]
        return names, paths
    except Exception:
        return set(), []


def main():
    cache = json.load(open(CACHE, encoding="utf-8"))
    # inv[(suggested_lower, size)] = original_name
    inv = {}
    suggested_names = set()
    for k, v in cache.items():
        if k == "__prompt_version__":
            continue
        try:
            size = int(k.rsplit("|", 1)[1])
        except (IndexError, ValueError):
            continue
        sug = (v.get("nome_sugerido") or "").strip()
        orig = (v.get("nome_original") or "").strip()
        if sug and orig and sug != orig:
            inv[(sug.lower(), size)] = orig
            suggested_names.add(sug.lower())
    print(f"Cache: {len(inv)} mapeamentos (nome novo+tamanho -> original).")

    ex_names, ex_paths = load_exclusions()
    ignored = {x.lower() for x in config.IGNORED_FOLDERS}

    def excluded(dpath, dname):
        if dname.lower() in ignored or dname.lower() in ex_names:
            return True
        n = os.path.normcase(os.path.normpath(dpath))
        return any(n == p or n.startswith(p + os.sep) for p in ex_paths)

    rows = []
    matched = 0
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not excluded(os.path.join(root, d), d)]
        for f in files:
            if f.lower() not in suggested_names:
                continue
            full = os.path.join(root, f)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            orig = inv.get((f.lower(), size))
            if orig:
                rows.append({"current_path": full, "original_name": orig, "suggested_name": f})
                matched += 1

    rows.sort(key=lambda x: x["current_path"].replace("/", "\\").count("\\"))
    ts = "reconstruido"
    out = os.path.join(config.REMEDIATION_DIR, f"rollback_reconstructed_{ts}.csv")
    os.makedirs(config.REMEDIATION_DIR, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["current_path", "original_name", "suggested_name"])
        w.writeheader()
        w.writerows(rows)

    print(f"Arquivos casados no disco: {matched}")
    print(f"Master reconstruído salvo: {out}")


if __name__ == "__main__":
    main()
