import re
from collections import Counter
from typing import List, Dict, Any
from pathlib import Path

class NamingPatterns:
    # Common stop words to ignore during word ranking
    STOP_WORDS = {"de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "com", "na", "no", "os", "as"}

    @classmethod
    def analyze(cls, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyzes naming habits, most used words, and structural repetition."""
        if not records:
            return {}

        word_counter = Counter()
        structural_patterns = Counter()

        for r in records:
            # Word Ranking
            name = Path(r["original_name"]).stem
            # Tokenize by space, underscore, hyphen
            words = re.split(r'[_ \-]', name)
            for word in words:
                word_clean = word.strip().lower()
                if len(word_clean) > 2 and word_clean not in cls.STOP_WORDS:
                    word_counter[word_clean] += 1

            # Structural Repetition (e.g. Financeiro/Financeiro_Relatorio)
            parts = Path(r["full_path"]).parts
            if len(parts) >= 2:
                parent_dir = parts[-2].lower()
                if parent_dir in name.lower():
                    structural_patterns[f"Parent '{parent_dir}' repeated in file name"] += 1

        top_words = dict(word_counter.most_common(50))
        top_structural_issues = dict(structural_patterns.most_common(20))

        return {
            "top_50_used_words": top_words,
            "top_repetitive_structures": top_structural_issues
        }
