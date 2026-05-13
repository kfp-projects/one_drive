from typing import List, Dict, Any
from pathlib import Path

class FolderDepthAnalysis:
    @staticmethod
    def analyze(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyzes folder depths, calculates averages, and ranks the deepest."""
        if not records:
            return {}

        depths = []
        path_depth_map = []

        for r in records:
            parts = Path(r["full_path"]).parts
            depth = len(parts)
            depths.append(depth)
            
            # Keep only directories for depth mapping, or infer from file
            dir_path = str(Path(r["full_path"]).parent)
            path_depth_map.append({"path": dir_path, "depth": depth - 1})

        # Remove duplicate directory entries
        unique_paths = {p["path"]: p["depth"] for p in path_depth_map}
        
        avg_depth = sum(depths) / len(depths) if depths else 0
        
        # Sort and get top 100 deepest
        sorted_paths = sorted(unique_paths.items(), key=lambda item: item[1], reverse=True)
        top_100_deepest = [{"path": p[0], "depth": p[1]} for p in sorted_paths[:100]]

        return {
            "average_depth": round(avg_depth, 2),
            "max_depth_found": max(depths) if depths else 0,
            "top_100_deepest_folders": top_100_deepest
        }
