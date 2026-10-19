"""Secret and identity scrubbing applied before anything is stored."""
from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("api_key", re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{12,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("windows_user_path", re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.I)),
    ("home_path", re.compile(r"/(?:home|Users)/[^/\s]+")),
]


@dataclass(frozen=True)
class Redaction:
    text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str) -> Redaction:
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    counts: dict[str, int] = {}
    result = text
    for name, pattern in PATTERNS:
        result, found = pattern.subn(f"[REDACTED:{name}]", result)
        if found:
            counts[name] = counts.get(name, 0) + found
    return Redaction(text=result, counts=counts)
