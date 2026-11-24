"""Command line entry point: screen, restore, eval.

Exit codes: 0 ok, 2 blocked (block mode found something), 1 usage or file error.
Findings are reported to stderr by kind and position only, never by value,
so the log of a blocked message does not itself leak what was blocked.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .detectors import Roster
from .evaluate import format_report, load_corpus, score
from .screen import MODES, TOKENISE, Screener, Vault

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = REPO_ROOT / "corpus" / "corpus.jsonl"
DEFAULT_ROSTER = REPO_ROOT / "corpus" / "roster.txt"


def _read(path: Optional[str]) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _screener(args) -> Screener:
    roster_path = args.roster or os.environ.get("PII_SCREEN_ROSTER")
    roster = None
    if roster_path:
        roster = Roster.from_file(roster_path, match_parts=not args.full_names_only)
    return Screener(roster)


def cmd_screen(args) -> int:
    mode = args.mode or os.environ.get("PII_SCREEN_MODE") or TOKENISE
    if mode not in MODES:
        print(f"error: mode must be one of {', '.join(MODES)}", file=sys.stderr)
        return 1
    text = _read(args.file)
    vault = Vault.load(args.vault) if args.vault and Path(args.vault).exists() else None
    result = _screener(args).screen(text, mode, vault)
    for f in result.findings:
        print(f"finding {f.kind} at {f.start}:{f.end}", file=sys.stderr)
    if result.blocked:
        print(f"BLOCKED: {len(result.findings)} finding(s), nothing written", file=sys.stderr)
        return 2
    if args.json:
        payload = {"mode": mode, "text": result.text, "counts": result.counts()}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(result.text)
    if mode == TOKENISE:
        if args.vault:
            result.vault.save(args.vault)
        elif result.findings:
            print("warning: no --vault given, placeholders cannot be restored later", file=sys.stderr)
    return 0


def cmd_restore(args) -> int:
    sys.stdout.write(Vault.load(args.vault).restore(_read(args.file)))
    return 0


def cmd_eval(args) -> int:
    roster = Roster.from_file(args.roster or DEFAULT_ROSTER, match_parts=not args.full_names_only)
    report = score(Screener(roster), load_corpus(args.corpus or DEFAULT_CORPUS))
    print(format_report(report, show_errors=args.errors))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pii-screen", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def roster_args(p):
        p.add_argument("--roster", help="file with one known name per line")
        p.add_argument("--full-names-only", action="store_true",
                       help="do not match a first or last name on its own")

    p = sub.add_parser("screen", help="screen a file or stdin")
    p.add_argument("file", nargs="?", help="input file, or - for stdin (default)")
    p.add_argument("--mode", choices=MODES, help="default: $PII_SCREEN_MODE or tokenise")
    p.add_argument("--vault", help="JSON file to read and write the placeholder map (tokenise)")
    p.add_argument("--json", action="store_true", help="print JSON with text and counts")
    roster_args(p)
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("restore", help="swap placeholders back using a vault file")
    p.add_argument("file", nargs="?", help="input file, or - for stdin (default)")
    p.add_argument("--vault", required=True)
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("eval", help="report precision and recall on the labelled corpus")
    p.add_argument("--corpus", help="JSONL corpus (default: the shipped one)")
    p.add_argument("--errors", action="store_true", help="list every miss and false positive")
    roster_args(p)
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        # ValueError covers a vault or corpus file that is not valid JSON.
        print(f"error: {exc}", file=sys.stderr)
        return 1
