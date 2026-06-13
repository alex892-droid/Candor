"""Bytecode de Candor : le jeu d'instructions maison + (dé)sérialisation binaire.

Un programme compilé est un *module* :
  * une table de constantes (Int 64 bits, Bool, Text)
  * une liste de fonctions (nom, nb de paramètres, nb de variables locales, code)
  * l'index de la fonction d'entrée (main)

Le code de chaque fonction est une suite d'octets, exécutée par la VM (voir vm.py).
Format de fichier `.canc` (gros-boutiste) :

    "CAND" | version(1) |
    u16 nb_constantes | [ tag(1) + données ]* |
    u16 nb_fonctions   | [ u16 len+nom | u16 nparams | u16 nlocals | u32 len+code ]* |
    u16 index_entrée

C'est un vrai format binaire : une fois écrit sur disque, Python n'intervient plus
dans la *sémantique* — il ne fait que lire des octets, comme n'importe quelle VM.
"""

import struct
from dataclasses import dataclass

from .errors import CandorError

MAGIC = b"CAND"
VERSION = 1


class Op:
    # pile / variables
    CONST = 1            # u16 index_constante  -> empile la constante
    LOAD = 2             # u16 slot             -> empile la locale
    STORE = 3            # u16 slot             -> dépile vers la locale
    POP = 4              #                       -> dépile et jette
    # arithmétique entière (64 bits, débordement défini)
    ADD = 16
    SUB = 17
    MUL = 18
    DIV = 19
    NEG = 20
    # comparaisons -> Bool
    EQ = 32
    NE = 33
    LT = 34
    GT = 35
    LE = 36
    GE = 37
    # logique
    NOT = 48
    # contrôle de flux (offset relatif signé sur 2 octets)
    JUMP = 64
    JUMP_IF_FALSE = 65   # dépile ; saute si faux
    # appels et intégrées
    CALL = 80            # u16 index_fonction, u8 nb_args
    SAY = 81             # dépile, affiche (effet Console), empile 0
    RETURN = 96          # dépile la valeur de retour


OP_NAMES = {v: k for k, v in vars(Op).items() if isinstance(v, int) and not k.startswith("_")}

# opérateur binaire AST -> opcode
BIN_OPS = {
    "+": Op.ADD, "-": Op.SUB, "*": Op.MUL, "/": Op.DIV,
    "==": Op.EQ, "!=": Op.NE, "<": Op.LT, ">": Op.GT, "<=": Op.LE, ">=": Op.GE,
}

_WITH_U16 = {Op.CONST, Op.LOAD, Op.STORE, Op.JUMP, Op.JUMP_IF_FALSE}


@dataclass
class RTFunc:
    name: str
    num_params: int
    num_locals: int
    code: bytes


@dataclass
class RTModule:
    consts: list
    functions: list      # list[RTFunc]
    entry: int


# --- assemblage : instructions symboliques -> octets -------------------------
# Une instruction symbolique est un couple [op, arg]. Pour les sauts, arg est un
# *index d'instruction cible* (label), résolu ici en offset d'octets relatif.

def instr_size(op):
    if op in _WITH_U16:
        return 3
    if op == Op.CALL:
        return 4
    return 1


def assemble(instrs):
    offsets = []
    pos = 0
    for op, _ in instrs:
        offsets.append(pos)
        pos += instr_size(op)
    offsets.append(pos)  # sentinelle : saut vers la fin (label == len(instrs))

    code = bytearray()
    for i, (op, arg) in enumerate(instrs):
        code.append(op)
        if op in (Op.CONST, Op.LOAD, Op.STORE):
            code += _u16(arg)
        elif op in (Op.JUMP, Op.JUMP_IF_FALSE):
            after = offsets[i] + 3
            code += struct.pack(">h", offsets[arg] - after)
        elif op == Op.CALL:
            fidx, argc = arg
            code += _u16(fidx)
            code.append(argc)
    return bytes(code)


# --- sérialisation du module -------------------------------------------------

def _u16(x):
    return bytes(((x >> 8) & 0xFF, x & 0xFF))


def serialize(consts, functions, entry):
    out = bytearray()
    out += MAGIC
    out.append(VERSION)

    out += _u16(len(consts))
    for c in consts:
        if isinstance(c, bool):                 # bool avant int (sous-classe)
            out.append(1)
            out.append(1 if c else 0)
        elif isinstance(c, int):
            out.append(0)
            out += struct.pack(">q", c)
        else:
            b = c.encode("utf-8")
            out.append(2)
            out += _u16(len(b))
            out += b

    out += _u16(len(functions))
    for name, nparams, nlocals, code in functions:
        nb = name.encode("utf-8")
        out += _u16(len(nb))
        out += nb
        out += _u16(nparams)
        out += _u16(nlocals)
        out += struct.pack(">I", len(code))
        out += code

    out += _u16(entry)
    return bytes(out)


def deserialize(data):
    if data[:4] != MAGIC:
        raise CandorError("fichier .canc invalide (signature absente)", None, "vm")
    i = 5
    if data[4] != VERSION:
        raise CandorError(f"version de bytecode {data[4]} non supportée", None, "vm")

    ncon = (data[i] << 8) | data[i + 1]
    i += 2
    consts = []
    for _ in range(ncon):
        tag = data[i]
        i += 1
        if tag == 0:
            (val,) = struct.unpack_from(">q", data, i)
            i += 8
            consts.append(val)
        elif tag == 1:
            consts.append(data[i] != 0)
            i += 1
        elif tag == 2:
            ln = (data[i] << 8) | data[i + 1]
            i += 2
            consts.append(data[i:i + ln].decode("utf-8"))
            i += ln
        else:
            raise CandorError(f"tag de constante inconnu : {tag}", None, "vm")

    nfun = (data[i] << 8) | data[i + 1]
    i += 2
    functions = []
    for _ in range(nfun):
        ln = (data[i] << 8) | data[i + 1]
        i += 2
        name = data[i:i + ln].decode("utf-8")
        i += ln
        nparams = (data[i] << 8) | data[i + 1]
        i += 2
        nlocals = (data[i] << 8) | data[i + 1]
        i += 2
        (clen,) = struct.unpack_from(">I", data, i)
        i += 4
        code = bytes(data[i:i + clen])
        i += clen
        functions.append(RTFunc(name, nparams, nlocals, code))

    entry = (data[i] << 8) | data[i + 1]
    return RTModule(consts, functions, entry)


# --- désassembleur (lit les octets et les rend lisibles) ---------------------

def _const_repr(c):
    if isinstance(c, bool):
        return "true" if c else "false"
    if isinstance(c, str):
        return '"' + c + '"'
    return str(c)


def signed16(code, ip):
    v = (code[ip] << 8) | code[ip + 1]
    return v - 0x10000 if v >= 0x8000 else v


def disassemble(module):
    lines = [
        f"; module Candor — {len(module.functions)} fonction(s), "
        f"{len(module.consts)} constante(s)",
        "; constantes : " + ", ".join(
            f"[{i}]={_const_repr(c)}" for i, c in enumerate(module.consts)
        ),
    ]
    for fi, fn in enumerate(module.functions):
        mark = "  (entrée)" if fi == module.entry else ""
        lines.append(f"\nfn #{fi} {fn.name}  params={fn.num_params} locals={fn.num_locals}{mark}")
        code = fn.code
        ip = 0
        while ip < len(code):
            start = ip
            op = code[ip]
            ip += 1
            name = OP_NAMES.get(op, f"?{op}")
            if op in (Op.CONST, Op.LOAD, Op.STORE):
                arg = (code[ip] << 8) | code[ip + 1]
                ip += 2
                extra = f"   ; {_const_repr(module.consts[arg])}" if op == Op.CONST else ""
                lines.append(f"  {start:4} {name:14} {arg}{extra}")
            elif op in (Op.JUMP, Op.JUMP_IF_FALSE):
                rel = signed16(code, ip)
                ip += 2
                lines.append(f"  {start:4} {name:14} {rel:+}  -> {ip + rel}")
            elif op == Op.CALL:
                fidx = (code[ip] << 8) | code[ip + 1]
                argc = code[ip + 2]
                ip += 3
                lines.append(f"  {start:4} {name:14} fn#{fidx} argc={argc}  ; {module.functions[fidx].name}")
            else:
                lines.append(f"  {start:4} {name}")
    return "\n".join(lines)
