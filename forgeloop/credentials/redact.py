from __future__ import annotations
import re

_KEY_RE = re.compile(r"sk-[A-Za-z0-9]+")


def redact(text: str) -> str:
    return _KEY_RE.sub("sk-****", text)
