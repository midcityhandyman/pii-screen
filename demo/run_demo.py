"""Offline demo. No key, no network.

Run from the repo root:  python demo/run_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pii_screen import BlockedError, Roster, Screener, guarded_call  # noqa: E402
from pii_screen.evaluate import format_report, load_corpus, score  # noqa: E402
from pii_screen.mock_model import MockModel  # noqa: E402

ROSTER_FILE = ROOT / "corpus" / "roster.txt"
MESSAGE = (
    "Alex Sample called from (555) 555-0142 about the leak at 123 Example Street. "
    "Send the quote to alex.sample@example.com. Alex is home after 4."
)


def section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> None:
    screener = Screener(Roster.from_file(ROSTER_FILE))

    section("1. Original message (synthetic)")
    print(MESSAGE)

    section("2. What the screen found")
    for f in screener.detect(MESSAGE):
        print(f"  {f.kind:<8} {f.start:>3}:{f.end:<3} {f.text}")

    section("3. Mode: block")
    result = screener.screen(MESSAGE, "block")
    print(f"blocked={result.blocked}  text={result.text}  counts={result.counts()}")

    section("4. Mode: redact")
    print(screener.screen(MESSAGE, "redact").text)

    section("5. Mode: tokenise")
    result = screener.screen(MESSAGE, "tokenise")
    print(result.text)
    print()
    print("Vault (stays on your side):")
    for token, value in result.vault.tokens.items():
        print(f"  {token:<14} -> {value}")

    section("6. Round trip through a mock third party model")
    model = MockModel()
    reply = guarded_call(screener, MESSAGE, model.complete)
    print("The model received:")
    print("  " + model.seen[0])
    print("The model replied:")
    print("  " + model.complete(model.seen[0]))
    print("The caller gets back, placeholders restored:")
    print("  " + reply)

    section("7. Block mode in front of the same model")
    blocked_model = MockModel()
    try:
        guarded_call(screener, MESSAGE, blocked_model.complete, mode="block")
    except BlockedError as exc:
        print(f"BlockedError: {exc}")
    print(f"calls that reached the model: {len(blocked_model.seen)}")

    section("8. Precision and recall on the labelled synthetic corpus")
    examples = load_corpus(ROOT / "corpus" / "corpus.jsonl")
    print(format_report(score(screener, examples)))

    section("9. Same corpus, full names only (no single first or last names)")
    strict = Screener(Roster.from_file(ROSTER_FILE, match_parts=False))
    print(format_report(score(strict, examples)))

    section("10. Every miss and false positive, default settings")
    for e in score(screener, examples).errors:
        print(f"  {e['id']:<10}{e['error']:<16}{e['kind']:<9}{e['text']!r}")


if __name__ == "__main__":
    main()
