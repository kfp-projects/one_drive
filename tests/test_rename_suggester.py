"""
Testes para os helpers determinísticos do rename_suggester:
- preservar_sufixo_duplicata: mantém "(1)/(2)/(3)" pra não colidir cópias.
- annotate_collisions: marca arquivos da mesma pasta com nome sugerido igual.

Não testam a chamada ao Gemini (essa exige API/rede) — só a lógica pura.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remediation.rename_suggester import (
    preservar_sufixo_duplicata,
    annotate_collisions,
)


class TestPreservarSufixoDuplicata(unittest.TestCase):

    def test_preserva_sufixo_quando_original_tem(self):
        out = preservar_sufixo_duplicata(
            "Documento Longo Original (2).pdf", "Doc Curto.pdf"
        )
        self.assertEqual(out, "Doc Curto (2).pdf")

    def test_sem_sufixo_no_original_nao_muda(self):
        out = preservar_sufixo_duplicata(
            "Documento Longo Original.pdf", "Doc Curto.pdf"
        )
        self.assertEqual(out, "Doc Curto.pdf")

    def test_nao_duplica_se_sugerido_ja_tem_numero(self):
        out = preservar_sufixo_duplicata(
            "Original (3).pdf", "Doc Curto (3).pdf"
        )
        self.assertEqual(out, "Doc Curto (3).pdf")

    def test_sugerido_vazio_retorna_vazio(self):
        self.assertEqual(preservar_sufixo_duplicata("X (1).pdf", ""), "")


class TestAnnotateCollisions(unittest.TestCase):

    def test_marca_colisao_mesma_pasta_mesmo_nome(self):
        results = [
            {"full_path": r"C:\docs\a.pdf", "nome_sugerido": "Cobranca BB.pdf"},
            {"full_path": r"C:\docs\b.pdf", "nome_sugerido": "Cobranca BB.pdf"},
            {"full_path": r"C:\docs\c.pdf", "nome_sugerido": "Outro Nome.pdf"},
        ]
        annotate_collisions(results)
        self.assertTrue(results[0]["collision"])
        self.assertTrue(results[1]["collision"])
        self.assertEqual(results[0]["collision_count"], 2)
        self.assertFalse(results[2]["collision"])

    def test_pastas_diferentes_nao_colidem(self):
        results = [
            {"full_path": r"C:\docs\x\a.pdf", "nome_sugerido": "Mesmo Nome.pdf"},
            {"full_path": r"C:\docs\y\b.pdf", "nome_sugerido": "Mesmo Nome.pdf"},
        ]
        annotate_collisions(results)
        self.assertFalse(results[0]["collision"])
        self.assertFalse(results[1]["collision"])

    def test_case_insensitive(self):
        results = [
            {"full_path": r"C:\docs\a.pdf", "nome_sugerido": "Nota Fiscal.pdf"},
            {"full_path": r"C:\docs\b.pdf", "nome_sugerido": "NOTA FISCAL.pdf"},
        ]
        annotate_collisions(results)
        self.assertTrue(results[0]["collision"])
        self.assertTrue(results[1]["collision"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
