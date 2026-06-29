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


# --------------------------------------------------------------------------- #
# Faithful quote alignment -- only the quoted words, ellipsis preserved.
# --------------------------------------------------------------------------- #
def test_alignment_preserves_ellipsis_and_excludes_elided_words():
    """Deut 24:15 quoted partially with an ellipsis (the user's report)."""
    exam = '"כִּי ﬠָ נִי הוּא… וְלֽאֹ יִקְרָא ﬠָ לֶי׽ אֶל ה\' וְהָיָה בְ�חֵטְא"'
    refs = [{"book": "דברים", "chapter": "כד", "verse": "טו"}]
    out = extract.align_quote_to_sefaria(exam, refs)
    if out is None:
        pytest.skip("Sefaria unreachable (offline)")
    assert "…" in out                              # ellipsis preserved
    assert "בְּיוֹמוֹ" not in out and "שְׂכָרוֹ" not in out  # elided words NOT added
    assert "נֹשֵׂא" not in out and "נַפְשׁוֹ" not in out      # middle (elided) words NOT added
    assert "עָנִי" in out and "חֵטְא" in out         # quoted words present
    assert "ה'" in out                              # divine-name abbreviation preserved


@pytest.mark.parametrize("n, heb", [(15, "טו"), (16, "טז"), (29, "כט"), (30, "ל"), (31, "לא"), (5, "ה")])
def test_int_to_gematria(n, heb):
    assert extract.int_to_gematria(n) == heb


def test_widen_refs_builds_verse_window():
    out = extract._widen_refs([{"book": "במדבר", "chapter": "לב", "verse": "ל"}], before=2, after=1)
    assert out[0]["verse"] == "כח-לא"  # 30 -> 28..31


def test_split_narrative_ignores_incidental_niqqud():
    """A lone vocalized word in the question is not pulled out as a verse."""
    narr, prompt = extract.split_narrative("את בנה של מי לא שׁכל דוד?")
    assert narr is None
    assert "שׁכל דוד" in prompt or "שכל דוד" in prompt


@pytest.mark.parametrize("base, track, stage", [
    ("beitsifri_mm2026", "mamlachti", "school"),
    ("beitsifri_mmd2026", "mamlachti_dati", "school"),
    ("ARTZI_PUB_MMD", "mamlachti_dati", "national"),    # mmd -> dati, not mamlachti
    ("artzi-mm-booklet", "mamlachti", "national"),       # -mm- on hyphen boundary
    ("regional_booklet_mamad", "mamlachti_dati", "district"),  # mamad -> dati
    ("adults_district_quiz33", "mamlachti", "district"),  # English "district"
    ("adults_international_bible_quiz", "mamlachti", "world"),  # "internat" -> world
    ("ARZI-MMLCHTI-1-WRITTEN", "mamlachti", "national"),  # transliteration + typo
])
def test_decode_filename_classification(base, track, stage):
    m = extract.decode_filename(base)
    assert m["track"] == track, m
    assert m["stage"] == stage, m


def test_dati_detected_before_mamlachti():
    """A mamlachti_dati marker must never be read as plain mamlachti."""
    for base in ("beitsifri_mmd2025", "ARTZI_PUB_MMD", "regional_booklet_mamad", "x_dati_2020"):
        assert extract.decode_filename(base)["track"] == "mamlachti_dati", base


def test_split_narrative_extracts_quoted_verse():
    narr, prompt = extract.split_narrative('על מי נאמר: "וַיֵּשְׁתְּ מִן הַיַּיִן וַיִּשְׁכָּר"?')
    assert narr is not None and "וַיֵּשְׁתְּ" in narr
    assert prompt.endswith("?") and "וַיֵּשְׁתְּ" not in prompt
