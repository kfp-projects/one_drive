import logging
from typing import List, Dict, Any
from remediation.policy_engine import PolicyEngine

logger = logging.getLogger(__name__)

class RemediationEngine:
    """
    Core engine that transforms analysis records into a structured action plan.
    """
    
    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records
        self.action_plan = []

    def process(self) -> List[Dict[str, Any]]:
        """
        Processes all records and categorizes them into actionable items.
        """
        logger.info(f"Processing {len(self.records)} records for remediation...")
        
        for record in self.records:
            action = PolicyEngine.get_action_category(record)
            
            if action == "IGNORE":
                continue
                
            remediation_item = {
                "original_name": record["original_name"],
                "suggested_name": record["suggested_name"],
                "full_path": record["full_path"],
                "action": action,
                "confidence": record.get("confidence_score", 0),
                "reason": record.get("naming_reason", "Remediação padrão"),
                "classification": record.get("classification", "UNKNOWN"),
                "risk_score": record.get("risk_level", "LOW")
            }
            
            self.action_plan.append(remediation_item)
            
        logger.info(f"Remediation plan created with {len(self.action_plan)} actions.")
        return self.action_plan