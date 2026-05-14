"""
Pipeline simplificado — delegador para o módulo de conformidade OneDrive.

Toda a lógica de detecção/sugestão vive em remediation.onedrive_compliance.
Este arquivo existe apenas como ponto de integração com scanner.py, mantendo
a assinatura .process(name, full_path) que o scanner já espera.

NOTA: o pipeline antigo aplicava transformações cosméticas (título, remoção
de stop words, abreviações). Foi descontinuado em prol do princípio "só toca
quando viola regra OneDrive concreta".
"""

import os
import json
from config import config
from scanner.classifier import StructuralClassifier
from remediation.onedrive_compliance import analyze


class PipelineSim:
    """
    Compatibilidade com a API do scanner.

    .process(name, full_path) retorna o mesmo formato dict que o pipeline
    antigo expunha, com os campos populados a partir da análise OneDrive.
    """

    # Mapeamentos código → label usado em detected_problems no scanner record
    VIOLATION_CODES = {
        "A": "FILENAME_TOO_LONG",
        "B": "PATH_TOO_LONG",
        "C": "FORBIDDEN_CHARS",
        "D": "RESERVED_NAME",
        "E": "INVALID_EDGE_CHARS",
        "F": "SUSPICIOUS_DOUBLE_EXT",
    }

    RISK_MAP = {"Baixo": "LOW", "Médio": "MEDIUM", "Alto": "HIGH"}

    ACTION_MAP = {
        "Renomear Automaticamente": "AUTO_RENAME",
        "Sugerir Renomeação": "SUGGEST_RENAME",
        "Sugerir Renomeação com Atenção": "SUGGEST_RENAME_CAUTION",
        "Manter Original": "NONE",
    }

    def __init__(self):
        self.classifier = StructuralClassifier()
        self.forbidden_chars = self._load_forbidden_chars()

    def _load_forbidden_chars(self):
        """Mantido por compatibilidade com scanner.py (que lê este atributo)."""
        try:
            rules_path = os.path.join(config.RULES_DIR, "onedrive_rules.json")
            with open(rules_path, "r", encoding="utf-8") as f:
                return json.load(f).get("forbidden_chars", [])
        except Exception:
            return ['"', '*', ':', '<', '>', '?', '/', '\\', '|', '#']

    def process(self, original_name: str, full_path: str) -> dict:
        """
        Roda análise OneDrive e devolve dict com campos que o scanner usa.
        """
        # Classificação estrutural (cache, business doc, etc.) continua
        classification_data = self.classifier.classify(full_path)
        result = analyze(original_name, full_path)

        violation_labels = [self.VIOLATION_CODES[v] for v in result["violacoes_detectadas"]]
        risk_level = self.RISK_MAP.get(result["risco"], "NONE")
        action = self.ACTION_MAP.get(result["acao"], "NONE")
        confidence = result["confianca"].rstrip("%") if result["confianca"] else ""

        return {
            "suggested_name": result["nome_sugerido"],
            "classification": classification_data["classification"],
            "structural_score": classification_data["score"],
            "semantic_summary": result["resumo_semantico"],
            "confidence_score": confidence,
            "naming_reason": result["motivo"],
            "context_analysis": "",
            # Campos novos da análise OneDrive (consumidos pelo scanner)
            "_onedrive_violations": violation_labels,
            "_onedrive_risk": risk_level,
            "_onedrive_action": action,
            "_onedrive_has_violation": result["tem_violacao"],
        }
