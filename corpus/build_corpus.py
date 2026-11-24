"""Builds the labelled synthetic corpus: corpus.jsonl and roster.txt.

Everything here is invented. Names are placeholder words, phone numbers sit
in the reserved 555-01xx range, emails use example.com style domains and the
addresses do not exist.

Labels are written inline as {KIND|text} and turned into character offsets.
The corpus has two parts:
  1. generated messages built from templates with a fixed random seed
  2. hand written hard cases: things the screen is expected to miss, things
     it is expected to flag wrongly, and clean messages with nothing in them

Labelling rule for names: only names on the roster are labelled, because the
screen only claims to find roster names. Other names are out of scope.

Run:  python corpus/build_corpus.py
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import List, Tuple

HERE = Path(__file__).resolve().parent
SEED = 7
GENERATED = 70

ROSTER = [
    "Alex Sample",
    "Jordan Example",
    "Casey Placeholder",
    "Robin Testcase",
    "Morgan Demo",
    "Riley Mockford",
    "Taylor Fakename",
    "Sam Dummy",
]

STREETS = [
    "123 Example Street",
    "42 Sample Ave, Apt 3B",
    "9 Placeholder Rd",
    "700 N Mockingbird Lane, Faketown, ZZ 00000",
    "1600 Test Blvd, Suite 200",
    "88 Lorem Ipsum Drive",
    "15 W 3rd St",
    "PO Box 12",
    "2B Fixture Court, Unit 4",
    "310 Dummy Data Way, Nowhere Falls, ZZ 00000-0001",
]

TEMPLATES = [
    "Hi, this is {N} calling about the leak under the sink, reach me at {P}.",
    "Please send the estimate to {E} and copy {E}.",
    "The job site is {A}. Gate code is on the work order.",
    "{N} asked for a callback on {P} before noon.",
    "New lead: {N}, {A}, {P}, {E}.",
    "Can someone confirm the appointment with {N}? Their email is {E}.",
    "Crew is running late to {A}, please text the customer at {P}.",
    "Invoice 2217 was paid by {N} on the 3rd.",
    "Voicemail left for {N} at {P}. No answer at {P} either.",
    "Ship the replacement part to {A} and email tracking to {E}.",
    "{N} and {N} will both be on site Thursday.",
    "Summarise this thread: customer at {A} says the door still sticks.",
    "Reminder: {N} prefers email ({E}) over phone ({P}).",
    "Walkthrough moved to 2 pm at {A}; call {P} if the lockbox is missing.",
]


def _name(rng: random.Random) -> str:
    full = rng.choice(ROSTER)
    first, last = full.split(" ")
    return rng.choice([full, full, full, first, last, f"{last}, {first}", full.lower(), full.upper()])


def _phone(rng: random.Random) -> str:
    n = f"01{rng.randint(0, 99):02d}"
    return rng.choice([
        f"(555) 555-{n}", f"555-555-{n}", f"555.555.{n}", f"+1 555 555 {n}",
        f"555 555 {n}", f"555-{n}", f"555555{n}", f"1-555-555-{n}", f"555-555-{n} ext. {rng.randint(2, 99)}",
    ])


def _email(rng: random.Random) -> str:
    first, last = rng.choice(ROSTER).lower().split(" ")
    return rng.choice([
        f"{first}.{last}@example.com", f"{first[0]}{last}@example.org",
        f"{first}_{last}{rng.randint(1, 99)}@mail.example.net",
        "billing@example.com", "front-desk+jobs@example.org",
    ])


FILLERS = {"N": ("NAME", _name), "P": ("PHONE", _phone), "E": ("EMAIL", _email),
           "A": ("ADDRESS", lambda rng: rng.choice(STREETS))}


def generated(rng: random.Random) -> List[str]:
    out = []
    for i in range(GENERATED):
        template = TEMPLATES[i % len(TEMPLATES)]

        def fill(m):
            kind, make = FILLERS[m.group(1)]
            return "{%s|%s}" % (kind, make(rng))

        out.append(re.sub(r"\{([NPEA])\}", fill, template))
    return out


# Hand written cases. The comment on each group says what we expect to happen.
HARD = [
    # Likely missed: the detail is real but written in a form the patterns do not cover.
    "You can email me at {EMAIL|alex dot sample at example dot com} any time.",
    "My cell is {PHONE|555 555 01 42}, mornings are best.",
    "Ring {PHONE|555 0142} after six.",
    "Number is {PHONE|five five five, zero one four two}.",
    "We are at {ADDRESS|12 example street}, the blue door.",
    "It is the house on {ADDRESS|Mockingbird Road, number 9}.",
    "Drop the keys at {ADDRESS|Unit 4, Fixture Court}.",
    "ask {NAME|alex} about the tile order",
    "{NAME|JORDAN} signed for the delivery.",
    # Likely partial: found, but the span will not match the label exactly.
    "{NAME|A. Sample} signed off on the change order.",
    "Spoke with {NAME|Jordon Example} (spelling from the voicemail).",
    "Send it to {NAME|Casey P.} at the office.",
    "Tel: {PHONE|555-555-0117 extension 22}.",
    # Likely false positives: nothing personal here, but it looks like something.
    "Sample photos are attached for the cabinet finish.",
    "Demo went well, the old vanity is out.",
    "Robin egg blue was the paint colour chosen for the trim.",
    "Part number 5550001234 is back ordered until next week.",
    "Order 400-2210 shipped this morning.",
    "Booked 2 Standard Court sessions for the team outing.",
    "Dummy load test on the breaker passed.",
    # Clean: nothing to find, and the screen should stay quiet.
    "Invoice 2026-11-03 total is $1,250.00, due in 30 days.",
    "The job took 3 hours 45 minutes including cleanup.",
    "Reference #A-4471-22 for the permit application.",
    "Version 10.4.2 of the scheduling app was released.",
    "See example.com/pricing for the current rate sheet.",
    "Meeting at 10:30 on 11/24/2026 in the main office.",
    "Tracking number 123456789012 shows out for delivery.",
    "A robin nested in the gutter, so we worked around it.",
    "Need 14 sheets of drywall, 2 boxes of screws and a sample of the grout.",
    "The demo day for the kitchen is set for next Tuesday.",
    "Mix ratio is 4 to 1, cure time 24 hours at 70 degrees.",
    "Model X-200 furnace, serial 00417-A, filter size 16x25x1.",
    # Mixed and awkward but in scope: the screen should get these.
    "From: {NAME|Casey Placeholder} <{EMAIL|casey.placeholder@example.com}>",
    "{NAME|Jordan}'s number changed to {PHONE|(555) 555-0188}, old one was {PHONE|555-555-0101}.",
    "Call {PHONE|+15555550123} or write to {EMAIL|Riley.Mockford@Example.COM}.",
    "{NAME|Morgan Demo} lives at {ADDRESS|77 Demo Terrace}; demo of the bathroom starts Monday.",
    "{NAME|Taylor Fakename}\n{ADDRESS|5 Fakename Place, Apt 2}\n{PHONE|555.555.0155}",
    "Same person twice: {EMAIL|sam.dummy@example.com} and again {EMAIL|sam.dummy@example.com}.",
    "Mail goes to {ADDRESS|P.O. Box 440}, deliveries to {ADDRESS|19 Sample Parkway}.",
    "Text {NAME|Riley} ({PHONE|555-0163}) when the inspector arrives at {ADDRESS|4410 E Placeholder Hwy}.",
]

LABEL_RE = re.compile(r"\{(EMAIL|PHONE|ADDRESS|NAME)\|([^}]*)\}", re.DOTALL)


def parse(annotated: str) -> Tuple[str, List[dict]]:
    """Turn '{KIND|text}' markup into plain text plus character spans."""
    text, spans, cursor = "", [], 0
    for m in LABEL_RE.finditer(annotated):
        text += annotated[cursor:m.start()]
        start = len(text)
        text += m.group(2)
        spans.append({"start": start, "end": len(text), "type": m.group(1), "text": m.group(2)})
        cursor = m.end()
    text += annotated[cursor:]
    return text, spans


def build() -> List[dict]:
    rng = random.Random(SEED)
    rows = []
    for prefix, items in (("gen", generated(rng)), ("hard", HARD)):
        for i, annotated in enumerate(items, 1):
            text, spans = parse(annotated)
            rows.append({"id": f"{prefix}-{i:03d}", "text": text, "spans": spans})
    return rows


def render(rows: List[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=True) + "\n" for r in rows)


def main() -> None:
    rows = build()
    (HERE / "corpus.jsonl").write_text(render(rows), encoding="utf-8", newline="\n")
    header = "# Synthetic roster for the test corpus. Every name is invented.\n"
    (HERE / "roster.txt").write_text(header + "\n".join(ROSTER) + "\n", encoding="utf-8", newline="\n")
    spans = sum(len(r["spans"]) for r in rows)
    print(f"wrote {len(rows)} examples with {spans} labelled spans")


if __name__ == "__main__":
    main()
