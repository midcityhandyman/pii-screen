"""An offline stand-in for a third party model.

It needs no key and makes no network call. It records every prompt it is
given so tests and the demo can prove what did and did not leave the screen.
"""
from __future__ import annotations

import re
from typing import List

from .screen import TOKEN_RE


class MockModel:
    def __init__(self) -> None:
        self.seen: List[str] = []

    def complete(self, prompt: str) -> str:
        self.seen.append(prompt)
        tokens = TOKEN_RE.findall(prompt)
        who = next((t for t in tokens if t.startswith("[[NAME")), "there")
        contact = next((t for t in tokens if t.startswith(("[[PHONE", "[[EMAIL"))), None)
        where = next((t for t in tokens if t.startswith("[[ADDRESS")), None)
        words = len(re.findall(r"\S+", prompt))
        reply = f"Draft reply: Hello {who}, thanks for your message ({words} words)."
        if where:
            reply += f" We can send someone to {where}."
        if contact:
            reply += f" We will confirm the time using {contact}."
        return reply
