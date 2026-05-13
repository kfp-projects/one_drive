import os
import csv
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List

from config import config
from utils.logger import setup_logger
from scanner.pipeline import PipelineSim

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
            "excessive_depth": 0
        }
        
        self.forbidden_chars = self.pipeline.forbidden_chars
        self._file_hashes: Dict[str, str] = {} # "name_size" -> path

    def scan_directory(self):
        """Recursively scans the directory and records issues."""
        logger.info(f"Starting scan in: {self.root_dir}")
        
        for root, dirs, files in os.walk(self.root_dir):
            root_path = Path(root)
            
            # Reset folder registry for each directory to detect collisions locally
            folder_registry = {} # suggested_name -> original_name
            
            # Remove ignored folders to prevent walking into them
            dirs[:] = [d for d in dirs if d not in config.IGNORED_FOLDERS]

            # Analyze directories
            for d in dirs:
                self.stats["total_folders"] += 1
                if self.stats["total_folders"] % 1000 == 0:
                    logger.info(f"Progress: Scanned {self.stats['total_folders']} folders...")
                self._analyze_path(root_path / d, is_dir=True, folder_registry=folder_registry)

            # Analyze files
            for f in files:
                file_path = root_path / f
                if file_path.suffix.lower() in config.IGNORED_EXTENSIONS:
                    continue
                    
                self.stats["total_files"] += 1
                if self.stats["total_files"] % 5000 == 0:
                    logger.info(f"Progress: Scanned {self.stats['total_files']} files...")
                self._analyze_path(file_path, is_dir=False, folder_registry=folder_registry)
                
        logger.info("Scan completed.")
        return self.stats

    def _analyze_path(self, path: Path, is_dir: bool, folder_registry: Dict[str, str]):
        path_str = str(path)
        name = path.name
        issues = []
        risk_level = "LOW"
        
        # 1. Path length check
        path_length = len(path_str)
        if path_length > config.MAX_PATH_LENGTH:
            self.stats["long_paths"] += 1
            issues.append(f"LONG_PATH ({path_length} > {config.MAX_PATH_LENGTH})")
            risk_level = "CRITICAL"

        # 2. Depth check
        depth = len(path.relative_to(self.root_dir).parts)
        if depth > config.MAX_DEPTH:
            self.stats["excessive_depth"] += 1
            issues.append(f"EXCESSIVE_DEPTH ({depth})")
            if risk_level != "CRITICAL": risk_level = "HIGH"

        # 3. Forbidden characters
        found_chars = [c for c in self.forbidden_chars if c in name]
        if found_chars:
            self.stats["forbidden_chars"] += 1
            issues.append(f"FORBIDDEN_CHARS ({''.join(found_chars)})")
            if risk_level not in ["CRITICAL", "HIGH"]: risk_level = "MEDIUM"

        # 4. Duplicate Check (Simple Name + Size hash for files)
        if not is_dir:
            try:
                file_info = f"{name}_{path.stat().st_size}"
                if file_info in self._file_hashes:
                    self.stats["duplicates"] += 1
                    issues.append("POSSIBLE_DUPLICATE")
                    if risk_level not in ["CRITICAL", "HIGH", "MEDIUM"]: risk_level = "MEDIUM"
                else:
                    self._file_hashes[file_info] = path_str
            except OSError:
                pass 

        # 5. Pipeline suggestion & Classification
        pipeline_result = self.pipeline.process(name, path_str)
        suggested_name = pipeline_result["suggested_name"]
        classification = pipeline_result["classification"]
        structural_score = pipeline_result["structural_score"]

        # 6. Conservative Naming: Check if change is actually needed
        # Avoid changing if it's already "clean enough" (no forbidden chars, reasonable length, human readable)
        is_clean_enough = not found_chars and len(name) < 50 and "_" not in name and "," not in name and ".." not in name
        
        if suggested_name != name and "POSSIBLE_DUPLICATE" not in issues:
             # Calculate ratio based on base name only (ignore extension)
             base_orig = os.path.splitext(name)[0]
             base_sugg = os.path.splitext(suggested_name)[0]
             reduction_ratio = len(base_sugg) / len(base_orig) if len(base_orig) > 0 else 1
             
             # Only suggest if it's not "clean enough" OR if reduction is significant
             # OR if there are critical issues like forbidden chars (already covered by action_required logic)
             if not is_clean_enough or reduction_ratio < 0.75:
                 if not issues: issues.append("SUBOPTIMAL_NAME")
             else:
                 suggested_name = name # Revert suggestion
                
        # 7. Collision Detection (Inside the same folder)
        if suggested_name != name:
            # Check if suggested name already exists in this folder or is already planned for another file
            root_path = path.parent
            if suggested_name in folder_registry:
                base, ext = os.path.splitext(suggested_name)
                counter = 1
                new_name = f"{base} ({counter}){ext}"
                while new_name in folder_registry or (root_path / new_name).exists():
                    counter += 1
                    new_name = f"{base} ({counter}){ext}"
                suggested_name = new_name
                issues.append("NAME_COLLISION_RESOLVED")
                risk_level = "MEDIUM"
            
            folder_registry[suggested_name] = name


        if not issues:
            risk_level = "NONE"
            
        # Determine action
        action_required = "RENAME" if issues and any(i in issues for i in ["LONG_PATH", "FORBIDDEN_CHARS", "NAME_COLLISION_RESOLVED"]) else ("SUGGEST_RENAME" if issues else "NONE")
        
        # Record
        self.records.append({
            "original_name": name,
            "full_path": path_str,
            "path_length": path_length,
            "extension": path.suffix if not is_dir else "DIR",
            "detected_problems": "; ".join(issues),
            "suggested_name": suggested_name if action_required != "NONE" else name,
            "risk_level": risk_level,
            "classification": classification,
            "structural_score": structural_score,
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
            "detected_problems", "suggested_name", "risk_level",
            "classification", "structural_score", 
            "semantic_summary", "confidence_score", "naming_reason", "context_analysis"
        ]
        
        filtered_records = [r for r in self.records if r["risk_level"] != "NONE"]

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
