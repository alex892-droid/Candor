"""Parser de Candor : descente récursive, jetons -> arbre syntaxique (AST).

Grammaire (v0) :

    program    := function*
    function   := "fn" IDENT "(" params? ")" "->" type effects? "do" block "end"
    params     := param ("," param)*
    param      := IDENT ":" type
    type       := "Int" | "Bool" | "Text"
    effects    := "uses" "[" (IDENT ("," IDENT)*)? "]"
    block      := statement*
    statement  := let | give | if | expr
    let        := "let" IDENT ":" type "=" expr      // type obligatoire (explicite)
    give       := "give" expr
    if         := "if" expr "then" block ("else" block)? "end"

Précédence des expressions (faible -> forte) :
    or, and, equality(== !=), comparison(< > <= >=), +/-, * /, unaire(not -), primaire
"""

from . import ast
from .errors import CandorError

VALID_TYPES = {"Int", "Bool", "Text"}


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    # --- primitives ----------------------------------------------------------

    def peek(self):
        return self.toks[self.pos]

    def at_end(self):
        return self.peek().kind == "EOF"

    def advance(self):
        t = self.toks[self.pos]
        if not self.at_end():
            self.pos += 1
        return t

    def check(self, kind, value=None):
        t = self.peek()
        if t.kind != kind:
            return False
        return value is None or t.value == value

    def match(self, kind, value=None):
        if self.check(kind, value):
            return self.advance()
        return None

    def expect(self, kind, value=None, what=None):
        if self.check(kind, value):
            return self.advance()
        t = self.peek()
        label = what or (repr(value) if value is not None else kind)
        raise CandorError(f"attendu {label}, trouvé {t.value!r}", t.line, "parser")

    # --- structure -----------------------------------------------------------

    def parse_program(self):
        funcs = []
        while not self.at_end():
            funcs.append(self.parse_function())
        return ast.Program(funcs)

    def parse_function(self):
        kw = self.expect("KEYWORD", "fn", "le mot-clé 'fn'")
        name = self.expect("IDENT", what="un nom de fonction").value
        self.expect("OP", "(")
        params = []
        if not self.check("OP", ")"):
            params.append(self.parse_param())
            while self.match("OP", ","):
                params.append(self.parse_param())
        self.expect("OP", ")")
        self.expect("OP", "->", "'->'")
        ret = self.parse_type()

        effects = []
        if self.match("KEYWORD", "uses"):
            self.expect("OP", "[")
            if not self.check("OP", "]"):
                effects.append(self.expect("IDENT", what="un nom d'effet").value)
                while self.match("OP", ","):
                    effects.append(self.expect("IDENT", what="un nom d'effet").value)
            self.expect("OP", "]")

        self.expect("KEYWORD", "do")
        body = self.parse_block(("end",))
        self.expect("KEYWORD", "end")
        return ast.Function(name, params, ret, effects, body, kw.line)

    def parse_param(self):
        name = self.expect("IDENT", what="un nom de paramètre").value
        self.expect("OP", ":")
        return ast.Param(name, self.parse_type())

    def parse_type(self):
        t = self.expect("IDENT", what="un type")
        if t.value not in VALID_TYPES:
            raise CandorError(
                f"type inconnu : {t.value!r} (attendu Int, Bool ou Text)", t.line, "parser"
            )
        return t.value

    # --- instructions --------------------------------------------------------

    def parse_block(self, stops):
        stmts = []
        while not self.at_end() and not (
            self.peek().kind == "KEYWORD" and self.peek().value in stops
        ):
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        t = self.peek()
        if t.kind == "KEYWORD" and t.value == "let":
            return self.parse_let()
        if t.kind == "KEYWORD" and t.value == "give":
            return self.parse_give()
        if t.kind == "KEYWORD" and t.value == "if":
            return self.parse_if()
        return ast.ExprStmt(self.parse_expr(), t.line)

    def parse_let(self):
        kw = self.advance()
        name = self.expect("IDENT", what="un nom de variable").value
        self.expect("OP", ":")
        typ = self.parse_type()
        self.expect("OP", "=")
        return ast.LetStmt(name, typ, self.parse_expr(), kw.line)

    def parse_give(self):
        kw = self.advance()
        return ast.GiveStmt(self.parse_expr(), kw.line)

    def parse_if(self):
        kw = self.advance()
        cond = self.parse_expr()
        self.expect("KEYWORD", "then")
        then_block = self.parse_block(("else", "end"))
        else_block = None
        if self.match("KEYWORD", "else"):
            else_block = self.parse_block(("end",))
        self.expect("KEYWORD", "end")
        return ast.IfStmt(cond, then_block, else_block, kw.line)

    # --- expressions ---------------------------------------------------------

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.check("KEYWORD", "or"):
            line = self.advance().line
            left = ast.Binary("or", left, self.parse_and(), line)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.check("KEYWORD", "and"):
            line = self.advance().line
            left = ast.Binary("and", left, self.parse_equality(), line)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        while self.check("OP", "==") or self.check("OP", "!="):
            tok = self.advance()
            left = ast.Binary(tok.value, left, self.parse_comparison(), tok.line)
        return left

    def parse_comparison(self):
        left = self.parse_additive()
        while any(self.check("OP", o) for o in ("<", ">", "<=", ">=")):
            tok = self.advance()
            left = ast.Binary(tok.value, left, self.parse_additive(), tok.line)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.check("OP", "+") or self.check("OP", "-"):
            tok = self.advance()
            left = ast.Binary(tok.value, left, self.parse_multiplicative(), tok.line)
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.check("OP", "*") or self.check("OP", "/"):
            tok = self.advance()
            left = ast.Binary(tok.value, left, self.parse_unary(), tok.line)
        return left

    def parse_unary(self):
        if self.check("KEYWORD", "not"):
            tok = self.advance()
            return ast.Unary("not", self.parse_unary(), tok.line)
        if self.check("OP", "-"):
            tok = self.advance()
            return ast.Unary("-", self.parse_unary(), tok.line)
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t.kind == "INT":
            self.advance()
            return ast.IntLit(t.value, t.line)
        if t.kind == "TEXT":
            self.advance()
            return ast.TextLit(t.value, t.line)
        if t.kind == "KEYWORD" and t.value in ("true", "false"):
            self.advance()
            return ast.BoolLit(t.value == "true", t.line)
        if t.kind == "OP" and t.value == "(":
            self.advance()
            e = self.parse_expr()
            self.expect("OP", ")")
            return e
        if t.kind == "IDENT":
            self.advance()
            if self.match("OP", "("):
                args = []
                if not self.check("OP", ")"):
                    args.append(self.parse_expr())
                    while self.match("OP", ","):
                        args.append(self.parse_expr())
                self.expect("OP", ")")
                return ast.Call(t.value, args, t.line)
            return ast.Ident(t.value, t.line)
        raise CandorError(f"expression attendue, trouvé {t.value!r}", t.line, "parser")
