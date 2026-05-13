import json
import os
from datetime import datetime
from typing import List, Dict, Any

class RollbackManager:
    """
    Manages the creation and tracking of rollback plans for reversibility.
    """
    
    @staticmethod
    def create_plan(action_plan: List[Dict[str, Any]], output_path: str):
        """
        Saves the action plan as a rollback JSON file.
        """
        rollback_data = {
            "timestamp": datetime.now().isoformat(),
            "total_actions": len(action_plan),
            "plan": action_plan
        }
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(rollback_data, f, indent=2, ensure_ascii=False)
            print(f"[+] Rollback plan saved: {output_path}")
        except Exception as e:
            print(f"[-] Error saving rollback plan: {e}")