"""
Update note: Never use this module to test your emit functions.
Use the file `auto_test.py` in the same directory instead.

"""

import ast
from astpretty import pprint
from yapypy.extended_python.parser import parse
from yapypy.extended_python.symbol_analyzer import ASTTagger, SymTable, to_tagged_ast, Tag
from yapypy.extended_python.pybc_emit import py_compile
import dis


def parse_expr(expr_code):
    return parse(expr_code).result.body[0].value


stmt = parse("""
print(1)
def f(x):
    a = 1
    def g(y):
        a + 1
        def u(z):
            k = 1
            v + k
    v = 3
    k = 4
""").result

res: Tag = to_tagged_ast(stmt)
print(res.tag.show_resolution())
#
stmt = parse("""
print({1: 2 for i in range(2)})
""").result

code = py_compile(stmt)
exec(code)
try:
    parse_expr('f(a=1, b)\n')
except SyntaxError:
    print('good')
#
# from bytecode import Bytecode, Instr, Label
# bc = Bytecode()
# bc.append(Instr("BUILD_MAP", 0))
# bc.append(Instr("LOAD_GLOBAL", "range"))
# bc.append(Instr("LOAD_CONST", 2))
# bc.append(Instr("CALL_FUNCTION", 1, lineno=2))
#
# l1 = Label()
# l2 = Label()
# bc.append(Instr("GET_ITER"))
# bc.append(l1)
# bc.append(Instr("FOR_ITER", l2))
# bc.append(Instr("STORE_FAST", "i"))
# bc.append(Instr("LOAD_CONST", 2))
# bc.append(Instr("LOAD_CONST", 1, lineno=1))
# bc.append(Instr("MAP_ADD", 2))
# bc.append(Instr("JUMP_ABSOLUTE", l1))
# bc.append(l2)
# bc.append(Instr("RETURN_VALUE", ))
#
# code = bc.to_code()
# print(eval(code))
# dis.show_code(code)
# dis.dis(code)
