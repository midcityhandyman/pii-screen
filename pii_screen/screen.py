"""The screen itself: block, redact or tokenise text before it is sent on."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .detectors import KINDS, Finding, Roster, detect

BLOCK = "block"
REDACT = "redact"
TOKENISE = "tokenise"
MODES = (BLOCK, REDACT, TOKENISE)

TOKEN_RE = re.compile(r"\[\[(?:" + "|".join(KINDS) + r")_\d+\]\]")


class BlockedError(Exception):
    """Raised by guarded_call when block mode finds something."""

    def __init__(self, findings: Sequence[Finding]):
        self.findings = list(findings)
        kinds = sorted({f.kind for f in self.findings})
        super().__init__(
            f"blocked: {len(self.findings)} finding(s) of kind {', '.join(kinds)}"
        )


class Vault:
    """Maps placeholders such as [[NAME_1]] back to the original text.

    The same original always gets the same placeholder, so a model can still
    tell that two mentions are the same person. The vault holds the real
    values: keep it on your side and never send it with the screened text.
    """

    def __init__(self) -> None:
        self.tokens: Dict[str, str] = {}
        self._by_value: Dict[Tuple[str, str], str] = {}
        self._counters: Dict[str, int] = {}

    def issue(self, kind: str, value: str, avoid: str = "") -> str:
        key = (kind, value)
        if key in self._by_value:
            return self._by_value[key]
        n = self._counters.get(kind, 0) + 1
        # Never issue a placeholder that already appears literally in the
        # source text, or restore would rewrite the wrong thing.
        while f"[[{kind}_{n}]]" in avoid:
            n += 1
        self._counters[kind] = n
        token = f"[[{kind}_{n}]]"
        self.tokens[token] = value
        self._by_value[key] = token
        return token

    def restore(self, text: str) -> str:
        return TOKEN_RE.sub(lambda m: self.tokens.get(m.group(), m.group()), text)

    def to_dict(self) -> Dict[str, str]:
        return dict(self.tokens)

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Vault":
        vault = cls()
        for token, value in data.items():
            kind, _, num = token.strip("[]").rpartition("_")
            vault.tokens[token] = value
            vault._by_value[(kind, value)] = token
            vault._counters[kind] = max(vault._counters.get(kind, 0), int(num))
        return vault

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Vault":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass
class ScreenResult:
    mode: str
    text: Optional[str]  # None when blocked
    findings: List[Finding] = field(default_factory=list)
    blocked: bool = False
    vault: Optional[Vault] = None

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out


class Screener:
    def __init__(self, roster: Optional[Roster] = None, kinds: Sequence[str] = KINDS):
        unknown = [k for k in kinds if k not in KINDS]
        if unknown:
            raise ValueError(f"unknown kind(s): {unknown}")
        self.roster = roster
        self.kinds = tuple(kinds)

    def detect(self, text: str) -> List[Finding]:
        return detect(text, self.roster, self.kinds)

    def screen(self, text: str, mode: str = TOKENISE, vault: Optional[Vault] = None) -> ScreenResult:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        findings = self.detect(text)
        if mode == BLOCK:
            if findings:
                return ScreenResult(mode, None, findings, blocked=True)
            return ScreenResult(mode, text, findings)
        if mode == TOKENISE and vault is None:
            vault = Vault()
        pieces: List[str] = []
        cursor = 0
        for f in findings:
            pieces.append(text[cursor:f.start])
            if mode == REDACT:
                pieces.append(f"[{f.kind}]")
            else:
                pieces.append(vault.issue(f.kind, f.text, avoid=text))
            cursor = f.end
        pieces.append(text[cursor:])
        return ScreenResult(mode, "".join(pieces), findings, vault=vault if mode == TOKENISE else None)


def guarded_call(
    screener: Screener,
    text: str,
    send: Callable[[str], str],
    mode: str = TOKENISE,
    vault: Optional[Vault] = None,
) -> str:
    """Screen text, pass the screened version to send, and return the reply.

    send is whatever talks to the third party model. It only ever sees the
    screened text. In tokenise mode the reply has its placeholders swapped
    back before it is returned. In block mode a finding raises BlockedError
    and send is never called.
    """
    result = screener.screen(text, mode, vault)
    if result.blocked:
        raise BlockedError(result.findings)
    reply = send(result.text)
    if mode == TOKENISE and result.vault is not None:
        return result.vault.restore(reply)
    return reply
