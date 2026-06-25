#!/usr/bin/env python3
"""
Bible Contest (Chidon HaTanach) extraction pipeline.

Downloads official Ministry of Education questionnaires, parses them, and writes
structured JSON conforming to the schema demonstrated in docs/beitsifri_mm2026.json.

Usage:
    python extract.py --all                 # extract all discovered files (skip existing)
    python extract.py --file beitsifri_mm2026
    python extract.py --all --force         # re-extract even if JSON exists
    python extract.py --manifest-only       # regenerate manifest.json only
    python extract.py --all --dry-run       # list what would be processed

See docs/json_extraction_prompt.md and docs/bible_contest_taxonomy.md for context.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import datetime
import unicodedata
import urllib.parse
from pathlib import Path

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content"
QUIZ_DIR = CONTENT_DIR / "quizzes"
MANIFEST_PATH = CONTENT_DIR / "manifest.json"
LOG_DIR = ROOT / "logs"
TMP_DIR = ROOT / ".tmp"

ARCHIVE_PAGES = [
    ("youth", "https://bible-contest.education.gov.il/youth/old-questionnaire/"),
    ("adult", "https://bible-contest.education.gov.il/adult/questionnaires/"),
]
FILE_BASE = "https://meyda.education.gov.il/files/bible-contest/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; chidon-hatanach-data/1.0)"}

SCHEMA_VERSION = "1.0"
TODAY = datetime.date.today().isoformat()

HEBREW_YEARS = {
    2026: 'תשפ"ו', 2025: 'תשפ"ה', 2024: 'תשפ"ד', 2023: 'תשפ"ג',
    2022: 'תשפ"ב', 2021: 'תשפ"א', 2020: 'תש"פ',  2019: 'תשע"ט',
    2018: 'תשע"ח', 2017: 'תשע"ז', 2016: 'תשע"ו', 2015: 'תשע"ה',
    2014: 'תשע"ד', 2013: 'תשע"ג', 2012: 'תשע"ב', 2011: 'תשע"א',
    2010: 'תש"ע',  2009: 'תשס"ט', 2008: 'תשס"ח',
}

# Stage tokens (substring, lowercased) -> stage. Hebrew transliterations plus
# English synonyms, since filenames are inconsistent.
STAGE_TOKENS = [
    ("beitsifri", "school"), ("school", "school"),
    ("mehozi", "district"), ("mehoz", "district"), ("mahoz", "district"),
    ("district", "district"), ("regional", "district"),
    ("artzi", "national"), ("arzi", "national"), ("national", "national"),
    ("olami", "world"), ("olam", "world"), ("world", "world"), ("internat", "world"),
]
# Track markers, matched on word boundaries (_ - / start / end / digit). The
# *dati* markers MUST be tested before "mm", because "mmd"/"mamad" contain "mm"
# and a mamlachti_dati file would otherwise be misread as mamlachti.
TRACK_DATI_TOKENS = ["mamlachti_dati", "mamlachtidati", "mmldati", "mmd", "mamad", "dati", "md"]
TRACK_MAM_TOKENS = ["mamlachti", "mamlchti", "mmlchti", "mlchti", "mm"]

# Explicit per-id overrides for filenames that cannot be decoded reliably
# (no stream marker, or stage encoded only in adult/preliminary naming). These
# take priority over token decoding. Track defaults to mamlachti for adult
# (general) contests, which are not split by religious stream.
ID_OVERRIDES = {
    "artziktav2016":                  {"track": "mamlachti", "stage": "national"},
    "mehozipumbi2016":                {"track": "mamlachti", "stage": "district", "age_group": "adult"},
    "PreMm25":                        {"track": "mamlachti", "stage": "national", "year_civil": 2025},
    "pre_adults_district_quiz":       {"track": "mamlachti", "stage": "district", "age_group": "adult"},
    "adults_district_quiz33":         {"track": "mamlachti", "stage": "district", "age_group": "adult"},
    "adults_international_bible_quiz": {"track": "mamlachti", "stage": "world", "age_group": "adult"},
    "internataionaladultswritten2020": {"track": "mamlachti", "stage": "world", "year_civil": 2020, "age_group": "adult"},
    "adults_2020":                    {"track": "mamlachti", "stage": "national", "year_civil": 2020, "age_group": "adult"},
    "adults_quiz_2022":               {"track": "mamlachti", "stage": "world", "year_civil": 2022, "age_group": "adult"},
}

# Confirmed unreadable in prior research (image-based PDFs). Marked immediately.
KNOWN_UNREADABLE = {"OLAMI_PUB_MMD", "ARTZI_PUB_MM"}

OPTION_KEYS = ["א", "ב", "ג", "ד", "ה"]

# Hebrew Bible book names, longest first so multi-word names match greedily.
BIBLE_BOOKS = sorted([
    "בראשית", "שמות", "ויקרא", "במדבר", "דברים",
    "יהושע", "שופטים", "שמואל א", "שמואל ב", "מלכים א", "מלכים ב",
    "ישעיהו", "ירמיהו", "יחזקאל",
    "הושע", "יואל", "עמוס", "עובדיה", "יונה", "מיכה", "נחום",
    "חבקוק", "צפניה", "חגי", "זכריה", "מלאכי",
    "תהילים", "תהלים", "משלי", "איוב",
    "שיר השירים", "רות", "איכה", "קהלת", "אסתר", "דניאל",
    "עזרא", "נחמיה", "דברי הימים א", "דברי הימים ב",
], key=len, reverse=True)

REPLACEMENT_CHAR = "�"

# Hebrew book name -> Sefaria canonical English name (for verse-text lookup).
SEFARIA_BOOKS = {
    "בראשית": "Genesis", "שמות": "Exodus", "ויקרא": "Leviticus", "במדבר": "Numbers",
    "דברים": "Deuteronomy", "יהושע": "Joshua", "שופטים": "Judges",
    "שמואל א": "I Samuel", "שמואל ב": "II Samuel", "מלכים א": "I Kings", "מלכים ב": "II Kings",
    "ישעיהו": "Isaiah", "ירמיהו": "Jeremiah", "יחזקאל": "Ezekiel",
    "הושע": "Hosea", "יואל": "Joel", "עמוס": "Amos", "עובדיה": "Obadiah", "יונה": "Jonah",
    "מיכה": "Micah", "נחום": "Nahum", "חבקוק": "Habakkuk", "צפניה": "Zephaniah", "חגי": "Haggai",
    "זכריה": "Zechariah", "מלאכי": "Malachi", "תהילים": "Psalms", "תהלים": "Psalms",
    "משלי": "Proverbs", "איוב": "Job", "שיר השירים": "Song of Songs", "רות": "Ruth",
    "איכה": "Lamentations", "קהלת": "Ecclesiastes", "אסתר": "Esther", "דניאל": "Daniel",
    "עזרא": "Ezra", "נחמיה": "Nehemiah", "דברי הימים א": "I Chronicles", "דברי הימים ב": "II Chronicles",
}

_GEMATRIA = {
    "א": 1, "ב": 2, "ג": 3, "ד": 4, "ה": 5, "ו": 6, "ז": 7, "ח": 8, "ט": 9,
    "י": 10, "כ": 20, "ל": 30, "מ": 40, "נ": 50, "ס": 60, "ע": 70, "פ": 80, "צ": 90,
    "ק": 100, "ר": 200, "ש": 300, "ת": 400,
    "ך": 20, "ם": 40, "ן": 50, "ף": 80, "ץ": 90,
}


def gematria(s: str) -> int:
    return sum(_GEMATRIA.get(c, 0) for c in (s or ""))


# --------------------------------------------------------------------------- #
# Text extraction (handles Hebrew RTL de-reversal)
# --------------------------------------------------------------------------- #
_DIGIT_RUN = re.compile(r"\d+")


def _is_hebrew_mark(ch: str) -> bool:
    """Hebrew combining points & cantillation marks (U+0591–U+05C7)."""
    return "֑" <= ch <= "ׇ"


def _delogicalize(line: str) -> str:
    """pdfplumber returns Hebrew lines in visual (reversed) order.

    A naive full-line reverse restores consonant order but flips every
    [base][marks] cluster into [marks][base] -- detaching niqqud from its
    letter. So we reverse *cluster* order, keeping each base letter together
    with its trailing combining marks, then flip multi-digit runs back, then
    NFC-normalize.
    """
    clusters: list[str] = []
    i, n = 0, len(line)
    while i < n:
        if line[i].isspace():
            clusters.append(line[i])
            i += 1
            continue
        j = i + 1
        while j < n and _is_hebrew_mark(line[j]):
            j += 1
        clusters.append(line[i:j])
        i = j
    rev = "".join(reversed(clusters))
    rev = _DIGIT_RUN.sub(lambda m: m.group(0)[::-1], rev)
    return unicodedata.normalize("NFC", rev)


# A *detached* mark is one not preceded by its base letter: at string start or
# right after whitespace. A correctly-placed mark is always preceded by a letter,
# so anchoring on (^|\s) avoids touching good text.
_DETACHED_MARK = re.compile(r"(^|\s)([֑-ׇ]+)\s*([א-ת])")
_SPACE_THEN_MARK = re.compile(r"\s[֑-ׇ]")
# A lone vocalized fragment: exactly one Hebrew base letter + niqqud, as a whole
# token (allowing surrounding punctuation such as an opening quote). A single
# vocalized letter is never a standalone Hebrew word (prefixes attach to the next
# word), so such a token is a spurious intra-word break.
_LONE_VOCALIZED = re.compile(r"^[^א-ת]*[א-ת][֑-ׇ]+[^א-ת]*$")


def _join_lone_fragments(s: str) -> str:
    """Reattach spurious intra-word breaks where vocalized words were split into
    single-letter fragments, e.g. 'וְ הִ נְ נִי אֹ מֵר' -> 'וְהִנְנִי אֹמֵר'.

    A token is merged onto the previous token iff the previous token was a lone
    vocalized single letter. Genuine words (>=2 letters, or unvocalized) start a
    fresh token, so real word boundaries are preserved.
    """
    out: list[str] = []
    attach = False
    for tok in s.split(" "):
        if not tok:
            continue
        if attach and out:
            out[-1] += tok
        else:
            out.append(tok)
        attach = bool(_LONE_VOCALIZED.match(tok))
    return " ".join(out)


def repair_hebrew_pdf_text(text: str | None) -> str | None:
    """Deterministically repair Hebrew text damaged by PDF extraction.

    Conservative and safe:
      * NFC normalize.
      * Reattach only *detached* combining marks -- those at a word/string start
        (after a space or the beginning), which cannot be correct since no word
        starts with a mark. " ֵּה" -> " הֵּ". The leading space is preserved, so
        real word boundaries are never merged. Correctly-placed marks (preceded
        by their letter) are untouched.
      * Rejoin words split into lone single-letter vocalized fragments
        (see _join_lone_fragments) -- never merges genuine multi-letter words.
      * Collapse runs of whitespace.

    Font-lost final letters (`�`) are NOT recovered here, and rarer multi-letter
    fragment splits may remain (flagged by audit_hebrew); fully-correct verse
    text comes from Sefaria enrichment where a reference exists.
    """
    if not text:
        return text
    s = unicodedata.normalize("NFKC", text)  # NFKC folds presentation forms (ﬠ->ע)
    s = re.sub(r"[{(\[][ספ][}\)\]]", "", s)  # {ס}/{פ} paragraph markers from source text
    prev = None
    while prev != s:  # repeat for chained detached clusters
        prev = s
        s = _DETACHED_MARK.sub(r"\1\3\2", s)
    s = re.sub(r"[ \t]{2,}", " ", s).strip()
    s = _join_lone_fragments(s)
    return unicodedata.normalize("NFC", s)


def audit_hebrew(obj, path: str = "") -> list[tuple[str, str]]:
    """Walk a questionnaire dict and return (json_path, snippet) for any string
    still showing a detached combining mark (space + mark) or the lost-char `�`.
    """
    found: list[tuple[str, str]] = []
    if isinstance(obj, str):
        if _SPACE_THEN_MARK.search(obj) or REPLACEMENT_CHAR in obj:
            found.append((path, obj[:60]))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found.extend(audit_hebrew(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(audit_hebrew(v, f"{path}[{i}]"))
    return found


def extract_pdf_pages(path: Path) -> list[str]:
    """Return one logical-order text string per page using pdfplumber."""
    import pdfplumber

    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for pg in pdf.pages:
            raw = pg.extract_text() or ""
            lines = [_delogicalize(ln) for ln in raw.splitlines()]
            pages.append("\n".join(lines))
    return pages


def extract_pdf_text_fallback(path: Path) -> str:
    """PyMuPDF fallback -- used only to confirm a PDF is genuinely empty."""
    try:
        import fitz
    except ImportError:
        return ""
    doc = fitz.open(str(path))
    return "\n".join(pg.get_text("text") for pg in doc)


def extract_docx_text(path: Path) -> list[str]:
    import docx

    d = docx.Document(str(path))
    return ["\n".join(p.text for p in d.paragraphs)]


def extract_doc_text(path: Path) -> list[str]:
    """Best-effort for old binary .doc via mammoth (works on .docx; .doc often fails)."""
    try:
        import mammoth

        with open(path, "rb") as fh:
            result = mammoth.extract_raw_text(fh)
        return [result.value]
    except Exception:
        return [""]


def hebrew_char_count(text: str) -> int:
    return sum(1 for c in text if "֐" <= c <= "ת")


# --------------------------------------------------------------------------- #
# Filename / metadata decoding
# --------------------------------------------------------------------------- #
def _match_track_token(low: str, tok: str) -> bool:
    """Match a track marker on a word boundary (_ - / start / end / digit)."""
    return re.search(rf"(?:^|[_\-]){re.escape(tok)}(?:$|[_\-]|\d)", low) is not None


def decode_filename(base: str) -> dict:
    """Best-effort decode of metadata from a source filename base.

    Modern series follow {stage}_{track}{year}; many older files do not, so
    every field is optional and unknowns are left as None. Explicit per-id
    overrides (ID_OVERRIDES) win over token decoding.
    """
    low = base.lower()
    meta = {"stage": None, "track": None, "year_civil": None, "age_group": None}

    for tok, stage in STAGE_TOKENS:
        if tok in low:
            meta["stage"] = stage
            break

    # dati markers first, so "mmd"/"mamad" are not read as plain "mm"
    for tok in TRACK_DATI_TOKENS:
        if _match_track_token(low, tok):
            meta["track"] = "mamlachti_dati"
            break
    if meta["track"] is None:
        for tok in TRACK_MAM_TOKENS:
            if _match_track_token(low, tok):
                meta["track"] = "mamlachti"
                break

    year = re.search(r"(20\d{2})", base)
    if year:
        meta["year_civil"] = int(year.group(1))

    if any(k in low for k in ("adult", "adults", "mehozipumbi", "writing_adults")):
        meta["age_group"] = "adult"
    elif meta["stage"]:
        meta["age_group"] = "youth"

    meta.update(ID_OVERRIDES.get(base, {}))  # explicit overrides win
    return meta


# --------------------------------------------------------------------------- #
# Source reference parsing
# --------------------------------------------------------------------------- #
def parse_source_refs(text: str) -> list[dict]:
    """Parse a Hebrew source string like 'שמות יד, כא; טו, כה; במדבר כ, יא'.

    Returns list of {book, chapter, verse}. A '; chap, verse' segment without a
    book name reuses the previous book.
    """
    refs: list[dict] = []
    current_book = None
    for seg in re.split(r"[;]", text):
        seg = seg.strip().strip(".")
        if not seg:
            continue
        book = None
        for b in BIBLE_BOOKS:
            if seg.startswith(b):
                book = b
                seg = seg[len(b):].strip()
                break
        if book:
            current_book = book
        if current_book is None:
            continue
        # remaining seg: "chapter, verse"  (verse may be a range 'כה-כו')
        m = re.match(r"^([א-ת]+)\s*,\s*([א-ת\-]+)", seg)
        if m:
            refs.append({"book": current_book, "chapter": m.group(1), "verse": m.group(2)})
        elif seg and re.match(r"^[א-ת]", seg):
            # chapter only
            refs.append({"book": current_book, "chapter": seg.split()[0], "verse": None})
    return refs


# --------------------------------------------------------------------------- #
# Verse-text enrichment via Sefaria (vocalized text by reference)
# --------------------------------------------------------------------------- #
# Vocalized verse text in the source PDFs is corrupted at the font level, so we
# fetch clean niqqud text from Sefaria using the extracted book/chapter/verse.
# Strip cantillation/te'amim (U+0591-05AF) + meteg/rafe/paseq/sof-pasuk markers,
# but KEEP niqqud (U+05B0-05BC, 05C1, 05C2, 05C7), maqaf, and the letters.
_CANTILLATION = re.compile("[\u0591-\u05af\u05bd\u05bf\u05c0\u05c3\u05c4\u05c5\u05c6]")
_TAGS = re.compile(r"<[^>]+>")
_VERSE_CACHE: dict[str, str | None] = {}
_VERSE_CACHE_FILE = TMP_DIR / "sefaria_cache.json"


def _load_verse_cache() -> None:
    if _VERSE_CACHE_FILE.exists():
        try:
            _VERSE_CACHE.update(json.loads(_VERSE_CACHE_FILE.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass


def _save_verse_cache() -> None:
    try:
        TMP_DIR.mkdir(exist_ok=True)
        _VERSE_CACHE_FILE.write_text(json.dumps(_VERSE_CACHE, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _clean_verse(he) -> str:
    if isinstance(he, list):
        he = " ".join(x if isinstance(x, str) else " ".join(x) for x in he)
    he = _TAGS.sub("", he or "")
    he = html.unescape(he)               # &nbsp; &thinsp; etc.
    he = re.sub(r"[{(\[][סספ]?[}\)\]]", "", he)  # {ס}/{פ}/() section markers
    he = he.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    he = _CANTILLATION.sub("", he)       # drop cantillation/te'amim, keep niqqud
    he = he.replace("־", " ")            # maqaf -> space, matching the pilot convention
    return re.sub(r"\s+", " ", he).strip()


def _sefaria_ref(book_he: str, chapter_he: str, verse_he: str | None) -> str | None:
    book = SEFARIA_BOOKS.get((book_he or "").strip())
    ch = gematria(chapter_he)
    if not book or not ch:
        return None
    ref = f"{book} {ch}"
    if verse_he:
        parts = re.split(r"[-־]", verse_he)
        v1 = gematria(parts[0])
        if v1:
            ref += f":{v1}"
            if len(parts) > 1 and gematria(parts[1]):
                ref += f"-{gematria(parts[1])}"
    return ref


def fetch_verse_text(refs: list[dict]) -> str | None:
    """Return clean vocalized text for the given references, or None on failure."""
    parts = []
    for r in refs:
        sref = _sefaria_ref(r.get("book"), r.get("chapter"), r.get("verse"))
        if not sref:
            return None
        if sref not in _VERSE_CACHE:
            try:
                url = f"https://www.sefaria.org/api/v3/texts/{urllib.parse.quote(sref)}?version=hebrew"
                d = json.loads(http_get(url))
                he = d["versions"][0]["text"] if d.get("versions") else d.get("he")
                _VERSE_CACHE[sref] = _clean_verse(he) or None
            except Exception:  # noqa: BLE001
                _VERSE_CACHE[sref] = None
        txt = _VERSE_CACHE[sref]
        if not txt:
            return None
        parts.append(txt)
    return " ".join(parts) if parts else None


# --- Faithful alignment: clean the quoted words only, never add elided words --- #
_ELLIPSIS_RE = re.compile(r"\s*(?:…|\.\s*\.\s*\.+|\.{2,})\s*")
_HEB_LETTER_RE = re.compile(r"[א-ת]")
_FINAL_FORMS = str.maketrans("ךםןףץ", "כמנפצ")


def _is_divine_abbrev(word: str) -> bool:
    return unicodedata.normalize("NFKC", word).strip("\"“”.,()[]") in {"ה'", "ה׳", "ה’", "יי"}


def _consonants(word: str, fold_finals: bool = True) -> str:
    w = unicodedata.normalize("NFKC", word)            # fold presentation forms (ﬠ->ע)
    w = "".join(c for c in w if "א" <= c <= "ת")        # keep Hebrew letters only
    return w.translate(_FINAL_FORMS) if fold_finals else w


def _segment_stream(seg: str) -> str:
    """Consonant skeleton of an exam quote segment (divine name -> יהוה)."""
    out = []
    for w in seg.split():
        if _is_divine_abbrev(w):
            out.append("יהוה")
        elif _HEB_LETTER_RE.search(w):
            out.append(_consonants(w))
    return "".join(out)


def _greedy_from(needle: str, hay: str, start: int) -> tuple[int, int] | None:
    """Subsequence match of `needle` in `hay` beginning exactly at `start`."""
    if start >= len(hay) or hay[start] != needle[0]:
        return None
    i = start
    for ch in needle:
        pos = hay.find(ch, i)
        if pos == -1:
            return None
        i = pos + 1
    return (start, i)


def _best_span(needle: str, hay: str, cursor: int) -> tuple[int, int] | None:
    """Find the *tightest* subsequence match of `needle` in `hay` (the quote sits
    near-contiguously in the verse), preferring matches at/after `cursor`. This
    avoids matching scattered characters earlier in the verse.
    """
    best = None
    max_span = len(needle) * 2 + 6
    for p in range(len(hay)):
        if hay[p] != needle[0]:
            continue
        span = _greedy_from(needle, hay, p)
        if span is None:
            continue
        length = span[1] - span[0]
        if length > max_span:
            continue
        key = (0 if p >= cursor else 1, length, p)  # after cursor, then tightest, then earliest
        if best is None or key < best[0]:
            best = (key, span)
    return best[1] if best else None


def align_quote_to_sefaria(exam_quote: str | None, refs: list[dict]) -> str | None:
    """Return clean vocalized text containing ONLY the words actually quoted in
    the exam (ellipsis preserved), sourced from Sefaria, or None if it can't be
    matched confidently. Never adds elided words.
    """
    if not exam_quote:
        return None
    sef = fetch_verse_text(refs)
    if not sef:
        return None
    sef_words = sef.split()
    stream_chars, pos2word = [], []
    for wi, w in enumerate(sef_words):
        for c in _consonants(w):
            stream_chars.append(c)
            pos2word.append(wi)
    sef_stream = "".join(stream_chars)
    if not sef_stream:
        return None

    out_segments = []
    cursor = 0
    for seg in _ELLIPSIS_RE.split(exam_quote):
        ex_stream = _segment_stream(seg)
        if len(ex_stream) < 4:          # too short to align reliably
            continue
        span = _best_span(ex_stream, sef_stream, cursor)
        if span is None:
            return None
        s, e = span
        w0, w1 = pos2word[s], pos2word[e - 1]
        # faithfulness guard: don't pull in un-quoted words the exam skipped
        # without an ellipsis (allow a small slack for words merged by lost chars)
        exam_word_count = sum(1 for w in seg.split() if _HEB_LETTER_RE.search(w))
        if (w1 - w0 + 1) > exam_word_count + 2:
            return None
        seg_has_divine = any(_is_divine_abbrev(w) for w in seg.split())
        words = []
        for w in sef_words[w0:w1 + 1]:
            if seg_has_divine and _consonants(w) == "יהוה":
                words.append("ה'")     # preserve the exam's abbreviation of the Name
            else:
                words.append(w)
        out_segments.append(" ".join(words))
        cursor = e
    if not out_segments:
        return None
    return " … ".join(out_segments)


# --------------------------------------------------------------------------- #
# Question-type classification (heuristic)
# --------------------------------------------------------------------------- #
def classify_question(prompt: str, options: list[dict]) -> str:
    opt_texts = [o["text"].strip() for o in options]
    if opt_texts and all(re.fullmatch(r"\d+", t) for t in opt_texts):
        return "numeric"
    if re.search(r"(על מי נאמר|על מה נאמר|מי אמר|למי נאמר|מי אמרו|בדברי מי)", prompt):
        return "speaker_id"
    if re.search(r"(^|\s)לא(\s|$)", prompt) and re.match(r"^(איזה|אילו|מה|מי)\b", prompt):
        return "negative_exclusion"
    return "multiple_choice"


NIQQUD = re.compile(r"[֑-ׇ]")  # Hebrew points & cantillation marks


def strip_niqqud(s: str) -> str:
    return NIQQUD.sub("", s)


def _is_vocalized_word(w: str) -> bool:
    return bool(NIQQUD.search(w) or REPLACEMENT_CHAR in w)


def _clean_question_text(q: str) -> str:
    q = re.sub(r"\s{2,}", " ", q.strip())
    q = re.sub(r'[\s:"“”׳״,\-]*\?+\s*$', "", q)   # drop a trailing '?' and any junk before it
    q = re.sub(r'[\s:"“”׳״,\-]+$', "", q).strip()  # drop trailing colon/quote/punct
    if q:
        q += "?"
    return q


def split_narrative(prompt: str) -> tuple[str | None, str]:
    """Lift an embedded *verse quote* out of the prompt into narrative_context.

    A verse is recognised conservatively, to avoid pulling out an incidental
    vocalized word that is really part of the question:
      1. a quotation-mark-delimited span containing >=2 vocalized words, else
      2. a run of >=3 consecutive vocalized words.
    The quoted text (including any ellipsis) is preserved verbatim; clean,
    quote-faithful verse text is produced later by Sefaria alignment.
    Returns (narrative_context_or_None, cleaned_question_prompt).
    """
    # 1) quotation-delimited vocalized span (prefer the longest)
    best = None
    for qm in re.finditer(r'"([^"]+)"', prompt):
        span = qm.group(1)
        if sum(_is_vocalized_word(w) for w in span.split()) >= 2:
            if best is None or len(span) > len(best.group(1)):
                best = qm
    if best:
        verse = best.group(1).strip().strip("“”").strip()
        question = _clean_question_text(prompt[:best.start()] + " " + prompt[best.end():])
        return (verse or None), (question or prompt.strip())

    # 2) a run of >=3 consecutive vocalized words
    words = prompt.split()
    voc = [_is_vocalized_word(w) for w in words]
    best_run = (0, 0)
    i = 0
    while i < len(words):
        if voc[i]:
            j = i
            while j < len(words) and voc[j]:
                j += 1
            if (j - i) > (best_run[1] - best_run[0]):
                best_run = (i, j)
            i = j
        else:
            i += 1
    a, b = best_run
    if b - a >= 3:
        verse = " ".join(words[a:b]).strip('"“”').strip()
        question = _clean_question_text(" ".join(words[:a] + words[b:]))
        return (verse or None), (question or prompt.strip())

    return None, prompt.strip()


# --------------------------------------------------------------------------- #
# Format 1 parser: school / written multiple-choice questionnaires
# --------------------------------------------------------------------------- #
OPT_RE = re.compile(r"^([א-ה])\.\s*(.*)$")
QNUM_RE = re.compile(r"^(\d+)\.\s+(.*)$")


def parse_questions(question_lines: list[str]) -> list[dict]:
    """Parse the question body into raw units: number, prompt, options."""
    units: list[dict] = []
    cur: dict | None = None
    expecting = 1
    for ln in question_lines:
        ln = ln.strip()
        if not ln or set(ln) <= {"_"}:
            continue
        qm = QNUM_RE.match(ln)
        om = OPT_RE.match(ln)
        if qm and int(qm.group(1)) == expecting and not (cur and len(cur["options"]) < 2):
            if cur:
                units.append(cur)
            cur = {"number": int(qm.group(1)), "prompt": qm.group(2).strip(), "options": []}
            expecting += 1
        elif om and cur is not None:
            cur["options"].append({"key": om.group(1), "text": om.group(2).strip()})
        elif cur is not None:
            if cur["options"]:
                cur["options"][-1]["text"] += " " + ln
            else:
                cur["prompt"] += " " + ln
    if cur:
        units.append(cur)
    return units


def parse_answer_key(answer_lines: list[str]) -> dict[int, dict]:
    """Parse the answer-key table into {qnum: {correct_option, refs:[...]}}.

    Linearized layout per question is roughly:
        <option_letter>. <answer text>
        <qnum> <source>            (qnum sometimes alone, sources may span lines)
    """
    answers: dict[int, dict] = {}
    blocks: list[dict] = []
    cur: dict | None = None
    for ln in answer_lines:
        ln = ln.strip()
        if not ln:
            continue
        om = OPT_RE.match(ln)
        if om:
            cur = {"correct_option": om.group(1), "answer_text": om.group(2).strip(), "src_lines": []}
            blocks.append(cur)
        elif cur is not None:
            cur["src_lines"].append(ln)

    for blk in blocks:
        qnum = None
        src_text_parts = []
        for sl in blk["src_lines"]:
            m = re.match(r"^(\d+)\s*(.*)$", sl)
            if m and qnum is None:
                qnum = int(m.group(1))
                if m.group(2).strip():
                    src_text_parts.append(m.group(2).strip())
            else:
                src_text_parts.append(sl)
        if qnum is None:
            continue
        refs = parse_source_refs(" ; ".join(src_text_parts)) if src_text_parts else []
        answers[qnum] = {
            "correct_option": blk["correct_option"],
            "answer_text": blk["answer_text"],
            "refs": refs,
        }
    return answers


def extract_answer_tables(path: Path) -> dict[int, dict]:
    """Parse the answer-key table into {qnum: {correct_option, refs}} using
    pdfplumber's table extraction -- far more robust than linearized text.

    Columns are RTL ([מקור | תשובה | שאלה] = source | answer | question#).
    Multi-line cells come out in reversed physical order, so we reverse lines
    within each cell to restore reading order.
    """
    import pdfplumber

    answers: dict[int, dict] = {}
    col = {"source": 0, "answer": 1, "qnum": 2}
    with pdfplumber.open(str(path)) as pdf:
        for pg in pdf.pages:
            for tbl in pg.extract_tables() or []:
                for row in tbl:
                    cells = [_delogicalize(c) if c else "" for c in row]
                    if len(cells) < 3:
                        continue
                    joined = " ".join(cells)
                    if "מקור" in joined and "שאלה" in joined:  # header row
                        for i, c in enumerate(cells):
                            if "מקור" in c:
                                col["source"] = i
                            elif "שאלה" in c:
                                col["qnum"] = i
                            elif "תשובה" in c:
                                col["answer"] = i
                        continue
                    qcell = cells[col["qnum"]].strip()
                    if not re.fullmatch(r"\d+", qcell):
                        continue
                    qnum = int(qcell)

                    def rejoin(cell, sep):
                        lines = [ln for ln in cell.splitlines() if ln.strip()]
                        return sep.join(reversed(lines))

                    a_join = rejoin(cells[col["answer"]], " ")
                    s_join = rejoin(cells[col["source"]], " ; ")
                    mo = re.search(r"([א-ה])\.", a_join)
                    answers[qnum] = {
                        "correct_option": mo.group(1) if mo else None,
                        "refs": parse_source_refs(s_join),
                    }
    return answers


def find_answer_key_start(pages: list[str]) -> int | None:
    """Return index of the first page that is the answer key ('תשובון')."""
    for i, pg in enumerate(pages):
        head = "\n".join(pg.splitlines()[:3])
        if "תשובון" in head:
            return i
    return None


def parse_metadata_page(text: str) -> dict:
    """Extract what we can from the cover/instructions page."""
    md = {
        "time_limit_minutes": None,
        "instructions_text": None,
        "credits": {
            "program_supervisor": None, "quiz_coordinator": None,
            "question_authors": [], "editor": None, "committee_members": [],
        },
    }
    text = strip_niqqud(text)  # cover-page labels carry niqqud that breaks matching
    m = re.search(r"זמן הבחינה[:\s]*?(\d+)", text)
    if m:
        md["time_limit_minutes"] = int(m.group(1))

    def grab(label):
        mm = re.search(label + r"[:\s]+([א-ת\"' ]+?)(?:\n|$)", text)
        return mm.group(1).strip() if mm else None

    sup = grab(r"הממונה על חידוני התנ\"ך")
    coord = grab(r"מרכז החידון ועורך החידון")
    auth = grab(r"מחבר(?:י)? השאלות")
    if sup:
        md["credits"]["program_supervisor"] = sup
    if coord:
        md["credits"]["quiz_coordinator"] = coord
    if auth:
        # split on comma or a conjunction vav (space + ו prefix), not vav inside a word
        parts = re.split(r"\s*,\s*|\s+ו(?=[א-ת])", auth)
        md["credits"]["question_authors"] = [a.strip() for a in parts if a.strip()]
    return md


# --------------------------------------------------------------------------- #
# Build questionnaire object
# --------------------------------------------------------------------------- #
def build_questionnaire(base: str, source_url: str, pages: list[str], meta: dict,
                        answers: dict[int, dict] | None = None,
                        enrich: bool = True) -> tuple[dict, str, str | None]:
    """Returns (questionnaire_dict, extraction_quality, notes).

    `answers` is the parsed answer key (from extract_answer_tables); if None,
    we fall back to parsing the answer-key text pages. When `enrich` is set,
    corrupted vocalized verses are replaced with clean text fetched from Sefaria.
    """
    ak_start = find_answer_key_start(pages)
    q_pages = pages[1:ak_start] if ak_start else pages[1:]

    q_lines: list[str] = []
    for pg in q_pages:
        q_lines.extend(pg.splitlines())
    raw_units = parse_questions(q_lines)

    if not answers:
        a_lines: list[str] = []
        for pg in (pages[ak_start:] if ak_start else []):
            a_lines.extend(pg.splitlines())
        answers = parse_answer_key(a_lines) if a_lines else {}

    page_meta = parse_metadata_page(pages[0]) if pages else {}

    notes_bits: list[str] = []

    units = []
    for ru in raw_units:
        n = ru["number"]
        narrative, prompt = split_narrative(ru["prompt"])
        prompt = repair_hebrew_pdf_text(prompt)
        narrative = repair_hebrew_pdf_text(narrative)
        for o in ru["options"]:
            o["text"] = repair_hebrew_pdf_text(o["text"])
        qtype = classify_question(prompt, ru["options"])
        ak = answers.get(n, {})
        correct = ak.get("correct_option")
        refs = ak.get("refs", [])

        primary_sources = []
        if qtype == "negative_exclusion" and refs:
            wrong_keys = [o["key"] for o in ru["options"] if o["key"] != correct]
            for ref, key in zip(refs, wrong_keys):
                primary_sources.append({**ref, "quoted_text": None, "scope": f"answer_option:{key}"})
            acceptable_refs = []
        else:
            for ref in refs:
                primary_sources.append({**ref, "quoted_text": None, "scope": "whole_unit"})
            acceptable_refs = [{"book": r["book"], "chapter": r["chapter"], "verse": r["verse"]} for r in refs]

        correct_text = next((o["text"] for o in ru["options"] if o["key"] == correct), None)
        units.append({
            "unit_id": f"q{n:02d}",
            "display_number": str(n),
            "narrative_context": narrative,
            "prompt": prompt,
            "question_type": qtype,
            "answer_style": "single_correct",
            "options": ru["options"],
            "correct_option": correct,
            "subquestions": None,
            "primary_sources": primary_sources,
            "scoring": {"points": 1},
            "acceptable_answers": [{
                "answer_text": correct_text,
                "source_refs": acceptable_refs,
                "is_primary": True,
            }] if correct_text else [],
            "media_attachments": None,
            "localizations": None,
            "format_confidence_note": None,
        })

    # Clean the *quoted* verse words via Sefaria alignment -- faithful to the
    # exam (ellipsis preserved, no elided words added). Falls back to the
    # repaired exam text when alignment is not confident; never the full verse.
    enrich_failed = False
    if enrich:
        for u in units:
            if not u["narrative_context"]:
                continue
            whole = [{"book": s["book"], "chapter": s["chapter"], "verse": s["verse"]}
                     for s in u["primary_sources"] if s["scope"] == "whole_unit"]
            aligned = align_quote_to_sefaria(u["narrative_context"], whole) if whole else None
            if aligned:
                u["narrative_context"] = aligned
            elif REPLACEMENT_CHAR in u["narrative_context"] or _SPACE_THEN_MARK.search(u["narrative_context"]):
                enrich_failed = True
                u["format_confidence_note"] = "verse shown as extracted from the exam; Sefaria alignment unavailable"
        _save_verse_cache()

    year = meta.get("year_civil")
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
            "points_per_question": 1,
            "max_points": len(units),
            "scoring_is_tiered": False,
        },
    }

    questionnaire = {
        "questionnaire_id": base,
        "source_url": source_url,
        "metadata": metadata,
        "sections": [{
            "section_id": "main",
            "section_title": None,
            "section_epigraph": None,
            "stage_subtype": "written",
            "live_stage_rules": None,
            "question_units": units,
        }],
        "answer_key_present": bool(answers),
        "answer_key_location": "same_document" if answers else "none",
        "import_provenance": {
            "fetched_from": source_url,
            "fetch_date": TODAY,
            "extraction_quality": "clean",
        },
    }

    # Determine extraction quality.
    quality = "clean"
    missing_answers = [u["display_number"] for u in units if u["correct_option"] is None]
    garbled = any(REPLACEMENT_CHAR in (u.get("narrative_context") or "") for u in units)
    if not units:
        quality = "manual_review_needed"
        notes_bits.append("no question units parsed")
    elif missing_answers:
        quality = "partial"
        notes_bits.append(f"missing answers for: {', '.join(missing_answers)}")
    if garbled or enrich_failed:
        if quality == "clean":
            quality = "partial"
        notes_bits.append("some narrative verse text could not be enriched from Sefaria; best-effort retained")

    questionnaire["import_provenance"]["extraction_quality"] = quality
    notes = "; ".join(notes_bits) if notes_bits else None
    if notes:
        questionnaire["import_provenance"]["extraction_notes"] = notes
    return questionnaire, quality, notes


def stub_questionnaire(base: str, source_url: str, meta: dict, quality: str, notes: str) -> dict:
    year = meta.get("year_civil")
    return {
        "questionnaire_id": base,
        "source_url": source_url,
        "metadata": {
            "contest_year_civil": year,
            "contest_year_hebrew": HEBREW_YEARS.get(year),
            "track": meta.get("track"),
            "stage": meta.get("stage"),
            "sitting": None,
            "age_group": meta.get("age_group"),
            "annual_theme": None,
            "credits": {"program_supervisor": None, "quiz_coordinator": None,
                        "question_authors": [], "editor": None, "committee_members": []},
            "syllabus": [],
            "time_limit_minutes": None,
            "instructions_text": None,
            "source_text_edition": None,
            "scoring_summary": {"points_per_question": None, "max_points": None, "scoring_is_tiered": False},
        },
        "sections": [],
        "answer_key_present": False,
        "answer_key_location": "none",
        "import_provenance": {
            "fetched_from": source_url,
            "fetch_date": TODAY,
            "extraction_quality": quality,
            "extraction_notes": notes,
        },
    }


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate(q: dict) -> list[str]:
    fails = []
    md = q.get("metadata", {})
    if q.get("questionnaire_id") is None:
        fails.append("missing questionnaire_id")
    y = md.get("contest_year_civil")
    if y is not None and not (2008 <= y <= 2026):
        fails.append(f"year {y} out of range")
    if md.get("track") not in (None, "mamlachti", "mamlachti_dati"):
        fails.append(f"bad track {md.get('track')}")
    if md.get("stage") not in (None, "school", "district", "national", "world"):
        fails.append(f"bad stage {md.get('stage')}")
    quality = q.get("import_provenance", {}).get("extraction_quality")
    units = [u for s in q.get("sections", []) for u in s.get("question_units", [])]
    if quality != "unreadable" and not units:
        fails.append("no question units")
    for u in units:
        for f in ("unit_id", "prompt", "question_type"):
            if not u.get(f):
                fails.append(f"{u.get('unit_id')} missing {f}")
        if u.get("question_type") == "multiple_choice":
            if not (3 <= len(u.get("options", [])) <= 4):
                fails.append(f"{u['unit_id']} option count {len(u.get('options', []))}")
            if not u.get("correct_option"):
                fails.append(f"{u['unit_id']} no correct_option")
    if not q.get("import_provenance", {}).get("fetch_date"):
        fails.append("no fetch_date")
    return fails


# --------------------------------------------------------------------------- #
# Networking & discovery
# --------------------------------------------------------------------------- #
def http_get(url: str, binary: bool = False, retries: int = 3):
    import requests

    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r.content if binary else r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def discover_files() -> list[dict]:
    """Scrape archive pages for questionnaire file links."""
    from bs4 import BeautifulSoup

    seen: dict[str, dict] = {}
    for age_group, page in ARCHIVE_PAGES:
        try:
            html = http_get(page)
        except Exception as e:  # noqa: BLE001
            print(f"  ! could not fetch archive {page}: {e}", file=sys.stderr)
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "bible-contest/" not in href and "/files/" not in href:
                continue
            if not re.search(r"\.(pdf|docx?|)$", href, re.I):
                pass
            m = re.search(r"/([^/]+\.(?:pdf|docx?|doc))$", href, re.I)
            if not m:
                continue
            fname = m.group(1)
            base = re.sub(r"\.(pdf|docx?|doc)$", "", fname, flags=re.I)
            is_answer = bool(re.search(r"(answers?|_ans|ans_|tshuvon|teshuvon|^an[_-])", base, re.I))
            url = href if href.startswith("http") else FILE_BASE + fname
            if base not in seen:
                seen[base] = {"base": base, "filename": fname, "url": url,
                              "age_group": age_group, "is_answer_key": is_answer}
    return list(seen.values())


def build_file_entry(base: str) -> dict:
    """Construct a file entry for --file mode (no scrape needed)."""
    meta = decode_filename(base)
    age = meta.get("age_group") or "youth"
    return {"base": base, "filename": base + ".pdf",
            "url": FILE_BASE + base + ".pdf", "age_group": age, "is_answer_key": False}


# --------------------------------------------------------------------------- #
# Per-file processing
# --------------------------------------------------------------------------- #
def process_file(entry: dict, force: bool) -> dict:
    base = entry["base"]
    out_path = QUIZ_DIR / f"{base}.json"
    result = {"id": base, "status": None, "extraction_quality": None,
              "question_count": 0, "duration_seconds": 0.0}
    start = time.time()

    if out_path.exists() and not force:
        result.update(status="skipped_existing")
        return result

    meta = decode_filename(base)
    meta["age_group"] = meta.get("age_group") or entry.get("age_group")
    url = entry["url"]

    if base in KNOWN_UNREADABLE:
        q = stub_questionnaire(base, url, meta, "unreadable", "image-based PDF (known from prior research)")
        write_json(out_path, q)
        result.update(status="success", extraction_quality="unreadable",
                      duration_seconds=round(time.time() - start, 2))
        return result

    # Download.
    TMP_DIR.mkdir(exist_ok=True)
    tmp = TMP_DIR / entry["filename"]
    try:
        data = http_get(url, binary=True)
        tmp.write_bytes(data)
    except Exception as e:  # noqa: BLE001
        result.update(status="fetch_failed", extraction_notes=str(e),
                      duration_seconds=round(time.time() - start, 2))
        return result

    ext = entry["filename"].lower().rsplit(".", 1)[-1]
    try:
        answers: dict[int, dict] = {}
        if ext == "pdf":
            pages = extract_pdf_pages(tmp)
            if hebrew_char_count("\n".join(pages)) < 40:
                fb = extract_pdf_text_fallback(tmp)
                if hebrew_char_count(fb) < 40:
                    q = stub_questionnaire(base, url, meta, "unreadable", "image-based PDF -- text layer empty")
                    write_json(out_path, q)
                    result.update(status="success", extraction_quality="unreadable",
                                  duration_seconds=round(time.time() - start, 2))
                    return result
            answers = extract_answer_tables(tmp)
        elif ext == "docx":
            pages = extract_docx_text(tmp)
        else:  # .doc
            pages = extract_doc_text(tmp)
            if hebrew_char_count("\n".join(pages)) < 40:
                q = stub_questionnaire(base, url, meta, "unreadable", "binary .doc -- could not extract text")
                write_json(out_path, q)
                result.update(status="success", extraction_quality="unreadable",
                              duration_seconds=round(time.time() - start, 2))
                return result
    except Exception as e:  # noqa: BLE001
        q = stub_questionnaire(base, url, meta, "unreadable", f"extraction error: {e}")
        write_json(out_path, q)
        result.update(status="success", extraction_quality="unreadable",
                      duration_seconds=round(time.time() - start, 2))
        return result

    q, quality, notes = build_questionnaire(base, url, pages, meta, answers)
    fails = validate(q)
    if fails:
        q["import_provenance"]["extraction_quality"] = "manual_review_needed"
        existing = q["import_provenance"].get("extraction_notes")
        fail_note = "validation: " + "; ".join(fails)
        q["import_provenance"]["extraction_notes"] = f"{existing}; {fail_note}" if existing else fail_note
        quality = "manual_review_needed"

    suspicious = audit_hebrew(q)
    if suspicious:
        result["suspicious_hebrew"] = len(suspicious)
        for jpath, snip in suspicious[:3]:
            print(f"   ! suspicious Hebrew at {jpath}: {snip!r}")

    write_json(out_path, q)
    count = len(q["sections"][0]["question_units"]) if q["sections"] else 0
    result.update(status="success", extraction_quality=quality, question_count=count,
                  duration_seconds=round(time.time() - start, 2))
    if notes:
        result["extraction_notes"] = notes
    return result


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def reclassify_existing() -> int:
    """Backfill metadata.track/stage/year on existing quiz JSONs using the
    (improved) decode_filename + overrides, without re-extracting text. Returns
    the number of files updated. Run regenerate_manifest() afterwards.
    """
    updated = 0
    for jp in sorted(QUIZ_DIR.glob("*.json")):
        if jp.name == "manifest.json":
            continue
        q = json.loads(jp.read_text(encoding="utf-8"))
        base = q.get("questionnaire_id") or jp.stem
        meta = decode_filename(base)
        md = q.setdefault("metadata", {})
        changed = False
        if meta["track"] and md.get("track") != meta["track"]:
            md["track"] = meta["track"]
            changed = True
        if meta["stage"] and md.get("stage") != meta["stage"]:
            md["stage"] = meta["stage"]
            changed = True
        if meta["year_civil"] and not md.get("contest_year_civil"):
            md["contest_year_civil"] = meta["year_civil"]
            md["contest_year_hebrew"] = HEBREW_YEARS.get(meta["year_civil"])
            changed = True
        if changed:
            write_json(jp, q)
            updated += 1
    return updated


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def regenerate_manifest() -> dict:
    quizzes = []
    for jp in sorted(QUIZ_DIR.glob("*.json")):
        if jp.name == "manifest.json":
            continue
        q = json.loads(jp.read_text(encoding="utf-8"))
        md = q.get("metadata", {})
        units = [u for s in q.get("sections", []) for u in s.get("question_units", [])]
        quizzes.append({
            "id": q.get("questionnaire_id"),
            "track": md.get("track"),
            "stage": md.get("stage"),
            "year_civil": md.get("contest_year_civil"),
            "year_hebrew": md.get("contest_year_hebrew"),
            "question_count": len(units),
            "json_path": f"quizzes/{jp.name}",
            "extraction_quality": q.get("import_provenance", {}).get("extraction_quality"),
            "has_answer_key": q.get("answer_key_present", False),
        })
    manifest = {"schema_version": SCHEMA_VERSION, "generated_at": TODAY, "quizzes": quizzes}
    write_json(MANIFEST_PATH, manifest)
    return manifest


def write_log(results: list[dict]) -> None:
    statuses = [r["status"] for r in results]
    log = {
        "run_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "total_files": len(results),
        "processed": sum(1 for s in statuses if s == "success"),
        "skipped_existing": sum(1 for s in statuses if s == "skipped_existing"),
        "failed": sum(1 for s in statuses if s == "fetch_failed"),
        "suspicious_hebrew_total": sum(r.get("suspicious_hebrew", 0) for r in results),
        "results": results,
    }
    write_json(LOG_DIR / "extraction_log.json", log)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Bible Contest extraction pipeline")
    ap.add_argument("--all", action="store_true", help="process all discovered files")
    ap.add_argument("--file", metavar="ID", help="process a single file by base id")
    ap.add_argument("--force", action="store_true", help="re-extract even if JSON exists")
    ap.add_argument("--manifest-only", action="store_true", help="regenerate manifest only")
    ap.add_argument("--reclassify", action="store_true",
                    help="backfill track/stage/year on existing quiz JSONs, then regenerate manifest")
    ap.add_argument("--dry-run", action="store_true", help="list what would be processed")
    args = ap.parse_args()

    QUIZ_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    _load_verse_cache()  # reuse Sefaria lookups across runs

    if args.reclassify:
        n = reclassify_existing()
        m = regenerate_manifest()
        print(f"reclassified {n} quiz JSONs; manifest regenerated ({len(m['quizzes'])} quizzes)")
        return 0

    if args.manifest_only:
        m = regenerate_manifest()
        print(f"manifest.json regenerated: {len(m['quizzes'])} quizzes")
        return 0

    if args.file:
        # Prefer the discovered entry (correct extension/URL); fall back to a
        # .pdf guess only if discovery can't find it.
        match = next((e for e in discover_files() if e["base"] == args.file), None)
        entries = [match or build_file_entry(args.file)]
    elif args.all:
        print("Discovering files from archive pages...")
        entries = [e for e in discover_files() if not e["is_answer_key"]]
        print(f"  found {len(entries)} questionnaire files")
    else:
        ap.print_help()
        return 1

    if args.dry_run:
        for e in entries:
            exists = (QUIZ_DIR / f"{e['base']}.json").exists()
            print(f"  {'[exists] ' if exists else ''}{e['base']}  <- {e['url']}")
        print(f"\n{len(entries)} files would be processed.")
        return 0

    results = []
    for e in entries:
        print(f"-> {e['base']}")
        r = process_file(e, args.force)
        results.append(r)
        print(f"   {r['status']} / {r.get('extraction_quality')} / {r['question_count']}q")

    if any(r["status"] in ("success",) for r in results):
        regenerate_manifest()
    write_log(results)
    print(f"\nDone. {len(results)} files. Log: logs/extraction_log.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
