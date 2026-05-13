import json
import os
import re
from typing import List, Dict, Any, Set
from config import config

class PolicyEngine:
    """
    Enforces corporate governance policies for file remediation.
    """
    _frozen_cache: Dict[str, Set[str]] = None

    @staticmethod
    def _load_frozen():
        if PolicyEngine._frozen_cache is not None:
            return PolicyEngine._frozen_cache
            
        path = config.FROZEN_ITEMS_PATH
        if not os.path.exists(path):
            PolicyEngine._frozen_cache = {"folders": set(), "files": set()}
            return PolicyEngine._frozen_cache
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                PolicyEngine._frozen_cache = {
                    "folders": set(f.lower() for f in data.get("frozen_folders", [])),
                    "files": set(f.lower() for f in data.get("frozen_files", []))
                }
        except Exception:
            PolicyEngine._frozen_cache = {"folders": set(), "files": set()}
            
        return PolicyEngine._frozen_cache
    
    # Paths that should NEVER be touched by automated remediation
    FORBIDDEN_CLASSIFICATIONS = {
        "TECHNICAL_METADATA",
        "CACHE",
        "SYSTEM_BACKUP",
        "DEVELOPMENT_ENVIRONMENT",
        "TEMPORARY"
    }
    
    FORBIDDEN_FOLDERS = {
        "AppData",
        ".metadata",
        ".plugins",
        "node_modules",
        "vendor",
        ".git",
        "__pycache__",
        "bin",
        "obj"
    }

    @staticmethod
    def is_protected(record: Dict[str, Any]) -> bool:
        """
        Determines if a file is protected by policy and should not be touched.
        """
        # 1. Classification check
        classification = record.get("classification", "UNKNOWN")
        if classification in PolicyEngine.FORBIDDEN_CLASSIFICATIONS:
            return True
            
        # 2. Path check (Forbidden folders and Frozen folders)
        full_path = record.get("full_path", "")
        path_parts = [p.lower() for p in re.split(r'[\\/]', full_path)]
        
        # System forbidden
        for forbidden in PolicyEngine.FORBIDDEN_FOLDERS:
            if forbidden.lower() in path_parts:
                return True
                
        # User defined frozen items
        frozen = PolicyEngine._load_frozen()
        
        # Check if any part of the path is a frozen folder
        for folder in frozen["folders"]:
            if folder in path_parts:
                return True
                
        # 3. System files check
        original_name = record.get("original_name", "")
        filename_lower = original_name.lower()
        if filename_lower in ["desktop.ini", "thumbs.db", ".ds_store"]:
            return True
            
        # 4. Frozen files check
        if filename_lower in frozen["files"]:
            return True
            
        return False

    @staticmethod
    def get_action_category(record: Dict[str, Any]) -> str:
        """
        Decides the safety category of a remediation action.
        """
        if PolicyEngine.is_protected(record):
            return "IGNORE"
            
        # Ensure confidence is a float for comparison
        raw_confidence = record.get("confidence_score", 0)
        try:
            confidence = float(raw_confidence) if raw_confidence not in ["", None] else 0.0
        except (ValueError, TypeError):
            confidence = 0.0
            
        risk_level = record.get("risk_level", "LOW")
        
        # If no suggestion was made, ignore
        if not record.get("suggested_name"):
            return "IGNORE"
            
        # If name is already clean
        if record.get("original_name") == record.get("suggested_name"):
            return "IGNORE"
            
        # Decision Logic
        if risk_level == "CRITICAL" or confidence < 50:
            return "CRITICAL_RESTRUCTURE"
            
        if confidence >= 95 and risk_level == "LOW":
            return "AUTO_FIX_SAFE"
            
        if confidence >= 80:
            return "SUGGEST_RENAME"
            
        return "MANUAL_REVIEW"