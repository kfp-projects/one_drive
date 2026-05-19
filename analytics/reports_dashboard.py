import json
import csv
import os
from datetime import datetime
from typing import List, Dict, Any

from config import config
from utils.logger import setup_logger
from analytics.path_statistics import PathStatistics
from analytics.folder_depth_analysis import FolderDepthAnalysis
from analytics.duplicate_analysis import DuplicateAnalysis
from analytics.naming_patterns import NamingPatterns

logger = setup_logger("analytics")

class ReportsDashboard:
    """
    Facade class that orchestrates all analytics modules and exports intelligence.
    """
    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records
        self.intelligence = {}

    def generate_intelligence(self):
        """Runs all analytics engines."""
        logger.info("Gerando Inteligência Analítica...")
        
        self.intelligence["path_statistics"] = PathStatistics.analyze(self.records)
        self.intelligence["folder_depth"] = FolderDepthAnalysis.analyze(self.records)
        self.intelligence["duplicate_analysis"] = DuplicateAnalysis.analyze(self.records)
        self.intelligence["naming_patterns"] = NamingPatterns.analyze(self.records)

        # Novas métricas em PT-BR
        self.intelligence["distribuicao_estrutural"] = self._analyze_structural_distribution()
        self.intelligence["categorias_de_arquivos"] = self._analyze_file_categories()
        self.intelligence["nomes_descritivos_longos"] = sum(
            1 for r in self.records if r.get("nome_descritivo_longo")
        )

        return self.intelligence

    def _analyze_file_categories(self) -> Dict[str, Any]:
        """Categoriza arquivos por tipo para inteligência de backup e organização."""
        categories = {
            "IMAGENS": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"],
            "AUDIO": [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"],
            "VIDEOS": [".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv"],
            "PROGRAMAS": [".exe", ".msi", ".bat", ".cmd", ".sh", ".com"],
            "BACKUPS": [".zip", ".rar", ".7z", ".bak", ".tar", ".gz", ".iso"],
            "INSTALACOES": ["setup", "install", "installer", "configurador"]
        }
        
        counts = {cat: 0 for cat in categories}
        counts["OUTROS"] = 0
        
        for r in self.records:
            ext = r.get("extension", "").lower()
            name = r.get("original_name", "").lower()
            found = False
            
            # Check by extension
            for cat, exts in categories.items():
                if cat != "INSTALACOES" and ext in exts:
                    counts[cat] += 1
                    found = True
                    break
            
            # Check by pattern (Installations)
            if not found:
                for pattern in categories["INSTALACOES"]:
                    if pattern in name:
                        counts["INSTALACOES"] += 1
                        found = True
                        break
            
            if not found:
                counts["OUTROS"] += 1
                
        return counts

    def _analyze_structural_distribution(self) -> Dict[str, Any]:
        """Calcula a distribuição entre documentos de negócio e lixo técnico."""
        distribution = {}
        for r in self.records:
            cls = r.get("classification", "UNKNOWN")
            distribution[cls] = distribution.get(cls, 0) + 1
            
        total = len(self.records)
        percentages = {k: round((v / total) * 100, 2) for k, v in distribution.items()}
        
        return {
            "contagem": distribution,
            "percentual": percentages
        }

    def generate_structural_suggestions(self) -> List[str]:
        """Gera sugestões automáticas baseadas nas métricas em PT-BR."""
        suggestions = []
        
        # Profundidade
        avg_depth = self.intelligence.get("folder_depth", {}).get("average_depth", 0)
        if avg_depth > 5:
            suggestions.append(f"SUGESTÃO: Sua profundidade média de pastas é {avg_depth}. Considere achatar a estrutura para evitar erros de limite de caracteres do Windows.")
            
        # Poluição
        pollution = self.intelligence.get("duplicate_analysis", {}).get("overall_pollution_rate", 0)
        if pollution > 10:
            suggestions.append(f"SUGESTÃO: {pollution}% dos arquivos usam termos como 'final' ou 'copia'. Considere adotar um histórico de versões oficial.")
            
        # Repetição
        repetition = self.intelligence.get("naming_patterns", {}).get("top_repetitive_structures", {})
        if repetition:
            top_rep = list(repetition.keys())[0] if repetition else "Nenhuma"
            suggestions.append(f"SUGESTÃO: Detectada redundância estrutural (ex: {top_rep}). O sistema removerá isso automaticamente.")
            
        return suggestions

    def export(self):
        """Exporta os relatórios analíticos em formatos JSON, CSV e TXT (PT-BR)."""
        os.makedirs(config.ANALYTICS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. Exportação JSON
        json_path = os.path.join(config.ANALYTICS_DIR, f"analytics_{timestamp}.json")
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(self.intelligence, f, indent=2, ensure_ascii=False)
            logger.info(f"Analytics JSON gerado: {json_path}")
        except Exception as e:
            logger.error(f"Falha ao escrever JSON: {e}")

        # 2. Exportação TXT Summary (PT-BR)
        txt_path = os.path.join(config.ANALYTICS_DIR, f"sumario_{timestamp}.txt")
        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write("=== SANEAMENTO DE DOCUMENTOS CORPORATIVOS: SUMÁRIO ANALÍTICO ===\n")
                f.write(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
                
                f.write("[ESTATÍSTICAS DE CAMINHO]\n")
                stats = self.intelligence.get("path_statistics", {})
                f.write(f"- Total de Itens Analisados: {stats.get('total_items_analyzed', 0)}\n")
                f.write(f"- Violações Críticas de Tamanho: {stats.get('critical_path_length_violations', 0)}\n\n")

                f.write("[CATEGORIAS DE ARQUIVOS (BACKUP)]\n")
                cats = self.intelligence.get("categorias_de_arquivos", {})
                for cat, count in cats.items():
                    f.write(f"- {cat}: {count} arquivos\n")
                f.write("\n")

                f.write("[DISTRIBUIÇÃO ESTRUTURAL]\n")
                dist = self.intelligence.get("distribuicao_estrutural", {})
                for cls, pct in dist.get("percentual", {}).items():
                    count = dist.get("contagem", {}).get(cls, 0)
                    f.write(f"- {cls}: {pct}% ({count} itens)\n")
                f.write("\n")
                
                f.write("[SUGESTÕES DE MELHORIA]\n")
                for sug in self.generate_structural_suggestions():
                    f.write(f"- {sug}\n")
                    
            logger.info(f"Sumário TXT gerado: {txt_path}")
        except Exception as e:
            logger.error(f"Falha ao escrever TXT: {e}")
            
        # 3. Exportação CSV (Caminhos mais profundos)
        csv_path = os.path.join(config.ANALYTICS_DIR, f"caminhos_profundos_{timestamp}.csv")
        try:
            top_paths = self.intelligence.get("folder_depth", {}).get("top_100_deepest_folders", [])
            if top_paths:
                with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=["path", "depth"])
                    writer.writeheader()
                    writer.writerows(top_paths)
                logger.info(f"Analytics CSV gerado: {csv_path}")
        except Exception as e:
            logger.error(f"Falha ao escrever CSV: {e}")
