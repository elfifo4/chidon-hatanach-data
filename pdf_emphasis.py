"""Deterministic visual-emphasis detection from the PDF text layer.

Bold is encoded in the font name (e.g. Heebo-ExtraBold, Arial-BoldMT); an
underline is a thin horizontal rect/line drawn under a word. We detect both per
word and wrap the matching word in the built quiz with inline <b>/<u> tags
(nested as <b><u>..</u></b> when both apply). This is reliable on every run,
unlike asking a vision model to report formatting.
"""
from __future__ import annotations

import re

import extract  # reuse _delogicalize (cluster de-reversal) + strip_niqqud

_PUNCT = "\"'.,;:?!()[]{}״׳…"
_WORD_GAP = 2.5          # x-gap (pt) that separates two words on a line
_UNDERLINE_MAX_H = 3.0   # a rect/line this thin is an underline rule


def _is_bold(fontname: str | None) -> bool:
    return "bold" in (fontname or "").lower()


def _thin_horizontals(page) -> list[dict]:
    """Thin, wide rects/lines that can serve as underlines."""
    out = []
    for r in list(page.rects) + list(page.lines):
        top, bottom = r.get("top"), r.get("bottom")
        height = (bottom - top) if (top is not None and bottom is not None) else r.get("height", 99)
        width = r.get("width") or abs((r.get("x1") or 0) - (r.get("x0") or 0))
        if height is not None and height <= _UNDERLINE_MAX_H and width and width >= 3:
            out.append({"x0": r["x0"], "x1": r["x1"], "top": top if top is not None else r.get("y0")})
    return out


def _split_words(line_chars: list[dict]) -> list[list[dict]]:
    words: list[list[dict]] = []
    cur: list[dict] = []
    for c in line_chars:
        if c["text"].isspace():
            if cur:
                words.append(cur)
                cur = []
            continue
        if cur and (c["x0"] - cur[-1]["x1"]) > _WORD_GAP:
            words.append(cur)
            cur = []
        cur.append(c)
    if cur:
        words.append(cur)
    return words


def _has_underline(unders: list[dict], x0, x1, top, bottom) -> bool:
    for u in unders:
        if u["x0"] <= x1 + 1 and u["x1"] >= x0 - 1 and (top - 3) <= u["top"] <= (bottom + 5):
            return True
    return False


def detect_emphasis(pdf_path) -> list[dict]:
    """Return [{line: logical text, spans: [{text, bold, underline}]}] for every
    line that contains at least one bold/underlined word."""
    import pdfplumber

    results: list[dict] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            unders = _thin_horizontals(page)
            chars = sorted(page.chars, key=lambda c: (round(c["top"]), c["x0"]))
            lines: list[list[dict]] = []
            for c in chars:
                if lines and abs(c["top"] - lines[-1][0]["top"]) <= 3:
                    lines[-1].append(c)
                else:
                    lines.append([c])
            for ln in lines:
                ln = sorted(ln, key=lambda c: c["x0"])
                line_logical = extract._delogicalize("".join(c["text"] for c in ln))
                spans = []
                for w in _split_words(ln):
                    wt = extract._delogicalize("".join(c["text"] for c in w)).strip()
                    if not wt:
                        continue
                    bold = sum(1 for c in w if _is_bold(c["fontname"])) >= max(1, len(w) // 2)
                    x0 = min(c["x0"] for c in w)
                    x1 = max(c["x1"] for c in w)
                    top = min(c["top"] for c in w)
                    bottom = max(c["bottom"] for c in w)
                    underline = _has_underline(unders, x0, x1, top, bottom)
                    if bold or underline:
                        spans.append({"text": wt, "bold": bold, "underline": underline})
                if spans:
                    results.append({"line": line_logical, "spans": spans})
    return results


# --------------------------------------------------------------------------- #
# Apply detected emphasis onto the built quiz
# --------------------------------------------------------------------------- #
def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", extract.strip_niqqud(s or "")).strip()


def _token_overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _wrap_token(text: str, span: dict) -> tuple[str, int]:
    target = extract.strip_niqqud(span["text"]).strip(_PUNCT)
    if not target:
        return text, 0
    toks = text.split(" ")
    for i, t in enumerate(toks):
        if "<" in t:  # already tagged
            continue
        if extract.strip_niqqud(t).strip(_PUNCT) == target:
            inner = t
            if span["underline"]:
                inner = f"<u>{inner}</u>"
            if span["bold"]:
                inner = f"<b>{inner}</b>"
            toks[i] = inner
            return " ".join(toks), 1
    return text, 0


def _apply_to_field(text: str, detected: list[dict]) -> tuple[str, int]:
    wrapped = 0
    nt = _norm(text)
    for d in detected:
        nline = _norm(d["line"])
        # tie this emphasis line to the field only when they clearly overlap
        if not nline or not (nline in nt or nt in nline or _token_overlap(nt, nline) >= 0.5):
            continue
        for span in d["spans"]:
            text, c = _wrap_token(text, span)
            wrapped += c
            if c:
                nt = _norm(text)
    return text, wrapped


def apply_emphasis(quiz: dict, detected: list[dict]) -> int:
    """Wrap emphasized words in the question text. Returns count.

    Applied to `prompt` and `narrative_context` only -- NOT to answer options.
    In these questionnaires an emphasized (usually underlined) option marks the
    *correct answer* in a solution version; rendering it would leak the answer.
    Genuine content emphasis (e.g. the bold "לא" in a "מי לא…" question) lives in
    the prompt and is preserved.
    """
    total = 0
    for section in quiz.get("sections", []) or []:
        for unit in section.get("question_units", []) or []:
            for field in ("prompt", "narrative_context"):
                if unit.get(field):
                    unit[field], c = _apply_to_field(unit[field], detected)
                    total += c
    return total
