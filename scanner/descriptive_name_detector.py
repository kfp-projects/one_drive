"""
Detector determinístico de "nomes descritivos longos" (frases inteiras usadas
como nome de arquivo).

Fase de DETECÇÃO apenas — não chama IA, não gera sugestão de renomeação.

Um nome é classificado como "descritivo longo" se TODAS as três condições
abaixo são verdadeiras (em conjunção):

1. Nome sem extensão tem MAIS DE 50 caracteres.
2. Nome contém MAIS DE 6 palavras (separadores: espaço, hífen, underscore).
3. Nome contém PELO MENOS UMA stopword portuguesa usada como CONECTIVO DE
   PROSA — stopwords escritas em CAIXA ALTA não contam (ex.: o "DO" de
   "BANCO DO BRASIL" ou o "DE" de "DERIVADOS DE PETROLEO" fazem parte de um
   nome próprio / registro estruturado, não de uma frase descritiva).

Se qualquer condição falha, o resultado é False. Curto-circuito.
"""

import os
from config import config
from rules.stopwords_pt import STOPWORDS_PT


def _eh_token_caixa_alta(token: str) -> bool:
    """True se o token tem letras e TODAS estão em maiúsculo (nome próprio/sigla).

    Ex.: 'DO' -> True, 'da' -> False, 'Da' -> False, '347a' -> False (tem
    minúscula), '(1)' -> False (sem letra).
    """
    if not any(c.isalpha() for c in token):
        return False
    return token == token.upper()


def _dividir_em_palavras(texto: str, separadores) -> list[str]:
    """Divide o texto por qualquer um dos separadores, removendo strings vazias."""
    # Normaliza todos os separadores em um único caractere antes de split
    # — mais simples do que regex pra esse caso.
    normalizado = texto
    if separadores:
        primeiro = separadores[0]
        for sep in separadores[1:]:
            normalizado = normalizado.replace(sep, primeiro)
        partes = normalizado.split(primeiro)
    else:
        partes = [texto]
    return [p for p in partes if p]


def eh_nome_descritivo_longo(nome_arquivo: str) -> bool:
    """
    Retorna True se o nome se encaixa nas três condições do detector.
    nome_arquivo pode incluir extensão — ela é removida antes da análise.
    """
    if not nome_arquivo:
        return False

    # Remove extensão (ex: 'doc.docx' -> 'doc')
    nome_sem_ext, _ = os.path.splitext(nome_arquivo)
    if not nome_sem_ext:
        return False

    # Condição 1: comprimento
    if len(nome_sem_ext) <= config.LIMITE_CARACTERES_NOME_DESCRITIVO:
        return False

    # Condição 2: contagem de palavras
    palavras = _dividir_em_palavras(nome_sem_ext, config.SEPARADORES_PALAVRAS)
    if len(palavras) <= config.LIMITE_PALAVRAS_NOME_DESCRITIVO:
        return False

    # Condição 3: stopword usada como conectivo de prosa.
    # Uma stopword só conta se NÃO estiver em caixa alta — assim "BANCO DO
    # BRASIL", "DERIVADOS DE PETROLEO" e afins (registros estruturados) não
    # são confundidos com frases descritivas.
    tem_conectivo = any(
        p.lower() in STOPWORDS_PT and not _eh_token_caixa_alta(p)
        for p in palavras
    )
    if not tem_conectivo:
        return False

    return True
