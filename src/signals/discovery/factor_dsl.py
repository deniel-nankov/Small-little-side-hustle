"""Factor expression DSL — the AST engine under every discovery agent (Stage 4, #52).

All three reference systems mine the same object: an operator tree over market data
(NVIDIA's signal-discovery blueprint: 66 operators across arithmetic/rank/time-series
families; AlphaAgent [KDD'25]: ASTs with subtree-isomorphism originality scoring;
QuantaAlpha: evolved factor code). This module gives the platform that object as a
small, safe, deterministic core:

* immutable expression nodes (:class:`Feature`, :class:`Unary`, :class:`Binary`,
  :class:`TimeSeries`) evaluated over a :class:`Panel` of aligned price series;
* NaN as the only missing-data signal — warmups, gaps, and division-by-~0 all yield
  NaN and propagate, so a bad point can never fabricate a score;
* S-expression serialization + :func:`parse` (the LLM interchange format);
* AlphaAgent metrics: :func:`node_count` (symbolic length), :func:`param_count`,
  :func:`similarity` (largest common subtree) for originality regularization;
* seeded :func:`random_expression` for evolutionary search.

No eval()/exec() anywhere: expressions are data, not code (SECURITY.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

from src.signals.construction._common import make_scores

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date
    from random import Random

    from src.data.contracts.schemas import PriceData, SignalScore

Expression = Union["Feature", "Unary", "Binary", "TimeSeries"]

#: Leaf features derivable from PriceData. ``ret`` = 1-day pct change of adjusted close.
FEATURES = ("open", "high", "low", "close", "volume", "adjclose", "ret")

_NAN = math.nan
_EPS = 1e-12

#: Candidate windows for time-series operators (trading-day scale).
WINDOWS = (2, 3, 5, 10, 21, 63)


@dataclass(frozen=True)
class Panel:
    """Aligned per-ticker series for each leaf feature (missing points are NaN)."""

    dates: tuple[date, ...]
    series: dict[str, dict[str, list[float]]]  # feature -> ticker -> aligned values

    @property
    def tickers(self) -> list[str]:
        """Tickers present in the panel, sorted."""
        return sorted(self.series["close"])


def panel_from_prices(prices: Sequence[PriceData]) -> Panel:
    """Build an aligned :class:`Panel` from price bars (gaps become NaN).

    Args:
        prices: Bars for any tickers/dates.

    Returns:
        A panel over the union of dates, with ``ret`` precomputed per ticker.

    Raises:
        ValueError: if ``prices`` is empty.
    """
    if not prices:
        raise ValueError("no prices provided")
    dates = tuple(sorted({bar.date for bar in prices}))
    index = {day: i for i, day in enumerate(dates)}
    tickers = sorted({bar.ticker for bar in prices})
    fields: dict[str, Callable[[PriceData], float]] = {
        "open": lambda b: b.open,
        "high": lambda b: b.high,
        "low": lambda b: b.low,
        "close": lambda b: b.close,
        "volume": lambda b: b.volume,
        "adjclose": lambda b: b.adjusted_close,
    }
    series: dict[str, dict[str, list[float]]] = {
        feature: {t: [_NAN] * len(dates) for t in tickers} for feature in FEATURES
    }
    for bar in prices:
        i = index[bar.date]
        for feature, getter in fields.items():
            series[feature][bar.ticker][i] = getter(bar)
    for ticker in tickers:
        adj = series["adjclose"][ticker]
        ret = series["ret"][ticker]
        for i in range(1, len(dates)):
            prev, cur = adj[i - 1], adj[i]
            if not math.isnan(prev) and not math.isnan(cur) and abs(prev) > _EPS:
                ret[i] = cur / prev - 1.0
    return Panel(dates=dates, series=series)


def _nan_or(value: float) -> float:
    """Map non-finite results to NaN so downstream stats never see inf."""
    return value if math.isfinite(value) else _NAN


@dataclass(frozen=True)
class Feature:
    """A leaf: one raw feature series per ticker."""

    name: str

    def evaluate(self, panel: Panel) -> dict[str, list[float]]:
        """Return the feature's aligned series for every ticker."""
        if self.name not in FEATURES:
            raise ValueError(f"unknown feature {self.name!r} (choose from {FEATURES})")
        return {t: list(vals) for t, vals in panel.series[self.name].items()}

    def __str__(self) -> str:
        """S-expression form (a bare feature name)."""
        return self.name


_UNARY_OPS = ("neg", "abs", "sign", "log1p_abs", "cs_rank", "cs_zscore")
_BINARY_OPS = ("add", "sub", "mul", "div", "max", "min")
_TS_OPS = ("delay", "delta", "ts_mean", "ts_std", "ts_min", "ts_max", "momentum")


@dataclass(frozen=True)
class Unary:
    """An element-wise or cross-sectional unary operator."""

    op: str
    child: Expression

    def evaluate(self, panel: Panel) -> dict[str, list[float]]:
        """Apply the operator to the child's series."""
        values = self.child.evaluate(panel)
        if self.op in ("cs_rank", "cs_zscore"):
            return _cross_sectional(self.op, values, len(panel.dates))
        unary_fns: dict[str, Callable[[float], float]] = {
            "neg": lambda x: -x,
            "abs": abs,
            "sign": lambda x: math.copysign(1.0, x) if x != 0 else 0.0,
            "log1p_abs": lambda x: math.copysign(math.log1p(abs(x)), x),
        }
        fn = unary_fns.get(self.op)
        if fn is None:
            raise ValueError(f"unknown unary operator {self.op!r}")
        return {
            t: [_NAN if math.isnan(x) else _nan_or(fn(x)) for x in vals]
            for t, vals in values.items()
        }

    def __str__(self) -> str:
        """S-expression form."""
        return f"({self.op} {self.child})"


@dataclass(frozen=True)
class Binary:
    """An element-wise binary operator (NaN-propagating, division is NaN-safe)."""

    op: str
    left: Expression
    right: Expression

    def evaluate(self, panel: Panel) -> dict[str, list[float]]:
        """Apply the operator pointwise to both children's series."""
        binary_fns: dict[str, Callable[[float, float], float]] = {
            "add": lambda a, b: a + b,
            "sub": lambda a, b: a - b,
            "mul": lambda a, b: a * b,
            "div": lambda a, b: a / b if abs(b) > _EPS else _NAN,
            "max": max,
            "min": min,
        }
        fn = binary_fns.get(self.op)
        if fn is None:
            raise ValueError(f"unknown binary operator {self.op!r}")
        lhs = self.left.evaluate(panel)
        rhs = self.right.evaluate(panel)
        out: dict[str, list[float]] = {}
        for ticker, lvals in lhs.items():
            rvals = rhs[ticker]
            out[ticker] = [
                _NAN if math.isnan(a) or math.isnan(b) else _nan_or(fn(a, b))
                for a, b in zip(lvals, rvals, strict=True)
            ]
        return out

    def __str__(self) -> str:
        """S-expression form."""
        return f"({self.op} {self.left} {self.right})"


@dataclass(frozen=True)
class TimeSeries:
    """A rolling/time-shift operator with an integer window parameter."""

    op: str
    child: Expression
    window: int

    def evaluate(self, panel: Panel) -> dict[str, list[float]]:
        """Apply the rolling operator per ticker (warmup points are NaN)."""
        if self.op not in _TS_OPS:
            raise ValueError(f"unknown time-series operator {self.op!r}")
        if self.window < 1:
            raise ValueError(f"window must be >= 1, got {self.window}")
        values = self.child.evaluate(panel)
        return {t: self._roll(vals) for t, vals in values.items()}

    def _roll(self, vals: list[float]) -> list[float]:
        n, w = len(vals), self.window
        out = [_NAN] * n
        for i in range(n):
            if self.op == "delay":
                if i >= w:
                    out[i] = vals[i - w]
                continue
            if self.op == "delta":
                if i >= w and not (math.isnan(vals[i]) or math.isnan(vals[i - w])):
                    out[i] = vals[i] - vals[i - w]
                continue
            if self.op == "momentum":
                if i >= w and not (math.isnan(vals[i]) or math.isnan(vals[i - w])):
                    base = vals[i - w]
                    out[i] = vals[i] / base - 1.0 if abs(base) > _EPS else _NAN
                continue
            if i < w - 1:
                continue
            window_vals = vals[i - w + 1 : i + 1]
            if any(math.isnan(v) for v in window_vals):
                continue
            if self.op == "ts_mean":
                out[i] = sum(window_vals) / w
            elif self.op == "ts_std":
                mean = sum(window_vals) / w
                out[i] = (
                    math.sqrt(sum((v - mean) ** 2 for v in window_vals) / (w - 1))
                    if w > 1
                    else 0.0
                )
            elif self.op == "ts_min":
                out[i] = min(window_vals)
            elif self.op == "ts_max":
                out[i] = max(window_vals)
        return [_nan_or(v) if not math.isnan(v) else v for v in out]

    def __str__(self) -> str:
        """S-expression form (window is the trailing argument)."""
        return f"({self.op} {self.child} {self.window})"


def _cross_sectional(
    op: str, values: dict[str, list[float]], n_dates: int
) -> dict[str, list[float]]:
    """Apply cs_rank / cs_zscore across tickers at each date (NaNs excluded)."""
    tickers = sorted(values)
    out = {t: [_NAN] * n_dates for t in tickers}
    for i in range(n_dates):
        row = [(t, values[t][i]) for t in tickers if not math.isnan(values[t][i])]
        if len(row) < 2:
            continue
        if op == "cs_rank":
            ordered = sorted(row, key=lambda tv: tv[1])
            for rank, (t, _) in enumerate(ordered):
                out[t][i] = rank / (len(ordered) - 1)
        else:  # cs_zscore
            xs = [v for _, v in row]
            mean = sum(xs) / len(xs)
            var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
            std = math.sqrt(var)
            for t, v in row:
                out[t][i] = (v - mean) / std if std > _EPS else 0.0
    return out


# ------------------------------------------------------------------ metrics (AlphaAgent)


def node_count(expr: Expression) -> int:
    """Symbolic length SL(f): total AST nodes."""
    if isinstance(expr, Feature):
        return 1
    if isinstance(expr, Unary | TimeSeries):
        return 1 + node_count(expr.child)
    return 1 + node_count(expr.left) + node_count(expr.right)


def param_count(expr: Expression) -> int:
    """Parameter count PC(f): free hyperparameters (time-series windows)."""
    if isinstance(expr, Feature):
        return 0
    if isinstance(expr, TimeSeries):
        return 1 + param_count(expr.child)
    if isinstance(expr, Unary):
        return param_count(expr.child)
    return param_count(expr.left) + param_count(expr.right)


def depth(expr: Expression) -> int:
    """Tree depth (a lone feature has depth 1)."""
    if isinstance(expr, Feature):
        return 1
    if isinstance(expr, Unary | TimeSeries):
        return 1 + depth(expr.child)
    return 1 + max(depth(expr.left), depth(expr.right))


def _subtrees(expr: Expression, acc: dict[str, int]) -> None:
    acc[str(expr)] = node_count(expr)
    if isinstance(expr, Unary | TimeSeries):
        _subtrees(expr.child, acc)
    elif isinstance(expr, Binary):
        _subtrees(expr.left, acc)
        _subtrees(expr.right, acc)


def similarity(a: Expression, b: Expression) -> int:
    """AlphaAgent originality metric: size of the largest common subtree of a and b."""
    subs_a: dict[str, int] = {}
    subs_b: dict[str, int] = {}
    _subtrees(a, subs_a)
    _subtrees(b, subs_b)
    common = set(subs_a) & set(subs_b)
    return max((subs_a[s] for s in common), default=0)


# ----------------------------------------------------------------------- serialization


def parse(text: str) -> Expression:
    """Parse an S-expression produced by ``str(expr)`` back into an AST.

    Args:
        text: e.g. ``"(div (delta close 5) (ts_std ret 21))"``.

    Returns:
        The expression tree.

    Raises:
        ValueError: on malformed input or unknown operators (message contains 'parse').
    """
    tokens = text.replace("(", " ( ").replace(")", " ) ").split()
    expr, pos = _parse_tokens(tokens, 0)
    if pos != len(tokens):
        raise ValueError(f"parse error: trailing tokens in {text!r}")
    return expr


def _parse_tokens(tokens: list[str], pos: int) -> tuple[Expression, int]:
    if pos >= len(tokens):
        raise ValueError("parse error: unexpected end of input")
    token = tokens[pos]
    if token != "(":
        if token in FEATURES:
            return Feature(token), pos + 1
        raise ValueError(f"parse error: unknown feature {token!r}")
    op = tokens[pos + 1] if pos + 1 < len(tokens) else ""
    args: list[Expression] = []
    window: int | None = None
    pos += 2
    while pos < len(tokens) and tokens[pos] != ")":
        if tokens[pos].isdigit():
            window = int(tokens[pos])
            pos += 1
        else:
            child, pos = _parse_tokens(tokens, pos)
            args.append(child)
    if pos >= len(tokens):
        raise ValueError("parse error: unbalanced parentheses")
    pos += 1  # consume ')'
    if op in _UNARY_OPS and len(args) == 1 and window is None:
        return Unary(op, args[0]), pos
    if op in _BINARY_OPS and len(args) == 2 and window is None:
        return Binary(op, args[0], args[1]), pos
    if op in _TS_OPS and len(args) == 1 and window is not None:
        return TimeSeries(op, args[0], window), pos
    raise ValueError(f"parse error: bad form ({op} ...)")


# ------------------------------------------------------------------- random generation


def random_expression(rng: Random, max_depth: int = 4) -> Expression:
    """Grow a random expression (seeded ``rng`` makes generation deterministic).

    Args:
        rng: Seeded random source.
        max_depth: Maximum tree depth (1 = a bare feature).

    Returns:
        A valid expression tree.
    """
    if max_depth <= 1 or rng.random() < 0.25:
        return Feature(rng.choice(FEATURES))
    kind = rng.random()
    if kind < 0.35:
        return Unary(rng.choice(_UNARY_OPS), random_expression(rng, max_depth - 1))
    if kind < 0.65:
        return TimeSeries(
            rng.choice(_TS_OPS), random_expression(rng, max_depth - 1), rng.choice(WINDOWS)
        )
    return Binary(
        rng.choice(_BINARY_OPS),
        random_expression(rng, max_depth - 1),
        random_expression(rng, max_depth - 1),
    )


# ------------------------------------------------------------------------- to scores


def to_scores(
    expr: Expression,
    panel: Panel,
    *,
    signal_name: str,
    signal_version: str,
) -> list[SignalScore]:
    """Evaluate ``expr`` and emit validated :class:`SignalScore` cross-sections.

    Dates where fewer than two tickers have finite values are skipped entirely.

    Args:
        expr: The factor expression.
        panel: Aligned market data.
        signal_name: Name recorded on every score.
        signal_version: Semver recorded on every score.

    Returns:
        Scores for every (ticker, date) with a finite value.
    """
    values = expr.evaluate(panel)
    scores: list[SignalScore] = []
    for i, day in enumerate(panel.dates):
        row = [(t, values[t][i]) for t in sorted(values) if not math.isnan(values[t][i])]
        if len(row) < 2:
            continue
        scores.extend(
            make_scores(
                [t for t, _ in row],
                [v for _, v in row],
                signal_name=signal_name,
                signal_version=signal_version,
                as_of=day,
                data_inputs=["prices"],
            )
        )
    return scores
