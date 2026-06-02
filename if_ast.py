"""AST для конструкции if-else (ЛР5 / доп. задание)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Union

from scanner import Token


@dataclass
class ExprNode:
    kind: str
    value: str = ""
    left: Optional["ExprNode"] = None
    right: Optional["ExprNode"] = None
    op: str = ""


@dataclass
class AssignNode:
    target: str
    expr: ExprNode
    line: int
    col: int


@dataclass
class IfStmtNode:
    cond_left: ExprNode
    rel_op: str
    cond_right: ExprNode
    then_stmt: AssignNode
    else_stmt: AssignNode
    line: int
    col: int


@dataclass
class ProgramNode:
    stmt: IfStmtNode


class IfASTBuilder:
    """Строит AST из потока лексем (после успешного синтаксического разбора)."""

    REL_OPS = {">", "<", ">=", "<=", "==", "!="}

    def __init__(self, tokens: List[Token]):
        self.tokens = self._filter(tokens)
        self.i = 0

    @staticmethod
    def _filter(tokens: List[Token]) -> List[Token]:
        out: List[Token] = []
        for t in tokens:
            if t.token_type == "ERROR":
                continue
            if t.token_type == "DELIMITER" and t.value in ("(пробел)", "\\t"):
                continue
            out.append(t)
        return out

    def build(self) -> Optional[ProgramNode]:
        if not self.tokens:
            return None
        stmt = self._parse_if_stmt()
        return ProgramNode(stmt=stmt) if stmt else None

    def _cur(self) -> Optional[Token]:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _adv(self) -> None:
        self.i += 1

    def _kw(self, w: str) -> bool:
        t = self._cur()
        if t and t.token_type == "KEYWORD" and t.value == w:
            self._adv()
            return True
        return False

    def _delim(self, ch: str) -> bool:
        t = self._cur()
        if t and t.token_type == "DELIMITER" and t.value == ch:
            self._adv()
            return True
        return False

    def _op(self, op: str) -> bool:
        t = self._cur()
        if t and t.token_type == "OPERATOR" and t.value == op:
            self._adv()
            return True
        return False

    def _skip_nl(self) -> None:
        while self._cur() and self._cur().token_type == "DELIMITER" and self._cur().value == "\\n":
            self._adv()

    def _parse_if_stmt(self) -> Optional[IfStmtNode]:
        if not self._kw("if"):
            return None
        line = self._cur().line if self._cur() else 1
        col = self._cur().start if self._cur() else 1

        left = self._parse_expr()
        rel = self._parse_rel_op()
        right = self._parse_expr()
        if left is None or rel is None or right is None:
            return None

        if not self._delim(":"):
            return None
        self._skip_nl()
        then_stmt = self._parse_assign()
        if then_stmt is None:
            return None

        self._skip_nl()
        if not self._kw("else"):
            return None
        if not self._delim(":"):
            return None
        self._skip_nl()
        else_stmt = self._parse_assign()
        if else_stmt is None:
            return None

        self._skip_nl()
        self._delim(";")
        return IfStmtNode(left, rel, right, then_stmt, else_stmt, line, col)

    def _parse_rel_op(self) -> Optional[str]:
        t = self._cur()
        if t and t.token_type == "OPERATOR" and t.value in self.REL_OPS:
            self._adv()
            return t.value
        return None

    def _parse_assign(self) -> Optional[AssignNode]:
        t = self._cur()
        if not t or t.token_type != "IDENTIFIER":
            return None
        target = t.value
        line, col = t.line, t.start
        self._adv()
        if not self._op("="):
            return None
        expr = self._parse_expr()
        if expr is None:
            return None
        return AssignNode(target, expr, line, col)

    def _parse_expr(self) -> Optional[ExprNode]:
        node = self._parse_term()
        if node is None:
            return None
        while True:
            t = self._cur()
            if t and t.token_type == "OPERATOR" and t.value in ("+", "-"):
                op = t.value
                self._adv()
                right = self._parse_term()
                if right is None:
                    return None
                node = ExprNode("binop", op=op, left=node, right=right)
            else:
                break
        return node

    def _parse_term(self) -> Optional[ExprNode]:
        node = self._parse_factor()
        if node is None:
            return None
        while True:
            t = self._cur()
            if t and t.token_type == "OPERATOR" and t.value in ("*", "/", "%", "//"):
                op = t.value
                self._adv()
                right = self._parse_factor()
                if right is None:
                    return None
                node = ExprNode("binop", op=op, left=node, right=right)
            else:
                break
        return node

    def _parse_factor(self) -> Optional[ExprNode]:
        t = self._cur()
        if t is None:
            return None
        if t.token_type in ("IDENTIFIER", "INTEGER"):
            self._adv()
            return ExprNode(t.token_type.lower(), t.value)
        if t.token_type == "DELIMITER" and t.value == "(":
            self._adv()
            node = self._parse_expr()
            if node is None:
                return None
            self._delim(")")
            return node
        return None


def format_ast(node: ProgramNode, indent: int = 0) -> str:
    pad = "  " * indent
    s = node.stmt
    lines = [
        f"{pad}Program",
        f"{pad}  IfStmt @{s.line}:{s.col}",
        f"{pad}    Condition: {_fmt_expr(s.cond_left)} {s.rel_op} {_fmt_expr(s.cond_right)}",
        f"{pad}    Then: Assign({s.then_stmt.target} = {_fmt_expr(s.then_stmt.expr)})",
        f"{pad}    Else: Assign({s.else_stmt.target} = {_fmt_expr(s.else_stmt.expr)})",
    ]
    return "\n".join(lines)


def _fmt_expr(e: ExprNode) -> str:
    if e.kind in ("identifier", "integer"):
        return e.value
    if e.kind == "binop" and e.left and e.right:
        return f"({ _fmt_expr(e.left) } {e.op} { _fmt_expr(e.right) })"
    return "?"
