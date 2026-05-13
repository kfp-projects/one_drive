import os
from typing import List, Set

class Config:
    """
    Central configuration for the Corporate Document Sanitation System.
    """
    # Thresholds
    MAX_PATH_LENGTH: int = 255
    MAX_FILENAME_LENGTH: int = 150
    MAX_DEPTH: int = 10

    # Rules
    IGNORED_EXTENSIONS: Set[str] = {'.tmp', '.log', '.ini', '.db'}
    IGNORED_FOLDERS: Set[str] = {'.git', 'node_modules', '__pycache__', '.venv', 'venv'}

    # Media Offloading
    MEDIA_EXTENSIONS: Set[str] = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', # Images
        '.mp3', '.wav', '.aac', '.flac', '.ogg', '.m4a',           # Audio
        '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv'             # Video
    }
    MEDIA_OFFLOAD_SOURCES: Set[str] = {
        'financeiro', 'rh', 'diretoria', 'informatica', 'sivenadm', 'dircom', 'cdm'
    }
    MEDIA_OFFLOAD_DIR: str = "_ARQUIVOS_PESADOS_MEDIA"

    # Operational
    DRY_RUN: bool = True  # Safety first: do not rename anything yet
    
    # Paths
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    RULES_DIR: str = os.path.join(BASE_DIR, "rules")
    OUTPUT_DIR: str = os.path.join(BASE_DIR, "outputs")
    REPORTS_DIR: str = os.path.join(OUTPUT_DIR, "reports")
    ANALYTICS_DIR: str = os.path.join(OUTPUT_DIR, "analytics")
    REMEDIATION_DIR: str = os.path.join(OUTPUT_DIR, "remediation")
    LOGS_DIR: str = os.path.join(BASE_DIR, "logs")

    # Remediation & Naming
    MIN_CONFIDENCE_AUTO_FIX: float = 95.0
    MAX_CORPORATE_NAME_LENGTH: int = 60
    
    # Style Policy
    STYLE_GUIDE_PATH: str = os.path.join(RULES_DIR, "corporate_naming_style.json")
    FROZEN_ITEMS_PATH: str = os.path.join(RULES_DIR, "frozen_items.json")

config = Config()
