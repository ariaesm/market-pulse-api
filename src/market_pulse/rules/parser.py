"""A tiny, safe expression language for alert rules (no ``eval``).

Grammar (case-insensitive keywords)::

    expr        := and_expr ( "or" and_expr )*
    and_expr    := term ( "and" term )*
    term        := comparison | "(" expr ")"
    comparison  := IDENT OP NUMBER
    OP          := "<" | "<=" | ">" | ">=" | "==" | "!="
    IDENT       := [a-z_][a-z0-9_]*          e.g. rsi_14, ema_20, macd_hist, close
    NUMBER      := -?digits[.digits][e[+-]digits]

Examples: ``rsi_14 < 30``, ``rsi_14 < 30 and close > 100``,
``(macd_hist > 0 or rsi_14 < 25) and volume >= 1000``.

The parser is a hand-written tokenizer plus recursive-descent parser producing an
immutable AST. Inputs are bounded in length, number of comparisons and nesting depth.
"""

from __future__ import annotations

import math
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from market_pulse.errors import RuleSyntaxError

MAX_EXPRESSION_LENGTH = 256
MAX_COMPARISONS = 16
MAX_DEPTH = 8

ComparisonOp = Literal["<", "<=", ">", ">=", "==", "!="]

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op><=|>=|==|!=|<|>)
  | (?P<lparen>\()
  | (?P<rparen>\))
    """,
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class Token:
    """A lexical token with its source position (for error messages)."""

    kind: str
    text: str
    pos: int


@dataclass(frozen=True, slots=True)
class Comparison:
    """Leaf node: ``identifier op number``."""

    identifier: str
    op: ComparisonOp
    value: float

    def evaluate(self, values: Mapping[str, float]) -> bool:
        """Compare; a missing or NaN operand evaluates to ``False``."""
        current = values.get(self.identifier)
        if current is None or math.isnan(current):
            return False
        return _OPS[self.op](float(current), self.value)

    def __str__(self) -> str:
        return f"{self.identifier} {self.op} {self.value:g}"


@dataclass(frozen=True, slots=True)
class BoolOp:
    """Inner node combining operands with ``and`` / ``or``."""

    op: Literal["and", "or"]
    operands: tuple[Node, ...]

    def evaluate(self, values: Mapping[str, float]) -> bool:
        """Short-circuit evaluation of all operands."""
        results = (operand.evaluate(values) for operand in self.operands)
        return all(results) if self.op == "and" else any(results)

    def __str__(self) -> str:
        parts = [f"({o})" if isinstance(o, BoolOp) else str(o) for o in self.operands]
        return f" {self.op} ".join(parts)


Node = Comparison | BoolOp


@dataclass(frozen=True, slots=True)
class Rule:
    """A parsed rule: the AST plus metadata."""

    source: str
    root: Node

    @property
    def identifiers(self) -> tuple[str, ...]:
        """Distinct identifiers referenced by the rule, in first-seen order."""
        seen: dict[str, None] = {}

        def walk(node: Node) -> None:
            if isinstance(node, Comparison):
                seen.setdefault(node.identifier, None)
            else:
                for child in node.operands:
                    walk(child)

        walk(self.root)
        return tuple(seen)

    def evaluate(self, values: Mapping[str, float]) -> bool:
        """Evaluate the rule against a mapping of identifier -> latest value."""
        return self.root.evaluate(values)

    def __str__(self) -> str:
        return str(self.root)


def tokenize(text: str) -> list[Token]:
    """Split ``text`` into tokens, raising :class:`RuleSyntaxError` on bad input."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise RuleSyntaxError(
                f"unexpected character {text[pos]!r} at position {pos}", details={"position": pos}
            )
        kind = match.lastgroup or ""
        if kind != "ws":
            value = match.group()
            if kind == "ident" and value.lower() in {"and", "or"}:
                kind, value = value.lower(), value.lower()
            elif kind == "ident":
                value = value.lower()
            tokens.append(Token(kind, value, pos))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.comparisons = 0

    def _peek(self) -> Token | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _expect(self, kind: str, what: str) -> Token:
        token = self._peek()
        if token is None:
            raise RuleSyntaxError(f"expected {what} but the expression ended")
        if token.kind != kind:
            raise RuleSyntaxError(
                f"expected {what} at position {token.pos}, found {token.text!r}",
                details={"position": token.pos},
            )
        self.index += 1
        return token

    def parse(self) -> Node:
        node = self._expr(0)
        token = self._peek()
        if token is not None:
            raise RuleSyntaxError(
                f"unexpected {token.text!r} at position {token.pos}",
                details={"position": token.pos},
            )
        return node

    def _binary(self, keyword: Literal["and", "or"], depth: int) -> Node:
        sub = self._term if keyword == "and" else self._and_expr
        operands = [sub(depth)]
        while (token := self._peek()) is not None and token.kind == keyword:
            self.index += 1
            operands.append(sub(depth))
        return operands[0] if len(operands) == 1 else BoolOp(keyword, tuple(operands))

    def _expr(self, depth: int) -> Node:
        if depth > MAX_DEPTH:
            raise RuleSyntaxError(f"expression nested deeper than {MAX_DEPTH} levels")
        return self._binary("or", depth)

    def _and_expr(self, depth: int) -> Node:
        return self._binary("and", depth)

    def _term(self, depth: int) -> Node:
        token = self._peek()
        if token is not None and token.kind == "lparen":
            self.index += 1
            node = self._expr(depth + 1)
            self._expect("rparen", "')'")
            return node
        return self._comparison()

    def _comparison(self) -> Comparison:
        ident = self._expect("ident", "an indicator name")
        op = self._expect("op", "a comparison operator")
        number = self._expect("number", "a number")
        value = float(number.text)
        if not math.isfinite(value):
            raise RuleSyntaxError(f"number {number.text!r} is not finite")
        self.comparisons += 1
        if self.comparisons > MAX_COMPARISONS:
            raise RuleSyntaxError(f"too many comparisons (max {MAX_COMPARISONS})")
        return Comparison(ident.text, op.text, value)  # type: ignore[arg-type]


def parse_rule(text: str) -> Rule:
    """Parse an alert rule expression into a :class:`Rule`."""
    if not text or not text.strip():
        raise RuleSyntaxError("rule expression is empty")
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise RuleSyntaxError(f"rule expression longer than {MAX_EXPRESSION_LENGTH} characters")
    return Rule(text.strip(), _Parser(tokenize(text)).parse())
