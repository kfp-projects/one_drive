"""
Testes para scanner.descriptive_name_detector.eh_nome_descritivo_longo.

Os 6 casos abaixo vêm direto do spec da fase de detecção.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner.descriptive_name_detector import eh_nome_descritivo_longo


class TestDescriptiveNameDetector(unittest.TestCase):

    def test_1_frase_inteira_com_stopwords(self):
        # 76 chars, 14 palavras, stopwords: como, os, aos, que, da, do
        nome = "Como fica os acessos aos números que fazem parte da do grupo da empresa.docx"
        self.assertTrue(eh_nome_descritivo_longo(nome))

    def test_2_nome_curto_falha_condicao_1(self):
        # "7011DANFE" tem 9 chars sem ext — falha no comprimento
        self.assertFalse(eh_nome_descritivo_longo("7011DANFE.pdf"))

    def test_3_curto_e_sem_stopword(self):
        # "Relatorio_Financeiro_Anual_2024" tem 31 chars sem ext — falha cond. 1
        # (e tb falha cond. 3, mas curto-circuito retorna na 1)
        self.assertFalse(eh_nome_descritivo_longo("Relatorio_Financeiro_Anual_2024.xlsx"))

    def test_4_curto_com_stopword(self):
        # "Contrato de Prestacao de Servicos" tem 33 chars sem ext — falha cond. 1
        # (mesmo tendo "de", o comprimento é insuficiente)
        self.assertFalse(eh_nome_descritivo_longo("Contrato de Prestacao de Servicos.docx"))

    def test_5_frase_longa_com_multiplas_stopwords(self):
        # 54 chars sem ext, 11 palavras, stopwords: da, com, o, sobre — wait,
        # 'sobre' não tá na lista. Tem 'da', 'com', 'o' — basta.
        nome = "Resumo da reuniao com o cliente sobre o projeto novo X.docx"
        self.assertTrue(eh_nome_descritivo_longo(nome))

    def test_6_longo_sem_stopword(self):
        # 57 chars sem ext, mas só 6 palavras → falha condição 2 (não > 6).
        # (Tb tem 'sem' como stopword, mas curto-circuito retorna na cond. 2.)
        nome = "ABCDEFGHIJKLMNOPQRSTUVWXYZ_muito_longo_sem_stopwords_aqui.pdf"
        self.assertFalse(eh_nome_descritivo_longo(nome))

    # Casos defensivos extras
    def test_7_nome_vazio(self):
        self.assertFalse(eh_nome_descritivo_longo(""))

    def test_8_so_extensao(self):
        # '.env' → splitext gera ('.env', '') — nome é '.env', 4 chars, falha cond. 1
        self.assertFalse(eh_nome_descritivo_longo(".env"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
