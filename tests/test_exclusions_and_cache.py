"""
Testes para:
- ScannerService._is_excluded: pastas excluídas por nome ou caminho.
- load_cache: invalidação automática quando a versão do prompt muda.
"""

import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner.scanner import ScannerService
import remediation.rename_suggester as rs


class TestScannerExclusions(unittest.TestCase):

    def setUp(self):
        self.scanner = ScannerService(root_dir=".")

    def test_exclui_por_nome(self):
        self.scanner.excluded_names = {"nao mexer"}
        self.scanner.excluded_paths = []
        self.assertTrue(self.scanner._is_excluded("NAO MEXER", r"C:\x\NAO MEXER"))
        self.assertTrue(self.scanner._is_excluded("nao mexer", r"C:\y\nao mexer"))
        self.assertFalse(self.scanner._is_excluded("Financeiro", r"C:\x\Financeiro"))

    def test_exclui_por_caminho_e_conteudo(self):
        alvo = os.path.normcase(os.path.normpath(r"C:\dados\Backup Antigo"))
        self.scanner.excluded_names = set()
        self.scanner.excluded_paths = [alvo]
        # A própria pasta
        self.assertTrue(self.scanner._is_excluded("Backup Antigo", r"C:\dados\Backup Antigo"))
        # Conteúdo dentro dela
        self.assertTrue(self.scanner._is_excluded("sub", r"C:\dados\Backup Antigo\sub"))
        # Pasta de nome parecido mas fora do prefixo NÃO é excluída
        self.assertFalse(self.scanner._is_excluded("Backup Antigo 2", r"C:\dados\Backup Antigo 2"))


class TestCacheVersioning(unittest.TestCase):

    def setUp(self):
        self._orig = rs.RENAME_CACHE_FILE
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        self._tmp.close()
        rs.RENAME_CACHE_FILE = self._tmp.name

    def tearDown(self):
        rs.RENAME_CACHE_FILE = self._orig
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_cache_de_versao_antiga_e_descartado(self):
        # Grava um cache com versão diferente da atual.
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({"__prompt_version__": "v-antiga", "arq.docx|10": {"x": 1}}, f)
        loaded = rs.load_cache()
        self.assertNotIn("arq.docx|10", loaded)
        self.assertEqual(loaded["__prompt_version__"], rs.PROMPT_VERSION)

    def test_cache_da_versao_atual_e_mantido(self):
        with open(self._tmp.name, "w", encoding="utf-8") as f:
            json.dump({"__prompt_version__": rs.PROMPT_VERSION, "arq.docx|10": {"x": 1}}, f)
        loaded = rs.load_cache()
        self.assertIn("arq.docx|10", loaded)


if __name__ == "__main__":
    unittest.main(verbosity=2)
