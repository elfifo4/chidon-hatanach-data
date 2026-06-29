"""Isolated OpenAI vision client for the pilot (Phase 2).

This is the ONLY module that talks to OpenAI. It is injectable/mockable: pass a
`client` to review_pages() in tests to avoid any network. The text baseline
stays the source of truth; merge_into_baseline only accepts vision text that is
clean (no replacement char / detached niqqud) and shape-compatible.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import pilot_validate

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
REPLACEMENT_CHAR = "�"
_SPACE_THEN_MARK = re.compile(r"\s[֑-ׇ]")

_PROMPT = (
    "You are transcribing a Hebrew Bible-contest questionnaire from page images. "
    "For each numbered question return faithful text in correct right-to-left reading "
    "order, preserving niqqud exactly as printed. Mark words that are visually "
    "emphasized (bold or underlined) using ONLY inline <b>...</b> or <u>...</u> tags; "
    "do not add any other tags. Do NOT add words that are not printed. Return strict "
    'JSON: {"questions":[{"display_number":"1","prompt":"...","options":'
    '[{"key":"א","text":"..."},{"key":"ב","text":"..."},{"key":"ג","text":"..."},'
    '{"key":"ד","text":"..."}]}]}'
)


class VisionUnavailable(RuntimeError):
    """Raised when vision is requested but not configured (no key/SDK)."""


def _build_client():
    if not os.environ.get("OPENAI_API_KEY"):
        raise VisionUnavailable(
            "OPENAI_API_KEY is not set. Export it, or run without --vision for the text baseline."
        )
    try:
        from openai import OpenAI
    except ImportError as e:  # noqa: BLE001
        raise VisionUnavailable("openai SDK not installed (pip install openai).") from e
    return OpenAI()


def _image_data_url(path: Path) -> str:
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def review_pages(images: list[Path], baseline: dict, *, client=None, model: str | None = None) -> dict:
    """Send rendered page images to the model and return parsed review JSON.

    Raises VisionUnavailable if no client/key is available.
    """
    client = client or _build_client()
    model = model or DEFAULT_MODEL
    content = [{"type": "text", "text": _PROMPT}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(img)}})
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(resp.choices[0].message.content)


def _is_clean(text: str | None) -> bool:
    return bool(text) and REPLACEMENT_CHAR not in text and not _SPACE_THEN_MARK.search(text)


def merge_into_baseline(quiz: dict, review: dict) -> list[dict]:
    """Apply vision review onto the baseline in place; return per-question warnings.

    Baseline is authoritative for structure (unit ids, correct_option, sources).
    Vision text replaces baseline text only when it is clean and shape-compatible.
    """
    warnings: list[dict] = []
    vmap = {str(q.get("display_number")): q for q in (review or {}).get("questions", [])}

    for unit in pilot_validate.iter_units(quiz):
        uid = unit.get("unit_id")
        vq = vmap.get(str(unit.get("display_number")))
        if not vq:
            warnings.append({"unit_id": uid, "warning": "no vision data for this question"})
            continue

        vp = vq.get("prompt")
        if vp:
            if _is_clean(vp):
                unit["prompt"] = vp
            else:
                warnings.append({"unit_id": uid, "warning": "vision prompt rejected (unclean text)"})

        vopts = vq.get("options") or []
        bopts = unit.get("options") or []
        same_shape = (len(vopts) == len(bopts) == 4
                      and [o.get("key") for o in vopts] == [o.get("key") for o in bopts])
        if not same_shape:
            warnings.append({"unit_id": uid, "warning": "vision option shape mismatch; kept baseline"})
            continue
        for bo, vo in zip(bopts, vopts):
            vt = vo.get("text")
            if vt and _is_clean(vt):
                bo["text"] = vt
            elif vt:
                warnings.append({"unit_id": uid, "warning": f"vision option {bo.get('key')} rejected"})

    return warnings
