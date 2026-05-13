import json
import os
from pathlib import Path
from config import config

class StructuralClassifier:
    """
    Classifies paths based on structural patterns to distinguish business documents 
    from technical junk.
    """
    def __init__(self):
        self.technical_patterns = []
        self.temporary_extensions = []
        self.business_extensions = []
        self._load_rules()

    def _load_rules(self):
        rules_path = os.path.join(config.RULES_DIR, "ignored_paths.json")
        try:
            if os.path.exists(rules_path):
                with open(rules_path, 'r', encoding='utf-8') as f:
                    rules = json.load(f)
                    self.technical_patterns = rules.get("technical_patterns", [])
                    self.temporary_extensions = rules.get("temporary_extensions", [])
                    self.business_extensions = rules.get("business_extensions", [])
        except Exception:
            # Fallback to defaults if file is missing or broken
            self.technical_patterns = [".metadata", ".plugins", "AppData", "node_modules", "cache"]
            self.temporary_extensions = [".tmp", ".log"]
            self.business_extensions = [".pdf", ".xlsx", ".docx"]

    def classify(self, path_str: str) -> dict:
        """
        Classifies a path and returns a dictionary with classification and score.
        """
        path = Path(path_str)
        name = path.name
        parts = [p.lower() for p in path.parts]
        ext = path.suffix.lower()

        # Check for technical patterns in path parts
        for pattern in self.technical_patterns:
            if pattern.lower() in parts:
                if "cache" in pattern.lower() or "node_modules" in pattern.lower():
                    return {"classification": "CACHE", "score": "IGNORE"}
                if "temp" in pattern.lower() or "tmp" in pattern.lower():
                    return {"classification": "TEMPORARY", "score": "IGNORE"}
                if "metadata" in pattern.lower() or "plugins" in pattern.lower() or ".git" in pattern.lower():
                    return {"classification": "TECHNICAL_METADATA", "score": "IGNORE"}
                if "appdata" in pattern.lower():
                    return {"classification": "SYSTEM_BACKUP", "score": "IGNORE"}
                return {"classification": "TECHNICAL_METADATA", "score": "IGNORE"}

        # Check for temporary extensions
        if ext in self.temporary_extensions:
            return {"classification": "TEMPORARY", "score": "IGNORE"}

        # Check for business documents
        if ext in self.business_extensions:
            return {"classification": "BUSINESS_DOCUMENT", "score": "HIGH"}

        # Check for development environment markers
        if any(p in ["bin", "obj", "node_modules", "__pycache__"] for p in parts):
            return {"classification": "DEVELOPMENT_ENVIRONMENT", "score": "IGNORE"}

        # Default classification
        return {"classification": "UNKNOWN", "score": "LOW"}
