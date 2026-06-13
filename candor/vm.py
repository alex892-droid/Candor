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
    def __init__(self, module):
        self.m = module

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
