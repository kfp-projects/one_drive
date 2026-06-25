"""Mede os comprimentos REAIS de caminho no disco (com suporte a caminho longo),
pra dimensionar o problema de PATH_TOO_LONG independente do report."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config

ROOT = r"C:\Users\kfpno\OneDrive - Kfp Distribuidora Ltda"
# Limite EFETIVO no caminho LOCAL: ~351 (400 da URL da nuvem menos o overhead
# de ~49 chars do prefixo SharePoint vs o prefixo local).
LIMIT = 351


def to_long(p):
    ap = os.path.abspath(p)
    return ap if ap.startswith("\\\\?\\") else "\\\\?\\" + ap


def strip_long(p):
    return p[4:] if p.startswith("\\\\?\\") else p


def main():
    d = json.load(open(config.EXCLUSIONS_PATH, encoding="utf-8"))
    ex_paths = [os.path.normcase(os.path.normpath(x)) for x in d.get("excluded_folder_paths", []) if x]
    ignored = {x.lower() for x in config.IGNORED_FOLDERS}

    def excluded(dpath, dname):
        if dname.lower() in ignored:
            return True
        n = os.path.normcase(os.path.normpath(dpath))
        return any(n == p or n.startswith(p + os.sep) for p in ex_paths)

    total = 0
    over = []
    buckets = {340: 0, 345: 0, 348: 0, 351: 0}
    maxlen = 0
    deepest = 0
    for root, dirs, files in os.walk(to_long(ROOT)):
        clean_root = strip_long(root)
        dirs[:] = [dd for dd in dirs if not excluded(os.path.join(clean_root, dd), dd)]
        depth = clean_root.count(os.sep)
        deepest = max(deepest, depth)
        for f in files:
            total += 1
            full = os.path.join(clean_root, f)
            L = len(full)
            maxlen = max(maxlen, L)
            for b in buckets:
                if L >= b:
                    buckets[b] += 1
            if L >= LIMIT:
                over.append((L, full))

    over.sort(reverse=True)
    print(f"Arquivos varridos: {total}")
    print(f"Profundidade maxima: {deepest} niveis | Maior caminho: {maxlen} chars")
    print("Arquivos por faixa de comprimento (caminho local):")
    for b in sorted(buckets):
        print(f"   >= {b}: {buckets[b]}")
    print(f"\n--- ACIMA do limite efetivo ({LIMIT}) -> {len(over)} arquivos ---")
    for L, p in over[:25]:
        print(f"  {L}  ...{p[-85:]}")


if __name__ == "__main__":
    main()
