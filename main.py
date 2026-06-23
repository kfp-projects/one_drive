import os
from datetime import datetime
from config import config
from utils.logger import setup_logger
from scanner.scanner import ScannerService
from analytics.reports_dashboard import ReportsDashboard
from utils.cleanup import cleanup_old_results


logger = setup_logger("main")


def run_pipeline(root_to_scan: str = "."):
    """Pipeline enxuto: limpa, escaneia, exporta relatório e gera analytics.

    A remediação (renomeação) é um passo SEPARADO e sob demanda, via a API de
    rename (remediation/rename_suggester) — não faz parte do scan.
    """
    logger.info("=== Organiza — PIPELINE START ===")
    cleanup_old_results()
    logger.info(f"Target directory: {root_to_scan}")

    scanner = ScannerService(root_dir=root_to_scan)

    logger.info("Phase 1: Scanning & analyzing (OneDrive compliance)...")
    stats = scanner.scan_directory()

    logger.info("Phase 2: Exporting reports...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_report = os.path.join(config.REPORTS_DIR, f"report_{timestamp}.csv")
    json_report = os.path.join(config.REPORTS_DIR, f"report_{timestamp}.json")
    scanner.export_reports(csv_report, json_report)

    logger.info("Phase 3: Generating analytics intelligence...")
    dashboard = ReportsDashboard(scanner.records)
    dashboard.generate_intelligence()
    dashboard.export()

    logger.info("=== Execution Summary ===")
    logger.info(f"Files: {stats['total_files']} | Folders: {stats['total_folders']} "
                f"| Long paths: {stats.get('long_paths', 0)} "
                f"| Descriptive names: {stats.get('nomes_descritivos_longos', 0)}")
    logger.info("[!] Finished successfully.")

    return {
        "stats": stats,
        "reports": {"csv": csv_report, "json": json_report},
    }


if __name__ == "__main__":
    run_pipeline(".")
