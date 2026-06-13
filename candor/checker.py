"""Vérificateur de Candor : c'est le coeur de la philosophie du langage.

Il s'exécute AVANT toute exécution et garantit, fonction par fonction (vérification
locale) :

  * tout nom utilisé existe         -> anti-hallucination
  * tout type est cohérent          -> pas de conversion silencieuse
  * tout 'give' correspond au type de retour
  * toute fonction aboutit à un 'give' sur tous les chemins
  * tout effet utilisé est déclaré  -> 'uses [...]' obligatoire

Une seule erreur suffit à refuser le programme : on échoue tôt et franchement.
"""

from . import ast
from .errors import CandorError

# Fonctions intégrées à signature fixe : nom -> {params, ret, effects}.
# "ANY" dans params = un argument de type Int, Bool ou Text.
BUILTINS = {
    "say": {"params": ["ANY"], "ret": "Int", "effects": ["Console"]},
    "at":  {"params": ["Text", "Int"], "ret": "Int", "effects": []},
}

# Intégrées polymorphes sur les listes, vérifiées à part (type d'élément dynamique).
LIST_BUILTINS = {"cons", "head", "tail", "is_empty", "get"}

# 'len' est polymorphe (Text ou liste), traité à part également.
RESERVED = set(BUILTINS) | LIST_BUILTINS | {"len"}


def is_list(t):
    return t.startswith("[") and t.endswith("]")


def elem_of(t):
    return t[1:-1]


class Checker:
    def __init__(self, program):
        self.program = program
        self.funcs = {}
        for f in program.functions:
            if f.name in RESERVED:
                raise CandorError(f"{f.name!r} est intégrée, ce nom est réservé", f.line, "checker")
            if f.name in self.funcs:
                raise CandorError(f"fonction redéfinie : {f.name!r}", f.line, "checker")
            self.funcs[f.name] = f

    def check(self):
        if "main" not in self.funcs:
            raise CandorError("aucune fonction 'main' trouvée", None, "checker")
        main = self.funcs["main"]
        if main.params:
            raise CandorError("'main' ne doit prendre aucun paramètre", main.line, "checker")
        if main.return_type != "Int":
            raise CandorError("'main' doit renvoyer Int", main.line, "checker")
        for f in self.program.functions:
            self.check_function(f)

    def check_function(self, f):
        env = {p.name: p.type for p in f.params}
        required = set()
        self.check_block(f.body, env, f, required)

        if not self.block_returns(f.body):
            raise CandorError(
                f"la fonction {f.name!r} n'aboutit pas toujours à un 'give'", f.line, "checker"
            )

        missing = required - set(f.effects)
        if missing:
            names = ", ".join(sorted(missing))
            raise CandorError(
                f"la fonction {f.name!r} utilise des effets non déclarés : {sorted(missing)} "
                f"— ajoute 'uses [{names}]'",
                f.line, "checker",
            )

    # --- instructions --------------------------------------------------------

    def check_block(self, stmts, env, f, required):
        for s in stmts:
            self.check_stmt(s, env, f, required)

    def check_stmt(self, s, env, f, required):
        if isinstance(s, ast.LetStmt):
            t = self.type_of(s.expr, env, required, s.type)
            if t != s.type:
                raise CandorError(
                    f"'{s.name}' est déclaré {s.type} mais la valeur est {t}", s.line, "checker"
                )
            if s.name in env:
                raise CandorError(
                    f"'{s.name}' est déjà lié — les liaisons Candor sont immuables", s.line, "checker"
                )
            env[s.name] = s.type

        elif isinstance(s, ast.GiveStmt):
            t = self.type_of(s.expr, env, required, f.return_type)
            if t != f.return_type:
                raise CandorError(
                    f"'give' renvoie {t} mais {f.name!r} déclare {f.return_type}", s.line, "checker"
                )

        elif isinstance(s, ast.IfStmt):
            ct = self.type_of(s.cond, env, required)
            if ct != "Bool":
                raise CandorError(
                    f"la condition de 'if' doit être Bool, trouvé {ct}", s.line, "checker"
                )
            # chaque branche a sa propre portée : les 'let' internes ne fuient pas
            self.check_block(s.then_block, dict(env), f, required)
            if s.else_block is not None:
                self.check_block(s.else_block, dict(env), f, required)

        elif isinstance(s, ast.ExprStmt):
            self.type_of(s.expr, env, required)

        else:  # pragma: no cover - filet
            raise CandorError("instruction inconnue (bug interne)", getattr(s, "line", None), "checker")

    # --- expressions ---------------------------------------------------------

    def type_of(self, e, env, required, expected=None):
        if isinstance(e, ast.IntLit):
            return "Int"
        if isinstance(e, ast.BoolLit):
            return "Bool"
        if isinstance(e, ast.TextLit):
            return "Text"

        if isinstance(e, ast.ListLit):
            exp_el = elem_of(expected) if (expected and is_list(expected)) else None
            if not e.elements:
                if expected is None or not is_list(expected):
                    raise CandorError(
                        "type d'une liste vide indéterminé — annote-le, ex. let xs: [Int] = []",
                        e.line, "checker",
                    )
                return expected
            et = self.type_of(e.elements[0], env, required, exp_el)
            for el in e.elements[1:]:
                t2 = self.type_of(el, env, required, exp_el)
                if t2 != et:
                    raise CandorError(
                        f"liste hétérogène : éléments {et} et {t2}", e.line, "checker"
                    )
            return "[" + et + "]"

        if isinstance(e, ast.Ident):
            if e.name not in env:
                raise CandorError(f"nom inconnu : {e.name!r}", e.line, "checker")
            return env[e.name]

        if isinstance(e, ast.Unary):
            t = self.type_of(e.operand, env, required)
            if e.op == "not":
                if t != "Bool":
                    raise CandorError(f"'not' attend Bool, trouvé {t}", e.line, "checker")
                return "Bool"
            if e.op == "-":
                if t != "Int":
                    raise CandorError(f"'-' unaire attend Int, trouvé {t}", e.line, "checker")
                return "Int"

        if isinstance(e, ast.Binary):
            lt = self.type_of(e.left, env, required)
            rt = self.type_of(e.right, env, required)
            op = e.op
            if op in ("+", "-", "*", "/"):
                if lt != "Int" or rt != "Int":
                    raise CandorError(f"'{op}' attend Int et Int, trouvé {lt} et {rt}", e.line, "checker")
                return "Int"
            if op in ("==", "!="):
                if lt != rt:
                    raise CandorError(f"'{op}' compare des types différents : {lt} et {rt}", e.line, "checker")
                return "Bool"
            if op in ("<", ">", "<=", ">="):
                if lt != "Int" or rt != "Int":
                    raise CandorError(f"'{op}' attend Int et Int, trouvé {lt} et {rt}", e.line, "checker")
                return "Bool"
            if op in ("and", "or"):
                if lt != "Bool" or rt != "Bool":
                    raise CandorError(f"'{op}' attend Bool et Bool, trouvé {lt} et {rt}", e.line, "checker")
                return "Bool"

        if isinstance(e, ast.Call):
            return self.type_of_call(e, env, required, expected)

        raise CandorError("expression inconnue (bug interne)", getattr(e, "line", None), "checker")

    def type_of_call(self, e, env, required, expected=None):
        name = e.name

        if name == "len":
            self._expect_argc(e, 1)
            t = self.type_of(e.args[0], env, required)
            if t != "Text" and not is_list(t):
                raise CandorError(f"'len' attend Text ou une liste, reçu {t}", e.line, "checker")
            return "Int"

        if name in LIST_BUILTINS:
            return self._type_of_list_call(e, env, required, expected)

        if name in BUILTINS:
            spec = BUILTINS[name]
            params = spec["params"]
            self._expect_argc(e, len(params))
            for idx, (arg, pt) in enumerate(zip(e.args, params), start=1):
                at = self.type_of(arg, env, required)
                if pt == "ANY":
                    if at not in ("Int", "Bool", "Text"):
                        raise CandorError(f"{name!r} ne sait pas traiter {at}", e.line, "checker")
                elif at != pt:
                    raise CandorError(
                        f"argument {idx} de {name!r} : attendu {pt}, reçu {at}", e.line, "checker"
                    )
            required.update(spec["effects"])
            return spec["ret"]

        if name not in self.funcs:
            raise CandorError(f"fonction inconnue : {name!r}", e.line, "checker")
        fn = self.funcs[name]
        self._expect_argc(e, len(fn.params))
        for i, (arg, p) in enumerate(zip(e.args, fn.params), start=1):
            at = self.type_of(arg, env, required, p.type)
            if at != p.type:
                raise CandorError(
                    f"argument {i} de {name!r} : attendu {p.type}, reçu {at}", e.line, "checker"
                )
        required.update(fn.effects)
        return fn.return_type

    def _expect_argc(self, e, n):
        if len(e.args) != n:
            raise CandorError(
                f"{e.name!r} attend {n} argument(s), reçu {len(e.args)}", e.line, "checker"
            )

    def _type_of_list_call(self, e, env, required, expected):
        name = e.name
        if name == "cons":                          # cons(x: T, xs: [T]) -> [T]
            self._expect_argc(e, 2)
            exp_el = elem_of(expected) if (expected and is_list(expected)) else None
            xt = self.type_of(e.args[0], env, required, exp_el)
            lst = self.type_of(e.args[1], env, required, "[" + xt + "]")
            if not is_list(lst):
                raise CandorError(f"'cons' : 2e argument doit être une liste, reçu {lst}", e.line, "checker")
            if elem_of(lst) != xt:
                raise CandorError(
                    f"'cons' : élément {xt} mais liste de {elem_of(lst)}", e.line, "checker"
                )
            return lst

        # head/tail/is_empty/get : le 1er argument est une liste
        self._expect_argc(e, 2 if name == "get" else 1)
        lst = self.type_of(e.args[0], env, required)
        if not is_list(lst):
            raise CandorError(f"{name!r} attend une liste, reçu {lst}", e.line, "checker")
        if name == "head":
            return elem_of(lst)
        if name == "tail":
            return lst
        if name == "is_empty":
            return "Bool"
        # get
        it = self.type_of(e.args[1], env, required)
        if it != "Int":
            raise CandorError(f"'get' : l'indice doit être Int, reçu {it}", e.line, "checker")
        return elem_of(lst)

    # --- analyse de retour certain -------------------------------------------

    def block_returns(self, stmts):
        return any(self.stmt_returns(s) for s in stmts)

    def stmt_returns(self, s):
        if isinstance(s, ast.GiveStmt):
            return True
        if isinstance(s, ast.IfStmt) and s.else_block is not None:
            return self.block_returns(s.then_block) and self.block_returns(s.else_block)
        return False
