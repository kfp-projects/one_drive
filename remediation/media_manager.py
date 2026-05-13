import os
import shutil
import csv
from datetime import datetime
from typing import List, Dict, Any
from config import config

class MediaManager:
    """
    Identifies and plans the move of heavy media files to a central root directory.
    """
    
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.offload_dir = os.path.join(root_dir, config.MEDIA_OFFLOAD_DIR)
        self.move_plan: List[Dict[str, str]] = []

    def plan_offload(self, scanner_records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """
        Scans records for media files in target folders and creates a move plan.
        """
        print(f"[*] Planning media offload for {len(scanner_records)} records...")
        
        for record in scanner_records:
            full_path = record["full_path"]
            ext = os.path.splitext(full_path)[1].lower()
            
            # Check if it's a media file
            if ext not in config.MEDIA_EXTENSIONS:
                continue
                
            # Check if it's from a target folder
            path_parts = [p.lower() for p in os.path.normpath(full_path).split(os.sep)]
            source_folder = None
            for target in config.MEDIA_OFFLOAD_SOURCES:
                if target in path_parts:
                    source_folder = target
                    break
            
            if not source_folder:
                continue
            
            # Plan destination
            relative_name = os.path.basename(full_path)
            # Create a subfolder in offload_dir based on the source folder
            dest_subfolder = os.path.join(self.offload_dir, source_folder.upper())
            dest_path = os.path.join(dest_subfolder, relative_name)
            
            self.move_plan.append({
                "original_path": full_path,
                "new_path": dest_path,
                "source_folder": source_folder.upper(),
                "file_name": relative_name,
                "extension": ext
            })
            
        print(f"[+] Media offload plan created: {len(self.move_plan)} files to move.")
        return self.move_plan

    def generate_manifest(self, output_path: str):
        """
        Generates a CSV manifest of the proposed/executed move.
        """
        if not self.move_plan:
            return

        headers = ["original_path", "new_path", "source_folder", "file_name", "timestamp"]
        timestamp = datetime.now().isoformat()
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                for item in self.move_plan:
                    row = item.copy()
                    row["timestamp"] = timestamp
                    # Remove keys not in headers
                    row = {k: v for k, v in row.items() if k in headers}
                    writer.writerow(row)
            print(f"[+] Media manifest generated: {output_path}")
        except Exception as e:
            print(f"[-] Error generating media manifest: {e}")

    def execute_move(self):
        """
        Performs the actual file movement.
        ONLY RUN IF DRY_RUN IS FALSE.
        """
        if config.DRY_RUN:
            print("[!] DRY_RUN is active. Skipping physical move.")
            return

        print(f"[*] Executing move of {len(self.move_plan)} media files...")
        success_count = 0
        
        for item in self.move_plan:
            src = item["original_path"]
            dst = item["new_path"]
            
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                # Using shutil.move to handle cross-device moves if necessary
                shutil.move(src, dst)
                success_count += 1
            except Exception as e:
                print(f"[-] Failed to move {src}: {e}")
                
        print(f"[#] Move completed. {success_count} files moved successfully.")
