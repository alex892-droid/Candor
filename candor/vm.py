"""Machine virtuelle de Candor : exécute le bytecode.

C'est ici que Candor *possède* sa sémantique, indépendamment de Python :
  * pile d'opérandes et trame d'appel gérées explicitement ;
  * les Int sont des entiers **64 bits signés avec débordement défini** (comme C,
    Rust ou Java) — contrairement au tree-walk, qui héritait des grands entiers de
    Python. C'est la preuve concrète que la valeur appartient au langage, pas à l'hôte.
"""

from . import bytecode
from .bytecode import Op
from .errors import CandorError

_MASK = 0xFFFFFFFFFFFFFFFF
_SIGN = 0x8000000000000000


def wrap64(n):
    """Ramène n dans l'intervalle des entiers signés 64 bits (débordement défini)."""
    n &= _MASK
    return n - (_MASK + 1) if n >= _SIGN else n


def render(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


class _Frame:
    __slots__ = ("code", "ip", "locals", "stack")

    def __init__(self, fn):
        self.code = fn.code
        self.ip = 0
        self.locals = [None] * fn.num_locals
        self.stack = []


class VM:
    def __init__(self, module, args=None):
        self.m = module
        self.args = args or []      # arguments passés au programme (CLI)

    def run(self):
        consts = self.m.consts
        funcs = self.m.functions
        frames = [_Frame(funcs[self.m.entry])]

        while frames:
            f = frames[-1]
            code = f.code
            op = code[f.ip]
            f.ip += 1

            if op == Op.CONST:
                idx = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                f.stack.append(consts[idx])
            elif op == Op.LOAD:
                slot = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                f.stack.append(f.locals[slot])
            elif op == Op.STORE:
                slot = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                f.locals[slot] = f.stack.pop()
            elif op == Op.POP:
                f.stack.pop()

            elif op == Op.ADD:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(wrap64(a + b))
            elif op == Op.SUB:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(wrap64(a - b))
            elif op == Op.MUL:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(wrap64(a * b))
            elif op == Op.DIV:
                b = f.stack.pop(); a = f.stack.pop()
                if b == 0:
                    raise CandorError("division par zéro", None, "runtime")
                q = abs(a) // abs(b)
                f.stack.append(wrap64(q if (a >= 0) == (b >= 0) else -q))
            elif op == Op.NEG:
                f.stack.append(wrap64(-f.stack.pop()))

            elif op == Op.EQ:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a == b)
            elif op == Op.NE:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a != b)
            elif op == Op.LT:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a < b)
            elif op == Op.GT:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a > b)
            elif op == Op.LE:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a <= b)
            elif op == Op.GE:
                b = f.stack.pop(); a = f.stack.pop(); f.stack.append(a >= b)
            elif op == Op.NOT:
                f.stack.append(not f.stack.pop())

            elif op == Op.JUMP:
                rel = bytecode.signed16(code, f.ip)
                f.ip += 2 + rel
            elif op == Op.JUMP_IF_FALSE:
                rel = bytecode.signed16(code, f.ip)
                f.ip += 2
                if not f.stack.pop():
                    f.ip += rel

            elif op == Op.CALL:
                fidx = (code[f.ip] << 8) | code[f.ip + 1]
                argc = code[f.ip + 2]
                f.ip += 3
                args = [f.stack.pop() for _ in range(argc)][::-1]
                callee = _Frame(funcs[fidx])
                for i, a in enumerate(args):
                    callee.locals[i] = a
                frames.append(callee)
            elif op == Op.SAY:
                print(render(f.stack.pop()))
                f.stack.append(0)
            elif op == Op.LEN:
                f.stack.append(len(f.stack.pop()))
            elif op == Op.AT:
                i = f.stack.pop()
                t = f.stack.pop()
                if i < 0 or i >= len(t):
                    raise CandorError("indice de texte hors limites", None, "runtime")
                f.stack.append(ord(t[i]))
            elif op == Op.BUILD_LIST:
                n = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                items = [f.stack.pop() for _ in range(n)][::-1]
                f.stack.append(tuple(items))
            elif op == Op.CONS:
                xs = f.stack.pop()
                x = f.stack.pop()
                f.stack.append((x,) + xs)
            elif op == Op.HEAD:
                xs = f.stack.pop()
                if not xs:
                    raise CandorError("'head' sur une liste vide", None, "runtime")
                f.stack.append(xs[0])
            elif op == Op.TAIL:
                xs = f.stack.pop()
                if not xs:
                    raise CandorError("'tail' sur une liste vide", None, "runtime")
                f.stack.append(xs[1:])
            elif op == Op.ISEMPTY:
                f.stack.append(len(f.stack.pop()) == 0)
            elif op == Op.GET:
                i = f.stack.pop()
                xs = f.stack.pop()
                if i < 0 or i >= len(xs):
                    raise CandorError("indice de liste hors limites", None, "runtime")
                f.stack.append(xs[i])
            elif op == Op.MAKE_RECORD:
                n = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                rec = {}
                for _ in range(n):
                    value = f.stack.pop()
                    key = f.stack.pop()
                    rec[key] = value
                f.stack.append(rec)
            elif op == Op.GET_FIELD:
                idx = (code[f.ip] << 8) | code[f.ip + 1]
                f.ip += 2
                f.stack.append(f.stack.pop()[consts[idx]])
            elif op == Op.ARG_COUNT:
                f.stack.append(len(self.args))
            elif op == Op.ARG:
                i = f.stack.pop()
                if i < 0 or i >= len(self.args):
                    raise CandorError("indice d'argument hors limites", None, "runtime")
                f.stack.append(self.args[i])
            elif op == Op.READ_FILE:
                path = f.stack.pop()
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        f.stack.append(fh.read())
                except OSError as ex:
                    raise CandorError(f"lecture impossible : {path} ({ex})", None, "runtime")
            elif op == Op.RETURN:
                value = f.stack.pop()
                frames.pop()
                if frames:
                    frames[-1].stack.append(value)
                else:
                    return value
            else:  # pragma: no cover
                raise CandorError(f"opcode inconnu : {op}", None, "vm")

        return 0
