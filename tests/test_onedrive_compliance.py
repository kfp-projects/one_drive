"""
Testes mínimos do módulo de conformidade OneDrive.

Rodar com:  python -m unittest tests.test_onedrive_compliance
        ou  python tests/test_onedrive_compliance.py
"""

import os
import sys
import unittest

# Permite rodar o arquivo direto sem instalar como pacote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from remediation.onedrive_compliance import analyze, _is_suspicious_double_extension


class TestDoubleExtension(unittest.TestCase):
    """Extensão dupla: datas/siglas NÃO são falsos positivos; reais são pegas."""

    def test_data_nao_e_extensao_dupla(self):
        self.assertFalse(_is_suspicious_double_extension("CONTAGEM KFP-BA - 15.05.xlsx"))

    def test_siglas_nao_sao_extensao_dupla(self):
        self.assertFalse(_is_suspicious_double_extension("CAIXA 05 2026 - PE.CE.AL.BA.xlsm"))

    def test_executavel_disfarcado_e_flagado(self):
        self.assertTrue(_is_suspicious_double_extension("nota.pdf.exe"))
        self.assertTrue(_is_suspicious_double_extension("foto.jpg.scr"))

    def test_dupla_real_txt_txt(self):
        self.assertTrue(_is_suspicious_double_extension("EFD.042026.x.txt.txt"))

    def test_extensao_simples_ok(self):
        self.assertFalse(_is_suspicious_double_extension("relatorio.pdf"))


class TestOneDriveCompliance(unittest.TestCase):

    # 1) Arquivo conforme → não tocar
    def test_1_arquivo_conforme_mantem_original(self):
        result = analyze("7011DANFE.pdf", "C:/Pasta/7011DANFE.pdf")
        self.assertFalse(result["tem_violacao"])
        self.assertEqual(result["acao"], "Manter Original")
        self.assertEqual(result["nome_sugerido"], "7011DANFE.pdf")
        self.assertIsNone(result["risco"])
        self.assertIsNone(result["confianca"])

    # 2) Caractere proibido → substituição por underscore, risco Baixo, 100%
    def test_2_caractere_proibido(self):
        result = analyze("relatorio:final.docx", "C:/Pasta/relatorio:final.docx")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("C", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "relatorio_final.docx")
        self.assertEqual(result["risco"], "Baixo")
        self.assertEqual(result["confianca"], "100%")
        self.assertEqual(result["acao"], "Renomear Automaticamente")

    # 3) Nome reservado → sufixo _arquivo, risco Baixo
    def test_3_nome_reservado(self):
        result = analyze("CON.txt", "C:/Pasta/CON.txt")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("D", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "CON_arquivo.txt")
        self.assertEqual(result["risco"], "Baixo")

    # 4) Espaço no fim do nome base (antes da extensão) → trim aplicado
    def test_4_espaco_no_fim_do_base(self):
        result = analyze("arquivo .pdf", "C:/Pasta/arquivo .pdf")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("E", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "arquivo.pdf")
        self.assertEqual(result["risco"], "Baixo")

    # 5) Nome com mais de 255 caracteres → truncado para caber em 250
    def test_5_nome_muito_longo(self):
        base = "a" * 300  # 300 'a' + .pdf = 304 chars
        name = base + ".pdf"
        result = analyze(name, f"C:/Pasta/{name}")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("A", result["violacoes_detectadas"])
        self.assertLessEqual(len(result["nome_sugerido"]), 250)
        self.assertTrue(result["nome_sugerido"].endswith(".pdf"))
        self.assertEqual(result["risco"], "Médio")
        self.assertEqual(result["confianca"], "95%")

    # 6) Caminho com mais de 400 chars
    def test_6_caminho_muito_longo_com_correcao_possivel(self):
        # Pasta de 300 chars + arquivo de 160 chars = 460 total
        folder = "C:/" + "x" * 297  # 300 chars
        base = "y" * 156
        name = base + ".pdf"  # 160 chars de nome
        full = folder + "/" + name  # 461 chars
        result = analyze(name, full)
        self.assertTrue(result["tem_violacao"])
        self.assertIn("B", result["violacoes_detectadas"])
        # Caminho final deve estar abaixo do limite
        self.assertLessEqual(len(result["caminho_sugerido"]), 400)

    def test_6b_caminho_inviavel_mantem_original(self):
        # Pasta tão longa que não dá pra salvar truncando só o nome
        folder = "C:/" + "x" * 390  # 393 chars
        name = "doc.pdf"  # só 7 chars
        full = folder + "/" + name  # 401 chars — passa de 400
        result = analyze(name, full)
        self.assertTrue(result["tem_violacao"])
        self.assertEqual(result["acao"], "Manter Original")
        self.assertIn("reorganização", result["motivo"].lower())

    # 7) Dupla extensão (caso típico — erro de digitação)
    def test_7_dupla_extensao_typo(self):
        result = analyze("CONTROLE SUPERMERCADO EXTRA.xl.xlsx",
                         "C:/Pasta/CONTROLE SUPERMERCADO EXTRA.xl.xlsx")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("F", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "CONTROLE SUPERMERCADO EXTRA.xlsx")
        self.assertEqual(result["risco"], "Baixo")

    # 8) Extensão composta legítima (.tar.gz) → não tocar (whitelist)
    def test_8_tar_gz_e_whitelist(self):
        result = analyze("backup.tar.gz", "C:/Pasta/backup.tar.gz")
        self.assertFalse(result["tem_violacao"])
        self.assertEqual(result["acao"], "Manter Original")

    # 9) Disfarce malicioso clássico (foto.jpg.exe) → remove .jpg interno
    def test_9_disfarce_malicioso(self):
        result = analyze("foto.jpg.exe", "C:/Pasta/foto.jpg.exe")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("F", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "foto.exe")

    # 10) F revela nome reservado → aplica D em sequência
    def test_10_f_revela_reservado(self):
        # 'CON.xl.txt' → após F vira 'CON.txt' → reservado → 'CON_arquivo.txt'
        result = analyze("CON.xl.txt", "C:/Pasta/CON.xl.txt")
        self.assertTrue(result["tem_violacao"])
        self.assertIn("F", result["violacoes_detectadas"])
        self.assertIn("D", result["violacoes_detectadas"])
        self.assertEqual(result["nome_sugerido"], "CON_arquivo.txt")

    # 11) Arquivo simples sem extensão dupla → não dispara F
    def test_11_extensao_simples(self):
        result = analyze("documento.pdf", "C:/Pasta/documento.pdf")
        self.assertFalse(result["tem_violacao"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
