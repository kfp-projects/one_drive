"""
Consolida todos os manifestos rollback_renames_*.csv num ÚNICO master,
corrigindo o caminho atual de arquivos que ficaram dentro de pastas
renomeadas (o ponto impreciso dos manifestos individuais).

Saída: outputs/remediation/rollback_master_<timestamp>.csv com colunas:
  current_path     -> onde o item ESTÁ agora no disco
  original_name    -> nome original (pra reverter)
  original_path    -> caminho original completo
  status           -> ok | relocated | not_found

Reverter = para cada linha com status ok/relocated, renomear current_path
de volta para original_name (na pasta onde ele está agora). Aplicar de cima
pra baixo só funciona se os pais forem revertidos antes; por isso ordenamos
do mais RASO pro mais profundo no master.

Uso: python tools/consolidate_rollback.py
"""
import os, csv, glob, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config


def _norm(p):
    return os.path.normcase(os.path.normpath(p))


def main():
    rd = config.REMEDIATION_DIR
    files = sorted(glob.glob(os.path.join(rd, "rollback_renames_*.csv")))
    if not files:
        print("Nenhum rollback_renames_*.csv encontrado.")
        return

    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                rows.append(r)
    print(f"Lidos {len(rows)} renomes de {len(files)} manifesto(s).")

    # Mapa de pastas renomeadas: new_path é um diretório existente agora.
    folder_map = {}  # old_dir_norm -> new_path
    for r in rows:
        np = r["new_path"]
        if os.path.isdir(np):
            folder_map[_norm(r["original_path"])] = np
    # Aplica do prefixo mais longo pro mais curto
    folder_items = sorted(folder_map.items(), key=lambda kv: len(kv[0]), reverse=True)

    def current_path(new_path):
        if os.path.exists(new_path):
            return new_path, "ok"
        n = _norm(new_path)
        for old_norm, new_dir in folder_items:
            if n.startswith(old_norm + os.sep):
                cand = new_dir + new_path[len(old_norm):]
                if os.path.exists(cand):
                    return cand, "relocated"
        return new_path, "not_found"

    out_rows = []
    counts = {"ok": 0, "relocated": 0, "not_found": 0}
    for r in rows:
        cur, status = current_path(r["new_path"])
        counts[status] += 1
        out_rows.append({
            "current_path": cur,
            "original_name": r["original_name"],
            "original_path": r["original_path"],
            "status": status,
        })

    # Mais raso primeiro (pais antes dos filhos) pra revert seguro
    out_rows.sort(key=lambda x: x["current_path"].replace("/", "\\").count("\\"))

    ts = max(os.path.basename(f).replace("rollback_renames_", "").replace(".csv", "")
             for f in files)
    out_path = os.path.join(rd, f"rollback_master_{ts}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["current_path", "original_name", "original_path", "status"])
        w.writeheader()
        w.writerows(out_rows)

    print(f"\nMaster salvo: {out_path}")
    print(f"  ok (caminho direto):     {counts['ok']}")
    print(f"  relocated (pasta movida):{counts['relocated']}")
    print(f"  not_found (sumiu/movido):{counts['not_found']}")
    print(f"  TOTAL revertível:        {counts['ok'] + counts['relocated']} / {len(rows)}")


if __name__ == "__main__":
    main()
