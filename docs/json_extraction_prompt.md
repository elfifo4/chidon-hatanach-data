# Claude Code Task: Bible Contest PDF/DOC → JSON Extraction Pipeline

## Your Mission

Build a Python extraction pipeline that downloads all official Israeli Bible Contest ("Chidon
HaTanach") questionnaires from the Ministry of Education website, parses them, and outputs
structured JSON files conforming to a defined schema. The resulting JSON files will be committed to
a public GitHub repository and consumed by a mobile app (KMP/Compose).

---

## Read These Files First

Before writing any code, read the following files that are already in this repository:

1. `docs/bible_contest_taxonomy.md` — Full research report on all 12 questionnaire formats and 20
   question types. This is your ground truth for understanding the content structure.
2. `docs/beitsifri_mm2026.json` — Completed pilot extraction of one questionnaire. This is your
   reference implementation for the JSON schema. Match its structure exactly.

---

## Source Materials

### Website structure

Questionnaire PDFs and DOC files are published on two sections of the official site:

- **Youth contest archive:** `https://bible-contest.education.gov.il/youth/old-questionnaire/`
- **Adult contest archive:** `https://bible-contest.education.gov.il/adult/questionnaires/`

The actual files are served from: `https://meyda.education.gov.il/files/bible-contest/{filename}`

### File naming convention (source files)

The source filenames already encode metadata. Examples:

- `beitsifri_mm2026.pdf` → stage=school, track=mamlachti, year=2026
- `mahoz_mm2026.pdf` → stage=district, track=mamlachti, year=2026
- `artzi_mm2026.pdf` → stage=national, track=mamlachti, year=2026
- `olami_mm2026.pdf` → stage=world, track=mamlachti, year=2026
- `beitsifri_md2026.pdf` → stage=school, track=mamlachti\_dati, year=2026

Decode the filename to extract metadata — do not hard-code the mapping.

**Stage codes:** `beitsifri` → school · `mahoz` → district · `artzi` → national · `olami` → world  
**Track codes:** `mm` → mamlachti · `md` → mamlachti\_dati  
**Year:** 4-digit civil year at end of base name

### File formats by era

- **2015–2026:** PDF (primary format)
- **2008–2014:** DOC or DOCX (some years have both PDF and DOC; prefer PDF when both exist)
- **Answer keys:** sometimes in the same file, sometimes as a separate file (e.g.,
  `beitsifri_mm2026_answers.pdf`)

---

## Output Structure

### Repository layout

/quizzes/

manifest.json

beitsifri\_mm2026.json

mahoz\_mm2026.json

artzi\_mm2026.json

...

/logs/

extraction\_log.json ← generated on each run

### Output filename convention

Use the source filename base (without extension) as the JSON filename: `beitsifri_mm2026.pdf` →
`quizzes/beitsifri_mm2026.json`

### manifest.json structure

{

"schema\_version": "1.0",

"generated\_at": "2026-06-22",

"quizzes": \[

    {

      "id": "beitsifri\_mm2026",

      "track": "mamlachti",

      "stage": "school",

      "year\_civil": 2026,

      "year\_hebrew": "תשפ\\"ו",

      "question\_count": 25,

      "json\_path": "quizzes/beitsifri\_mm2026.json",

      "extraction\_quality": "clean",

      "has\_answer\_key": true

    }

\]

}

`extraction_quality` values: `"clean"` · `"partial"` · `"manual_review_needed"` · `"unreadable"`

---

## JSON Schema

Conform exactly to the schema demonstrated in `docs/beitsifri_mm2026.json`. Key rules:

### Top-level fields

| Field                 | Required | Notes                                                  |
|:----------------------|:---------|:-------------------------------------------------------|
| `questionnaire_id`    | ✓        | Same as filename base (e.g. `"beitsifri_mm2026"`)      |
| `source_url`          | ✓        | Full URL of the source file                            |
| `metadata`            | ✓        | See below                                              |
| `sections`            | ✓        | Array; most questionnaires have one section (`"main"`) |
| `answer_key_present`  | ✓        | boolean                                                |
| `answer_key_location` | ✓        | `"same_document"` · `"separate_file"` · `"none"`       |
| `import_provenance`   | ✓        | See below                                              |

### metadata fields

{

"contest\_year\_civil": 2026,

"contest\_year\_hebrew": "תשפ\\"ו",

"track": "mamlachti",

"stage": "school",

"age\_group": "youth",

"time\_limit\_minutes": 30,

"scoring\_summary": {

    "points\_per\_question": 1,

    "max\_points": 25,

    "scoring\_is\_tiered": false

},

"credits": {

    "program\_supervisor": null,

    "quiz\_coordinator": null,

    "question\_authors": \[\]

},

"annual\_theme": null

}

### question\_unit fields

{

"unit\_id": "q01",

"display\_number": "1",

"narrative\_context": null,

"prompt": "...",

"question\_type": "multiple\_choice",

"answer\_style": "single\_correct",

"options": \[

    {"key": "א", "text": "..."},

    {"key": "ב", "text": "..."},

    {"key": "ג", "text": "..."},

    {"key": "ד", "text": "..."}

\],

"correct\_option": "ג",

"primary\_sources": \[

    {"book": "בראשית", "chapter": "א", "verse": "כז", "scope": "whole\_unit"}

\],

"acceptable\_answers": \[

    {

      "answer\_text": "...",

      "source\_refs": \[{"book": "בראשית", "chapter": "א", "verse": "כז"}\],

      "is\_primary": true

    }

\],

"scoring": {"points": 1},

"subquestions": null

}

### question\_type values (from taxonomy)

`multiple_choice` · `negative_exclusion` · `speaker_id` · `numeric` · `verse_completion` ·
`true_false` · `composite` · `association_progressive_hint` · `common_word_puzzle` · `open` ·
`source_identification` · `sequence`

### scope values for primary\_sources

`"whole_unit"` · `"answer_option:<key>"` · `"subquestion:<id>"` · `"alternative_answer:<id>"`

For `negative_exclusion` questions: sources attach to the *wrong* answer options (scope
`"answer_option:א"` etc.), not to the correct answer.

### import\_provenance

{

"fetched\_from": "https://meyda.education.gov.il/files/bible-contest/beitsifri\_mm2026.pdf",

"fetch\_date": "2026-06-22",

"extraction\_quality": "clean",

"extraction\_notes": null

}

---

## Pipeline Architecture

Build the pipeline as a single Python script (`extract.py`) with the following CLI interface:

\# Extract all files (skip already-extracted)

python extract.py \--all

\# Extract a specific file

python extract.py \--file beitsifri\_mm2026

\# Force re-extraction even if JSON exists

python extract.py \--all \--force

\# Only regenerate manifest (no extraction)

python extract.py \--manifest-only

\# Dry run: list what would be processed

python extract.py \--all \--dry-run

### Processing steps per file

1. Check if `quizzes/{id}.json` already exists → skip unless `--force`
2. Download the source file (PDF or DOC) to a temp directory
3. Extract text using the appropriate parser
4. Parse the text into the JSON schema
5. Validate the output (question count, required fields, etc.)
6. Write `quizzes/{id}.json`
7. Log the result

### Recommended libraries

pdfplumber \# primary PDF text extraction

pymupdf (fitz)      \# fallback PDF extraction \+ image detection

python-docx \# DOCX parsing

mammoth \# DOC → plain text conversion

requests \# HTTP download

Install with:

pip install pdfplumber pymupdf python-docx mammoth requests

---

## Hebrew Year Mapping

HEBREW\_YEARS \= {

    2026: 'תשפ"ו', 2025: 'תשפ"ה', 2024: 'תשפ"ד', 2023: 'תשפ"ג',

    2022: 'תשפ"ב', 2021: 'תשפ"א', 2020: 'תש"פ',  2019: 'תשע"ט',

    2018: 'תשע"ח', 2017: 'תשע"ז', 2016: 'תשע"ו', 2015: 'תשע"ה',

    2014: 'תשע"ד', 2013: 'תשע"ג', 2012: 'תשע"ב', 2011: 'תשע"א',

    2010: 'תש"ע',  2009: 'תשס"ט', 2008: 'תשס"ח'

}

---

## Error Handling Requirements

### Unreadable files (handle gracefully — do not crash)

| Error type                                  | Detection                                   | Action                                                              |
|:--------------------------------------------|:--------------------------------------------|:--------------------------------------------------------------------|
| Image-based PDF (scanned)                   | pdfplumber returns empty or near-empty text | Set `extraction_quality: "unreadable"`, log reason, write stub JSON |
| Corrupted / password-protected file         | Exception on open                           | Same as above                                                       |
| DOC binary (pre-2007 format)                | mammoth raises error                        | Try raw text extraction, fall back to stub                          |
| Network error                               | requests exception                          | Retry 3×, then mark as `"fetch_failed"` in log                      |
| Partial extraction (some questions missing) | Question count \< expected                  | Set `extraction_quality: "partial"`, include what was extracted     |

### Stub JSON for unreadable files

When a file cannot be extracted, write a minimal JSON so the manifest remains complete:

{

"questionnaire\_id": "beitsifri\_mm2026",

"source\_url": "...",

"metadata": { ... },

"sections": \[\],

"answer\_key\_present": false,

"answer\_key\_location": "none",

"import\_provenance": {

    "fetched\_from": "...",

    "fetch\_date": "...",

    "extraction\_quality": "unreadable",

    "extraction\_notes": "Image-based PDF — text layer empty"

}

}

### Known unreadable files (from prior research)

These files were confirmed unreadable in a previous analysis run — mark them as `"unreadable"`
immediately without attempting extraction:

- `OLAMI_PUB_MMD.pdf` — image-based PDF, returns empty text
- `ARTZI_PUB_MM.pdf` — image-based PDF, returns empty text

DOC files from 2008–2013 may return HTTP 403\. Log as `"fetch_failed"`.

---

## Extraction Log Format

Write `logs/extraction_log.json` on every run:

{

"run\_at": "2026-06-22T14:30:00",

"total\_files": 48,

"processed": 45,

"skipped\_existing": 2,

"failed": 1,

"results": \[

    {

      "id": "beitsifri\_mm2026",

      "status": "success",

      "extraction\_quality": "clean",

      "question\_count": 25,

      "duration\_seconds": 3.2

    },

    {

      "id": "OLAMI\_PUB\_MMD",

      "status": "success",

      "extraction\_quality": "unreadable",

      "question\_count": 0,

      "extraction\_notes": "Image-based PDF"

    }

\]

}

---

## Quality Validation (run after each extraction)

After parsing, validate before writing:

- [ ] `questionnaire_id` matches filename
- [ ] `metadata.contest_year_civil` is in range 2008–2026
- [ ] `metadata.track` is one of: `mamlachti`, `mamlachti_dati`
- [ ] `metadata.stage` is one of: `school`, `district`, `national`, `world`
- [ ] At least one `question_unit` exists (unless `extraction_quality: "unreadable"`)
- [ ] Each `question_unit` has `unit_id`, `prompt`, `question_type`
- [ ] For `multiple_choice`: `options` array has 3–4 items and `correct_option` is set
- [ ] `import_provenance.fetch_date` is set

If validation fails: set `extraction_quality: "manual_review_needed"` and log the failing checks.

---

## Incremental Update Workflow

The pipeline should support being re-run each year when new questionnaires are published:

1. Run `python extract.py --all` — new files are fetched, existing files are skipped
2. Review `logs/extraction_log.json` for any `"manual_review_needed"` items
3. Fix manually if needed, then re-run with `--force --file <id>` for that specific file
4. Commit the new JSON files and updated `manifest.json` to the public GitHub repo

---

## Constraints

- Do not hard-code a fixed list of filenames. Discover available files by scraping the archive
  pages.
- All output JSON must be UTF-8 encoded with `ensure_ascii=False`.
- Do not store downloaded PDFs/DOCs in the repository — only the extracted JSON.
- The `manifest.json` must be regenerated on every run that modifies any quiz JSON.
- Be conservative: if text extraction is ambiguous, prefer `extraction_quality: "partial"` over
  silently producing wrong data. The cost of marking something for manual review is lower than
  shipping incorrect questions to users.
