import re
import json
import os
from typing import Dict, Any, List

class SemanticNamingEngine:
    """
    Implements corporate semantic naming intelligence.
    Transforms messy names into human-readable corporate standards.
    """
    
    def __init__(self, style_guide_path: str):
        with open(style_guide_path, 'r', encoding='utf-8') as f:
            self.style = json.load(f)
            
        # Expanded stop words for PT-BR and EN
        self.stop_words = {
            "o", "a", "os", "as", "um", "uma", "uns", "umas",
            "de", "da", "do", "das", "dos", "para", "com", "em", "por", "que", "ao", "aos", "no", "na", "nos", "nas",
            "the", "a", "an", "of", "for", "with", "in", "by", "and", "e", "on", "at", "to", "from", "is", "are",
            "fazem", "parte", "fazer", "esta", "estao", "ser"
        }

    def apply_corporate_style(self, name: str, extension: str) -> Dict[str, Any]:
        """
        Applies local heuristics to clean and style the name.
        """
        # 0. Initial Clean (Remove conversational starters from style guide)
        clean_name = name.lower()
        starters = self.style.get("forbidden_conversational_starters", [])
        for starter in starters:
            if clean_name.startswith(starter.lower()):
                clean_name = clean_name[len(starter):].strip()
        
        # 1. Title Case
        name = clean_name.title()
        
        # 2. Local Stop word removal (Heuristic)
        words = name.split()
        clean_words = []
        for word in words:
            # Check if word (lowered) is a stop word
            if word.lower() not in self.stop_words:
                clean_words.append(word)
        
        # If all words removed (unlikely), keep original
        if not clean_words:
            clean_words = words
            
        # 3. Join with separator
        new_name = self.style.get("separator", " ").join(clean_words)
        
        # 4. Remove redundant suffixes/prefixes from style guide
        for pattern in self.style.get("redundant_suffixes", []):
            # Case insensitive replace of full words
            new_name = re.sub(rf'\b{pattern}\b', '', new_name, flags=re.IGNORECASE)

        # 5. Max length enforcement
        max_len = self.style.get("max_length", 60)
        if len(new_name) > max_len:
            # Try to cut at last space
            if ' ' in new_name[:max_len]:
                new_name = new_name[:max_len].rsplit(' ', 1)[0]
            else:
                new_name = new_name[:max_len]
            
        # 6. Cleanup
        new_name = re.sub(r'\s+', ' ', new_name).strip()
        
        # 7. Restore Protected Terms Casing
        protected = self.style.get("protected_terms", [])
        for term in protected:
            # Match term even if it's followed by state code or preceded/followed by underscores
            # Catch KFP at start of word/string or after separator
            pattern = rf'({term})([A-Za-z]{{2}})?'
            
            def restore_case(match):
                prefix = match.group(1).upper()
                suffix = match.group(2).upper() if match.group(2) else ""
                return prefix + suffix

            new_name = re.sub(pattern, restore_case, new_name, flags=re.IGNORECASE)

        # 8. Final Name with Extension
        final_name = f"{new_name}{extension}"


        
        return {
            "suggested_name": final_name,
            "semantic_summary": "Extracted core business subject and removed conversational noise.",
            "confidence_score": self._calculate_confidence(name, new_name),
            "naming_reason": "Corporate Semantic Standard"
        }

    def remove_context_redundancy(self, name: str, parent_path: str) -> str:
        """
        Removes words from the file name that are already present in the IMMEDIATE parent folder.
        Ensures the file name doesn't become too generic.
        """
        base, ext = os.path.splitext(name)
        
        # Get only the immediate parent folder name
        parent_folder = os.path.basename(parent_path.strip(os.sep))
        parent_parts = set(re.split(r'[\s\-_]', parent_folder.lower()))
        
        name_parts = base.split()
        protected = [t.lower() for t in self.style.get("protected_terms", [])]
        
        clean_parts = []
        for word in name_parts:
            # Rule 1: NEVER remove protected terms
            is_protected = any(word.lower().startswith(p) for p in protected)
            if is_protected:
                clean_parts.append(word)
                continue
                
            # Rule 2: Only remove if the word is in the IMMEDIATE parent folder 
            # AND the filename is long enough to justify losing context (> 50 chars or > 6 words)
            if word.lower() in parent_parts and (len(base) > 50 or len(name_parts) > 6):
                # Potential redundancy, but check if we are leaving the name too empty
                # Also, never remove the very first word if it's part of the subject
                if name_parts.index(word) == 0 and word.lower() not in self.stop_words:
                    clean_parts.append(word)
                    continue

                remaining_significant_words = len([w for w in name_parts[name_parts.index(word)+1:] if w.lower() not in self.stop_words])
                if remaining_significant_words >= 3:
                    continue # Safe to remove
            
            clean_parts.append(word)
                
        # Safety: if we removed everything or made it too short, revert to original
        result_base = " ".join(clean_parts)
        if len(result_base) < 15 or len(clean_parts) < 3:
            return name
            
        return result_base + ext

    def _calculate_confidence(self, original: str, new: str) -> float:
        """
        Calculates confidence score (0-100).
        """
        if original.strip() == new.strip():
            return 100.0
            
        # If change is minor (mostly case and spacing)
        if original.lower().replace(" ", "") == new.lower().replace(" ", ""):
            return 98.0
            
        # If major reduction occurred
        ratio = len(new) / len(original) if len(original) > 0 else 1
        if ratio < 0.4:
            return 60.0
            
        return 85.0
