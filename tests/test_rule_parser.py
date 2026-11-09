import pytest

from market_pulse.errors import RuleSyntaxError
from market_pulse.rules import BoolOp, Comparison, parse_rule, tokenize


def test_parses_single_comparison() -> None:
    rule = parse_rule("RSI_14 < 30")
    assert rule.root == Comparison("rsi_14", "<", 30.0)
    assert rule.identifiers == ("rsi_14",)


def test_and_binds_tighter_than_or() -> None:
    rule = parse_rule("rsi_14 < 30 or rsi_14 > 70 and close >= 1e3")
    assert rule.root == BoolOp(
        "or",
        (
            Comparison("rsi_14", "<", 30.0),
            BoolOp("and", (Comparison("rsi_14", ">", 70.0), Comparison("close", ">=", 1000.0))),
        ),
    )
    assert rule.identifiers == ("rsi_14", "close")


def test_parentheses_override_precedence() -> None:
    rule = parse_rule("(macd_hist > 0 OR rsi_14 < 25) AND volume != -1.5")
    assert isinstance(rule.root, BoolOp)
    assert rule.root.op == "and"
    assert str(rule) == "(macd_hist > 0 or rsi_14 < 25) and volume != -1.5"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"rsi_14": 25.0, "close": 10.0}, True),
        ({"rsi_14": 75.0, "close": 2000.0}, True),
        ({"rsi_14": 75.0, "close": 10.0}, False),
        ({"rsi_14": 50.0, "close": 2000.0}, False),
        ({"rsi_14": float("nan"), "close": 2000.0}, False),
        ({}, False),
    ],
)
def test_evaluation(values: dict[str, float], expected: bool) -> None:
    rule = parse_rule("rsi_14 < 30 or (rsi_14 > 70 and close > 1000)")
    assert rule.evaluate(values) is expected


def test_all_operators() -> None:
    values = {"x": 5.0}
    assert parse_rule("x == 5").evaluate(values)
    assert parse_rule("x != 4").evaluate(values)
    assert parse_rule("x <= 5").evaluate(values)
    assert parse_rule("x >= 5").evaluate(values)
    assert not parse_rule("x < 5").evaluate(values)
    assert not parse_rule("x > 5").evaluate(values)


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "rsi_14",
        "rsi_14 <",
        "rsi_14 < abc",
        "30 > rsi_14",
        "rsi_14 = 30",
        "rsi_14 < 30 and",
        "(rsi_14 < 30",
        "rsi_14 < 30)",
        "rsi_14 < 30 rsi_14 > 10",
        "__import__('os') < 1",
        "rsi_14 < 30; drop",
        "rsi_14 < 1e999",
        "x < 1 and " * 20 + "x < 1",
        "(" * 12 + "x < 1" + ")" * 12,
        "x < " + "1" * 300,
    ],
)
def test_rejects_invalid_or_unsafe_input(expression: str) -> None:
    with pytest.raises(RuleSyntaxError):
        parse_rule(expression)


def test_tokenizer_reports_position() -> None:
    with pytest.raises(RuleSyntaxError) as info:
        tokenize("rsi_14 < 30 $")
    assert info.value.details == {"position": 12}
