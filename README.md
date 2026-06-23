<a id="top"></a>

# Chidon HaTanach — Quiz Data · נתוני שאלוני חידון התנ"ך

<p align="center">
  <a href="#english"><img src="https://img.shields.io/badge/%F0%9F%87%AC%F0%9F%87%A7%20English-Read-1f6feb?style=for-the-badge" alt="Read in English"></a>
  &nbsp;
  <a href="#hebrew"><img src="https://img.shields.io/badge/%F0%9F%87%AE%F0%9F%87%B1%20%D7%A2%D7%91%D7%A8%D7%99%D7%AA-%D7%9C%D7%A7%D7%A8%D7%99%D7%90%D7%94-2da44e?style=for-the-badge" alt="קריאה בעברית"></a>
</p>

---

<a id="english"></a>

## 🇺🇸 English

Structured JSON data for the official Israeli Bible Contest (**Chidon HaTanach** / חידון התנ"ך).

This repository is the **public data store** for the contest questionnaires. It holds machine-readable JSON files extracted from the official questionnaires published by the Israeli Ministry of Education, plus a manifest that indexes them. The data is consumed by the Chidon HaTanach mobile app (Kotlin Multiplatform / Compose).

> **This repo contains data only — not the extraction pipeline.** The pipeline (`extract.py`) lives alongside the app project and writes its output here.

### Repository layout

```
quizzes/
  manifest.json          # index of all quizzes (see below)
  beitsifri_mm2026.json  # one file per questionnaire
  mahoz_mm2026.json
  artzi_mm2026.json
  ...
logs/
  extraction_log.json    # written on each pipeline run
```

- One JSON file per questionnaire. The filename is the source file's base name (e.g. `beitsifri_mm2026.pdf` → `quizzes/beitsifri_mm2026.json`).
- Source PDFs/DOCs are **not** stored here — only the extracted JSON.
- All JSON is UTF-8 with non-ASCII characters preserved (`ensure_ascii=False`).

### Questionnaire naming

Each questionnaire id encodes its metadata: `{stage}_{track}{year}`.

| Part  | Codes | Meaning |
| :---- | :---- | :---- |
| Stage | `beitsifri` · `mahoz` · `artzi` · `olami` | school · district · national · world |
| Track | `mm` · `md` | mamlachti · mamlachti_dati |
| Year  | 4-digit civil year | e.g. `2026` |

Example: `beitsifri_md2026` → school stage, mamlachti_dati track, year 2026.

**Coverage:** civil years 2008–2026 (PDF for 2015+, DOC/DOCX for 2008–2014).

### `manifest.json`

The manifest is the entry point — consumers read it to discover available quizzes without listing the directory.

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-06-22",
  "quizzes": [
    {
      "id": "beitsifri_mm2026",
      "track": "mamlachti",
      "stage": "school",
      "year_civil": 2026,
      "year_hebrew": "תשפ\"ו",
      "question_count": 25,
      "json_path": "quizzes/beitsifri_mm2026.json",
      "extraction_quality": "clean",
      "has_answer_key": true
    }
  ]
}
```

`extraction_quality` is one of: `clean` · `partial` · `manual_review_needed` · `unreadable`. The manifest is regenerated on every run that modifies any quiz JSON.

### Quiz JSON schema

Each quiz file conforms to the schema below (version `1.0`).

**Top-level**

| Field | Required | Notes |
| :---- | :---- | :---- |
| `questionnaire_id` | ✓ | Same as filename base, e.g. `"beitsifri_mm2026"` |
| `source_url` | ✓ | Full URL of the source file |
| `metadata` | ✓ | See below |
| `sections` | ✓ | Array of sections; most quizzes have one (`"main"`), each holding `question_units` |
| `answer_key_present` | ✓ | boolean |
| `answer_key_location` | ✓ | `"same_document"` · `"separate_file"` · `"none"` |
| `import_provenance` | ✓ | See below |

**metadata**

```json
{
  "contest_year_civil": 2026,
  "contest_year_hebrew": "תשפ\"ו",
  "track": "mamlachti",
  "stage": "school",
  "age_group": "youth",
  "time_limit_minutes": 30,
  "scoring_summary": {
    "points_per_question": 1,
    "max_points": 25,
    "scoring_is_tiered": false
  },
  "credits": {
    "program_supervisor": null,
    "quiz_coordinator": null,
    "question_authors": []
  },
  "annual_theme": null
}
```

**question_unit**

```json
{
  "unit_id": "q01",
  "display_number": "1",
  "narrative_context": null,
  "prompt": "...",
  "question_type": "multiple_choice",
  "answer_style": "single_correct",
  "options": [
    {"key": "א", "text": "..."},
    {"key": "ב", "text": "..."},
    {"key": "ג", "text": "..."},
    {"key": "ד", "text": "..."}
  ],
  "correct_option": "ג",
  "primary_sources": [
    {"book": "בראשית", "chapter": "א", "verse": "כז", "scope": "whole_unit"}
  ],
  "acceptable_answers": [
    {
      "answer_text": "...",
      "source_refs": [{"book": "בראשית", "chapter": "א", "verse": "כז"}],
      "is_primary": true
    }
  ],
  "scoring": {"points": 1},
  "subquestions": null
}
```

**`question_type` values:** `multiple_choice` · `negative_exclusion` · `speaker_id` · `numeric` · `verse_completion` · `true_false` · `composite` · `association_progressive_hint` · `common_word_puzzle` · `open` · `source_identification` · `sequence`

**`scope` values for `primary_sources`:** `"whole_unit"` · `"answer_option:<key>"` · `"subquestion:<id>"` · `"alternative_answer:<id>"`

> For `negative_exclusion` questions, sources attach to the *wrong* answer options (`"answer_option:א"`, …), not to the correct answer.

**import_provenance**

```json
{
  "fetched_from": "https://meyda.education.gov.il/files/bible-contest/beitsifri_mm2026.pdf",
  "fetch_date": "2026-06-22",
  "extraction_quality": "clean",
  "extraction_notes": null
}
```

### How the data is generated

The JSON is produced by an extraction pipeline (`extract.py`) that:

1. Scrapes the official archive pages to discover available questionnaires (youth & adult).
2. Downloads each source file from `https://meyda.education.gov.il/files/bible-contest/{filename}`.
3. Extracts text (PDF via `pdfplumber`/`pymupdf`, DOC/DOCX via `mammoth`/`python-docx`).
4. Parses the text into the schema above and validates it.
5. Writes `quizzes/{id}.json` and updates `manifest.json`.
6. Records the run in `logs/extraction_log.json`.

Files that cannot be parsed (e.g. scanned/image-based PDFs) get a **stub JSON** with `extraction_quality: "unreadable"` so the manifest stays complete.

**Updating each year:** run `python extract.py --all` (new files fetched, existing skipped) → review `logs/extraction_log.json` for `manual_review_needed` items → fix and re-run `python extract.py --force --file <id>` → commit the new JSON and `manifest.json`.

### Consuming the data

Read `quizzes/manifest.json` first, then fetch individual quiz files by their `json_path`. Raw files:

```
https://raw.githubusercontent.com/elfifo4/chidon-hatanach-data/main/quizzes/manifest.json
https://raw.githubusercontent.com/elfifo4/chidon-hatanach-data/main/quizzes/<id>.json
```

Always check a quiz's `extraction_quality` before presenting its questions — values other than `clean` may contain incomplete or unverified content.

<p align="right"><a href="#top">⬆ back to top</a></p>

---

<a id="hebrew"></a>

## 🇮🇱 עברית

<div dir="rtl">

נתוני JSON מובְנים לחידון התנ"ך הרשמי (**חידון התנ"ך**).

ה‑repository הזה הוא **מאגר הנתונים הציבורי** של שאלוני החידון. הוא מחזיק קובצי JSON קריאים‑למכונה שחולצו מהשאלונים הרשמיים שמפרסם משרד החינוך, וכן קובץ manifest שמאנדקס אותם. הנתונים נצרכים על‑ידי אפליקציית חידון התנ"ך (Kotlin Multiplatform / Compose).

> **ה‑repo הזה מכיל נתונים בלבד — לא את ה‑pipeline.** ה‑pipeline (`extract.py`) נמצא לצד פרויקט האפליקציה וכותב את הפלט שלו לכאן.

### מבנה ה‑repository

```
quizzes/
  manifest.json          # אינדקס של כל השאלונים (ראו למטה)
  beitsifri_mm2026.json  # קובץ אחד לכל שאלון
  mahoz_mm2026.json
  artzi_mm2026.json
  ...
logs/
  extraction_log.json    # נכתב בכל הרצה של ה‑pipeline
```

- קובץ JSON אחד לכל שאלון. שם הקובץ הוא שם הבסיס של קובץ המקור (לדוגמה `beitsifri_mm2026.pdf` ← `quizzes/beitsifri_mm2026.json`).
- קובצי ה‑PDF/DOC המקוריים **אינם** נשמרים כאן — רק ה‑JSON שחולץ.
- כל ה‑JSON מקודד ב‑UTF-8 עם שמירת תווים שאינם ASCII‏ (`ensure_ascii=False`).

### קונבנציית שמות השאלונים

כל מזהה שאלון מקודד את המטא‑דאטה שלו: `{stage}_{track}{year}`.

| חלק | קודים | משמעות |
| :---- | :---- | :---- |
| שלב (Stage) | `beitsifri` · `mahoz` · `artzi` · `olami` | בית‑ספרי · מחוזי · ארצי · עולמי |
| מסלול (Track) | `mm` · `md` | ממלכתי · ממלכתי‑דתי |
| שנה (Year) | שנה לועזית בת 4 ספרות | למשל `2026` |

דוגמה: `beitsifri_md2026` ← שלב בית‑ספרי, מסלול ממלכתי‑דתי, שנת 2026.

**טווח שנים:** 2008–2026 (PDF משנת 2015 ואילך, DOC/DOCX לשנים 2008–2014).

### `manifest.json`

ה‑manifest הוא נקודת הכניסה — צרכנים קוראים אותו כדי לגלות אילו שאלונים זמינים בלי לסרוק את התיקייה.

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-06-22",
  "quizzes": [
    {
      "id": "beitsifri_mm2026",
      "track": "mamlachti",
      "stage": "school",
      "year_civil": 2026,
      "year_hebrew": "תשפ\"ו",
      "question_count": 25,
      "json_path": "quizzes/beitsifri_mm2026.json",
      "extraction_quality": "clean",
      "has_answer_key": true
    }
  ]
}
```

`extraction_quality` הוא אחד מ: `clean` · `partial` · `manual_review_needed` · `unreadable`. ה‑manifest נוצר מחדש בכל הרצה ששינתה קובץ quiz כלשהו.

### סכמת ה‑JSON של שאלון

כל קובץ שאלון תואם לסכמה הבאה (גרסה `1.0`).

**שדות עליונים (Top-level)**

| שדה | חובה | הערות |
| :---- | :---- | :---- |
| `questionnaire_id` | ✓ | זהה לשם הבסיס של הקובץ, למשל `"beitsifri_mm2026"` |
| `source_url` | ✓ | כתובת ה‑URL המלאה של קובץ המקור |
| `metadata` | ✓ | ראו למטה |
| `sections` | ✓ | מערך מקטעים; לרוב מקטע אחד (`"main"`), שמכיל `question_units` |
| `answer_key_present` | ✓ | בוליאני |
| `answer_key_location` | ✓ | `"same_document"` · `"separate_file"` · `"none"` |
| `import_provenance` | ✓ | ראו למטה |

**metadata**

```json
{
  "contest_year_civil": 2026,
  "contest_year_hebrew": "תשפ\"ו",
  "track": "mamlachti",
  "stage": "school",
  "age_group": "youth",
  "time_limit_minutes": 30,
  "scoring_summary": {
    "points_per_question": 1,
    "max_points": 25,
    "scoring_is_tiered": false
  },
  "credits": {
    "program_supervisor": null,
    "quiz_coordinator": null,
    "question_authors": []
  },
  "annual_theme": null
}
```

**question_unit**

```json
{
  "unit_id": "q01",
  "display_number": "1",
  "narrative_context": null,
  "prompt": "...",
  "question_type": "multiple_choice",
  "answer_style": "single_correct",
  "options": [
    {"key": "א", "text": "..."},
    {"key": "ב", "text": "..."},
    {"key": "ג", "text": "..."},
    {"key": "ד", "text": "..."}
  ],
  "correct_option": "ג",
  "primary_sources": [
    {"book": "בראשית", "chapter": "א", "verse": "כז", "scope": "whole_unit"}
  ],
  "acceptable_answers": [
    {
      "answer_text": "...",
      "source_refs": [{"book": "בראשית", "chapter": "א", "verse": "כז"}],
      "is_primary": true
    }
  ],
  "scoring": {"points": 1},
  "subquestions": null
}
```

**ערכי `question_type`:** `multiple_choice` · `negative_exclusion` · `speaker_id` · `numeric` · `verse_completion` · `true_false` · `composite` · `association_progressive_hint` · `common_word_puzzle` · `open` · `source_identification` · `sequence`

**ערכי `scope` עבור `primary_sources`:** `"whole_unit"` · `"answer_option:<key>"` · `"subquestion:<id>"` · `"alternative_answer:<id>"`

> בשאלות `negative_exclusion`, המקורות משויכים לתשובות ה*שגויות* (`"answer_option:א"` וכו'), ולא לתשובה הנכונה.

**import_provenance**

```json
{
  "fetched_from": "https://meyda.education.gov.il/files/bible-contest/beitsifri_mm2026.pdf",
  "fetch_date": "2026-06-22",
  "extraction_quality": "clean",
  "extraction_notes": null
}
```

### איך הנתונים נוצרים

ה‑JSON נוצר על‑ידי pipeline חילוץ (`extract.py`) ש:

1. סורק את דפי הארכיון הרשמיים כדי לגלות אילו שאלונים זמינים (נוער ומבוגרים).
2. מוריד כל קובץ מקור מ‑`https://meyda.education.gov.il/files/bible-contest/{filename}`.
3. מחלץ טקסט (PDF דרך `pdfplumber`/`pymupdf`, ‏DOC/DOCX דרך `mammoth`/`python-docx`).
4. מנתח את הטקסט לסכמה שלמעלה ומאמת אותו.
5. כותב `quizzes/{id}.json` ומעדכן את `manifest.json`.
6. מתעד את ההרצה ב‑`logs/extraction_log.json`.

קבצים שלא ניתן לנתח (למשל PDF סרוקים מבוססי‑תמונה) מקבלים **stub JSON** עם `extraction_quality: "unreadable"`, כך שה‑manifest נשאר שלם.

**עדכון מדי שנה:** הרצת `python extract.py --all` (קבצים חדשים נמשכים, קיימים מדולגים) ← בדיקת `logs/extraction_log.json` עבור פריטי `manual_review_needed` ← תיקון והרצה מחדש `python extract.py --force --file <id>` ← commit לקובצי ה‑JSON החדשים ול‑`manifest.json`.

### צריכת הנתונים

קִראו תחילה את `quizzes/manifest.json`, ואז משכו קובצי שאלון בודדים לפי ה‑`json_path` שלהם. קבצים גולמיים:

```
https://raw.githubusercontent.com/elfifo4/chidon-hatanach-data/main/quizzes/manifest.json
https://raw.githubusercontent.com/elfifo4/chidon-hatanach-data/main/quizzes/<id>.json
```

תמיד בִדקו את ה‑`extraction_quality` של שאלון לפני הצגת השאלות שלו — ערכים שאינם `clean` עלולים להכיל תוכן חלקי או לא‑מאומת.

</div>

<p align="right"><a href="#top">⬆ חזרה למעלה</a></p>
