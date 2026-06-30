"""Tests for the public/oral (פומבי) parser.

Synthetic fixtures exercise the 2017m3 micro-grammar (composite / crossword /
head-to-head, two tracks) with *unvocalized* quotes, so no corpus or Sefaria
lookup is triggered. An autouse fixture additionally neutralises the network
fallback as a belt-and-braces guard.
"""

import pytest

import extract
import public_parser as pp


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # _inline_clean_quote falls back to Sefaria when the corpus misses; block it.
    monkeypatch.setattr(extract, "align_quote_to_sefaria", lambda *a, **k: None)


# A compact booklet: a תקנון page (no inline answers) followed by the three
# stages, each split into ממלכתי / ממלכתי-דתי tracks.
PAGES = [
    # page 0 -- cover / credits
    "חידון התנ\"ך הארצי לנוער\nהממונה על חידוני התנ\"ך: פלוני אלמוני\n",
    # page 1 -- תקנון (regulation prose, must NOT become questions)
    "תקנון החידון וסדריו\n"
    "כל חידון מורכב מ-3 שלבים: שלב א - שאלות בעקבות קטעי שירה; שלב ב - תשבצים; שלב ג - ראש בראש.\n"
    "תשובה נכונה לכל שאלה תזכה את המתמודד/ת ב-5 נקודות.\n"
    "בשלב הזה אפשר לבקש רמזים - כל רמז יגרע מהניקוד 2 נקודות. הזמן המוקצה: 45 שניות.\n",
    # page 2 -- Stage A (poetry / composite)
    "שלב א - שאלות בעקבות קטעי שירה\n"
    "ממלכתי:\n"
    "שאלה 1\n"
    "מלך מסוים החליט לאפשר ליהודים לשוב: \"מי בכם מכל עמו יהי אלהיו עמו\".\n"
    "א. מיהו המלך?\n"
    "ב. כיצד יש לסייע לעולים?\n"
    "תשובות:\n"
    "א. המלך הוא כורש מלך פרס.\n"
    "ב. בתרומות של כסף וזהב ורכוש.\n"
    "(תתקבל גם התשובה: להחזיר את אוצר המקדש)\n"
    "מי בכם מכל עמו יהי אלהיו עמו ויעל לירושלם: (עזרא א, 3)\n"
    "ממלכתי-דתי:\n"
    "שאלה 2\n"
    "נביא קרא לעם: \"העת לכם לשבת בבתיכם\".\n"
    "א. מיהו הנביא?\n"
    "תשובות:\n"
    "א. הנביא הוא חגי.\n"
    "ויהי דבר ה' ביד חגי הנביא: (חגי א, ג)\n",
    # page 3 -- Stage B (crossword)
    "שלב ב\n"
    "תשבצים\n"
    "ממלכתי:\n"
    "תשבץ 1:\n"
    "1. (מאונך) על העיר הזאת נאמר שאין יוצא ואין בא. (5)\n"
    "התשובה: יריחו\n"
    "ויריחו סגרת ומסגרת: (יהושע ו, 1)\n"
    "2. (מאוזן) ידו יבשה לאחר שהורה לתפוס את איש האלוהים. (5)\n"
    "התשובה: ירבעם\n"
    "ויהי כשמע המלך: (מלכים א יג, 4)\n",
    # page 4 -- Stage C (head-to-head)
    "שלב ג\n"
    "ראש בראש\n"
    "ראש בראש: ממלכתי\n"
    "צמד 1: תשועת ירושלים\n"
    "1. מי אמר: \"בימים ההם תושע יהודה\"?\n"
    "התשובה: ירמיה\n"
    "בימים ההם תושע יהודה וירושלם: (ירמיה לג, 16)\n"
    "2. מי אמר: \"כי מירושלם תצא שארית\"?\n"
    "התשובה: ישעיה (יתקבל גם: ישעיהו)\n"
    "כי מירושלם תצא שארית: (מלכים ב יט, לא)\n",
]


@pytest.fixture
def sections():
    secs, _info = pp.parse_public_sections(PAGES)
    return secs


def _unit(sections, section_id):
    sec = next(s for s in sections if s["section_id"] == section_id)
    return sec


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def test_looks_public_true_on_public_booklet():
    assert pp.looks_public(PAGES) is True


def test_looks_public_false_on_multiple_choice():
    mc_pages = [
        "חידון בית ספרי\nהוראות למתמודדים\n",
        "1. באיזה יום נברא האדם?\nא. ראשון\nב. שני\nג. שישי\nד. שבת\n"
        "2. מי ילדה את עשו?\nא. שרה\nב. רבקה\nג. רחל\nד. הגר\n",
        "תשובון\n1. ג\n2. ב\n",
    ]
    assert pp.looks_public(mc_pages) is False


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #
def test_six_sections_two_tracks_per_stage(sections):
    ids = [s["section_id"] for s in sections]
    assert ids == [
        "stage_א_mamlachti", "stage_א_mamlachti-dati",
        "stage_ב_mamlachti",
        "stage_ג_mamlachti",
    ]


def test_stage_subtypes(sections):
    subs = {s["section_id"]: s["stage_subtype"] for s in sections}
    assert subs["stage_א_mamlachti"] == "live-rounds"
    assert subs["stage_ב_mamlachti"] == "crossword"
    assert subs["stage_ג_mamlachti"] == "head-to-head"


def test_takanon_not_parsed_as_questions(sections):
    # The regulation page mentions "שלב א/ב/ג" but carries no inline answers,
    # so it must not produce any question units.
    total = sum(len(s["question_units"]) for s in sections)
    assert total == 4  # 2 poetry + 1 crossword + 1 head-to-head


# --------------------------------------------------------------------------- #
# Poetry / composite
# --------------------------------------------------------------------------- #
def test_poetry_composite_subquestions_and_answers(sections):
    sec = _unit(sections, "stage_א_mamlachti")
    u = sec["question_units"][0]
    assert u["question_type"] == "composite"
    assert u["answer_style"] == "free_text_model_answer"
    assert [sq["label"] for sq in u["subquestions"]] == ["א", "ב"]
    a, b = u["subquestions"]
    assert a["prompt"] == "מיהו המלך?"
    assert a["acceptable_answers"][0]["answer_text"] == "המלך הוא כורש מלך פרס."
    # the parenthetical alternate becomes a non-primary acceptable answer
    alts = [x["answer_text"] for x in b["acceptable_answers"] if not x["is_primary"]]
    assert "להחזיר את אוצר המקדש" in alts


def test_poetry_source_ref_and_answer_not_polluted_by_verse(sections):
    sec = _unit(sections, "stage_א_mamlachti")
    u = sec["question_units"][0]
    refs = u["primary_sources"]
    assert {"book": "עזרא", "chapter": "א", "verse": "ג"} == {
        k: refs[0][k] for k in ("book", "chapter", "verse")
    }
    # the printed source verse must not leak into the model answer
    b = u["subquestions"][1]
    assert "ויעל לירושלם" not in b["acceptable_answers"][0]["answer_text"]


# --------------------------------------------------------------------------- #
# Crossword
# --------------------------------------------------------------------------- #
def test_crossword_lengths_directions_answers(sections):
    sec = _unit(sections, "stage_ב_mamlachti")
    u = sec["question_units"][0]
    assert u["question_type"] == "mini_crossword"
    assert u["display_number"] == "תשבץ 1"
    c1, c2 = u["subquestions"]
    assert c1["label"] == "1 (מאונך)" and c1["answer_length"] == "5"
    assert c1["acceptable_answers"][0]["answer_text"] == "יריחו"
    assert "(5)" not in c1["prompt"]
    assert c2["label"] == "2 (מאוזן)"
    assert c2["acceptable_answers"][0]["source_refs"][0]["book"] == "מלכים א"


# --------------------------------------------------------------------------- #
# Head-to-head
# --------------------------------------------------------------------------- #
def test_head_to_head_pair_and_alternates(sections):
    sec = _unit(sections, "stage_ג_mamlachti")
    u = sec["question_units"][0]
    assert u["display_number"].startswith("צמד 1")
    assert u["narrative_context"] == "תשועת ירושלים"
    q1, q2 = u["subquestions"]
    assert q1["acceptable_answers"][0]["answer_text"] == "ירמיה"
    alts = [x["answer_text"] for x in q2["acceptable_answers"] if not x["is_primary"]]
    assert alts == ["ישעיהו"]


# --------------------------------------------------------------------------- #
# Live-stage rules
# --------------------------------------------------------------------------- #
def test_live_stage_rules_parsed(sections):
    rules = sections[0]["live_stage_rules"]
    assert rules["points_per_correct"] == 5
    assert rules["points_decay_per_hint"] == 2
    assert rules["time_limit_seconds"] == 45


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #
def test_build_questionnaire_clean_and_valid():
    q, quality, _notes = pp.build_public_questionnaire(
        "fixture_pub", "http://example/fixture.pdf", PAGES, {"year_civil": 2017}
    )
    assert quality == "clean"
    assert extract.validate(q) == []
    assert q["metadata"]["scoring_summary"]["scoring_is_tiered"] is True
    assert len(q["sections"]) == 4
