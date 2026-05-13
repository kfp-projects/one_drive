import os
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

def main():
    logger.info("=== Corporate Document Sanitation System V1 - PIPELINE START ===")
    
    # Cleanup Phase
    cleanup_old_results()

    
    # Target Configuration
    root_to_scan = input("Enter the path to scan (default is current dir): ") or "."
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
        confirm = input(f"Proceed with moving {len(media_move_plan)} media files? (y/N): ")
        if confirm.lower() == 'y':
            media_manager.execute_move()
    
    # Summary
    logger.info("=== Execution Summary ===")
    logger.info(f"Total Files: {stats['total_files']}")
    logger.info(f"Total Folders: {stats['total_folders']}")
    logger.info(f"Long Paths: {stats['long_paths']}")
    logger.info(f"Excessive Depth: {stats['excessive_depth']}")
    logger.info(f"Forbidden Chars: {stats['forbidden_chars']}")
    logger.info(f"Possible Duplicates: {stats['duplicates']}")
    
    print(f"\n[!] Execution finished successfully.")
    print(f"[!] CSV Report: {csv_report}")
    print(f"[!] JSON Report: {json_report}")

if __name__ == "__main__":
    main()
