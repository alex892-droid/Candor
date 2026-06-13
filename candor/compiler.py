"""Compilateur de Candor : AST vérifié -> module bytecode (octets).

Stratégie : machine à pile. Chaque expression laisse sa valeur au sommet de la pile ;
chaque instruction la consomme. Les variables (paramètres + 'let') sont rangées dans
des *slots* numérotés, attribués à la compilation.

Le compilateur lance d'abord le vérificateur : on ne compile jamais un programme
que Candor refuserait d'exécuter.
"""

from . import ast, bytecode
from .bytecode import Op
from .checker import Checker
from .errors import CandorError


class _FuncCompiler:
    def __init__(self, module, func):
        self.module = module        # Compiler (pool de constantes + index des fonctions)
        self.func = func
        self.instrs = []            # list[[op, arg]]
        self.scopes = [{}]          # pile de portées : nom -> slot
        self.num_slots = 0
        for p in func.params:
            self.declare(p.name)

    # -- portées et slots --
    def declare(self, name):
        slot = self.num_slots
        self.num_slots += 1
        self.scopes[-1][name] = slot
        return slot

    def resolve(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        raise CandorError(f"slot introuvable : {name!r} (bug interne)", None, "compiler")

    # -- émission --
    def emit(self, op, arg=None):
        self.instrs.append([op, arg])
        return len(self.instrs) - 1

    def here(self):
        return len(self.instrs)

    def patch(self, index, label):
        self.instrs[index][1] = label

    def compile(self):
        for s in self.func.body:
            self.stmt(s)
        return bytecode.assemble([(op, arg) for op, arg in self.instrs])

    # -- instructions --
    def stmt(self, s):
        if isinstance(s, ast.LetStmt):
            self.expr(s.expr)
            self.emit(Op.STORE, self.declare(s.name))
        elif isinstance(s, ast.GiveStmt):
            self.expr(s.expr)
            self.emit(Op.RETURN)
        elif isinstance(s, ast.ExprStmt):
            self.expr(s.expr)
            self.emit(Op.POP)
        elif isinstance(s, ast.IfStmt):
            self.expr(s.cond)
            j_else = self.emit(Op.JUMP_IF_FALSE)
            self.scopes.append({})
            for st in s.then_block:
                self.stmt(st)
            self.scopes.pop()
            if s.else_block is not None:
                j_end = self.emit(Op.JUMP)
                self.patch(j_else, self.here())
                self.scopes.append({})
                for st in s.else_block:
                    self.stmt(st)
                self.scopes.pop()
                self.patch(j_end, self.here())
            else:
                self.patch(j_else, self.here())

    # -- expressions --
    def expr(self, e):
        if isinstance(e, ast.IntLit):
            self.emit(Op.CONST, self.module.const(e.value))
        elif isinstance(e, ast.BoolLit):
            self.emit(Op.CONST, self.module.const(e.value))
        elif isinstance(e, ast.TextLit):
            self.emit(Op.CONST, self.module.const(e.value))
        elif isinstance(e, ast.ListLit):
            for el in e.elements:
                self.expr(el)
            self.emit(Op.BUILD_LIST, len(e.elements))
        elif isinstance(e, ast.RecordLit):
            for fname, fexpr in e.fields:           # chaque champ : (clé Text, valeur)
                self.emit(Op.CONST, self.module.const(fname))
                self.expr(fexpr)
            self.emit(Op.MAKE_RECORD, len(e.fields))
        elif isinstance(e, ast.FieldAccess):
            self.expr(e.obj)
            self.emit(Op.GET_FIELD, self.module.const(e.field))
        elif isinstance(e, ast.Ident):
            self.emit(Op.LOAD, self.resolve(e.name))
        elif isinstance(e, ast.Unary):
            self.expr(e.operand)
            self.emit(Op.NOT if e.op == "not" else Op.NEG)
        elif isinstance(e, ast.Binary):
            self.binary(e)
        elif isinstance(e, ast.Call):
            self.call(e)
        else:  # pragma: no cover
            raise CandorError("expression non compilable (bug interne)", getattr(e, "line", None), "compiler")

    def binary(self, e):
        if e.op == "and":
            # a and b == si a faux -> false, sinon b
            self.expr(e.left)
            j_false = self.emit(Op.JUMP_IF_FALSE)
            self.expr(e.right)
            j_end = self.emit(Op.JUMP)
            self.patch(j_false, self.here())
            self.emit(Op.CONST, self.module.const(False))
            self.patch(j_end, self.here())
        elif e.op == "or":
            # a or b == si a vrai -> true, sinon b
            self.expr(e.left)
            j_false = self.emit(Op.JUMP_IF_FALSE)
            self.emit(Op.CONST, self.module.const(True))
            j_end = self.emit(Op.JUMP)
            self.patch(j_false, self.here())
            self.expr(e.right)
            self.patch(j_end, self.here())
        else:
            self.expr(e.left)
            self.expr(e.right)
            self.emit(bytecode.BIN_OPS[e.op])

    def call(self, e):
        if e.name == "say":
            self.expr(e.args[0])
            self.emit(Op.SAY)
        elif e.name == "len":
            self.expr(e.args[0])
            self.emit(Op.LEN)
        elif e.name == "at":
            self.expr(e.args[0])
            self.expr(e.args[1])
            self.emit(Op.AT)
        elif e.name == "cons":
            self.expr(e.args[0])
            self.expr(e.args[1])
            self.emit(Op.CONS)
        elif e.name == "head":
            self.expr(e.args[0])
            self.emit(Op.HEAD)
        elif e.name == "tail":
            self.expr(e.args[0])
            self.emit(Op.TAIL)
        elif e.name == "is_empty":
            self.expr(e.args[0])
            self.emit(Op.ISEMPTY)
        elif e.name == "get":
            self.expr(e.args[0])
            self.expr(e.args[1])
            self.emit(Op.GET)
        elif e.name == "read_file":
            self.expr(e.args[0])
            self.emit(Op.READ_FILE)
        elif e.name == "arg":
            self.expr(e.args[0])
            self.emit(Op.ARG)
        elif e.name == "arg_count":
            self.emit(Op.ARG_COUNT)
        else:
            for a in e.args:
                self.expr(a)
            self.emit(Op.CALL, (self.module.func_index[e.name], len(e.args)))


class Compiler:
    def __init__(self, program):
        self.program = program
        self.consts = []
        self._const_index = {}
        self.func_index = {f.name: i for i, f in enumerate(program.functions)}

    def const(self, value):
        key = (type(value).__name__, value)   # distingue bool de int
        if key in self._const_index:
            return self._const_index[key]
        idx = len(self.consts)
        self.consts.append(value)
        self._const_index[key] = idx
        return idx

    def compile(self):
        Checker(self.program).check()          # franchise : on refuse tôt
        functions = []
        for f in self.program.functions:
            fc = _FuncCompiler(self, f)
            code = fc.compile()
            functions.append((f.name, len(f.params), fc.num_slots, code))
        entry = self.func_index["main"]
        return bytecode.serialize(self.consts, functions, entry)
