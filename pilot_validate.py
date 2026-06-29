"""Pure, network-free validators and stats for the single-PDF pilot output.

These operate on a questionnaire dict in the existing repo schema (the object
written by extract.build_questionnaire). Kept dependency-light so they are easy
to unit-test without touching the network or the full pipeline.
"""
from __future__ import annotations

import re

OPTION_KEYS = ("א", "ב", "ג", "ד")
REPLACEMENT_CHAR = "�"
_SPACE_THEN_MARK = re.compile(r"\s[֑-ׇ]")  # detached niqqud == suspected RTL/corruption
# A stray standalone integer right after Hebrew text == leaked page furniture
# (e.g. "אביגיל 5"). Numeric options are "3"/"12" alone, so they don't match.
_TRAILING_FURNITURE = re.compile(r"[א-ת]\s+\d{1,3}\s*$")


def iter_units(quiz: dict):
    for section in quiz.get("sections", []) or []:
        for unit in section.get("question_units", []) or []:
            yield unit


def unit_texts(unit: dict):
    """All human-facing Hebrew strings on a unit."""
    yield unit.get("prompt")
    yield unit.get("narrative_context")
    for o in unit.get("options") or []:
        yield o.get("text")
    for a in unit.get("acceptable_answers") or []:
        yield a.get("answer_text")


def has_four_answers(unit: dict) -> bool:
    return len(unit.get("options") or []) == 4


def has_correct_answer(unit: dict) -> bool:
    return bool(unit.get("correct_option"))


def has_source(unit: dict) -> bool:
    return bool(unit.get("primary_sources"))


def is_suspicious(unit: dict) -> bool:
    """True if any text shows a replacement char or detached niqqud."""
    for t in unit_texts(unit):
        if t and (REPLACEMENT_CHAR in t or _SPACE_THEN_MARK.search(t)):
            return True
    return False


def validate_quiz(quiz: dict, expected_count: int | None = 35) -> list[str]:
    """Return a list of hard structural errors (empty == valid)."""
    errors: list[str] = []
    units = list(iter_units(quiz))

    if expected_count is not None and len(units) != expected_count:
        errors.append(f"expected {expected_count} questions, found {len(units)}")

    seen_ids: set[str] = set()
    for unit in units:
        uid = unit.get("unit_id") or "?"
        if uid in seen_ids:
            errors.append(f"{uid}: duplicate unit_id")
        seen_ids.add(uid)

        if not (unit.get("prompt") or "").strip():
            errors.append(f"{uid}: empty prompt")

        opts = unit.get("options") or []
        if len(opts) != 4:
            errors.append(f"{uid}: {len(opts)} options (expected 4)")
        for o in opts:
            if not (o.get("text") or "").strip():
                errors.append(f"{uid}: empty option {o.get('key')!r}")

        co = unit.get("correct_option")
        if not co:
            errors.append(f"{uid}: missing correct_option")
        elif co not in OPTION_KEYS:
            errors.append(f"{uid}: correct_option {co!r} not in {OPTION_KEYS}")

        for t in unit_texts(unit):
            if t and REPLACEMENT_CHAR in t:
                errors.append(f"{uid}: replacement char in text")
                break

    return errors


def furniture_contamination(quiz: dict) -> list[dict]:
    """Prompt/option fields ending with a stray integer after Hebrew (likely a
    leaked page number). Empty list == clean."""
    hits: list[dict] = []
    for unit in iter_units(quiz):
        fields = [("prompt", unit.get("prompt"))]
        fields += [(f"option:{o.get('key')}", o.get("text")) for o in unit.get("options") or []]
        for label, text in fields:
            if text and _TRAILING_FURNITURE.search(text.strip()):
                hits.append({"unit_id": unit.get("unit_id"), "field": label, "text": text})
    return hits


def stats(quiz: dict) -> dict:
    """Aggregate counts used by the pilot report."""
    units = list(iter_units(quiz))
    contamination = furniture_contamination(quiz)
    return {
        "questions_detected": len(units),
        "with_four_answers": sum(1 for u in units if has_four_answers(u)),
        "with_correct_answer": sum(1 for u in units if has_correct_answer(u)),
        "with_source": sum(1 for u in units if has_source(u)),
        "suspected_rtl_or_corruption": sum(1 for u in units if is_suspicious(u)),
        "suspicious_unit_ids": [u.get("unit_id") for u in units if is_suspicious(u)],
        "page_furniture_contamination": len(contamination),
        "page_furniture_fields": contamination,
    }
