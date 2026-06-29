"""Pilot tests -- pure, no network. Covers HTML validation, structure
validators on the golden JSON, vision merge with an injected fake client, the
VisionUnavailable path, and evaluation diffing.
"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extract              # noqa: E402
import html_format          # noqa: E402
import pdf_emphasis         # noqa: E402
import pilot_validate       # noqa: E402
import pdf_vision           # noqa: E402
import tanach_corpus        # noqa: E402
import vision_client        # noqa: E402

GOLDEN = ROOT / "content" / "quizzes" / "beitsifri_mmd2026.json"


# --------------------------- HTML validation ------------------------------- #
@pytest.mark.parametrize("s, ok", [
    ("plain text", True),
    ("את בנה של מי <u>לא</u> שכל דוד?", True),
    ("<b>שלום</b> <i>עולם</i>", True),
    ("<u>לא", False),               # unclosed
    ("</b>oops", False),            # stray close
    ('<span style="x">no</span>', False),  # disallowed tag
])
def test_validate_html(s, ok):
    assert html_format.validate_html(s)[0] is ok


def test_sanitize_strips_invalid_keeps_valid():
    assert html_format.sanitize("<u>לא</u>") == "<u>לא</u>"
    assert html_format.sanitize('<span>x</span>לא') == "xלא"
    assert html_format.normalize_for_compare("  <u>לא</u>  שכל ") == "לא שכל"


# --------------------------- structure validators -------------------------- #
def test_golden_passes_structure():
    quiz = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert pilot_validate.validate_quiz(quiz, expected_count=35) == []
    st = pilot_validate.stats(quiz)
    assert st["questions_detected"] == 35
    assert st["with_four_answers"] == 35
    assert st["with_correct_answer"] == 35


def test_validate_catches_problems():
    quiz = json.loads(GOLDEN.read_text(encoding="utf-8"))
    bad = copy.deepcopy(quiz)
    units = bad["sections"][0]["question_units"]
    units[0]["options"] = units[0]["options"][:3]   # only 3 answers
    units[1]["correct_option"] = None               # missing correct
    units[2]["prompt"] = units[2]["prompt"] + "�"    # replacement char
    errs = pilot_validate.validate_quiz(bad, expected_count=35)
    assert any("options (expected 4)" in e for e in errs)
    assert any("missing correct_option" in e for e in errs)
    assert any("replacement char" in e for e in errs)


# --------------------------- vision merge (mock) --------------------------- #
def _mini_quiz():
    return {"questionnaire_id": "x", "sections": [{"question_units": [{
        "unit_id": "q01", "display_number": "1", "prompt": "מי לא שכל?",
        "correct_option": "ב",
        "options": [{"key": "א", "text": "אחינעם"}, {"key": "ב", "text": "אביגיל"},
                    {"key": "ג", "text": "מעכה"}, {"key": "ד", "text": "חגית"}],
        "primary_sources": [{"book": "שמואל ב", "chapter": "ג", "verse": "ב", "scope": "whole_unit"}],
    }]}]}


def test_merge_applies_emphasis_and_preserves_structure():
    quiz = _mini_quiz()
    review = {"questions": [{"display_number": "1", "prompt": "מי <u>לא</u> שכל?",
                            "options": [{"key": "א", "text": "אחינעם"}, {"key": "ב", "text": "אביגיל"},
                                        {"key": "ג", "text": "מעכה"}, {"key": "ד", "text": "חגית"}]}]}
    warnings = vision_client.merge_into_baseline(quiz, review)
    u = quiz["sections"][0]["question_units"][0]
    assert u["prompt"] == "מי <u>לא</u> שכל?"          # emphasis merged
    assert u["correct_option"] == "ב"                  # structure preserved
    assert u["primary_sources"][0]["book"] == "שמואל ב"
    assert warnings == []


def test_merge_rejects_unclean_and_shape_mismatch():
    quiz = _mini_quiz()
    review = {"questions": [{"display_number": "1", "prompt": "מי לא שכל בְ�",  # unclean
                            "options": [{"key": "א", "text": "x"}]}]}            # wrong shape
    warnings = vision_client.merge_into_baseline(quiz, review)
    u = quiz["sections"][0]["question_units"][0]
    assert u["prompt"] == "מי לא שכל?"                  # baseline kept (vision unclean)
    assert [o["text"] for o in u["options"]] == ["אחינעם", "אביגיל", "מעכה", "חגית"]
    assert any("unclean" in w["warning"] for w in warnings)
    assert any("shape mismatch" in w["warning"] for w in warnings)


def test_apply_emphasis_bold_and_underline():
    quiz = _mini_quiz()
    quiz["sections"][0]["question_units"][0]["prompt"] = "מי לא שכל?"
    detected = [{"line": "מי לא שכל?",
                 "spans": [{"text": "לא", "bold": True, "underline": True}]}]
    n = pdf_emphasis.apply_emphasis(quiz, detected)
    assert n == 1
    prompt = quiz["sections"][0]["question_units"][0]["prompt"]
    assert prompt == "מי <b><u>לא</u></b> שכל?"
    assert html_format.validate_html(prompt)[0]


def test_apply_emphasis_does_not_touch_unrelated_question():
    quiz = _mini_quiz()
    quiz["sections"][0]["question_units"][0]["prompt"] = "מתי לא ירד גשם?"
    # emphasis belongs to a totally different line/question
    detected = [{"line": "את בנה של מי לא שכל דוד?",
                 "spans": [{"text": "לא", "bold": True, "underline": False}]}]
    n = pdf_emphasis.apply_emphasis(quiz, detected)
    assert n == 0  # low overlap -> not applied to the unrelated prompt


def test_furniture_contamination_flags_trailing_integer():
    quiz = _mini_quiz()
    quiz["sections"][0]["question_units"][0]["options"][1]["text"] = "אביגיל 5"
    hits = pilot_validate.furniture_contamination(quiz)
    assert len(hits) == 1 and hits[0]["field"] == "option:ב"


def test_furniture_contamination_clean_by_default():
    assert pilot_validate.furniture_contamination(_mini_quiz()) == []


def test_corpus_available_false_for_bad_path():
    assert tanach_corpus.available("/no/such/corpus.jsonl") is False


@pytest.mark.skipif(not tanach_corpus.available(), reason="Tanach corpus not present")
def test_corpus_resolves_verse_from_corrupted_quote():
    res = tanach_corpus.resolve_quote(" אֶֽרֶץ זֵית שֶׁמֶן וּדְ בָש")  # spurious space inside ודבש
    assert res is not None
    text, ref = res
    assert (ref["book"], ref["chapter"], ref["verse"]) == ("דברים", 8, 8)
    assert "וּדְבָשׁ" in text


@pytest.mark.skipif(not tanach_corpus.available(), reason="Tanach corpus not present")
def test_inline_clean_fixes_intra_word_space_without_ref():
    prompt = '" אֶֽרֶץ זֵית שֶׁמֶן וּדְ בָש" - איזה מהמינים הללו מוזכר במגילת רות?'
    out, ok = extract._inline_clean_quote(prompt, [])  # no answer-key ref
    assert ok
    assert "וּדְבָשׁ" in out and "וּדְ בָש" not in out


def test_vision_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(vision_client.VisionUnavailable):
        vision_client.review_pages([], {})  # no injected client, no key


# --------------------------- evaluation ------------------------------------ #
def test_evaluate_identical_is_clean(tmp_path):
    quiz = json.loads(GOLDEN.read_text(encoding="utf-8"))
    ev = pdf_vision.evaluate(quiz, str(GOLDEN))
    assert ev["questions_with_diffs"] == 0


def test_evaluate_detects_diff(tmp_path):
    quiz = json.loads(GOLDEN.read_text(encoding="utf-8"))
    perturbed = copy.deepcopy(quiz)
    u0 = perturbed["sections"][0]["question_units"][0]
    u0["correct_option"] = "א" if u0["correct_option"] != "א" else "ב"  # guaranteed different
    p = tmp_path / "golden.json"
    p.write_text(json.dumps(quiz, ensure_ascii=False), encoding="utf-8")
    ev = pdf_vision.evaluate(perturbed, str(p))
    assert ev["questions_with_diffs"] == 1
    assert "correct_option" in ev["diffs"][0]
