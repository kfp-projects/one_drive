"""
Conformidade OneDrive / SharePoint — detecção, classificação e correção de violações.

Princípio central: se um arquivo está em conformidade com as regras oficiais
do OneDrive, NÃO sugerir nenhuma alteração. Padronização cosmética NÃO é
objetivo deste módulo. Sugestões só são geradas quando há violação técnica
concreta (fonte: Microsoft Learn, 2025).

Regras carregadas de rules/onedrive_rules.json — fonte única da verdade.

API pública: analyze(name, full_path) -> dict (formato no docstring de analyze).
"""

import json
import os
import re
from typing import Optional, Tuple, List


_RULES = None

# Extensões de arquivo "de verdade". Se o segmento interno de um nome com 2
# pontos finais for uma destas, é provável extensão dupla suspeita
# (ex.: nota.pdf.exe). Se não for, o ponto é parte do nome (data, sigla, versão).
_KNOWN_EXTENSIONS = {
    # documentos
    "doc", "docx", "xls", "xlsx", "xlsm", "ppt", "pptx", "pdf", "txt", "rtf",
    "csv", "odt", "ods", "odp",
    # imagens
    "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "heic", "svg",
    # áudio/vídeo
    "mp3", "wav", "aac", "flac", "ogg", "m4a", "mp4", "mov", "avi", "mkv", "wmv", "flv",
    # arquivos/compactados
    "zip", "rar", "7z", "tar", "gz", "iso", "bak",
    # executáveis/scripts (os mais perigosos numa extensão dupla)
    "exe", "msi", "bat", "cmd", "com", "scr", "ps1", "sh", "vbs", "js", "jar",
    # web/dados
    "html", "htm", "xml", "json",
}


def _load_rules() -> dict:
    """Carrega rules/onedrive_rules.json uma única vez (lazy)."""
    global _RULES
    if _RULES is not None:
        return _RULES
    from config import config
    rules_path = os.path.join(config.RULES_DIR, "onedrive_rules.json")
    with open(rules_path, "r", encoding="utf-8") as f:
        _RULES = json.load(f)
    return _RULES


def _effective_max_path(rules: dict) -> int:
    """Limite EFETIVO de caminho no disco local.

    O OneDrive mede o caminho na URL da nuvem (SharePoint), ~`cloud_url_overhead`
    chars mais longa que o prefixo local. Logo, o limite real no caminho local é
    max_path_length menos esse overhead. Sem isso, arquivos que estouram no
    OneDrive passam despercebidos (caminho local fica abaixo de 400).
    """
    return rules["max_path_length"] - rules.get("cloud_url_overhead", 0)


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------

def _is_reserved_name(name: str) -> bool:
    """
    (D) Verifica se o nome é reservado pelo Windows/OneDrive/SharePoint.
    Comparação case-insensitive conforme spec da Microsoft.
    """
    rules = _load_rules()
    base, _ = os.path.splitext(name)
    base_upper = base.upper()
    name_lower = name.lower()

    # Match exato (CON, PRN, AUX, NUL, desktop.ini, .lock, …)
    exact = {x.upper() for x in rules["reserved_names_exact"]}
    if base_upper in exact or name.upper() in exact:
        return True

    # Prefixos reservados (~$ = arquivos temp do Office)
    for prefix in rules["reserved_prefixes"]:
        if name.startswith(prefix):
            return True

    # Substrings reservadas (_vti_ = interno do SharePoint)
    for substr in rules["reserved_substrings"]:
        if substr.lower() in name_lower:
            return True

    # Regex (COM0-COM9, LPT0-LPT9)
    for pattern in rules["reserved_regex"]:
        if re.match(pattern, base_upper):
            return True

    return False


def _is_suspicious_double_extension(name: str) -> bool:
    """
    (F) Detecta dupla extensão suspeita: arquivo.xl.xlsx, foto.jpg.exe etc.
    Os DOIS últimos segmentos devem parecer extensões (curtos, alfanuméricos).
    Whitelist cobre extensões compostas legítimas (.tar.gz etc).
    """
    rules = _load_rules()
    whitelist = [w.lower() for w in rules.get("double_extension_whitelist", [])]
    max_inner = rules.get("max_inner_extension_chars", 5)

    name_lower = name.lower()
    for white in whitelist:
        if name_lower.endswith(white):
            return False

    # rsplit('.', 2) → no máximo 2 splits a partir da direita
    parts = name.rsplit(".", 2)
    if len(parts) < 3:
        return False  # apenas 1 (ou 0) extensão, nada de duplo

    inner, outer = parts[1], parts[2]
    # Ambos devem parecer extensão: alfanuméricos, 1..max_inner chars
    if not (1 <= len(inner) <= max_inner and inner.isalnum()):
        return False
    if not (1 <= len(outer) <= max_inner and outer.isalnum()):
        return False
    # Segurança PRIMEIRO: se o interno é extensão conhecida, é disfarce real
    # (nota.pdf.exe, foto.JPG.scr) — sinaliza sempre, mesmo em caixa alta.
    if inner.lower() in _KNOWN_EXTENSIONS:
        return True
    # Senão, excluir falsos positivos onde o ponto faz parte do NOME:
    #  - data/versão numérica: "15.05.xlsx", "doc.2024.pdf"  (inner numérico)
    #  - sigla em CAIXA ALTA:  "PE.CE.AL.BA.xlsm" (BA = Bahia)  (inner maiúsculo)
    if inner.isdigit() or inner.isupper():
        return False
    # Resta minúsculo não-extensão: típico typo de extensão ("xl.xlsx").
    return True


def _detect_violations(name: str, full_path: str) -> List[str]:
    """
    Retorna lista de códigos de violação (A/B/C/D/E/F) na ordem em que foram
    encontradas. Lista vazia significa: conforme, não sugerir nada.
    """
    rules = _load_rules()
    violations: List[str] = []

    # (A) nome > 255
    if len(name) > rules["max_filename_length"]:
        violations.append("A")

    # (B) caminho completo acima do limite EFETIVO (400 menos overhead da nuvem)
    if len(full_path) > _effective_max_path(rules):
        violations.append("B")

    # (C) caractere proibido no nome
    if any(c in name for c in rules["forbidden_chars"]):
        violations.append("C")

    # (D) nome reservado
    if _is_reserved_name(name):
        violations.append("D")

    # (E) espaço/ponto/til nas bordas do nome base (não da extensão)
    base, _ = os.path.splitext(name)
    edges = set(rules["edge_chars"])
    if base and (base[0] in edges or base[-1] in edges):
        violations.append("E")

    # (F) dupla extensão suspeita
    if _is_suspicious_double_extension(name):
        violations.append("F")

    return violations


# ---------------------------------------------------------------------------
# Correções — uma função por violação
# ---------------------------------------------------------------------------

def _fix_forbidden_chars(name: str) -> Tuple[str, List[str]]:
    """
    Correção (C): cada caractere proibido vira underscore.
    Underscores consecutivos resultantes são colapsados em um único.
    Retorna (novo_nome, lista_dos_chars_encontrados).
    """
    rules = _load_rules()
    found = [c for c in rules["forbidden_chars"] if c in name]
    for c in rules["forbidden_chars"]:
        name = name.replace(c, "_")
    name = re.sub(r"_+", "_", name)
    return name, found


def _fix_reserved(name: str) -> str:
    """Correção (D): adiciona sufixo _arquivo antes da extensão."""
    base, ext = os.path.splitext(name)
    return f"{base}_arquivo{ext}"


def _fix_edge_chars(name: str) -> str:
    """Correção (E): remove espaço/ponto/til das bordas do nome base."""
    rules = _load_rules()
    base, ext = os.path.splitext(name)
    chars = "".join(rules["edge_chars"])
    base = base.strip(chars)
    return base + ext


def _fix_double_extension(name: str) -> str:
    """
    Correção (F): remove a extensão INTERNA, preservando a externa (que é a
    que o Windows usa pra abrir o arquivo).
    Ex: 'arquivo.xl.xlsx' -> 'arquivo.xlsx'
        'foto.jpg.exe'    -> 'foto.exe'
    """
    parts = name.rsplit(".", 2)
    if len(parts) < 3:
        return name
    base, _inner, outer = parts
    return f"{base}.{outer}"


def _fix_filename_length(name: str) -> str:
    """
    Correção (A): trunca o nome (sem extensão) para que o total fique em
    (max_filename_length - margem). Preserva extensão e começo do nome
    (geralmente mais informativo). Faz trim de bordas após o corte.
    """
    rules = _load_rules()
    max_total = rules["max_filename_length"] - rules["margem_seguranca_nome"]
    base, ext = os.path.splitext(name)
    if len(name) <= max_total:
        return name
    base_max = max(1, max_total - len(ext))
    truncated = base[:base_max].rstrip("".join(rules["edge_chars"]))
    return truncated + ext


def _fix_path_length(name: str, full_path: str) -> Optional[str]:
    """
    Correção (B): encurta o NOME do arquivo o suficiente para que o caminho
    total fique abaixo de (max_path_length - margem).

    Retorna None quando o truncamento agressivo deixaria menos do que
    min_useful_base_chars caracteres úteis — nesse caso a correção apenas
    por renomeação é impossível e o spec manda manter o original.
    """
    rules = _load_rules()
    max_path = _effective_max_path(rules) - rules["margem_seguranca_path"]
    if len(full_path) <= max_path:
        return name
    excess = len(full_path) - max_path
    base, ext = os.path.splitext(name)
    new_base_len = len(base) - excess
    if new_base_len < rules["min_useful_base_chars"]:
        return None
    truncated = base[:new_base_len].rstrip("".join(rules["edge_chars"]))
    return truncated + ext


# ---------------------------------------------------------------------------
# Geração de motivo (pt-BR, específico, sem jargão)
# ---------------------------------------------------------------------------

def _motivo(violation: str, before: str = "", after: str = "",
            extra: Optional[List[str]] = None) -> str:
    if violation == "C":
        chars = "".join(extra or [])
        return (f"Nome contém caractere(s) proibido(s) pelo OneDrive ({chars}). "
                f"Substituído(s) por underscore.")
    if violation == "D":
        return ("Nome reservado do Windows/OneDrive causa falha de sincronização. "
                "Adicionado sufixo _arquivo.")
    if violation == "E":
        return ("Nome começa ou termina com espaço, ponto ou til — causa erro de "
                "upload no OneDrive. Bordas removidas.")
    if violation == "A":
        return (f"Nome excede o limite de 255 caracteres do OneDrive "
                f"(atual: {len(before)}). Truncado preservando o início.")
    if violation == "B":
        removed = len(os.path.splitext(before)[0]) - len(os.path.splitext(after)[0])
        return (f"Caminho completo excede 400 caracteres. Nome do arquivo "
                f"encurtado em {removed} caractere(s).")
    if violation == "F":
        return ("Nome com dupla extensão suspeita (provável erro de digitação "
                "ou arquivo disfarçado). Extensão interna removida.")
    return ""


_VIOLATION_LABELS_SHORT = {
    "A": "nome > 255 chars",
    "B": "caminho > 400 chars",
    "C": "caractere proibido",
    "D": "nome reservado",
    "E": "borda inválida",
    "F": "dupla extensão",
}


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def analyze(name: str, full_path: str) -> dict:
    """
    Analisa um arquivo ou pasta contra as regras do OneDrive e retorna um
    dicionário no formato:

    {
      "nome_original": str,
      "caminho_original": str,
      "tem_violacao": bool,
      "violacoes_detectadas": list[str],     # subset de ["A","B","C","D","E"]
      "nome_sugerido": str,                  # == nome_original quando sem violação
      "caminho_sugerido": str,
      "risco": "Baixo" | "Médio" | "Alto" | None,
      "classificacao": "Conformidade OneDrive",
      "confianca": "100%" | "95%" | "80%" | None,
      "acao": "Renomear Automaticamente" | "Sugerir Renomeação"
             | "Sugerir Renomeação com Atenção" | "Manter Original",
      "motivo": str,                         # texto humano específico em pt-BR
      "resumo_semantico": str                # 1 linha resumindo a correção
    }
    """
    violations = _detect_violations(name, full_path)
    parent_dir = os.path.dirname(full_path)

    # Caminho feliz: zero violação → não tocar, não inventar motivo cosmético
    if not violations:
        return {
            "nome_original": name,
            "caminho_original": full_path,
            "tem_violacao": False,
            "violacoes_detectadas": [],
            "nome_sugerido": name,
            "caminho_sugerido": full_path,
            "risco": None,
            "classificacao": "Conformidade OneDrive",
            "confianca": None,
            "acao": "Manter Original",
            "motivo": "",
            "resumo_semantico": "",
        }

    # Aplica correções na ordem C → F → D → E → A → B.
    # F vai antes de D porque remover extensão interna pode revelar nome
    # reservado (ex: 'CON.xl.txt' → 'CON.txt' precisa de D).
    new_name = name
    motivos: List[str] = []
    aggressive_truncation = False
    applied = set()

    if "C" in violations:
        before = new_name
        new_name, found = _fix_forbidden_chars(new_name)
        motivos.append(_motivo("C", before, new_name, extra=found))
        applied.add("C")

    if "F" in violations:
        before = new_name
        new_name = _fix_double_extension(new_name)
        motivos.append(_motivo("F", before, new_name))
        applied.add("F")

    # D pode disparar pela primeira vez aqui (F revelou) ou ter sido pré-detectado
    if "D" in violations or _is_reserved_name(new_name):
        before = new_name
        new_name = _fix_reserved(new_name)
        if before != new_name:
            motivos.append(_motivo("D", before, new_name))
            applied.add("D")
            if "D" not in violations:
                violations.append("D")

    if "E" in violations:
        before = new_name
        new_name = _fix_edge_chars(new_name)
        motivos.append(_motivo("E", before, new_name))
        applied.add("E")

    # A pode ter sido criada pela correção (D), revalidamos
    rules = _load_rules()
    if "A" in violations or len(new_name) > rules["max_filename_length"]:
        before = new_name
        new_name = _fix_filename_length(new_name)
        if before != new_name:
            motivos.append(_motivo("A", before, new_name))
            applied.add("A")
            if "A" not in violations:
                violations.append("A")

    new_full_path = os.path.join(parent_dir, new_name) if parent_dir else new_name

    if "B" in violations or len(new_full_path) > _effective_max_path(rules):
        before = new_name
        fixed = _fix_path_length(new_name, new_full_path)
        if fixed is None:
            # Truncamento agressivo demais — spec manda manter original
            return {
                "nome_original": name,
                "caminho_original": full_path,
                "tem_violacao": True,
                "violacoes_detectadas": violations,
                "nome_sugerido": name,
                "caminho_sugerido": full_path,
                "risco": None,
                "classificacao": "Conformidade OneDrive",
                "confianca": None,
                "acao": "Manter Original",
                "motivo": ("Caminho excede limite — requer reorganização da estrutura "
                           "de pastas, não apenas renomeação."),
                "resumo_semantico": "Caminho longo demais para correção apenas por renomeação.",
            }
        chars_removed = len(os.path.splitext(before)[0]) - len(os.path.splitext(fixed)[0])
        if chars_removed > 30:
            aggressive_truncation = True
        new_name = fixed
        new_full_path = os.path.join(parent_dir, new_name) if parent_dir else new_name
        motivos.append(_motivo("B", before, new_name))
        applied.add("B")
        if "B" not in violations:
            violations.append("B")

    # Risco: pior violação corrigida define
    if "B" in applied and aggressive_truncation:
        risco, confianca = "Alto", "80%"
    elif "A" in applied or "B" in applied:
        risco, confianca = "Médio", "95%"
    else:
        risco, confianca = "Baixo", "100%"

    # Ação derivada
    if risco == "Baixo" and confianca == "100%":
        acao = "Renomear Automaticamente"
    elif risco == "Alto":
        acao = "Sugerir Renomeação com Atenção"
    else:
        acao = "Sugerir Renomeação"

    resumo = ("Corrigida(s) violação(ões) de conformidade OneDrive: "
              + ", ".join(_VIOLATION_LABELS_SHORT[v] for v in violations) + ".")

    return {
        "nome_original": name,
        "caminho_original": full_path,
        "tem_violacao": True,
        "violacoes_detectadas": violations,
        "nome_sugerido": new_name,
        "caminho_sugerido": new_full_path,
        "risco": risco,
        "classificacao": "Conformidade OneDrive",
        "confianca": confianca,
        "acao": acao,
        "motivo": " ".join(motivos),
        "resumo_semantico": resumo,
    }
