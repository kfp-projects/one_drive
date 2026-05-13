import json
import os
from typing import List, Dict, Any

class BatchPlanner:
    """
    Organizes remediation actions into manageable batches based on risk and action types.
    """
    
    @staticmethod
    def create_batches(action_plan: List[Dict[str, Any]], output_dir: str):
        """
        Groups actions by category and saves them into separate batch files.
        """
        batches = {
            "AUTO_FIX_SAFE": [],
            "SUGGEST_RENAME": [],
            "MANUAL_REVIEW": [],
            "CRITICAL_RESTRUCTURE": []
        }
        
        for item in action_plan:
            action = item.get("action")
            if action in batches:
                batches[action].append(item)
                
        for action_type, items in batches.items():
            if not items:
                continue
                
            batch_filename = f"batch_{action_type.lower()}.json"
            batch_path = os.path.join(output_dir, batch_filename)
            
            with open(batch_path, 'w', encoding='utf-8') as f:
                json.dump(items, f, indent=2, ensure_ascii=False)
            
            print(f"[+] Batch created: {batch_filename} ({len(items)} items)")