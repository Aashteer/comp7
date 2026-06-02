from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from scanner import Token


@dataclass
class SyntaxErrorRecord:
    fragment: str
    line: int
    col: int
    message: str

    def location_ru(self) -> str:
        return f"строка {self.line}, позиция {self.col}"

    def location_en(self) -> str:
        return f"line {self.line}, position {self.col}"


@dataclass
class ParseResult:
    ok: bool
    errors: List[SyntaxErrorRecord] = field(default_factory=list)


class Parser:
    REL_OPS = {'>', '<', '>=', '<=', '==', '!='}
    SYNC_KEYWORDS: Set[str] = {'if', 'else', 'elif'}

    def __init__(self, tokens: List["Token"], lang: str = "ru"):
        self._raw = tokens
        self.tokens: List["Token"] = self._filter_tokens(tokens)
        self.i = 0
        self.errors: List[SyntaxErrorRecord] = []
        self.lang = lang if lang in ("ru", "en") else "ru"

    def _m(self, ru: str, en: str) -> str:
        return en if self.lang == "en" else ru

    @staticmethod
    def _filter_tokens(tokens: List["Token"]) -> List["Token"]:
        out: List["Token"] = []
        for t in tokens:
            if t.token_type == 'ERROR':
                continue
            if t.token_type == 'DELIMITER':
                if t.value in ('(пробел)', '\\t'):
                    continue
            out.append(t)
        return out

    def parse(self) -> ParseResult:
        self.errors = []
        self.i = 0
        if not self.tokens:
            self._add_error(
                "EOF",
                1,
                1,
                self._m("Пустой поток лексем после фильтрации", "Empty token stream after filtering"),
            )
            return ParseResult(ok=False, errors=list(self.errors))

        self._parse_if_stmt()

        if self._current() is not None:
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line,
                t.start,
                self._m(
                    "Лишние лексемы после завершения конструкции if-else",
                    "Extra tokens after the if-else construct",
                ),
            )
            while self._current() is not None:
                self._advance()

        return ParseResult(ok=len(self.errors) == 0, errors=list(self.errors))

    def _current(self) -> Optional["Token"]:
        if self.i >= len(self.tokens):
            return None
        return self.tokens[self.i]

    def _advance(self) -> None:
        self.i += 1

    def _fragment(self, t: Optional["Token"]) -> str:
        if t is None:
            return "EOF"
        return t.value if len(t.value) <= 32 else t.value[:29] + "..."

    def _add_error(self, fragment: str, line: int, col: int, message: str) -> None:
        self.errors.append(SyntaxErrorRecord(fragment=fragment, line=line, col=col, message=message))

    def _sync_skip_to(self, *sync_values: str) -> None:
        vals = set(sync_values)
        while self._current() is not None:
            t = self._current()
            if t.token_type == 'KEYWORD' and t.value in vals:
                return
            if t.token_type == 'DELIMITER' and t.value in vals:
                return
            if t.token_type == 'OPERATOR' and t.value in vals:
                return
            self._advance()

    def _parse_if_stmt(self) -> None:
        if not self._match_keyword("if"):
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m("Ожидалось ключевое слово if", "Expected keyword 'if'"),
            )
            self._sync_skip_to("if", ":")
            if not self._match_keyword("if"):
                return

        self._parse_condition()

        if not self._match_delimiter(":"):
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m("Ожидалось ':' после условия", "Expected ':' after condition"),
            )
            self._sync_skip_to(":", "else")
            self._match_delimiter(":")

        self._parse_suite(sync_before_else=True)

        if not self._match_keyword("else"):
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m("Ожидалось ключевое слово else", "Expected keyword 'else'"),
            )
            self._sync_skip_to("else", ":")
            if not self._match_keyword("else"):
                return

        if not self._match_delimiter(":"):
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m("Ожидалось ':' после else", "Expected ':' after 'else'"),
            )
            self._sync_skip_to(":", "if", "else")
            self._match_delimiter(":")

        self._parse_suite(sync_before_else=False)

        while self._is_newline():
            self._advance()

        if not self._match_delimiter(";"):
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m(
                    "Ожидалась ';' в конце конструкции if-else",
                    "Expected ';' at the end of the if-else construct",
                ),
            )
            self._sync_skip_to(";", "\n", "if")

        while self._is_newline():
            self._advance()

    def _parse_condition(self) -> None:
        start_ok = self._parse_expr()
        if not start_ok:
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m("Ожидалось выражение в условии", "Expected expression in condition"),
            )
            self._sync_skip_to(":", "else")
            return

        if not self._parse_rel_op():
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m(
                    "Ожидался оператор сравнения (>, <, >=, <=, ==, !=)",
                    "Expected comparison operator (>, <, >=, <=, ==, !=)",
                ),
            )
            self._sync_skip_to(":", "else")
            return

        if not self._parse_expr():
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m(
                    "Ожидалось выражение после оператора сравнения",
                    "Expected expression after comparison operator",
                ),
            )
            self._sync_skip_to(":", "else")

    def _parse_rel_op(self) -> bool:
        t = self._current()
        if t and t.token_type == "OPERATOR" and t.value in self.REL_OPS:
            self._advance()
            return True
        return False

    def _parse_suite(self, sync_before_else: bool) -> None:
        while self._is_newline():
            self._advance()

        if not self._parse_stmt():
            t = self._current()
            self._add_error(
                self._fragment(t),
                t.line if t else 1,
                t.start if t else 1,
                self._m(
                    "Ожидался оператор присваивания (идентификатор = выражение)",
                    "Expected assignment (identifier = expression)",
                ),
            )
            if sync_before_else:
                self._sync_skip_to("else", "if", ":")
            else:
                self._sync_skip_to("if", "else")
            return

        while self._is_newline():
            self._advance()

    def _parse_stmt(self) -> bool:
        t = self._current()
        if not t or t.token_type != "IDENTIFIER":
            return False
        self._advance()

        if not self._match_operator("="):
            ct = self._current()
            self._add_error(
                self._fragment(ct),
                ct.line if ct else t.line,
                ct.start if ct else t.start,
                self._m("Ожидался оператор '='", "Expected '=' operator"),
            )
            self._sync_skip_to("else", ";", "\n", ":")
            return False

        if not self._parse_expr():
            ct = self._current()
            self._add_error(
                self._fragment(ct),
                ct.line if ct else t.line,
                ct.start if ct else t.start,
                self._m(
                    "Ожидалось выражение в правой части присваивания",
                    "Expected expression on the right-hand side of assignment",
                ),
            )
            self._sync_skip_to("else", ";", "\n")
            return False

        return True

    def _parse_expr(self) -> bool:
        if not self._parse_term():
            return False
        while True:
            t = self._current()
            if t and t.token_type == "OPERATOR" and t.value in ("+", "-"):
                self._advance()
                if not self._parse_term():
                    ct = self._current()
                    self._add_error(
                        self._fragment(ct),
                        ct.line if ct else t.line,
                        ct.start if ct else t.start,
                        self._m(
                            "Ожидался терм после оператора + или -",
                            "Expected term after + or - operator",
                        ),
                    )
                    return False
            else:
                break
        return True

    def _parse_term(self) -> bool:
        if not self._parse_factor():
            return False
        while True:
            t = self._current()
            if t and t.token_type == "OPERATOR" and t.value in ("*", "/", "%", "//"):
                self._advance()
                if not self._parse_factor():
                    ct = self._current()
                    self._add_error(
                        self._fragment(ct),
                        ct.line if ct else t.line,
                        ct.start if ct else t.start,
                        self._m("Ожидался множитель после оператора", "Expected operand after operator"),
                    )
                    return False
            else:
                break
        return True

    def _parse_factor(self) -> bool:
        t = self._current()
        if t is None:
            self._add_error(
                "EOF",
                1,
                1,
                self._m("Незавершённое выражение", "Incomplete expression"),
            )
            return False

        if t.token_type == "IDENTIFIER" or t.token_type == "INTEGER":
            self._advance()
            return True

        if t.token_type == "DELIMITER" and t.value == "(":
            self._advance()
            if not self._parse_expr():
                return False
            if not self._match_delimiter(")"):
                ct = self._current()
                self._add_error(
                    self._fragment(ct),
                    ct.line if ct else t.line,
                    ct.start if ct else t.start,
                    self._m("Ожидалась закрывающая скобка ')'", "Expected closing parenthesis ')'"),
                )
                self._sync_skip_to(")", ":", "else", ";", "\n")
                self._match_delimiter(")")
            return True

        self._add_error(
            self._fragment(t),
            t.line,
            t.start,
            self._m("Ожидался идентификатор, число или '('", "Expected identifier, number, or '('"),
        )
        return False

    def _is_newline(self) -> bool:
        t = self._current()
        return t is not None and t.token_type == "DELIMITER" and t.value == "\\n"

    def _is_delimiter(self, ch: str) -> bool:
        t = self._current()
        return t is not None and t.token_type == "DELIMITER" and t.value == ch

    def _match_keyword(self, word: str) -> bool:
        t = self._current()
        if t and t.token_type == "KEYWORD" and t.value == word:
            self._advance()
            return True
        return False

    def _match_delimiter(self, ch: str) -> bool:
        t = self._current()
        if t and t.token_type == "DELIMITER" and t.value == ch:
            self._advance()
            return True
        return False

    def _match_operator(self, op: str) -> bool:
        t = self._current()
        if t and t.token_type == "OPERATOR" and t.value == op:
            self._advance()
            return True
        return False


class ParserError(Exception):
    pass
