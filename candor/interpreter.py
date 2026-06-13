"""Interpréteur de Candor : exécute l'AST après que le vérificateur l'a validé.

Comme la vérification a déjà eu lieu, l'exécution suppose des types corrects ;
elle ne re-vérifie que ce qui ne peut l'être qu'à l'exécution (ex. division par zéro).
"""

from . import ast
from .checker import Checker
from .errors import CandorError


class ReturnSignal(Exception):
    """Porté par 'give' pour remonter la valeur de retour hors du corps."""

    def __init__(self, value):
        self.value = value


class Interpreter:
    def __init__(self, program):
        self.program = program
        self.funcs = {f.name: f for f in program.functions}

    def run(self):
        Checker(self.program).check()      # franchise : on refuse tôt si quoi que ce soit cloche
        return self.call(self.funcs["main"], [])

    def call(self, fn, args):
        env = {p.name: a for p, a in zip(fn.params, args)}
        try:
            self.exec_block(fn.body, env)
        except ReturnSignal as r:
            return r.value
        return None  # inatteignable : le checker garantit un 'give'

    # --- instructions --------------------------------------------------------

    def exec_block(self, stmts, env):
        for s in stmts:
            self.exec_stmt(s, env)

    def exec_stmt(self, s, env):
        if isinstance(s, ast.LetStmt):
            env[s.name] = self.eval(s.expr, env)
        elif isinstance(s, ast.GiveStmt):
            raise ReturnSignal(self.eval(s.expr, env))
        elif isinstance(s, ast.IfStmt):
            if self.eval(s.cond, env):
                self.exec_block(s.then_block, dict(env))
            elif s.else_block is not None:
                self.exec_block(s.else_block, dict(env))
        elif isinstance(s, ast.ExprStmt):
            self.eval(s.expr, env)

    # --- expressions ---------------------------------------------------------

    def eval(self, e, env):
        if isinstance(e, ast.IntLit):
            return e.value
        if isinstance(e, ast.BoolLit):
            return e.value
        if isinstance(e, ast.TextLit):
            return e.value
        if isinstance(e, ast.Ident):
            return env[e.name]
        if isinstance(e, ast.Unary):
            v = self.eval(e.operand, env)
            return (not v) if e.op == "not" else (-v)
        if isinstance(e, ast.Binary):
            return self.eval_binary(e, env)
        if isinstance(e, ast.Call):
            return self.eval_call(e, env)
        raise CandorError("évaluation impossible (bug interne)", getattr(e, "line", None), "runtime")

    def eval_binary(self, e, env):
        op = e.op
        # court-circuit pour les booléens
        if op == "and":
            return bool(self.eval(e.left, env)) and bool(self.eval(e.right, env))
        if op == "or":
            return bool(self.eval(e.left, env)) or bool(self.eval(e.right, env))

        a = self.eval(e.left, env)
        b = self.eval(e.right, env)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            if b == 0:
                raise CandorError("division par zéro", e.line, "runtime")
            q = abs(a) // abs(b)                       # division entière, troncature vers zéro
            return q if (a >= 0) == (b >= 0) else -q
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if op == "<":
            return a < b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == ">=":
            return a >= b
        raise CandorError(f"opérateur inconnu : {op}", e.line, "runtime")  # pragma: no cover

    def eval_call(self, e, env):
        if e.name == "say":
            print(self.render(self.eval(e.args[0], env)))
            return 0
        if e.name == "len":
            return len(self.eval(e.args[0], env))
        if e.name == "at":
            t = self.eval(e.args[0], env)
            i = self.eval(e.args[1], env)
            if i < 0 or i >= len(t):
                raise CandorError("indice de texte hors limites", e.line, "runtime")
            return ord(t[i])
        args = [self.eval(a, env) for a in e.args]
        return self.call(self.funcs[e.name], args)

    @staticmethod
    def render(v):
        if isinstance(v, bool):       # bool avant int (bool est sous-classe d'int en Python)
            return "true" if v else "false"
        return str(v)
