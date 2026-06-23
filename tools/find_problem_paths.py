"""Localiza os arquivos problemáticos do OneDrive nos DOIS OneDrives e captura
erros de acesso do os.walk (revela por que pastas fundas não foram varridas)."""
import os

ROOTS = [
    r"C:\Users\kfpno\OneDrive - Kfp Distribuidora Ltda",
    r"C:\Users\kfpno\OneDrive",
]
TOKENS = ["tabelas de pre", "radiador celsius", "bonifica", "faturamento comercial", "download 2"]


def to_long(p):
    ap = os.path.abspath(p)
    return ap if ap.startswith("\\\\?\\") else "\\\\?\\" + ap


def strip_long(p):
    return p[4:] if p.startswith("\\\\?\\") else p


def main():
    errors = []

    def on_err(e):
        errors.append((getattr(e, "filename", "?"), e.__class__.__name__, str(e)[:80]))

    hits = []
    for ROOT in ROOTS:
        if not os.path.isdir(ROOT):
            print("(root nao existe)", ROOT)
            continue
        for root, dirs, files in os.walk(to_long(ROOT), onerror=on_err):
            clean = strip_long(root)
            low = clean.lower()
            for name in list(dirs) + files:
                nl = name.lower()
                if any(t in nl for t in TOKENS):
                    full = os.path.join(clean, name)
                    hits.append((len(full), full))

    hits.sort(reverse=True)
    print(f"=== {len(hits)} itens com tokens-problema ===")
    for L, p in hits[:15]:
        print(f"  len={L}  {p[-95:]}")

    print(f"\n=== {len(errors)} ERROS de acesso no walk (pastas que falharam) ===")
    seen = set()
    for fn, cls, msg in errors:
        key = strip_long(str(fn))[-70:]
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{cls}] ...{key} | {msg}")
        if len(seen) >= 15:
            break


if __name__ == "__main__":
    main()
