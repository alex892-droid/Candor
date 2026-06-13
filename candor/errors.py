"""Erreurs de Candor.

Principe : une erreur porte TOUJOURS une phase (lexer/parser/checker/runtime),
un message clair, et — quand c'est possible — la ligne. La franchise s'applique
aussi aux messages d'erreur.
"""


class CandorError(Exception):
    def __init__(self, message, line=None, phase="error"):
        self.message = message
        self.line = line
        self.phase = phase
        super().__init__(message)

    def render(self):
        where = f" ligne {self.line}" if self.line is not None else ""
        return f"[Candor · {self.phase}{where}] {self.message}"
