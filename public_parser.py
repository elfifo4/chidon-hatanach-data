"""Parser for the public/oral (פומבי) contest formats.

The multiple-choice parser in ``extract.py`` assumes "numbered question + 4
options א/ב/ג/ד + an answer key with one correct letter". The public/oral
booklets break every one of those assumptions: they are organised into *stages*
(שלב א/ב/ג), often run as two parallel quizzes (ממלכתי / ממלכתי-דתי), the answers
are printed inline right under each question, and the question types are open,
composite (א/ב sub-questions), verse-completion, mini-crossword, etc.

This module parses that family into the *existing* schema (see
``docs/beitsifri_mm2026.json``) without touching the MC path. The first grammar
implemented is the youth national public booklet (``2017m3``), whose three
stages share one micro-grammar:

    שלב א - שאלות בעקבות קטעי שירה   -> composite (narrative + quote + א/ב)
    שלב ב - תשבצים                   -> mini_crossword (clue + direction + length)
    שלב ג - ראש בראש                 -> head-to-head pairs (צמד) of short open Qs

Detection (``looks_public``) is deliberately conservative so the 16 working MC
quizzes never reach this code.
"""

from __future__ import annotations

import re

from extract import (
    HEBREW_YEARS,
    TODAY,
    _inline_clean_quote,
    parse_metadata_page,
    parse_source_refs,
    repair_hebrew_pdf_text,
    strip_niqqud,
)


# --------------------------------------------------------------------------- #
# Line classification
# --------------------------------------------------------------------------- #
_STAGE_RE = re.compile(r"^\s*שלב\s+([אבגד])\b\s*[:\-–]?\s*(.*)$")
# A track marker is a line that is *only* a track designation, optionally
# prefixed by a stage name (e.g. "ראש בראש: ממלכתי-דתי").
_TRACK_DATI_RE = re.compile(r"^\s*(?:[^:]*:\s*)?ממלכתי\s*[-–]\s*דתי\s*:?\s*$")
_TRACK_MAML_RE = re.compile(r"^\s*(?:[^:]*:\s*)?ממלכתי\s*:?\s*$")

_Q_RE = re.compile(r"^\s*שאלה\s+(\d+)\s*$")           # poetry unit
_CROSSWORD_RE = re.compile(r"^\s*תשבץ\s+(\d+)\s*:\s*$")  # crossword container
_ZEMED_RE = re.compile(r"^\s*צמד\s+(\d+)\s*:\s*(.*)$")    # head-to-head container

# Sub-items inside a container.
_CLUE_RE = re.compile(r"^\s*(\d+)\.\s*\((מאונך|מאוזן)\)\s*(.*)$")
_NUM_ITEM_RE = re.compile(r"^\s*(\d+)\.\s*(.*)$")
_SUBQ_RE = re.compile(r"^\s*([א-ד])\.\s*(.*)$")

# Answer markers.
_ANSWERS_PLURAL_RE = re.compile(r"^\s*תשובות\s*:\s*$")      # poetry, per-sub answers
_ANSWER_SINGLE_RE = re.compile(r"^\s*ה?תשובה\s*:\s*(.*)$")  # crossword / head-to-head

# A trailing "(ספר פרק, פסוק)" source annotation on a verse line.
_SOURCE_PAREN_RE = re.compile(r"\(([^()]*?)\)\s*$")
# Length hint such as "(5)" or "(3, 5)" on a crossword clue.
_LENGTH_RE = re.compile(r"\(\s*(\d+(?:\s*,\s*\d+)*)\s*\)")
# Inline "also accepted" alternates inside an answer.
_ALSO_RE = re.compile(r"(?:יתקבל(?:ו)? גם|תתקבל גם(?:\s+התשובה)?)\s*:?\s*(.+)")

_BOOK_HINT = re.compile(
    r"בראשית|שמות|ויקרא|במדבר|דברים|יהושע|שופטים|שמואל|מלכים|ישעיה|ירמיה|"
    r"יחזקאל|הושע|יואל|עמוס|עובדיה|יונה|מיכה|נחום|חבקוק|צפניה|חגי|זכריה|"
    r"מלאכי|תהלים|תהילים|משלי|איוב|רות|אסתר|דניאל|עזרא|נחמיה|דברי הימים|"
    r"שיר השירים|קהלת|איכה"
)


def looks_public(pages: list[str]) -> bool:
    """Conservative detector for the public/oral booklets.

    Requires the staged structure (שלב א/ב/ג) *and* inline answer markers, and
    the absence of a dense multiple-choice option grid. The MC school/district
    quizzes have neither stage headers nor inline 'התשובה:' lines, so they never
    match.
    """
    text = "\n".join(pages)
    has_stages = bool(re.search(r"שלב\s+[בג]\b", text))
    has_inline_answers = ("התשובה:" in text or "תשובות:" in text)
    has_public_stage_names = bool(
        re.search(r"ראש\s+בראש|תשבצים|בעקבות\s+(?:קטעי|סרטונים)|המילה המשותפת|מה הקשר", text)
    )
    return has_stages and has_inline_answers and has_public_stage_names


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
_NIQQUD_RE = re.compile(r"[ְ-ׇ]")


def _has_niqqud(line: str) -> bool:
    """A vocalized line (a printed source verse) vs. an unvocalized prose answer.

    Source verses carry dense niqqud; the inline model answers are written in
    plain modern Hebrew. Two+ niqqud marks reliably distinguishes them (a stray
    mark can leak into prose from a quoted word)."""
    return len(_NIQQUD_RE.findall(line)) >= 2


def _clean(s: str | None) -> str | None:
    return repair_hebrew_pdf_text(s) if s else s


def _is_source_line(line: str) -> list[dict]:
    """If ``line`` ends in a parsable "(book chap, verse)" annotation, return the
    parsed refs; otherwise []."""
    m = _SOURCE_PAREN_RE.search(line)
    if not m:
        return []
    inner = m.group(1)
    if not _BOOK_HINT.search(inner):
        return []
    return parse_source_refs(inner)


def _strip_judge_note(answer: str) -> tuple[str, str | None]:
    """Split an answer like 'גבעת האלהים (אם המתמודד/ת עונה ...)' into
    (answer, note)."""
    i = answer.find("(")
    if i == -1:
        return answer.strip(), None
    return answer[:i].strip(), answer[i:].strip()


def _split_alternates(answer: str) -> tuple[str, list[str], str | None]:
    """Return (primary_answer, alternates[], note). Handles 'יתקבל גם:' / parens."""
    note = None
    body, paren = _strip_judge_note(answer)
    alternates: list[str] = []
    src = answer
    m = _ALSO_RE.search(src)
    if m:
        # The alternates clause is usually inside the parenthetical.
        primary = src[: m.start()].strip().rstrip("(").strip()
        primary, _ = _strip_judge_note(primary)
        rest = m.group(1).rstrip(") ")
        alternates = [a.strip() for a in re.split(r"\s*/\s*|\s*;\s*", rest) if a.strip()]
        return primary, alternates, None
    if paren and not _BOOK_HINT.search(paren):
        note = paren
    return body, alternates, note


def _clean_inline(text: str | None, refs: list[dict] | None = None) -> str | None:
    """Repair the text, then clean any embedded vocalized verse quote *in place*
    via the Tanach corpus (keeping the surrounding framing and quote marks)."""
    if not text:
        return text
    repaired = _clean(text)
    cleaned, _ok = _inline_clean_quote(repaired, refs or [])
    return cleaned


def _has_quote(text: str) -> bool:
    return bool(re.search(r"[\"״]\s*\S.*?[\"״]", text or "", re.DOTALL))


# --------------------------------------------------------------------------- #
# Stage segmentation
# --------------------------------------------------------------------------- #
_STAGE_SUBTYPE = {
    "תשבצים": "crossword",
    "ראש בראש": "head-to-head",
}


def _stage_subtype(name: str, body_lines: list[str] | None = None) -> str:
    name = name.strip()
    for key, sub in _STAGE_SUBTYPE.items():
        if key in name:
            return sub
    if "תשבץ" in name:
        return "crossword"
    if "ראש בראש" in name:
        return "head-to-head"
    # The stage name often sits on the line *after* "שלב ב"; fall back to the
    # container openers present in the stage body.
    if body_lines is not None:
        if any(_CROSSWORD_RE.match(l) for l in body_lines):
            return "crossword"
        if any(_ZEMED_RE.match(l) for l in body_lines):
            return "head-to-head"
    return "live-rounds"


def _track_label(track: str | None) -> str | None:
    return {"mamlachti": "ממלכתי", "mamlachti-dati": "ממלכתי-דתי"}.get(track or "")


def _segment(lines: list[str]) -> list[dict]:
    """Group lines into stage blocks: [{letter, name, subtype, blocks:[{track, lines}]}].

    A stage block starts at a 'שלב X' header. Within a stage, 'ממלכתי:' /
    'ממלכתי-דתי:' markers split the questions into per-track sub-blocks. Lines
    before the first stage header (cover + תקנון) are dropped because they carry
    no inline answers.
    """
    stages: list[dict] = []
    cur_stage: dict | None = None
    cur_block: dict | None = None

    def new_block(track):
        nonlocal cur_block
        cur_block = {"track": track, "lines": []}
        cur_stage["blocks"].append(cur_block)

    for ln in lines:
        ms = _STAGE_RE.match(ln)
        if ms:
            name = ms.group(2).strip()
            cur_stage = {"letter": ms.group(1), "name": name, "blocks": []}
            stages.append(cur_stage)
            cur_block = None
            continue
        if cur_stage is None:
            continue
        if _TRACK_DATI_RE.match(ln):
            new_block("mamlachti-dati")
            continue
        if _TRACK_MAML_RE.match(ln):
            new_block("mamlachti")
            continue
        if cur_block is None:
            new_block(None)
        cur_block["lines"].append(ln)

    # A stage may appear twice (once in the תקנון list, once as real content).
    # Keep only stage blocks that actually contain an inline answer marker.
    real = []
    for st in stages:
        st["blocks"] = [
            b for b in st["blocks"]
            if any(_ANSWERS_PLURAL_RE.match(x) or _ANSWER_SINGLE_RE.match(x) for x in b["lines"])
        ]
        if st["blocks"]:
            body = [l for b in st["blocks"] for l in b["lines"]]
            st["subtype"] = _stage_subtype(st["name"], body)
            real.append(st)
    # Merge stages that share the same letter+name (content split across the
    # תקנון mention and the real pages) -- here we just take the real ones.
    return real


# --------------------------------------------------------------------------- #
# Per-stage unit parsing
# --------------------------------------------------------------------------- #
def _split_containers(lines: list[str], opener: re.Pattern) -> list[tuple[re.Match, list[str]]]:
    """Split lines into (opener_match, body_lines) groups."""
    groups: list[tuple[re.Match, list[str]]] = []
    cur: list[str] | None = None
    cur_m = None
    for ln in lines:
        m = opener.match(ln)
        if m:
            if cur_m is not None:
                groups.append((cur_m, cur))
            cur_m, cur = m, []
        elif cur is not None:
            cur.append(ln)
    if cur_m is not None:
        groups.append((cur_m, cur))
    return groups


def _collect_sources(body_lines: list[str]) -> tuple[list[dict], list[str]]:
    """Return (refs, non_source_lines). Refs from every '(ref)' annotation."""
    refs: list[dict] = []
    kept: list[str] = []
    for ln in body_lines:
        r = _is_source_line(ln)
        if r:
            refs.extend(r)
        else:
            kept.append(ln)
    return refs, kept


def _parse_poetry_unit(num: str, body: list[str], track: str | None) -> dict:
    """שאלה N: narrative + quote, א/ב sub-questions, תשובות: per-sub answers."""
    # Find the boundary lines: first subquestion, the answer marker.
    sub_idx = next((i for i, l in enumerate(body) if _SUBQ_RE.match(l)), None)
    ans_idx = next((i for i, l in enumerate(body) if _ANSWERS_PLURAL_RE.match(l)), None)

    narrative_lines = body[: sub_idx if sub_idx is not None else (ans_idx or len(body))]
    narrative = " ".join(l.strip() for l in narrative_lines).strip()

    # Sub-question prompts (between sub_idx and answer marker).
    subq_prompts: dict[str, str] = {}
    if sub_idx is not None:
        cur_label = None
        for l in body[sub_idx: ans_idx if ans_idx is not None else len(body)]:
            m = _SUBQ_RE.match(l)
            if m:
                cur_label = m.group(1)
                subq_prompts[cur_label] = m.group(2).strip()
            elif cur_label:
                subq_prompts[cur_label] += " " + l.strip()

    # Answers (after תשובות:), labelled א./ב.; the rest are source verses.
    answers: dict[str, str] = {}
    extra_accepts: dict[str, list[str]] = {}
    refs: list[dict] = []
    if ans_idx is not None:
        cur_label = None
        for l in body[ans_idx + 1:]:
            # A vocalized line begins the printed source-verse block: harvest any
            # ref it carries but stop appending text to the model answers.
            if _has_niqqud(l):
                refs.extend(_is_source_line(l))
                cur_label = None
                continue
            src_refs = _is_source_line(l)
            if src_refs:
                refs.extend(src_refs)
                cur_label = None
                continue
            m = _SUBQ_RE.match(l)
            if m:
                cur_label = m.group(1)
                answers[cur_label] = m.group(2).strip()
                continue
            also = re.search(r"תתקבל גם(?:\s+התשובה)?\s*:?\s*(.+)", l)
            if also:
                tgt = cur_label or (list(answers) or ["א"])[-1]
                extra_accepts.setdefault(tgt, []).append(also.group(1).strip(" )."))
                continue
            if cur_label:
                answers[cur_label] += " " + l.strip()

    labels = sorted(set(subq_prompts) | set(answers), key=lambda x: "אבגד".index(x))
    subquestions = []
    for lab in labels:
        accepts = [{"answer_text": _clean(answers.get(lab)), "source_refs": [], "is_primary": True}] \
            if answers.get(lab) else []
        for alt in extra_accepts.get(lab, []):
            accepts.append({"answer_text": _clean(alt), "source_refs": [], "is_primary": False})
        subquestions.append({
            "subquestion_id": lab,
            "label": lab,
            "prompt": _clean(subq_prompts.get(lab, "")),
            "points": None,
            "acceptable_answers": accepts,
            "requires_free_text_judging": True,
        })

    primary_sources = [{**r, "quoted_text": None, "scope": "whole_unit"} for r in refs]
    return {
        "unit_id": f"q{int(num):02d}",
        "display_number": num,
        "narrative_context": _clean_inline(narrative, refs),
        "prompt": None,
        "question_type": "composite",
        "answer_style": "free_text_model_answer",
        "options": None,
        "correct_option": None,
        "subquestions": subquestions,
        "primary_sources": primary_sources,
        "scoring": {"points": None},
        "acceptable_answers": [],
        "media_attachments": None,
        "localizations": None,
        "format_confidence_note": None,
    }


def _parse_crossword_unit(num: str, body: list[str], track: str | None) -> dict:
    """תשבץ N: a set of (מאונך/מאוזן) clues, each clue + length + answer + source."""
    clues = _split_containers(body, _CLUE_RE)
    subquestions = []
    all_refs: list[dict] = []
    for m, clue_body in clues:
        clue_num, direction = m.group(1), m.group(2)
        # Clue text + length: everything up to the answer marker.
        pre: list[str] = [m.group(3)]
        ans_line = None
        post: list[str] = []
        seen_answer = False
        for l in clue_body:
            am = _ANSWER_SINGLE_RE.match(l)
            if am and not seen_answer:
                ans_line, seen_answer = am.group(1), True
                continue
            (post if seen_answer else pre).append(l)
        clue_text = " ".join(x.strip() for x in pre if x.strip())
        lengths = _LENGTH_RE.findall(clue_text)
        length = lengths[-1] if lengths else None
        if length:
            clue_text = clue_text[: clue_text.rfind("(")].strip()
        answer, alternates, _note = _split_alternates(ans_line or "")
        refs, _ = _collect_sources(post)
        all_refs.extend(refs)
        accepts = [{"answer_text": _clean(answer), "source_refs": refs, "is_primary": True}] if answer else []
        for alt in alternates:
            accepts.append({"answer_text": _clean(alt), "source_refs": [], "is_primary": False})
        subquestions.append({
            "subquestion_id": clue_num,
            "label": f"{clue_num} ({direction})",
            "prompt": _clean_inline(clue_text, refs),
            "points": None,
            "answer_length": length,
            "acceptable_answers": accepts,
            "requires_free_text_judging": False,
        })
    return {
        "unit_id": f"crossword{int(num):02d}",
        "display_number": f"תשבץ {num}",
        "narrative_context": None,
        "prompt": None,
        "question_type": "mini_crossword",
        "answer_style": "single_correct",
        "options": None,
        "correct_option": None,
        "subquestions": subquestions,
        "primary_sources": [{**r, "quoted_text": None, "scope": "whole_unit"} for r in all_refs],
        "scoring": {"points": None},
        "acceptable_answers": [],
        "media_attachments": None,
        "localizations": None,
        "format_confidence_note": None,
    }


def _parse_zemed_unit(num: str, theme: str, body: list[str], track: str | None) -> dict:
    """צמד N: theme -> a small set of short open questions (each: clue + answer + source)."""
    items = _split_containers(body, _NUM_ITEM_RE)
    subquestions = []
    all_refs: list[dict] = []
    for m, item_body in items:
        item_num = m.group(1)
        pre = [m.group(2)]
        ans_line = None
        post: list[str] = []
        seen_answer = False
        for l in item_body:
            am = _ANSWER_SINGLE_RE.match(l)
            if am and not seen_answer:
                ans_line, seen_answer = am.group(1), True
                continue
            (post if seen_answer else pre).append(l)
        clue_text = " ".join(x.strip() for x in pre if x.strip())
        answer, alternates, _note = _split_alternates(ans_line or "")
        refs, _ = _collect_sources(post)
        all_refs.extend(refs)
        accepts = [{"answer_text": _clean(answer), "source_refs": refs, "is_primary": True}] if answer else []
        for alt in alternates:
            accepts.append({"answer_text": _clean(alt), "source_refs": [], "is_primary": False})
        subquestions.append({
            "subquestion_id": item_num,
            "label": item_num,
            "prompt": _clean_inline(clue_text, refs),
            "points": None,
            "acceptable_answers": accepts,
            "requires_free_text_judging": True,
        })
    return {
        "unit_id": f"pair{int(num):02d}",
        "display_number": f"צמד {num}" + (f": {theme}" if theme else ""),
        "narrative_context": _clean(theme) or None,
        "prompt": None,
        "question_type": "composite",
        "answer_style": "free_text_model_answer",
        "options": None,
        "correct_option": None,
        "subquestions": subquestions,
        "primary_sources": [{**r, "quoted_text": None, "scope": "whole_unit"} for r in all_refs],
        "scoring": {"points": None},
        "acceptable_answers": [],
        "media_attachments": None,
        "localizations": None,
        "format_confidence_note": None,
    }


def _parse_block(subtype: str, track: str | None, lines: list[str]) -> list[dict]:
    units: list[dict] = []
    if subtype == "crossword":
        for m, body in _split_containers(lines, _CROSSWORD_RE):
            unit = _parse_crossword_unit(m.group(1), body, track)
            if unit["subquestions"]:
                units.append(unit)
    elif subtype == "head-to-head":
        for m, body in _split_containers(lines, _ZEMED_RE):
            unit = _parse_zemed_unit(m.group(1), m.group(2).strip(), body, track)
            if unit["subquestions"]:
                units.append(unit)
    else:  # live-rounds / poetry
        for m, body in _split_containers(lines, _Q_RE):
            unit = _parse_poetry_unit(m.group(1), body, track)
            if unit["subquestions"]:
                units.append(unit)
    return units


# --------------------------------------------------------------------------- #
# Live-stage rules (best effort, from the תקנון prose)
# --------------------------------------------------------------------------- #
def _live_rules_for(stage_letter: str, full_text: str) -> dict | None:
    """Best-effort points/time/hint-decay for a stage, scanned from the תקנון."""
    text = strip_niqqud(full_text)
    rules: dict = {}
    # Points per correct answer: "ב-5 נקודות".
    mp = re.search(r"ב[-־]?\s*(\d+)\s+נקודות", text)
    if mp:
        rules["points_per_correct"] = int(mp.group(1))
    # Hint decay: "כל רמז ... יגרע ... 2 נקודות".
    mh = re.search(r"רמז[^.]{0,40}?(\d+)\s+נקודות", text)
    if mh:
        rules["points_decay_per_hint"] = int(mh.group(1))
    # Time limit: "45 שניות" / "2 דקות".
    mt = re.search(r"(\d+)\s+שניות", text)
    if mt:
        rules["time_limit_seconds"] = int(mt.group(1))
    return rules or None


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def parse_public_sections(pages: list[str]) -> tuple[list[dict], dict]:
    """Parse the public/oral booklet into schema ``sections[]``.

    Returns (sections, info) where info carries {'unit_count', 'stage_count'}.
    """
    lines: list[str] = []
    for pg in pages:
        lines.extend(pg.splitlines())

    full_text = "\n".join(pages)
    stages = _segment(lines)

    sections: list[dict] = []
    total_units = 0
    seen_letters: list[str] = []
    for st in stages:
        if st["letter"] not in seen_letters:
            seen_letters.append(st["letter"])
        rules = _live_rules_for(st["letter"], full_text)
        for blk in st["blocks"]:
            units = _parse_block(st["subtype"], blk["track"], blk["lines"])
            if not units:
                continue
            total_units += len(units)
            track_he = _track_label(blk["track"])
            title = f"שלב {st['letter']} - {st['name']}".strip(" -")
            if track_he:
                title = f"{title} ({track_he})"
            sections.append({
                "section_id": f"stage_{st['letter']}_{blk['track'] or 'all'}",
                "section_title": title,
                "section_epigraph": None,
                "stage_subtype": st["subtype"],
                "track": blk["track"],
                "live_stage_rules": rules,
                "question_units": units,
            })

    return sections, {"unit_count": total_units, "stage_count": len(seen_letters)}


# --------------------------------------------------------------------------- #
# Questionnaire envelope (parallel to extract.build_questionnaire for MC)
# --------------------------------------------------------------------------- #
def _count_answered(sections: list[dict]) -> tuple[int, int]:
    """Return (subquestions_total, subquestions_with_an_answer)."""
    total = answered = 0
    for s in sections:
        for u in s["question_units"]:
            for sq in u.get("subquestions") or []:
                total += 1
                if any(a.get("answer_text") for a in sq.get("acceptable_answers", [])):
                    answered += 1
    return total, answered


def build_public_questionnaire(base: str, source_url: str, pages: list[str],
                               meta: dict) -> tuple[dict, str, str | None]:
    """Assemble a full questionnaire dict from the public/oral booklet.

    Returns (questionnaire, extraction_quality, notes), mirroring the shape of
    ``extract.build_questionnaire`` so ``process_file`` can treat both paths the
    same.
    """
    sections, info = parse_public_sections(pages)
    page_meta = parse_metadata_page(pages[0]) if pages else {}

    year = meta.get("year_civil")
    is_tiered = any(s.get("live_stage_rules") for s in sections)
    metadata = {
        "contest_year_civil": year,
        "contest_year_hebrew": HEBREW_YEARS.get(year),
        "track": meta.get("track"),
        "stage": meta.get("stage"),
        "sitting": None,
        "age_group": meta.get("age_group"),
        "annual_theme": None,
        "credits": page_meta.get("credits", {
            "program_supervisor": None, "quiz_coordinator": None,
            "question_authors": [], "editor": None, "committee_members": [],
        }),
        "syllabus": [],
        "time_limit_minutes": page_meta.get("time_limit_minutes"),
        "instructions_text": page_meta.get("instructions_text"),
        "source_text_edition": None,
        "scoring_summary": {
            "points_per_question": None,
            "max_points": None,
            "scoring_is_tiered": is_tiered,
        },
    }

    questionnaire = {
        "questionnaire_id": base,
        "source_url": source_url,
        "metadata": metadata,
        "sections": sections,
        "answer_key_present": info["unit_count"] > 0,
        "answer_key_location": "same_document",
        "import_provenance": {
            "fetched_from": source_url,
            "fetch_date": TODAY,
            "extraction_quality": "clean",
        },
    }

    total, answered = _count_answered(sections)
    notes_bits: list[str] = []
    if info["unit_count"] == 0:
        quality = "manual_review_needed"
        notes_bits.append("no public question units parsed")
    elif total and answered / total < 0.6:
        quality = "partial"
        notes_bits.append(f"only {answered}/{total} sub-questions have an answer")
    else:
        quality = "clean"
    notes_bits.append(
        f"public/oral format: {len(sections)} sections, {info['unit_count']} units, "
        f"{info['stage_count']} stages"
    )

    questionnaire["import_provenance"]["extraction_quality"] = quality
    notes = "; ".join(notes_bits)
    questionnaire["import_provenance"]["extraction_notes"] = notes
    return questionnaire, quality, notes
