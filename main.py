import os
import json
from datetime import datetime
from config import config
from utils.logger import setup_logger
from scanner.scanner import ScannerService
from analytics.reports_dashboard import ReportsDashboard
from remediation.remediation_engine import RemediationEngine
from remediation.rollback_manager import RollbackManager
from remediation.batch_planner import BatchPlanner
from remediation.rename_simulator import RenameSimulator
from remediation.media_manager import MediaManager
from utils.cleanup import cleanup_old_results


# Setup main logger
logger = setup_logger("main")

def run_pipeline(root_to_scan: str = "."):
    logger.info("=== Corporate Document Sanitation System V1 - PIPELINE START ===")
    
    # Cleanup Phase
    cleanup_old_results()

    logger.info(f"Target directory: {root_to_scan}")
    
    if config.DRY_RUN:
        logger.info("[MODE] DRY_RUN is Active. No files will be modified.")

    # Initialize Service
    scanner = ScannerService(root_dir=root_to_scan)
    
    # Phase 1: Scan & Process Pipeline
    logger.info("Phase 1: Analyzing and Processing Pipeline...")
    stats = scanner.scan_directory()
    
    # Phase 2: Report Generation
    logger.info("Phase 2: Generating Action Plans...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_report = os.path.join(config.REPORTS_DIR, f"report_{timestamp}.csv")
    json_report = os.path.join(config.REPORTS_DIR, f"report_{timestamp}.json")
    
    scanner.export_reports(csv_report, json_report)
    
    # Phase 3: Analytics Layer
    logger.info("Phase 3: Generating Analytics Intelligence...")
    dashboard = ReportsDashboard(scanner.records)
    dashboard.generate_intelligence()
    dashboard.export()
    
    # Phase 4: Remediation Action Planning
    logger.info("Phase 4: Creating Remediation Action Plan...")
    remediation = RemediationEngine(scanner.records)
    action_plan = remediation.process()
    
    # Save Rollback and Batches
    rollback_file = os.path.join(config.REMEDIATION_DIR, f"rollback_plan_{timestamp}.json")
    simulation_file = os.path.join(config.REMEDIATION_DIR, f"simulation_view_{timestamp}.txt")
    
    RollbackManager.create_plan(action_plan, rollback_file)
    BatchPlanner.create_batches(action_plan, config.REMEDIATION_DIR)
    RenameSimulator.generate_view(action_plan, simulation_file)
    
    logger.info(f"Remediation plans generated in {config.REMEDIATION_DIR}")
    
    # Phase 5: Media Offloading
    logger.info("Phase 5: Planning Media Offload...")
    media_manager = MediaManager(root_to_scan)
    media_move_plan = media_manager.plan_offload(scanner.records)
    
    manifest_file = os.path.join(config.REMEDIATION_DIR, f"media_offload_manifest_{timestamp}.csv")
    media_manager.generate_manifest(manifest_file)
    
    if not config.DRY_RUN and media_move_plan:
        logger.info(f"Ready to move {len(media_move_plan)} media files. Waiting for API trigger.")
    
    # Summary
    logger.info("=== Execution Summary ===")
    logger.info(f"Total Files: {stats['total_files']}")
    logger.info(f"Total Folders: {stats['total_folders']}")
    logger.info(f"Long Paths: {stats['long_paths']}")
    logger.info(f"Excessive Depth: {stats['excessive_depth']}")
    logger.info(f"Forbidden Chars: {stats['forbidden_chars']}")
    logger.info(f"Possible Duplicates: {stats['duplicates']}")
    
    logger.info("[!] Execution finished successfully.")
    
    media_breakdown, media_files = categorize_media(media_move_plan or [])

    # Atualiza o relatório JSON com as mídias categorizadas para persistência
    try:
        if os.path.exists(json_report):
            with open(json_report, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
            if isinstance(report_data, dict):
                report_data["media_breakdown"] = media_breakdown
                report_data["media_files"] = media_files
                with open(json_report, 'w', encoding='utf-8') as f:
                    json.dump(report_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to update JSON report with media categorization: {e}")

    return {
        "stats": stats,
        "reports": {
            "csv": csv_report,
            "json": json_report
        },
        "media_move_plan_count": len(media_move_plan) if media_move_plan else 0,
        "media_breakdown": media_breakdown,
        "media_files": media_files
    }


MEDIA_CATEGORIES = {
    "imagens": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"},
    "audio":   {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"},
    "video":   {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv"},
}


def categorize_media(move_plan):
    summary = {key: {"count": 0, "extensions": {}} for key in MEDIA_CATEGORIES}
    summary["outros"] = {"count": 0, "extensions": {}}
    files = []

    for item in move_plan:
        ext = (item.get("extension") or "").lower()
        bucket = "outros"
        for category, exts in MEDIA_CATEGORIES.items():
            if ext in exts:
                bucket = category
                break
        summary[bucket]["count"] += 1
        summary[bucket]["extensions"][ext] = summary[bucket]["extensions"].get(ext, 0) + 1

        files.append({
            "category": bucket,
            "name": item.get("file_name"),
            "path": item.get("original_path"),
            "extension": ext,
            "source_folder": item.get("source_folder")
        })

    return summary, files

def execute_media_move(root_to_scan: str):
    media_manager = MediaManager(root_to_scan)
    scanner = ScannerService(root_dir=root_to_scan)
    scanner.scan_directory()
    media_manager.plan_offload(scanner.records)
    media_manager.execute_move()
    return True

if __name__ == "__main__":
    run_pipeline(".")
