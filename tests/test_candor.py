"""Tests de Candor.

Fonctionne avec pytest (`python -m pytest -q`) OU seul (`python tests/test_candor.py`)
grâce au runner intégré en bas de fichier.
"""

import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candor import bytecode                     # noqa: E402
from candor.compiler import Compiler             # noqa: E402
from candor.errors import CandorError          # noqa: E402
from candor.interpreter import Interpreter      # noqa: E402
from candor.lexer import tokenize               # noqa: E402
from candor.parser import Parser                # noqa: E402
from candor.vm import VM                         # noqa: E402


def run_source(src):
    program = Parser(tokenize(src)).parse_program()
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = Interpreter(program).run()
    return code, buf.getvalue()


def run_vm(src):
    """Compile en bytecode binaire, recharge les octets, exécute sur la VM."""
    program = Parser(tokenize(src)).parse_program()
    module = bytecode.deserialize(Compiler(program).compile())
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = VM(module).run()
    return code, buf.getvalue()


def expect_error(src):
    try:
        run_source(src)
    except CandorError as e:
        return e
    raise AssertionError("une CandorError était attendue, aucune n'a été levée")


# --- programmes valides ------------------------------------------------------

def test_hello():
    code, out = run_source(
        'fn main() -> Int uses [Console] do\n  say("Bonjour")\n  give 0\nend\n'
    )
    assert code == 0
    assert "Bonjour" in out


def test_arithmetic():
    src = (
        "fn square(n: Int) -> Int do\n  give n * n\nend\n"
        'fn main() -> Int uses [Console] do\n  say(square(6))\n  give 0\nend\n'
    )
    _, out = run_source(src)
    assert out.strip() == "36"


def test_bool_render():
    src = "fn main() -> Int uses [Console] do\n  say(3 < 5)\n  give 0\nend\n"
    _, out = run_source(src)
    assert out.strip() == "true"


def test_if_else_branches():
    src = (
        "fn abs(n: Int) -> Int do\n"
        "  if n < 0 then\n    give -n\n  else\n    give n\n  end\n"
        "end\n"
        "fn main() -> Int uses [Console] do\n  say(abs(-7))\n  give 0\nend\n"
    )
    _, out = run_source(src)
    assert out.strip() == "7"


# --- erreurs attrapées AVANT exécution ---------------------------------------

def test_missing_effect_is_rejected():
    e = expect_error('fn main() -> Int do\n  say("x")\n  give 0\nend\n')
    assert e.phase == "checker"
    assert "Console" in e.message


def test_unknown_name_is_rejected():
    e = expect_error("fn main() -> Int do\n  give x\nend\n")
    assert "inconnu" in e.message.lower()


def test_type_mismatch_is_rejected():
    e = expect_error("fn main() -> Int do\n  let a: Int = true\n  give a\nend\n")
    assert e.phase == "checker"


def test_immutability_is_enforced():
    e = expect_error(
        "fn main() -> Int do\n  let a: Int = 1\n  let a: Int = 2\n  give a\nend\n"
    )
    assert "immuable" in e.message.lower() or "déjà" in e.message.lower()


def test_missing_give_is_rejected():
    e = expect_error(
        "fn f() -> Int do\n  let a: Int = 1\nend\n"
        "fn main() -> Int do\n  give 0\nend\n"
    )
    assert "give" in e.message.lower()


def test_unknown_function_is_rejected():
    e = expect_error("fn main() -> Int do\n  give foo()\nend\n")
    assert "inconnue" in e.message.lower()


# --- erreur d'exécution -------------------------------------------------------

def test_division_by_zero():
    e = expect_error("fn main() -> Int do\n  give 1 / 0\nend\n")
    assert e.phase == "runtime"


# --- chemin bytecode : compilateur + VM --------------------------------------

_SQUARE = (
    "fn square(n: Int) -> Int do\n  give n * n\nend\n"
    'fn main() -> Int uses [Console] do\n  say(square(6))\n  give 0\nend\n'
)


def test_vm_matches_interpreter():
    _, out = run_vm(_SQUARE)
    assert out.strip() == "36"


def test_vm_if_else():
    src = (
        "fn abs(n: Int) -> Int do\n"
        "  if n < 0 then\n    give -n\n  else\n    give n\n  end\n"
        "end\n"
        "fn main() -> Int uses [Console] do\n  say(abs(-7))\n  give 0\nend\n"
    )
    _, out = run_vm(src)
    assert out.strip() == "7"


def test_vm_short_circuit_and_or():
    src = (
        "fn main() -> Int uses [Console] do\n"
        "  say(true and false)\n"
        "  say(false or true)\n"
        "  give 0\nend\n"
    )
    _, out = run_vm(src)
    assert out.split() == ["false", "true"]


def test_vm_owns_int_semantics():
    # Sur la VM, 2^63 - 1 + 1 déborde et boucle vers le minimum 64 bits signé.
    src = (
        "fn main() -> Int uses [Console] do\n"
        "  say(9223372036854775807 + 1)\n"
        "  give 0\nend\n"
    )
    _, out_vm = run_vm(src)
    assert out_vm.strip() == "-9223372036854775808"
    # Le tree-walk, lui, hérite des grands entiers de Python : pas de débordement.
    _, out_tree = run_source(src)
    assert out_tree.strip() == "9223372036854775808"


def test_bytecode_roundtrip_and_disassemble():
    data = Compiler(Parser(tokenize(_SQUARE)).parse_program()).compile()
    assert data[:4] == b"CAND"
    module = bytecode.deserialize(data)
    text = bytecode.disassemble(module)
    assert "fn #" in text and "CALL" in text


# --- runner intégré (sans pytest) --------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
            passed += 1
        except AssertionError as a:
            print(f" FAIL  {t.__name__} : {a}")
        except Exception as ex:  # noqa: BLE001
            print(f" ERR   {t.__name__} : {type(ex).__name__}: {ex}")
    print(f"\n{passed}/{len(tests)} tests passés")
    sys.exit(0 if passed == len(tests) else 1)
