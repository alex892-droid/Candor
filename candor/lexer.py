"""Lexer de Candor : transforme le texte source en une liste de jetons (tokens).

Aucune magie : un caractère inattendu est une erreur, pas une supposition.
"""

from dataclasses import dataclass

from .errors import CandorError

KEYWORDS = {
    "fn", "do", "end", "let", "give", "if", "then", "else",
    "uses", "and", "or", "not", "true", "false",
}

TWO_CHAR_OPS = {"->", "==", "!=", "<=", ">="}
SINGLE_CHARS = set("+-*/<>=:,()[]")

_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}


@dataclass
class Token:
    kind: str      # IDENT | INT | TEXT | KEYWORD | OP | EOF
    value: object
    line: int


def tokenize(src):
    tokens = []
    i = 0
    line = 1
    n = len(src)

    while i < n:
        c = src[i]

        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue

        # commentaire jusqu'à la fin de la ligne
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        # chaîne de texte
        if c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\n":
                    raise CandorError("chaîne de texte non terminée", line, "lexer")
                if src[j] == "\\" and j + 1 < n:
                    buf.append(_ESCAPES.get(src[j + 1], src[j + 1]))
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            if j >= n:
                raise CandorError("chaîne de texte non terminée", line, "lexer")
            tokens.append(Token("TEXT", "".join(buf), line))
            i = j + 1
            continue

        # entier
        if c.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            tokens.append(Token("INT", int(src[i:j]), line))
            i = j
            continue

        # identifiant ou mot-clé
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            word = src[i:j]
            tokens.append(Token("KEYWORD" if word in KEYWORDS else "IDENT", word, line))
            i = j
            continue

        # opérateurs à deux caractères
        if src[i:i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("OP", src[i:i + 2], line))
            i += 2
            continue

        # opérateurs / ponctuation à un caractère
        if c in SINGLE_CHARS:
            tokens.append(Token("OP", c, line))
            i += 1
            continue

        raise CandorError(f"caractère inattendu : {c!r}", line, "lexer")

    tokens.append(Token("EOF", None, line))
    return tokens
