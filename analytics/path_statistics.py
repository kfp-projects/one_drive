from typing import List, Dict, Any
from pathlib import Path

class PathStatistics:
    @staticmethod
    def analyze(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculates general path statistics and department risks."""
        if not records:
            return {}

        long_paths_count = sum(1 for r in records if r["path_length"] > 255)
        
        # Risk by Department (Top level folder after root)
        department_risks = {}
        for r in records:
            parts = Path(r["full_path"]).parts
            if len(parts) > 1:
                # Assuming root is parts[0], department is parts[1]
                dept = parts[1]
                if dept not in department_risks:
                    department_risks[dept] = {"issues": 0, "total": 0}
                
                department_risks[dept]["total"] += 1
                if r["risk_level"] in ["HIGH", "CRITICAL"]:
                    department_risks[dept]["issues"] += 1

        # Calculate high risk departments
        for dept in department_risks:
            total = department_risks[dept]["total"]
            issues = department_risks[dept]["issues"]
            department_risks[dept]["risk_percentage"] = (issues / total) * 100 if total > 0 else 0

        # Sort departments by issue count descending
        sorted_depts = dict(sorted(department_risks.items(), key=lambda item: item[1]["issues"], reverse=True))

        return {
            "total_items_analyzed": len(records),
            "critical_path_length_violations": long_paths_count,
            "department_risk_profile": sorted_depts
        }
