import os
from typing import List, Set

class Config:
    """
    Central configuration for the Corporate Document Sanitation System.
    """
    # OneDrive/SharePoint compliance thresholds (Microsoft Learn, 2025).
    # Single source: rules/onedrive_rules.json. Constantes aqui são fallback.
    MAX_FILENAME_LENGTH: int = 255
    MAX_PATH_LENGTH: int = 400
    MARGEM_SEGURANCA_NOME: int = 5
    MARGEM_SEGURANCA_PATH: int = 5
    MIN_USEFUL_BASE_CHARS: int = 10
    # Informativo apenas — não viola OneDrive, mas é métrica útil para o analytics
    MAX_DEPTH: int = 10

    # Detecção de "nomes descritivos longos" (frases usadas como nome).
    # Fase de DETECÇÃO apenas — não gera sugestão de renomeação.
    LIMITE_CARACTERES_NOME_DESCRITIVO: int = 50
    LIMITE_PALAVRAS_NOME_DESCRITIVO: int = 6
    SEPARADORES_PALAVRAS: list = (" ", "_", "-")

    # Rules
    IGNORED_EXTENSIONS: Set[str] = {'.tmp', '.log', '.ini', '.db'}
    # Pastas que o scanner pula completamente — não entra, não conta.
    # Inclui pastas técnicas (.git, etc.) e as pastas de backup criadas pelo
    # próprio sistema (uma vez movido pra lá, é "já backupado", não é mídia
    # pra remediar).
    IGNORED_FOLDERS: Set[str] = {
        '.git', 'node_modules', '__pycache__', '.venv', 'venv',
        '_ARQUIVOS_PESADOS_MEDIA',
        'backup de imagens',
        'backup de audios',
    }

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
