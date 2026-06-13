"""Arbre syntaxique de Candor. Chaque noeud porte sa ligne source pour des
erreurs précises et locales."""

from dataclasses import dataclass


# --- structure ---------------------------------------------------------------

@dataclass
class Program:
    functions: list


@dataclass
class Param:
    name: str
    type: str


@dataclass
class Function:
    name: str
    params: list          # list[Param]
    return_type: str
    effects: list          # list[str]
    body: list             # list[Stmt]
    line: int


# --- instructions ------------------------------------------------------------

@dataclass
class LetStmt:
    name: str
    type: str
    expr: object
    line: int


@dataclass
class GiveStmt:
    expr: object
    line: int


@dataclass
class IfStmt:
    cond: object
    then_block: list
    else_block: object     # list | None
    line: int


@dataclass
class ExprStmt:
    expr: object
    line: int


# --- expressions -------------------------------------------------------------

@dataclass
class Binary:
    op: str
    left: object
    right: object
    line: int


@dataclass
class Unary:
    op: str
    operand: object
    line: int


@dataclass
class Call:
    name: str
    args: list
    line: int


@dataclass
class Ident:
    name: str
    line: int


@dataclass
class IntLit:
    value: int
    line: int


@dataclass
class BoolLit:
    value: bool
    line: int


@dataclass
class TextLit:
    value: str
    line: int
