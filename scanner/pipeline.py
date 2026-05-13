import re
import json
import os
from config import config
from scanner.classifier import StructuralClassifier
from services.semantic_naming_engine import SemanticNamingEngine

class PipelineSim:
    """
    Simulates the AI skills using regex and python logic for local fast-processing.
    This acts as a placeholder before true LLM integration.
    """
    def __init__(self):
        self.abbreviations = {}
        self.forbidden_chars = []
        self.classifier = StructuralClassifier()
        self.semantic_engine = SemanticNamingEngine(config.STYLE_GUIDE_PATH)
        self._load_rules()

    def _load_rules(self):
        try:
            with open(os.path.join(config.RULES_DIR, "abbreviations.json"), 'r') as f:
                self.abbreviations = json.load(f)
            with open(os.path.join(config.RULES_DIR, "forbidden_chars.json"), 'r') as f:
                self.forbidden_chars = json.load(f).get("forbidden", [])
        except Exception as e:
            print(f"Warning: Could not load rules for pipeline: {e}")

    def normalize_name(self, name: str) -> str:
        """Simulates normalize_name.md skill - Corporate Standard"""
        base, ext = os.path.splitext(name)
        
        # Detect if user deliberately uses snake_case
        prefers_snake_case = '_' in base and ' ' not in base
        
        # Remove emojis/special chars, internal dots, and commas
        # Replace with space initially, we will fix the separator later
        for char in ['~', '#', '%', '&', '*', '{', '}', '\\', ':', '<', '>', '?', '/', '|', '"', ',', '.']:
            base = base.replace(char, ' ')
            
        # If it was snake_case, the previous step didn't touch '_' yet. 
        # But we want to treat '_' as a separator too.
        if not prefers_snake_case:
            base = base.replace('_', ' ')
            
        # Remove (1), (2), - copy, - copia
        base = re.sub(r'\(\d+\)', '', base)
        base = re.sub(r'(?i)\s*-\s*copia', '', base)
        base = re.sub(r'(?i)\s*-\s*copy', '', base)
        
        # Replace multiple spaces with one space, then trim
        base = re.sub(r'\s+', ' ', base).strip()
        
        # Title Case as per corporate standard
        base = base.title()
        
        # If snake_case was preferred, restore it
        if prefers_snake_case:
            base = base.replace(' ', '_')
            
        return base + ext


    def abbreviation_engine(self, name: str) -> str:
        """Simulates abbreviation_engine.md skill"""
        base, ext = os.path.splitext(name)
        
        for word, abbrev in self.abbreviations.items():
            pattern = re.compile(rf'\b{word}\b', re.IGNORECASE)
            base = pattern.sub(abbrev, base)
            
        return base + ext

    def process(self, original_name: str, full_path: str) -> dict:
        """Runs the simulated pipeline to generate a suggested name and semantic metadata"""
        # 1. Structural Classification
        classification_data = self.classifier.classify(full_path)
        
        # 2. Technical Normalization
        normalized = self.normalize_name(original_name)
        base_norm, ext = os.path.splitext(normalized)
        
        # 3. Semantic Intelligence (Reduction & Styling)
        semantic_result = self.semantic_engine.apply_corporate_style(base_norm, ext)
        
        # 4. Context Awareness (Remove redundancy with parent folders)
        parent_dir = os.path.dirname(full_path)
        final_suggested = self.semantic_engine.remove_context_redundancy(
            semantic_result["suggested_name"], 
            parent_dir
        )
        
        # 5. Abbreviation Engine (Final polish)
        suggested = self.abbreviation_engine(final_suggested)
        
        return {
            "suggested_name": suggested,
            "classification": classification_data["classification"],
            "structural_score": classification_data["score"],
            "semantic_summary": semantic_result["semantic_summary"],
            "confidence_score": semantic_result["confidence_score"],
            "naming_reason": semantic_result["naming_reason"],
            "context_analysis": f"Removed redundancy from parent path: {os.path.basename(parent_dir)}"
        }


