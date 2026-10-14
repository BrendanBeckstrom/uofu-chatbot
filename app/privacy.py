"""Redact personal identifiers before anything is written to the local logs."""

import re

PATTERNS = [
    (re.compile(r"\bu\d{7}\b", re.I), "[uNID]"),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"), "[phone]"),
]


def redact(text: str) -> str:
    for pattern, label in PATTERNS:
        text = pattern.sub(label, text)
    return text
