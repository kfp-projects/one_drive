import os
from typing import List, Dict, Any

class RenameSimulator:
    """
    Simulates the rename process by creating a human-readable visualization of changes.
    """
    
    @staticmethod
    def generate_view(action_plan: List[Dict[str, Any]], output_path: str):
        """
        Creates a text-based comparison (BEFORE -> AFTER) for the user to review.
        """
        lines = [
            "===========================================================",
            "REMEDIATION SIMULATION REPORT",
            "===========================================================\n",
            f"Total Actions Planned: {len(action_plan)}\n",
            "Classification Legend:",
            "  [SAFE]     - Automated fix recommended",
            "  [REVIEW]   - Semantic suggestion, needs verification",
            "  [CRITICAL] - High risk path or complex restructuring\n",
            "-----------------------------------------------------------"
        ]
        
        # Sort by action type for better readability
        sorted_plan = sorted(action_plan, key=lambda x: x['action'])
        
        for item in sorted_plan:
            action_tag = {
                "AUTO_FIX_SAFE": "[SAFE]  ",
                "SUGGEST_RENAME": "[REVIEW]",
                "MANUAL_REVIEW": "[REVIEW]",
                "CRITICAL_RESTRUCTURE": "[CRITIC]"
            }.get(item['action'], "[UNK]   ")
            
            lines.append(f"{action_tag} {item['original_name']}")
            lines.append(f"         -> {item['suggested_name']}")
            lines.append(f"         Reason: {item['reason']}")
            lines.append(f"         Path:   {item['full_path']}")
            lines.append("-" * 60)
            
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))
            print(f"[+] Simulation view generated: {output_path}")
        except Exception as e:
            print(f"[-] Error generating simulation view: {e}")