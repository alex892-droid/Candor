"""Tests de Candor.

Fonctionne avec pytest (`python -m pytest -q`) OU seul (`python tests/test_candor.py`)
grâce au runner intégré en bas de fichier.
"""

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candor import bytecode                     # noqa: E402
from candor.compiler import Compiler             # noqa: E402
from candor.errors import CandorError          # noqa: E402
from candor.interpreter import Interpreter      # noqa: E402
from candor.lexer import tokenize               # noqa: E402
from candor.parser import Parser                # noqa: E402
from candor.vm import VM                         # noqa: E402


def run_source(src, args=None):
    program = Parser(tokenize(src)).parse_program()
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = Interpreter(program, args or []).run()
    return code, buf.getvalue()


def run_vm(src, args=None):
    """Compile en bytecode binaire, recharge les octets, exécute sur la VM."""
    program = Parser(tokenize(src)).parse_program()
    module = bytecode.deserialize(Compiler(program).compile())
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = VM(module, args or []).run()
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


# --- primitives de texte (len / at) ------------------------------------------

def test_len_and_at():
    src = (
        "fn main() -> Int uses [Console] do\n"
        '  let s: Text = "AB"\n'
        "  say(len(s))\n"      # 2
        "  say(at(s, 0))\n"     # 65 ('A')
        "  give 0\nend\n"
    )
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert out_tree.split() == ["2", "65"]
    assert out_vm.split() == ["2", "65"]


def test_at_wrong_type_is_rejected():
    e = expect_error(
        'fn main() -> Int do\n  give at("x", "y")\nend\n'
    )
    assert e.phase == "checker"


# --- étape self-hosting : un analyseur écrit en Candor ------------------------

def _example_path(name):
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", name)


def _read_example(name):
    with open(_example_path(name), "r", encoding="utf-8") as f:
        return f.read()


def test_calc_example_both_engines():
    src = _read_example("calc.can")
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert out_tree.strip().endswith("12")
    assert out_vm.strip().endswith("12")


# --- listes immuables (étape 2) ----------------------------------------------

def _nums(out):
    return [w for w in out.split() if w.lstrip("-").isdigit()]


def test_lists_literal_and_ops():
    src = (
        "fn sum_list(xs: [Int]) -> Int do\n"
        "  if is_empty(xs) then give 0 else give head(xs) + sum_list(tail(xs)) end\n"
        "end\n"
        "fn main() -> Int uses [Console] do\n"
        "  let xs: [Int] = [12, 34, 5]\n"
        "  say(len(xs))\n"        # 3
        "  say(get(xs, 1))\n"      # 34
        "  say(sum_list(xs))\n"    # 51
        "  give 0\nend\n"
    )
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert _nums(out_tree) == ["3", "34", "51"]
    assert _nums(out_vm) == ["3", "34", "51"]


def test_cons_and_empty_with_annotation():
    src = (
        "fn main() -> Int uses [Console] do\n"
        "  let xs: [Int] = cons(1, cons(2, []))\n"
        "  say(len(xs))\n"        # 2
        "  say(head(xs))\n"       # 1
        "  give 0\nend\n"
    )
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert _nums(out_tree) == ["2", "1"]
    assert _nums(out_vm) == ["2", "1"]


def test_empty_list_without_annotation_rejected():
    e = expect_error("fn main() -> Int do\n  give head([])\nend\n")
    assert e.phase == "checker"


def test_heterogeneous_list_rejected():
    e = expect_error('fn main() -> Int do\n  let xs: [Int] = [1, true]\n  give 0\nend\n')
    assert e.phase == "checker"


def test_lexer_example_both_engines():
    src = _read_example("lexer.can")
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert _nums(out_tree) == ["3", "12", "51"]
    assert _nums(out_vm) == ["3", "12", "51"]


# --- enregistrements (étape 2b) ----------------------------------------------

def test_record_construct_and_field_access():
    src = (
        "record Point { x: Int, y: Int }\n"
        "fn main() -> Int uses [Console] do\n"
        "  let p: Point = Point { x: 3, y: 7 }\n"
        "  say(p.x)\n"          # 3
        "  say(p.y)\n"          # 7
        "  give 0\nend\n"
    )
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert _nums(out_tree) == ["3", "7"]
    assert _nums(out_vm) == ["3", "7"]


def test_record_missing_field_rejected():
    e = expect_error(
        "record Point { x: Int, y: Int }\n"
        "fn main() -> Int do\n  let p: Point = Point { x: 1 }\n  give 0\nend\n"
    )
    assert e.phase == "checker"


def test_record_wrong_field_type_rejected():
    e = expect_error(
        "record Point { x: Int, y: Int }\n"
        "fn main() -> Int do\n  let p: Point = Point { x: 1, y: true }\n  give 0\nend\n"
    )
    assert e.phase == "checker"


def test_unknown_record_rejected():
    e = expect_error("fn main() -> Int do\n  let p: Nope = Nope { a: 1 }\n  give 0\nend\n")
    assert e.phase == "checker"


def test_field_access_on_non_record_rejected():
    e = expect_error("fn main() -> Int do\n  let n: Int = 5\n  give n.x\nend\n")
    assert e.phase == "checker"


def test_tokens_example_both_engines():
    src = _read_example("tokens.can")
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert _nums(out_tree) == ["5", "12", "0", "2"]
    assert _nums(out_vm) == ["5", "12", "0", "2"]


# --- effet File + arguments (étape 3) ----------------------------------------

def test_read_file_and_args():
    src = (
        "fn main() -> Int uses [Console, File] do\n"
        "  say(arg_count())\n"               # 1
        "  let c: Text = read_file(arg(0))\n"
        "  say(len(c))\n"                     # 5 (= len("hello"))
        "  give 0\nend\n"
    )
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("hello")
        _, out_tree = run_source(src, [path])
        _, out_vm = run_vm(src, [path])
        assert _nums(out_tree) == ["1", "5"]
        assert _nums(out_vm) == ["1", "5"]
    finally:
        os.unlink(path)


def test_file_effect_must_be_declared():
    e = expect_error(
        'fn main() -> Int uses [Console] do\n  say(read_file("x"))\n  give 0\nend\n'
    )
    assert e.phase == "checker"
    assert "File" in e.message


# --- sous-chaîne (sub) -------------------------------------------------------

def test_sub():
    src = (
        "fn main() -> Int uses [Console] do\n"
        '  say(sub("bonjour", 0, 3))\n'      # bon
        '  say(sub("bonjour", 3, 4))\n'      # jour
        "  give 0\nend\n"
    )
    _, out_tree = run_source(src)
    _, out_vm = run_vm(src)
    assert out_tree.split() == ["bon", "jour"]
    assert out_vm.split() == ["bon", "jour"]


# --- ÉTAPE 4 : le lexer de Candor écrit EN Candor ----------------------------

def _python_lexer_counts(path):
    from collections import Counter
    with open(path, encoding="utf-8") as f:
        toks = [t for t in tokenize(f.read()) if t.kind != "EOF"]
    m = {"INT": 0, "IDENT": 1, "KEYWORD": 2, "TEXT": 3, "OP": 4}
    c = Counter(m[t.kind] for t in toks)
    return [len(toks), c[0], c[1], c[2], c[3], c[4]]


def test_selfhost_lexer_agrees_with_reference_vm():
    """Le lexer Candor (sur la VM) produit les MÊMES comptages que le lexer Python."""
    lexer_src = _read_example("selfhost_lexer.can")
    for tgt in ("hello.can", "math.can", "tokens.can", "lexer.can", "selfhost_lexer.can"):
        path = _example_path(tgt)
        _, out = run_vm(lexer_src, [path])
        got = [int(x) for x in out.split()]
        assert got == _python_lexer_counts(path), (tgt, got)


def test_selfhost_lexer_tree_walk_small_file():
    # Le tree-walk récursif est limité par la pile Python : on le vérifie sur un petit fichier.
    lexer_src = _read_example("selfhost_lexer.can")
    path = _example_path("hello.can")
    _, out = run_source(lexer_src, [path])
    assert [int(x) for x in out.split()] == _python_lexer_counts(path)


# --- ÉTAPE 4b : le parser de Candor écrit EN Candor --------------------------

def test_selfhost_parser_builds_ast_and_evaluates():
    """Le parser Candor construit un AST (record Node) qu'un évaluateur séparé parcourt."""
    src = _read_example("selfhost_parser.can")
    cases = {
        "2+3*4-(10-6)/2": "12",
        "1+2+3+4": "10",
        "2*3*4": "24",
        "(1+2)*(3+4)": "21",
        "100/5/2": "10",
        "7-2-1": "4",
        "8/3": "2",               # division entière, troncature vers zéro
    }
    for expr, expected in cases.items():
        _, out_vm = run_vm(src, [expr])
        _, out_tree = run_source(src, [expr])
        assert _nums(out_vm)[-1] == expected, (expr, out_vm)
        assert _nums(out_tree)[-1] == expected, (expr, out_tree)


# --- ÉTAPE 4c : chaîne complète parse -> compile -> VM, écrite EN Candor ------

def test_selfhost_full_pipeline():
    src = _read_example("selfhost_compiler.can")
    cases = {
        "2+3*4-(10-6)/2": "12",
        "1+2+3+4": "10",
        "2*3*4": "24",
        "(1+2)*(3+4)": "21",
        "100/5/2": "10",
        "8/3": "2",
        "7-2-1": "4",
    }
    for expr, expected in cases.items():
        _, out_vm = run_vm(src, [expr])
        _, out_tree = run_source(src, [expr])
        assert _nums(out_vm)[-1] == expected, (expr, out_vm)
        assert _nums(out_tree)[-1] == expected, (expr, out_tree)


# --- ÉTAPE 4d : variables + table des symboles, parsing sur tokens -----------

def test_selfhost_let_variables():
    src = _read_example("selfhost_let.can")
    cases = {
        "let x = 2+3 in x*x": "25",
        "let a = 10 in let b = 20 in a+b": "30",
        "let x = 5 in let y = x*2 in x+y": "15",
        "1+2*3": "7",
        "let x = 7 in x": "7",
        "let n = 100 in n/4/5": "5",
        "(let x = 3 in x*x)+1": "10",
    }
    for expr, expected in cases.items():
        _, out_vm = run_vm(src, [expr])
        _, out_tree = run_source(src, [expr])
        assert _nums(out_vm)[-1] == expected, (expr, out_vm)
        assert _nums(out_tree)[-1] == expected, (expr, out_tree)


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
