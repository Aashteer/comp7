"""TAC (трёхадресный код) для if-else и форматирование отчёта."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from if_ast import IfStmtNode, ProgramNode, format_ast
from ir_passes import IfConversionPass, RedundantTempElimPass, PassResult, run_passes


@dataclass
class TacInstr:
    index: int
    op: str
    args: List[str]
    comment: str = ""

    def format(self) -> str:
        args_s = ", ".join(self.args) if self.args else ""
        c = f"  ; {self.comment}" if self.comment else ""
        return f"{self.index:3d}: {self.op}({args_s}){c}"


def _emit_gen():
    n = 0
    instrs: List[TacInstr] = []

    def emit(op: str, args: List[str], comment: str = "") -> str:
        nonlocal n
        n += 1
        instrs.append(TacInstr(n, op, args, comment))
        return f"t{n}"

    return emit, instrs


def _expr_to_tac(expr, emit) -> str:
    from if_ast import ExprNode

    if expr.kind in ("identifier", "integer"):
        return expr.value
    if expr.kind == "binop" and expr.left and expr.right:
        left = _expr_to_tac(expr.left, emit)
        right = _expr_to_tac(expr.right, emit)
        return emit(expr.op.upper(), [left, right, ""], f"{left} {expr.op} {right}")
    return "?"


def ast_to_tac(node: ProgramNode) -> List[TacInstr]:
    """Генерация TAC для if-else (-O0, с условным переходом)."""
    emit, instrs = _emit_gen()
    s = node.stmt

    left = _expr_to_tac(s.cond_left, emit)
    right = _expr_to_tac(s.cond_right, emit)
    cmp_temp = emit("CMP", [left, s.rel_op, right], "условие if")
    emit("BR_COND", [cmp_temp, "L_then", "L_else"], "условный переход")

    emit("LABEL", ["L_then"], "ветка then")
    then_val = _expr_to_tac(s.then_stmt.expr, emit)
    emit("ASSIGN", [s.then_stmt.target, then_val], "then-присваивание")
    emit("GOTO", ["L_end"], "")

    emit("LABEL", ["L_else"], "ветка else")
    else_val = _expr_to_tac(s.else_stmt.expr, emit)
    emit("ASSIGN", [s.else_stmt.target, else_val], "else-присваивание")

    emit("LABEL", ["L_end"], "слияние потоков")
    return instrs


def tac_to_canonical(node: ProgramNode) -> str:
    s = node.stmt
    return (
        f"if ({_canon_expr(s.cond_left)} {s.rel_op} {_canon_expr(s.cond_right)})\n"
        f"  {s.then_stmt.target} = {_canon_expr(s.then_stmt.expr)};\n"
        f"else\n"
        f"  {s.else_stmt.target} = {_canon_expr(s.else_stmt.expr)};"
    )


def _canon_expr(expr) -> str:
    from if_ast import ExprNode

    if expr.kind in ("identifier", "integer"):
        return expr.value
    if expr.kind == "binop" and expr.left and expr.right:
        return f"({_canon_expr(expr.left)} {expr.op} {_canon_expr(expr.right)})"
    return "?"


def run_if_optimizations(instrs: List[TacInstr]) -> List[PassResult]:
    return run_passes(instrs, [RedundantTempElimPass(), IfConversionPass()])


def section(title: str) -> str:
    return f"\n{title}\n\n"


def format_if_bonus_report(ast_text: str, instrs: List[TacInstr], opts: List[PassResult], canon: str) -> str:
    parts = [
        section("Собственный конвейер IR (Python)").strip(),
        section("AST (конструкция if-else, ЛР5)").strip(),
        ast_text,
        section("IR: трёхадресный код (-O0, до оптимизаций)").strip(),
    ]
    parts.extend(i.format() for i in instrs)
    parts.append(section("Каноническая строковая форма").strip())
    parts.append(canon)

    for opt in opts:
        parts.append(opt.format_report())

    final = opts[-1].output_ir if opts else instrs
    parts.append(section("Итоговый IR (после своих оптимизаций)").strip())
    parts.extend(i.format() for i in final)
    return "\n".join(parts)
