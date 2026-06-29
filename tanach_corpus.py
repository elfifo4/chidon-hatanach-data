"""Local Tanach corpus lookup.

Resolves a (PDF-corrupted) quote to its clean vocalized verse text by matching
the quote's consonant skeleton against a full Tanach corpus -- independent of any
answer-key reference. This is the bullet-proof source for embedded verse quotes:
the returned text has correct word boundaries (no spurious intra-word spaces) and
no lost letters.

Corpus: one verse per line (JSONL) with `text_with_niqqud` (vowels, no cantillation,
spaces not maqaf), `text_plain` (consonants), `book`, `chapter`, `verse`, `ref`.
Path is configurable via the TANACH_CORPUS env var.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

DEFAULT_CORPUS = os.environ.get(
    "TANACH_CORPUS",
    "/Users/eladfinish/Projects/Bible-RAG/data/processed/all_verses.jsonl",
)

_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_SOF_MARKS = re.compile(r"[׃׀׆׳״]")
_ELLIPSIS = re.compile(r"\s*(?:…|\.\s*\.\s*\.+|\.{2,})\s*")

_INDEX = None  # cache: (verses, global_skeleton, pos2verse)


def _skeleton(s: str | None) -> str:
    """Consonant-only skeleton (no niqqud/spaces/punct, final forms normalised)."""
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(c for c in s if "א" <= c <= "ת")
    return s.translate(_FINALS)


def _clean_niqqud(s: str | None) -> str:
    return re.sub(r"\s+", " ", _SOF_MARKS.sub("", s or "")).strip()


def available(path: str = DEFAULT_CORPUS) -> bool:
    return Path(path).exists()


def _load(path: str):
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    verses: list[dict] = []
    parts: list[str] = []
    pos2verse: list[int] = []
    p = Path(path)
    if p.exists():
        for line in p.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            niqqud = _clean_niqqud(v.get("text_with_niqqud") or "")
            sk = _skeleton(v.get("text_plain") or niqqud)
            idx = len(verses)
            verses.append({
                "book": v.get("book"), "chapter": v.get("chapter"),
                "verse": v.get("verse"), "ref": v.get("ref"), "niqqud": niqqud,
            })
            parts.append(sk)
            pos2verse.extend([idx] * len(sk))
    _INDEX = (verses, "".join(parts), pos2verse)
    return _INDEX


def resolve_quote(quote: str | None, path: str = DEFAULT_CORPUS) -> tuple[str, dict] | None:
    """Locate the verse(s) the quote came from.

    Returns (clean_joined_niqqud_text, ref) where ref is
    {book, chapter, verse} of the first matched verse, or None if no confident
    match. Uses the longest ellipsis-delimited segment as the anchor, so partial
    quotes still resolve; widens by one verse to cover the other segments.
    """
    if not quote:
        return None
    verses, glob, pos2verse = _load(path)
    if not glob:
        return None
    segments = [s for s in _ELLIPSIS.split(quote) if s.strip()]
    anchor = max((_skeleton(s) for s in segments), key=len, default="")
    if len(anchor) < 6:        # too short to resolve unambiguously
        return None
    pos = glob.find(anchor)
    if pos < 0:
        return None
    v0, v1 = pos2verse[pos], pos2verse[pos + len(anchor) - 1]
    if v1 - v0 > 3:            # implausibly long span -> not trustworthy
        return None
    lo, hi = max(0, v0 - 1), min(len(verses) - 1, v1 + 1)
    book = verses[v0]["book"]
    while lo < v0 and verses[lo]["book"] != book:
        lo += 1
    while hi > v1 and verses[hi]["book"] != book:
        hi -= 1
    text = " ".join(verses[i]["niqqud"] for i in range(lo, hi + 1))
    first = verses[v0]
    return text, {"book": first["book"], "chapter": first["chapter"], "verse": first["verse"]}
