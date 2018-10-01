import ast
from typing import NamedTuple
from kizmi.extended_python.symbol_analyzer import SymTable, Tag
from kizmi.utils.namedlist import INamedList, as_namedlist, trait
from Redy.Magic.Pattern import Pattern
from bytecode import *
from bytecode.concrete import FreeVar, CellVar
from bytecode.flags import CompilerFlags


class IndexedAnalyzedSymTable(NamedTuple):
    bounds: list
    freevars: list
    cellvars: list
    borrowed_cellvars: list


class Context(INamedList, metaclass=trait(as_namedlist)):
    bc: Bytecode
    sym_tb: IndexedAnalyzedSymTable
    parent: 'Context'

    def update(self, bc=None, sym_tb=None, parent=None):
        return Context(bc if bc is not None else self.bc,
                       sym_tb if sym_tb is not None else self.sym_tb,
                       parent if parent is not None else self.parent)

    def enter_new(self, tag_table: SymTable):

        sym_tb = IndexedAnalyzedSymTable(
            *[list(each) for each in tag_table.analyzed])

        bc = Bytecode()
        if tag_table.depth > 1:
            bc.flags |= CompilerFlags.NESTED

        if not sym_tb.freevars:
            bc.flags |= CompilerFlags.NOFREE
        else:
            bc.freevars.extend(sym_tb.freevars)

        bc.cellvars.extend(sym_tb.cellvars)
        return self.update(parent=self, bc=Bytecode(), sym_tb=sym_tb)

    def load_name(self, name, lineno=None):
        sym_tb = self.sym_tb
        if name in sym_tb.cellvars:
            return Instr('LOAD_DEREF', CellVar(name), lineno=lineno)
        elif name in sym_tb.freevars:
            return Instr('LOAD_DEREF', FreeVar(name), lineno=lineno)
        elif name in sym_tb.bounds:
            return Instr('LOAD_FAST', name, lineno=lineno)
        return Instr("LOAD_GLOBAL", name, lineno=lineno)

    def store_name(self, name, lineno=None):
        sym_tb = self.sym_tb
        if name in sym_tb.cellvars:
            self.bc.append(Instr('STORE_DEREF', CellVar(name), lineno=lineno))
        elif name in sym_tb.freevars:
            self.bc.append(Instr('STORE_DEREF', FreeVar(name), lineno=lineno))
        elif name in sym_tb.bounds:
            self.bc.append(Instr('STORE_FAST', name, lineno=lineno))
        return Instr("STORE_GLOBAL", name, lineno=lineno)

    def load_closure(self, lineno=None):
        parent = self.parent
        freevars = self.sym_tb.freevars
        if freevars:
            for each in self.sym_tb.freevars:
                if each in parent.sym_tb.cellvars:
                    parent.bc.append(
                        Instr('LOAD_CLOSURE', CellVar(each), lineno=lineno))
                elif each in parent.sym_tb.borrowed_cellvars:
                    parent.bc.append(
                        Instr('LOAD_CLOSURE', FreeVar(each), lineno=lineno))
                else:
                    raise RuntimeError
            parent.bc.append(Instr('BUILD_TUPLE', len(freevars)))


@Pattern
def py_emit(node: ast.AST, ctx: Context):
    return type(node)


@py_emit.case(Tag)
def py_emit(node: Tag, ctx: Context):
    new_ctx = ctx.enter_new(node.tag)
    return py_emit(node.it, new_ctx)


@py_emit.case(ast.FunctionDef)
def py_emit(node: ast.FunctionDef, new_ctx: Context):
    """
    https://docs.python.org/3/library/dis.html#opcode-MAKE_FUNCTION
    MAKE_FUNCTION flags:
    0x01 a tuple of default values for positional-only and positional-or-keyword parameters in positional order
    0x02 a dictionary of keyword-only parameters’ default values
    0x04 an annotation dictionary
    0x08 a tuple containing cells for free variables, making a closure
    the code associated with the function (at TOS1)
    the qualified name of the function (at TOS)

    """
    parent_ctx = new_ctx.parent
    args = node.args
    make_function_flags = 0
    if args.defaults:
        make_function_flags |= 0x01
    if args.kw_defaults:
        make_function_flags |= 0x02

    annotations = []
    for arg in args.args:
        if arg.annotation:
            annotations.append((arg.arg, arg.annotation))

    for arg in args.kwonlyargs:
        if arg.annotation:
            annotations.append((arg.arg, arg.annotation))
    arg = args.vararg
    if arg and arg.annotation:
        annotations.append((arg.arg, arg.annotation))

    arg = args.kwarg
    if arg and arg.annotation:
        annotations.append((arg.arg, arg.annotation))

    if any(annotations):
        make_function_flags |= 0x04

    raise NotImplemented


@py_emit.case(ast.Name)
def py_emit(node: ast.Name, ctx: Context):
    ctx.load_name(node.id, lineno=node.lineno)


@py_emit.case(ast.Expr)
def py_emit(node: ast.Expr, ctx: Context):
    py_emit(node, ctx)
    ctx.bc.append('POP_TOP')


@py_emit.case(ast.YieldFrom)
def py_emit(node: ast.YieldFrom, ctx: Context):
    append = ctx.bc.append
    py_emit(node.value, ctx)
    append(Instr('GET_YIELD_FROM_ITER', lineno=node.lineno))
    append(Instr('LOAD_CONST', None, lineno=node.lineno))
    append(Instr("YIELD_FROM", lineno=node.lineno))


@py_emit.case(ast.Yield)
def py_emit(node: ast.Yield, ctx: Context):
    py_emit(node.value)
    ctx.bc.append(Instr('YIELD_VALUE', lineno=node.lineno))


@py_emit.case(ast.Return)
def py_emit(node: ast.Return, ctx: Context):
    py_emit(node.value)
    ctx.bc.append(Instr('RETURN_VALUE', lineno=node.lineno))


@py_emit.case(ast.Pass)
def py_emit(node: ast.Pass, ctx: Context):
    pass


@py_emit.case(ast.UnaryOp)
def py_emit(node: ast.UnaryOp, ctx: Context):
    py_emit(node.value, ctx)
    inst = {
        ast.Not: "UNARY_NOT",
        ast.USub: "UNARY_NEGATIVE",
        ast.UAdd: "UNARY_POSITIVE",
        ast.Invert: "UNARY_INVERT"
    }.get(type(node.op))
    if inst:
        ctx.bc.append(Instr(inst, lineno=node.lineno))
    else:
        raise TypeError("type mismatched")


@py_emit.case(ast.BinOp)
def py_emit(node: ast.BinOp, ctx: Context):
    py_emit(node.left, ctx)
    py_emit(node.right, ctx)
    inst = {
        ast.Add: "BINARY_ADD",
        ast.BitAnd: "BINARY_AND",
        ast.Sub: "BINARY_SUBTRACT",
        ast.Div: "BINARY_TRUE_DIVIDE",
        ast.FloorDiv: "BINARY_FLOOR_DIVIDE",
        ast.LShift: "BINARY_LSHIFT",
        ast.RShift: "BINARY_RSHIFT",
        ast.MatMult: "BINARY_MATRIX_MULTIPLY",
        ast.Pow: "BINARY_POWER",
        ast.BitOr: "BINARY_OR",
        ast.BitXor: "BINARY_XOR",
        ast.Mult: "BINARY_MULTIPLY",
        ast.Mod: "BINARY_MODULO"
    }.get(type(node.op))
    if inst:
        ctx.bc.append(Instr(inst, lineno=node.lineno))
    else:
        raise TypeError("type mismatched")


@py_emit.case(ast.BoolOp)
def py_emit(node: ast.BoolOp, ctx: Context):
    inst = {
        ast.And: "JUMP_IF_FALSE_OR_POP",
        ast.Or: "JUMP_IF_TRUE_OR_POP"
    }.get(type(node.op))
    if inst:
        label = Label()
        for expr in node.values[:-1]:
            py_emit(expr, ctx)
            ctx.bc.append(Instr(inst, label, lineno=node.lineno))
        py_emit(node.values[-1], ctx)
        ctx.bc.append(label)
    else:
        raise TypeError("type mismatched")


@py_emit.case(ast.Num)
def py_emit(node: ast.Num, ctx: Context):
    ctx.bc.append(Instr("LOAD_CONST", node.n, lineno=node.lineno))