"""Detectors for the four kinds of personal detail the screen looks for.

Each detector returns Finding objects with character offsets into the input.
Phones, emails and street addresses are found with patterns. Names are found
only from a roster the caller supplies, never by guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

EMAIL = "EMAIL"
PHONE = "PHONE"
ADDRESS = "ADDRESS"
NAME = "NAME"
KINDS = (EMAIL, PHONE, ADDRESS, NAME)


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    kind: str
    text: str


EMAIL_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)

_EXT = r"(?:\s?(?:ext\.?|x)\s?\d{1,5})?"
PHONE_RE = re.compile(
    rf"""
    (?:
        # separated: +1 555 555 0142, (555) 555-0142, 555.555.0142
        (?<![\w+])(?<!\d[-.])
        (?:\+?1[\s.-]?)?
        (?:\(\d{{3}}\)[\s.-]?|\d{{3}}[\s.-])
        \d{{3}}[\s.-]\d{{4}}
        (?![-.]?\d){_EXT}
      |
        # run of ten digits, optional country code: 5555550142, +15555550142
        (?<![\w+-])(?:\+?1)?\d{{10}}(?![\w-])
      |
        # local seven digit form: 555-0142
        (?<![\w.-])\d{{3}}-\d{{4}}(?![-.]?\d){_EXT}
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_SUFFIX = (
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|"
    r"Way|Place|Pl|Terrace|Ter|Circle|Cir|Parkway|Pkwy|Highway|Hwy)"
)
ADDRESS_RE = re.compile(
    rf"""
    (?:
        \b\d{{1,6}}[A-Za-z]?\s+
        (?:(?:N|S|E|W|North|South|East|West)\.?\s+)?
        (?:[A-Z][A-Za-z']+\s+|\d{{1,3}}(?:st|nd|rd|th)\s+){{1,3}}
        {_SUFFIX}\b
        (?:\.?,?\s+(?:Apt|Apartment|Unit|Suite|Ste|\#)\.?\s*[A-Za-z0-9-]+)?
        (?:\.?,\s+[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?,\s+[A-Z]{{2}}(?:\s+\d{{5}}(?:-\d{{4}})?)?)?
      |
        \bP\.?\s?O\.?\s+Box\s+\d+\b
    )
    """,
    re.VERBOSE,
)


def _matches(pattern: "re.Pattern[str]", kind: str, text: str) -> List[Finding]:
    return [Finding(m.start(), m.end(), kind, m.group()) for m in pattern.finditer(text)]


def find_emails(text: str) -> List[Finding]:
    return _matches(EMAIL_RE, EMAIL, text)


def find_phones(text: str) -> List[Finding]:
    return _matches(PHONE_RE, PHONE, text)


def find_addresses(text: str) -> List[Finding]:
    return _matches(ADDRESS_RE, ADDRESS, text)


class Roster:
    """A list of known names to look for.

    Full names match in any letter case, in "First Last" or "Last, First"
    order. With match_parts on (the default) each part of a name also matches
    alone, but only with the capitalisation given in the roster, so a roster
    entry "Robin Testcase" finds "Robin" and leaves "robin" (the bird) alone.
    Parts shorter than three letters never match alone.
    """

    def __init__(self, names: Iterable[str], match_parts: bool = True):
        self.names = [" ".join(n.split()) for n in names if n and n.strip()]
        self.match_parts = match_parts
        full: List[str] = []
        parts = set()
        for name in self.names:
            tokens = name.split(" ")
            full.append(r"\s+".join(re.escape(t) for t in tokens))
            if len(tokens) > 1:
                rest = r"\s+".join(re.escape(t) for t in tokens[:-1])
                full.append(re.escape(tokens[-1]) + r",\s*" + rest)
            parts.update(t for t in tokens if len(t) >= 3)
        full.sort(key=len, reverse=True)
        self._full = (
            re.compile(r"\b(?:" + "|".join(full) + r")\b", re.IGNORECASE) if full else None
        )
        ordered = sorted(parts, key=len, reverse=True)
        self._parts = (
            re.compile(r"\b(?:" + "|".join(re.escape(p) for p in ordered) + r")\b")
            if ordered and match_parts
            else None
        )

    @classmethod
    def from_file(cls, path, match_parts: bool = True) -> "Roster":
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        names = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
        return cls(names, match_parts=match_parts)

    def find(self, text: str) -> List[Finding]:
        found: List[Finding] = []
        if self._full is not None:
            found.extend(_matches(self._full, NAME, text))
        if self._parts is not None:
            found.extend(_matches(self._parts, NAME, text))
        return found


def resolve_overlaps(findings: Sequence[Finding]) -> List[Finding]:
    """Keep the earliest finding, preferring the longer one on a tie, and drop
    anything that overlaps a finding already kept."""
    kept: List[Finding] = []
    last_end = -1
    for f in sorted(findings, key=lambda f: (f.start, -(f.end - f.start), KINDS.index(f.kind))):
        if f.start >= last_end:
            kept.append(f)
            last_end = f.end
    return kept


def detect(text: str, roster: "Roster | None" = None, kinds: Sequence[str] = KINDS) -> List[Finding]:
    found: List[Finding] = []
    if EMAIL in kinds:
        found.extend(find_emails(text))
    if PHONE in kinds:
        found.extend(find_phones(text))
    if ADDRESS in kinds:
        found.extend(find_addresses(text))
    if NAME in kinds and roster is not None:
        found.extend(roster.find(text))
    return resolve_overlaps(found)
