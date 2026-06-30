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

# Vendored, repo-committed corpus so the pipeline runs offline anywhere.
# Override with TANACH_CORPUS to point at a fuller source if desired.
_REPO_CORPUS = Path(__file__).resolve().parent / "data" / "tanach_verses.jsonl"
DEFAULT_CORPUS = os.environ.get("TANACH_CORPUS") or str(_REPO_CORPUS)

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
            # vendored corpus uses `niqqud`; a fuller source may use `text_with_niqqud`
            niqqud = _clean_niqqud(v.get("niqqud") or v.get("text_with_niqqud") or "")
            sk = _skeleton(niqqud)  # niqqud-stripped == text_plain skeleton
            idx = len(verses)
            verses.append({
                "book": v.get("book"), "chapter": v.get("chapter"),
                "verse": v.get("verse"), "ref": v.get("ref"), "niqqud": niqqud,
            })
            parts.append(sk)
            pos2verse.extend([idx] * len(sk))
    _INDEX = (verses, "".join(parts), pos2verse)
    return _INDEX


def _locate(segment: str, glob: str) -> tuple[int, int] | None:
    """Find ``segment`` in the corpus skeleton. Returns (pos, length) or None.

    Tries the full segment skeleton first; on failure falls back to the longest
    contiguous word-window that *is* present. The fallback bridges abbreviations
    the corpus spells out -- chiefly the divine name (exam: "ה'" -> skeleton "ה";
    corpus: "יהוה") -- which otherwise break the single contiguous match.
    """
    full = _skeleton(segment)
    if len(full) >= 6:
        pos = glob.find(full)
        if pos >= 0:
            return pos, len(full)
    words = segment.split()
    skels = [_skeleton(w) for w in words]
    n = len(words)
    for win_len in range(n, 0, -1):
        for start in range(0, n - win_len + 1):
            sk = "".join(skels[start:start + win_len])
            if len(sk) < 12:           # demand a solid anchor for the fallback
                continue
            pos = glob.find(sk)
            if pos >= 0:
                return pos, len(sk)
    return None


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
    segments = sorted((s for s in _ELLIPSIS.split(quote) if s.strip()),
                      key=lambda s: len(_skeleton(s)), reverse=True)
    located = None
    for seg in segments:
        located = _locate(seg, glob)
        if located:
            break
    if not located:
        return None
    pos, alen = located
    v0, v1 = pos2verse[pos], pos2verse[pos + alen - 1]
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
