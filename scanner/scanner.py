import os
import csv
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List

from config import config
from utils.logger import setup_logger
from scanner.pipeline import PipelineSim
from scanner.descriptive_name_detector import eh_nome_descritivo_longo

logger = setup_logger("scanner")

class ScannerService:
    """
    Core service for scanning directories.
    Calculates path limits, detects duplicates, and simulates AI rules.
    """
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.records: List[Dict[str, Any]] = []
        self.pipeline = PipelineSim()

        self.stats = {
            "total_files": 0,
            "total_folders": 0,
            "long_paths": 0,
            "forbidden_chars": 0,
            "duplicates": 0,
            "excessive_depth": 0,
            "nomes_descritivos_longos": 0,
        }

        self.forbidden_chars = self.pipeline.forbidden_chars
        self._file_hashes: Dict[str, str] = {}

        self.frozen_folders, self.frozen_files = self._load_frozen_items()

    def _load_frozen_items(self):
        try:
            with open(config.FROZEN_ITEMS_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                folders = {x.lower() for x in data.get("frozen_folders", [])}
                files = {x.lower() for x in data.get("frozen_files", [])}
                return folders, files
        except Exception as e:
            logger.warning(f"Could not load frozen_items.json: {e}")
            return set(), set()

    def scan_directory(self):
        """Recursively scans the directory and records issues."""
        logger.info(f"Starting scan in: {self.root_dir}")

        # Pré-computa o set em lowercase pra comparação case-insensitive —
        # pega "Backup de Imagens" / "BACKUP DE IMAGENS" / etc.
        ignored_lower = {x.lower() for x in config.IGNORED_FOLDERS}

        for root, dirs, files in os.walk(self.root_dir):
            root_path = Path(root)

            # Remove ignored folders to prevent walking into them (case-insensitive)
            dirs[:] = [d for d in dirs if d.lower() not in ignored_lower]

            for d in dirs:
                self.stats["total_folders"] += 1
                if self.stats["total_folders"] % 1000 == 0:
                    logger.info(f"Progress: Scanned {self.stats['total_folders']} folders...")
                self._analyze_path(root_path / d, is_dir=True)

            for f in files:
                file_path = root_path / f
                if file_path.suffix.lower() in config.IGNORED_EXTENSIONS:
                    continue
                self.stats["total_files"] += 1
                if self.stats["total_files"] % 5000 == 0:
                    logger.info(f"Progress: Scanned {self.stats['total_files']} files...")
                self._analyze_path(file_path, is_dir=False)
                
        logger.info("Scan completed.")
        return self.stats

    def _analyze_path(self, path: Path, is_dir: bool):
        """
        Coleta metadados e delega a análise para o pipeline (conformidade OneDrive).
        Pasta/arquivo em conformidade resulta em sugestão == original e
        action_required == "NONE" — não geramos sugestões cosméticas.
        """
        path_str = str(path)
        name = path.name
        path_length = len(path_str)

        # --- Métricas informativas para o analytics (NÃO viram violação) -----
        depth = len(path.relative_to(self.root_dir).parts)
        if depth > config.MAX_DEPTH:
            self.stats["excessive_depth"] += 1

        # Duplicata (informativa apenas — OneDrive permite nomes duplicados em
        # pastas diferentes; nem deduplica nem gera violação)
        if not is_dir:
            try:
                file_info = f"{name}_{path.stat().st_size}"
                if file_info in self._file_hashes:
                    self.stats["duplicates"] += 1
                else:
                    self._file_hashes[file_info] = path_str
            except OSError:
                pass

        # --- Análise de conformidade OneDrive (única fonte de violação) ------
        pipeline_result = self.pipeline.process(name, path_str)
        violation_codes = pipeline_result.get("_onedrive_violations", [])
        suggested_name = pipeline_result["suggested_name"]
        risk_level = pipeline_result.get("_onedrive_risk", "NONE") or "NONE"
        action_required = pipeline_result.get("_onedrive_action", "NONE") or "NONE"

        # Stats alinhados às regras OneDrive
        if "FILENAME_TOO_LONG" in violation_codes:
            self.stats.setdefault("long_filenames", 0)
            self.stats["long_filenames"] += 1
        if "PATH_TOO_LONG" in violation_codes:
            self.stats["long_paths"] += 1
        if "FORBIDDEN_CHARS" in violation_codes:
            self.stats["forbidden_chars"] += 1
        if "RESERVED_NAME" in violation_codes:
            self.stats.setdefault("reserved_names", 0)
            self.stats["reserved_names"] += 1
        if "INVALID_EDGE_CHARS" in violation_codes:
            self.stats.setdefault("invalid_edges", 0)
            self.stats["invalid_edges"] += 1
        if "SUSPICIOUS_DOUBLE_EXT" in violation_codes:
            self.stats.setdefault("double_ext", 0)
            self.stats["double_ext"] += 1

        # --- Frozen/shared: itens compartilhados não podem ser alterados -----
        is_shared = False
        if is_dir and name.lower() in self.frozen_folders:
            is_shared = True
        elif not is_dir and name.lower() in self.frozen_files:
            is_shared = True
        if is_shared:
            suggested_name = name
            action_required = "BLOCKED"

        # --- Detecção informativa: nome descritivo longo (só arquivos) -------
        # Fase APENAS de contagem — não influencia violação OneDrive nem
        # gera sugestão de renomeação. Aplica-se só a arquivos.
        nome_descritivo_longo = (not is_dir) and eh_nome_descritivo_longo(name)
        if nome_descritivo_longo:
            self.stats["nomes_descritivos_longos"] += 1

        self.records.append({
            "original_name": name,
            "full_path": path_str,
            "path_length": path_length,
            "extension": path.suffix if not is_dir else "DIR",
            "is_dir": is_dir,
            "is_shared": is_shared,
            "nome_descritivo_longo": nome_descritivo_longo,
            "detected_problems": "; ".join(violation_codes),
            "suggested_name": suggested_name,
            "risk_level": risk_level,
            "classification": pipeline_result["classification"],
            "structural_score": pipeline_result["structural_score"],
            "action_required": action_required,
            "semantic_summary": pipeline_result.get("semantic_summary", ""),
            "confidence_score": pipeline_result.get("confidence_score", ""),
            "naming_reason": pipeline_result.get("naming_reason", ""),
            "context_analysis": pipeline_result.get("context_analysis", "")
        })


    def export_reports(self, csv_path: str, json_path: str):
        """Exports the findings to CSV and JSON."""
        logger.info(f"Exporting reports...")
        
        # Make directories if they don't exist
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        
        fieldnames = [
            "original_name", "full_path", "path_length", "extension",
            "is_dir", "is_shared", "nome_descritivo_longo",
            "detected_problems", "suggested_name", "risk_level",
            "classification", "structural_score",
            "semantic_summary", "confidence_score", "naming_reason", "context_analysis"
        ]
        
        # Inclui itens compartilhados (frozen) mesmo sem violação, para que
        # apareçam na listagem com o badge "Bloqueado" e o usuário saiba que
        # existem mas não podem ser alterados. Também inclui registros que só
        # têm "nome descritivo longo" (informativo, fase de detecção).
        filtered_records = [
            r for r in self.records
            if r["risk_level"] != "NONE"
            or r.get("is_shared")
            or r.get("nome_descritivo_longo")
        ]

        # CSV Export
        try:
            with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                for record in filtered_records:
                    writer.writerow(record)
            logger.info(f"CSV Report generated: {csv_path}")
        except Exception as e:
            logger.error(f"Failed to export CSV: {e}")

        # JSON Export
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({"issues": filtered_records}, f, indent=2, ensure_ascii=False)
            logger.info(f"JSON Report generated: {json_path}")
        except Exception as e:
            logger.error(f"Failed to export JSON: {e}")
