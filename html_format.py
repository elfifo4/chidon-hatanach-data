"""Minimal inline-HTML helpers for emphasis preserved inside text strings.

Only three tags are allowed: <b>, <u>, <i>. No span/style objects. Used to
validate vision-inserted emphasis and to normalize text before evaluation.
"""
from __future__ import annotations

import re

ALLOWED_TAGS = ("b", "u", "i")
_TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)\s*>")


def validate_html(s: str | None) -> tuple[bool, list[str]]:
    """Return (is_valid, errors). Valid == only <b>/<u>/<i>, properly balanced."""
    errors: list[str] = []
    stack: list[str] = []
    for m in _TAG_RE.finditer(s or ""):
        tag = m.group(1).lower()
        closing = m.group(0).startswith("</")
        if tag not in ALLOWED_TAGS:
            errors.append(f"disallowed tag <{tag}>")
            continue
        if closing:
            if not stack or stack[-1] != tag:
                errors.append(f"unbalanced </{tag}>")
            else:
                stack.pop()
        else:
            stack.append(tag)
    if stack:
        errors.append("unclosed tags: " + ", ".join(stack))
    return (not errors, errors)


def strip_tags(s: str | None) -> str:
    return _TAG_RE.sub("", s or "")


def sanitize(s: str | None) -> str | None:
    """Keep emphasis only if it's valid; otherwise drop all tags (text kept)."""
    if not s:
        return s
    ok, _ = validate_html(s)
    return s if ok else strip_tags(s)


def has_html(s: str | None) -> bool:
    return bool(s) and _TAG_RE.search(s) is not None


def normalize_for_compare(s: str | None) -> str:
    """Text-only, whitespace-collapsed form for evaluation (ignores emphasis)."""
    return re.sub(r"\s+", " ", strip_tags(s)).strip()
