"""
Stopwords portuguesas para a detecção de "nomes descritivos longos" (frases
inteiras usadas como nome de arquivo).

Lista intencionalmente CURTA — só palavras de ligação/conexão que sinalizam
estrutura de frase. Não inclui substantivos comuns.

Fonte única — qualquer mudança aqui afeta o detector em
scanner.descriptive_name_detector e o relatório do scanner.
"""

STOPWORDS_PT: frozenset[str] = frozenset({
    # Artigos definidos / indefinidos
    "a", "o", "as", "os", "um", "uma", "uns", "umas",

    # Preposições simples
    "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas",
    "com", "sem", "para", "por", "pelo", "pela", "pelos", "pelas",
    "ao", "aos",

    # Pronomes interrogativos / relativos
    "que", "qual", "quais",
    "como", "quando", "onde", "porque",

    # Conectivos
    "se", "e", "ou", "mas",

    # Demonstrativos
    "este", "esta", "estes", "estas",
    "esse", "essa", "esses", "essas",
    "isto", "isso", "aquilo",

    # Verbos auxiliares / cópula
    "ser", "é", "foi", "são", "está", "estão", "ter", "há",
})
