"""Score the screen against a labelled corpus.

Two views are reported. Exact: a predicted span counts only if kind, start
and end all equal a labelled span. Relaxed: a predicted span counts if it
overlaps a labelled span of the same kind at all. Exact is the honest number
for redaction quality, relaxed shows how often the screen at least noticed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from .detectors import KINDS
from .screen import Screener

Span = Tuple[int, int, str]


@dataclass
class Counts:
    gold: int = 0
    pred: int = 0
    tp: int = 0  # exact matches
    pred_hit: int = 0  # predictions overlapping a gold span of the same kind
    gold_hit: int = 0  # gold spans overlapped by a prediction of the same kind

    @staticmethod
    def _ratio(a: int, b: int) -> float:
        return a / b if b else 1.0

    @property
    def fp(self) -> int:
        return self.pred - self.tp

    @property
    def fn(self) -> int:
        return self.gold - self.tp

    @property
    def precision(self) -> float:
        return self._ratio(self.tp, self.pred)

    @property
    def recall(self) -> float:
        return self._ratio(self.tp, self.gold)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def relaxed_precision(self) -> float:
        return self._ratio(self.pred_hit, self.pred)

    @property
    def relaxed_recall(self) -> float:
        return self._ratio(self.gold_hit, self.gold)

    def add(self, other: "Counts") -> None:
        for name in ("gold", "pred", "tp", "pred_hit", "gold_hit"):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class Report:
    examples: int = 0
    by_kind: Dict[str, Counts] = field(default_factory=lambda: {k: Counts() for k in KINDS})
    errors: List[dict] = field(default_factory=list)

    @property
    def overall(self) -> Counts:
        total = Counts()
        for c in self.by_kind.values():
            total.add(c)
        return total


def load_corpus(path) -> List[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _overlaps(a: Span, b: Span) -> bool:
    return a[2] == b[2] and a[0] < b[1] and b[0] < a[1]


def score(screener: Screener, examples: List[dict]) -> Report:
    report = Report(examples=len(examples))
    for ex in examples:
        text = ex["text"]
        gold = {(s["start"], s["end"], s["type"]) for s in ex["spans"]}
        pred = {(f.start, f.end, f.kind) for f in screener.detect(text)}
        for kind in KINDS:
            c = report.by_kind[kind]
            g = {s for s in gold if s[2] == kind}
            p = {s for s in pred if s[2] == kind}
            c.gold += len(g)
            c.pred += len(p)
            c.tp += len(g & p)
            c.pred_hit += sum(1 for s in p if any(_overlaps(s, t) for t in g))
            c.gold_hit += sum(1 for t in g if any(_overlaps(s, t) for s in p))
        for s in sorted(pred - gold):
            report.errors.append({"id": ex["id"], "error": "false_positive", "kind": s[2], "text": text[s[0]:s[1]]})
        for s in sorted(gold - pred):
            report.errors.append({"id": ex["id"], "error": "missed", "kind": s[2], "text": text[s[0]:s[1]]})
    return report


def format_report(report: Report, show_errors: bool = False) -> str:
    overall = report.overall
    lines = [
        f"Corpus: {report.examples} examples, {overall.gold} labelled spans",
        "",
        "Exact span match (kind, start and end all equal)",
        f"{'kind':<9}{'gold':>6}{'pred':>6}{'tp':>6}{'fp':>6}{'fn':>6}{'precision':>11}{'recall':>8}{'f1':>7}",
    ]
    rows = list(report.by_kind.items()) + [("ALL", overall)]
    for kind, c in rows:
        lines.append(
            f"{kind:<9}{c.gold:>6}{c.pred:>6}{c.tp:>6}{c.fp:>6}{c.fn:>6}"
            f"{c.precision:>11.3f}{c.recall:>8.3f}{c.f1:>7.3f}"
        )
    lines += ["", "Relaxed match (same kind, any overlap)", f"{'kind':<9}{'precision':>11}{'recall':>8}"]
    for kind, c in rows:
        lines.append(f"{kind:<9}{c.relaxed_precision:>11.3f}{c.relaxed_recall:>8.3f}")
    if show_errors:
        lines += ["", f"Errors under exact match ({len(report.errors)})"]
        for e in report.errors:
            lines.append(f"  {e['id']:<10}{e['error']:<16}{e['kind']:<9}{e['text']!r}")
    return "\n".join(lines)
