"""Point d'entrée de Candor.

    python -m candor run     <fichier.can> [args...]   interprète (tree-walk)
    python -m candor compile <fichier.can> [out.canc]  compile en bytecode binaire
    python -m candor exec    <fichier.canc|.can> [args...]  exécute sur la VM bytecode
    python -m candor dis     <fichier.canc|.can>       désassemble le bytecode

    python -m candor <fichier.can> [args...]            raccourci pour 'run'

Les [args...] sont accessibles dans le programme via arg(i) / arg_count().
"""

import os
import sys

from . import bytecode
from .compiler import Compiler
from .errors import CandorError
from .interpreter import Interpreter
from .lexer import tokenize
from .parser import Parser
from .vm import VM


def _parse(path):
    with open(path, "r", encoding="utf-8") as f:
        return Parser(tokenize(f.read())).parse_program()


def _module_from(path):
    """Charge un module bytecode depuis un .canc, ou compile un .can à la volée."""
    if path.endswith(".canc"):
        with open(path, "rb") as f:
            return bytecode.deserialize(f.read())
    return bytecode.deserialize(Compiler(_parse(path)).compile())


def cmd_run(path, prog_args=None):
    return Interpreter(_parse(path), prog_args or []).run()


def cmd_compile(path, out=None):
    data = Compiler(_parse(path)).compile()
    out = out or (os.path.splitext(path)[0] + ".canc")
    with open(out, "wb") as f:
        f.write(data)
    print(f"écrit {out} ({len(data)} octets)")
    return 0


def cmd_exec(path, prog_args=None):
    return VM(_module_from(path), prog_args or []).run()


def cmd_dis(path):
    print(bytecode.disassemble(_module_from(path)))
    return 0


def main(argv):
    if not argv:
        print(__doc__)
        return 2

    cmd, rest = argv[0], argv[1:]
    try:
        if cmd == "run":
            return cmd_run(rest[0], rest[1:])
        if cmd == "compile":
            return cmd_compile(rest[0], rest[1] if len(rest) > 1 else None)
        if cmd == "exec":
            return cmd_exec(rest[0], rest[1:])
        if cmd == "dis":
            return cmd_dis(rest[0])
        return cmd_run(cmd, rest)  # raccourci : 'python -m candor fichier.can [args...]'
    except IndexError:
        print(__doc__)
        return 2
    except FileNotFoundError:
        print(f"[Candor] fichier introuvable : {rest[0] if rest else cmd}")
        return 2
    except CandorError as e:
        print(e.render())
        return 1


if __name__ == "__main__":
    result = main(sys.argv[1:])
    sys.exit(result if isinstance(result, int) else 0)
