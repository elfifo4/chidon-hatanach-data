"""Tests for Hebrew niqqud repair and Sefaria verse enrichment.

Run: .venv/bin/python -m pytest tests/test_repair.py -v

The deterministic tests assert what `repair_hebrew_pdf_text` reliably guarantees
(mark reattachment, NFC, no word merging). The user's four verse examples are
real Bible verses whose correct word boundaries cannot be reconstructed
deterministically -- those are validated via Sefaria lookup (network; skipped
offline).
"""
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import extract  # noqa: E402

NFC = lambda s: unicodedata.normalize("NFC", s)
# Sefaria distinguishes qamatz-qatan (U+05C7); the user's examples used a plain
# qamatz (U+05B8). Fold them together for verse comparison.
_fold = lambda s: NFC(s).replace("ׇ", "ָ")

# The user's reported broken extractions (corrupted inputs).
BROKEN = [
    "ֵּה ִמית ְבמ ֹות ֹו ַר ִבים ֵּמ ֲא ֶּשר ֵּה ִמית ְב ַח ָייו",
    "אֹכְלִים ְו ֹש ִתים יַיִן",
    "ְב ַח ָייו",
    "ּובָ נּו חָ רְ בוֹת עוֹלָם",
]


@pytest.mark.parametrize("text", BROKEN)
def test_no_detached_marks_after_repair(text):
    """Every 'space + combining mark' is gone -- marks reattached to a letter."""
    out = extract.repair_hebrew_pdf_text(text)
    assert extract._SPACE_THEN_MARK.search(out) is None, repr(out)


@pytest.mark.parametrize("text", BROKEN)
def test_repair_is_nfc(text):
    out = extract.repair_hebrew_pdf_text(text)
    assert out == NFC(out)


def test_no_combining_mark_at_word_start():
    """No word (whitespace-delimited token) may start with a combining mark."""
    for text in BROKEN:
        out = extract.repair_hebrew_pdf_text(text)
        for tok in out.split():
            assert not extract._is_hebrew_mark(tok[0]), repr(tok)


def test_real_word_boundary_preserved():
    """The space before a new word is NOT swallowed (no merging) -- requirement #3.

    A final-form letter (ך ם ן ף ץ) only occurs at a word end, so it must never
    be immediately followed by another Hebrew letter or mark.
    """
    import re
    for text in BROKEN:
        out = extract.repair_hebrew_pdf_text(text)
        assert re.search(r"[ךםןףץ][א-ת֑-ׇ]", out) is None, repr(out)


def test_empty_and_none():
    assert extract.repair_hebrew_pdf_text("") == ""
    assert extract.repair_hebrew_pdf_text(None) is None


def test_clean_text_unchanged():
    """Already-correct text round-trips (only NFC/whitespace normalization)."""
    clean = "מי אמר פסוק זה?"
    assert extract.repair_hebrew_pdf_text(clean) == clean


def test_clean_vocalized_verse_unchanged():
    """Clean Sefaria-style verse text must not be altered (no false merges)."""
    verse = "תֻּמֶּיךָ וְאוּרֶיךָ לְאִישׁ חֲסִידֶךָ"
    assert extract.repair_hebrew_pdf_text(verse) == verse


def test_lone_fragment_spaces_collapsed():
    """Single-letter vocalized fragments rejoin into words (the user's example)."""
    broken = 'שולח אליו שלמה: "וְ הִ נְ נִי אֹ מֵר לִ בְנוֹת בַּיִת לְ שֵׁם ה\' אֱ הָי"'
    out = extract.repair_hebrew_pdf_text(broken)
    assert "וְהִנְנִי" in out and "אֹמֵר" in out and "לִבְנוֹת" in out, repr(out)
    assert "וְ הִ" not in out and "אֹ מֵר" not in out
    # real word boundary kept: 'ה'' (the Name) stays a separate token
    assert "ה'" in out.split()


# --------------------------------------------------------------------------- #
# Sefaria integration -- exact verse recovery by reference (network).
# --------------------------------------------------------------------------- #
def _sefaria(refs):
    try:
        return extract.fetch_verse_text(refs)
    except Exception:
        return None


@pytest.mark.parametrize("refs, expected", [
    # Judges 16:30 -- the user's example 1.
    ([{"book": "שופטים", "chapter": "טז", "verse": "ל"}],
     "הֵמִית בְּמוֹתוֹ רַבִּים מֵאֲשֶׁר הֵמִית בְּחַיָּיו"),
    # Isaiah 61:4 -- the user's example 4.
    ([{"book": "ישעיהו", "chapter": "סא", "verse": "ד"}],
     "וּבָנוּ חָרְבוֹת עוֹלָם"),
])
def test_sefaria_recovers_user_examples(refs, expected):
    verse = _sefaria(refs)
    if verse is None:
        pytest.skip("Sefaria unreachable (offline)")
    assert _fold(expected) in _fold(verse), f"{expected!r} not in {verse!r}"
