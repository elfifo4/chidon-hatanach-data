# HANDOFF — Chidon HaTanach data pipeline + app

_Last updated end of the session that built the extraction pipeline, the PDF-vision pilot, and
separate-answer-key extraction. Next focus: **parsing the public/oral question formats** so users
can experience every question type._

## Repos
- **Data/pipeline:** `/Users/eladfinish/AndroidStudioProjects/chidon-hatanach-data`
  (GitHub `elfifo4/chidon-hatanach-data`). Branch **`main`**, clean, pushed. Python venv at `.venv`.
- **Mobile app:** `/Users/eladfinish/AndroidStudioProjects/BibleContestAndroidApp`
  (KMP/Compose + Ktor server). Branch **`chidonim`**. Reads quiz data from
  `raw.githubusercontent.com/elfifo4/chidon-hatanach-data/main/content/{manifest.json,quizzes/<id>.json}`
  via `shared/.../pastQuizzes/data/RawGitHubQuizDataSource.kt` (`RAW_BASE`).
- **Tanach corpus source (read-only):** `/Users/eladfinish/Projects/Bible-RAG/data/processed/all_verses.jsonl`.

## Pipeline layout (data repo)
- `extract.py` — core. CLI: `--all` (archive), `--file <id>`, `--reclassify`, `--manifest-only`,
  and pilot flags `--url / --file <pdf> / --vision / --output / --report / --expected /
  --keep-debug-images / --batch`.
- `tanach_corpus.py` — resolve a quote to clean verse text by consonant match against the vendored
  corpus `data/tanach_verses.jsonl` (committed, ~6 MB, 23,202 verses). Override `TANACH_CORPUS`;
  regenerate with `tools/build_tanach_corpus.py`.
- `pdf_vision.py` — single-PDF/batch pilot: download, render, baseline reuse, vision, report, eval,
  cleanup (`run_pilot`, `run_batch`, `_baseline_extract`, `_separate_answer_key`).
- `pdf_emphasis.py` — deterministic bold/underline detection → inline `<b>/<u>`, **prompt/narrative
  only, never options** (so the correct answer is never leaked).
- `html_format.py` — validate/sanitize/normalize the 3 allowed inline tags (`<b><u><i>`).
- `pilot_validate.py` — structure validators + report stats (incl. page-furniture contamination).
- `vision_client.py` — isolated OpenAI client (`OPENAI_API_KEY`, optional `OPENAI_MODEL`; `--vision`
  only; mocked in tests).
- Tests: `tests/test_repair.py`, `tests/test_pdf_vision.py` — **65 passing**, no network.
- Taxonomy / schema ground truth: `docs/bible_contest_taxonomy.md`, `docs/beitsifri_mm2026.json`,
  `docs/json_extraction_prompt.md`.

## Capabilities delivered
1. Full extraction pipeline (RTL de-reversal, niqqud repair, answer-key tables, Sefaria, manifest,
   classification). One full archive run produced 227 files.
2. Niqqud fix: cluster-aware `_delogicalize` + `repair_hebrew_pdf_text` (reattach detached marks,
   join lone single-letter fragments).
3. Faithful verse quotes: clean only the *quoted* words, ellipsis preserved — via the local Tanach
   corpus (no ref needed); kills intra-word spaces and restores lost letters.
4. Broadened track/stage classification + `--reclassify` backfill (manifest clean/partial with both
   fields: 4 → 16).
5. PDF-vision pilot (merged): baseline + optional OpenAI `--vision`; emphasis as inline HTML; eval.
6. App rendering: `htmlToAnnotatedString` (KMP) so `<b>/<u>` render in the quiz screen.
7. Inline verses: verse kept in `prompt` with quotes in original order (`narrative_context=null`).
8. Page-number footer stripping (geometry + parser guard + validation).
9. Separate answer-key files: layout-flexible answer-table parsing, digit-verse + abbreviated-book
   sources, stream-aware ranked pairing with a strict answered-row-count guard.

## Numbers
- Curated 27-file school+district batch → **16 app-ready** (was 5). Outputs in gitignored `output/`
  (`output/batch_summary.json`).

## ⚠️ Critical status nuance
- **`main` has the improved CODE but `content/` JSON is mostly OLD-pipeline output.** Only
  `content/quizzes/beitsifri_mmd2026.json` is in the new format. The other ~225 files are stale.
- Improvements are split:
  - **Shared core (applies to `--all`):** de-reversal, niqqud repair, page-furniture, layout-flexible
    answer tables, digit/abbrev sources, classification.
  - **Pilot-path only (`pdf_vision`, `inline_quotes=True`):** inline-verse corpus cleaning, emphasis
    HTML, separate-answer-key pairing, report/eval. **NOT in `--all`.**
- To get full pilot quality into the app, **regenerate `content/`** by either (a) batch-running the
  pilot per file into `content/quizzes/`, or (b) porting the pilot-only logic into the `--all` path.
  This is still open.

## Open items
1. Regenerate `content/` with the new pipeline (see nuance above).
2. Decide the new schema is canonical (inline verse + `narrative_context=null` + inline `<b>/<u>`).
3. Small gaps: `district_2018`/`_mamad` (answer file unpaired), `regional_written_*` (correct ok,
   sources missing), `mehozi-mmd2026` (1 page-furniture), ~5 empty (scanned/odd layout).
4. **Public/oral formats — NEXT FOCUS (see below).**
5. App repo `chidonim`: confirm HTML-render changes committed; `RAW_BASE` is on `/main/`.

## How to run
```bash
cd /Users/eladfinish/AndroidStudioProjects/chidon-hatanach-data
.venv/bin/python -m pytest tests/ -q
.venv/bin/python extract.py --url https://meyda.education.gov.il/files/bible-contest/<id>.pdf \
  --output output/<id>.json --report output/<id>.report.json
.venv/bin/python extract.py --batch "schoola,district-writing-mamad,..."
# vision: add --vision --keep-debug-images (needs OPENAI_API_KEY in ~/.zshenv)
```

---

## NEXT FOCUS — Parse the public/oral formats (all question types)

Goal: users should be able to experience **every** question type, not just multiple-choice. Today the
pipeline only handles MC well; the public/oral (פומבי) formats yield 0–2 questions
(`2017m3`, `mehozipumbi2018`, `adults_quiz_2025`, `champ_champ_2019`, `*_PUB`, …).

These are the live/staged rounds (formats 3,4,6,8,9,10,11 in `docs/bible_contest_taxonomy.md`).
The current parser assumes "numbered question + 4 options א/ב/ג/ד + answer key with one correct
letter" — none of which holds here. Question types to support (taxonomy "20 question types"):
`open` (short/free-text + model answer), `verse_completion`, `true_false`, `numeric`, `speaker_id`,
`composite` (a/b/c subquestions, possibly different source per part), `association_progressive_hint`
("מה הקשר", graded hints), `common_word_puzzle` ("המילה המשותפת"), `source_identification`,
`sequence`, mini-crossword.

Two sides of the work:
- **Extraction (this repo):** per-format parsers that emit the existing schema, using the fields
  already designed for it — `question_type` (free-form), `subquestions[]`, `answer_style`,
  `acceptable_answers[]`, `live_stage_rules`, `scoring`. Do NOT break the MC path.
- **App rendering (BibleContestAndroidApp):** new UI for non-MC types (open answer + reveal model
  answer, composite/subquestions, true/false, verse completion, crossword). The quiz screen today
  renders only `multiple_choice`.

Constraints/guidance: keep MC behavior intact; reuse the corpus + niqqud + page-furniture machinery;
faithful to the exam; plan before building (likely format-by-format, starting with the most common /
highest-value public format).

### Progress — public parser, format #1 (`2017m3`) DONE
- **New module `public_parser.py`.** Parses the youth national public booklet grammar (Format 3):
  three stages as `sections[]` split by track (ממלכתי / ממלכתי-דתי):
  - `שלב א` "בעקבות קטעי שירה" → `stage_subtype:"live-rounds"`, units `question_type:"composite"`
    with `subquestions[]` (א/ב), each `acceptable_answers[]` (incl. `תתקבל גם` alternates),
    `requires_free_text_judging:true`, `narrative_context` = framing + corpus-cleaned quote.
  - `שלב ב` "תשבצים" → `mini_crossword`, subquestions = clues with `label "N (מאונך/מאוזן)"`,
    `answer_length` ("5", "3,5"), single answer + source ref.
  - `שלב ג` "ראש בראש" → `head-to-head`, units = `צמד N: <theme>` containers, subquestions = the
    paired short questions (answer + `יתקבל גם` alternates + source).
  - `live_stage_rules` (points_per_correct / decay_per_hint / time_limit_seconds) best-effort from תקנון.
  - Entry points: `looks_public(pages)` (conservative detector), `parse_public_sections(pages)`,
    `build_public_questionnaire(base, url, pages, meta)` (full envelope, mirrors `build_questionnaire`).
- **Dispatch (auto-detect):** `process_file` routes a PDF to the public parser iff
  `public_parser.looks_public(pages)`; everything else stays on the MC path. Verified `looks_public`
  is **False** on the MC quizzes (beitsifri_*, MMTEST) and **True** on `2017m3`.
- **Corpus matcher hardened (helps MC too):** `tanach_corpus.resolve_quote` now has a longest-word-window
  fallback (`_locate`) so quotes containing the divine name `ה'` (corpus spells `יהוה`) still resolve
  **offline** — previously these only cleaned when Sefaria was reachable/cached. Span guard unchanged.
- **`validate()`** relaxed: a unit may carry its question in `subquestions`/`narrative_context` instead
  of a top-level `prompt` (MC units still require prompt via that same OR).
- **Result:** `2017m3` → 6 sections / 40 units / 3 stages, quality `clean`, validates, 0 suspicious Hebrew.
  Output written to `output/2017m3.json` (content/ left untouched on purpose).
- **Tests:** `tests/test_public_parser.py` (11 tests, synthetic fixtures, no network). Suite now **76 passing**.

### Public parser — remaining formats (next sessions, same pattern: grammar variant + fixture)
`looks_public` is intentionally scoped to the `2017m3` stage vocabulary, so other public files still fall
through to the MC path (no worse than today) until their grammar is added:
- `mehozipumbi2018` / `adults_*` — Format 9 א/ב/ג with a **different source on part ג** (multi-source/sub-q).
- `2013m3` — Format 11 common-word-puzzle ("המילה המשותפת") + embedded true/false.
- `2011m4` — Format 10 association progressive-hint ("מה הקשר") + length-constrained crossword.
- `champ_champ_2019` / `adults_quiz_2025` — Format 4/6 "צמד" pairs, "שאלת ראש הממשלה", numeric/date types.

### ⚠️ App side — CONSUMING WORK REQUIRED (BibleContestAndroidApp, branch `chidonim`)
The quiz screen renders **only `multiple_choice`**. The new public JSON needs UI for:
composite/subquestions (reveal model answer), open answer, true/false, verse completion, mini-crossword,
and section/stage grouping with `live_stage_rules`. **No schema change needed** — the fields already exist.
Also: these public quizzes won't appear in the app until `content/` is regenerated (separate open item #1).
