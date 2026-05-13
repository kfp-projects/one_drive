import re
from typing import List, Dict, Any

class DuplicateAnalysis:
    PATTERNS = {
        "os_copy_suffix": r'(?i)\(\d+\)|\s*-\s*c[oó]pia',
        "final_suffix": r'(?i)[_ \-]final\b',
        "atualizado_suffix": r'(?i)[_ \-]atualizado\b',
        "novo_suffix": r'(?i)[_ \-]novo\b',
        "versao_suffix": r'(?i)[_ \-]v\d+|[_ \-]vers[aã]o'
    }

    @classmethod
    def analyze(cls, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Detects patterns of bad file versioning/duplication."""
        if not records:
            return {}

        results = {pattern_name: 0 for pattern_name in cls.PATTERNS}
        total_files = sum(1 for r in records if r["extension"] != "DIR")
        
        for r in records:
            if r["extension"] == "DIR":
                continue
            
            name = r["original_name"]
            for pattern_name, regex in cls.PATTERNS.items():
                if re.search(regex, name):
                    results[pattern_name] += 1

        # Calculate percentages
        percentages = {
            k: round((v / total_files) * 100, 2) if total_files > 0 else 0 
            for k, v in results.items()
        }

        # Calculate "polluted" total
        polluted_count = sum(results.values())
        pollution_rate = round((polluted_count / total_files) * 100, 2) if total_files > 0 else 0

        return {
            "duplication_patterns_found": results,
            "duplication_percentages": percentages,
            "overall_pollution_rate": pollution_rate
        }
