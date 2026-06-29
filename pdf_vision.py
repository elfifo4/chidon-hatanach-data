"""Single-PDF pilot orchestration (no archive crawl).

Phase 1: download/local input -> reuse extract.py text baseline -> validate ->
write output JSON + report, with optional evaluation against a golden JSON.
Phase 2: optional Vision enhancement (--vision) renders pages locally and asks
an isolated vision client to recover formatting / fix what the PDF text layer
misses; the text baseline stays the source of truth where it succeeds.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import extract
import html_format
import pdf_emphasis
import pilot_validate

TMP_ROOT = extract.ROOT / "tmp" / "pdf_vision"
OUTPUT_ROOT = extract.ROOT / "output"
EXPECTED_QUESTION_COUNT = 35
RENDER_DPI = 200


# --------------------------------------------------------------------------- #
# Input resolution
# --------------------------------------------------------------------------- #
def _resolve_input(url: str | None, file: str | None, force: bool) -> tuple[Path, str, str, Path]:
    """Return (pdf_path, quiz_id, source_url, work_dir). Never crawls the archive."""
    if file:
        pdf_path = Path(file).expanduser().resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"--file not found: {pdf_path}")
        quiz_id = pdf_path.stem
        work_dir = TMP_ROOT / quiz_id
        work_dir.mkdir(parents=True, exist_ok=True)
        return pdf_path, quiz_id, f"file://{pdf_path}", work_dir

    if url:
        filename = url.rstrip("/").rsplit("/", 1)[-1]
        quiz_id = filename.rsplit(".", 1)[0]
        work_dir = TMP_ROOT / quiz_id
        work_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = work_dir / filename
        if force or not pdf_path.exists():
            print(f"  downloading {url}")
            pdf_path.write_bytes(extract.http_get(url, binary=True))
        else:
            print(f"  reusing cached {pdf_path}")
        return pdf_path, quiz_id, url, work_dir

    raise ValueError("pilot requires --url or --file")


# --------------------------------------------------------------------------- #
# Baseline (reuse existing pipeline)
# --------------------------------------------------------------------------- #
def _baseline_extract(pdf_path: Path, quiz_id: str, source_url: str) -> dict:
    pages = extract.extract_pdf_pages(pdf_path)
    answers = extract.extract_answer_tables(pdf_path)
    meta = extract.decode_filename(quiz_id)
    # Pilot keeps the quoted verse inline in the prompt (with quotes, in its
    # original position) instead of splitting it into narrative_context.
    quiz, _quality, _notes = extract.build_questionnaire(
        quiz_id, source_url, pages, meta, answers, inline_quotes=True)
    return quiz


# --------------------------------------------------------------------------- #
# Phase 2: local rendering + vision enhancement
# --------------------------------------------------------------------------- #
def render_pages(pdf_path: Path, work_dir: Path, dpi: int = RENDER_DPI) -> list[Path]:
    """Render each PDF page to work_dir/page_NNN.png locally (PyMuPDF)."""
    import fitz

    images: list[Path] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    doc = fitz.open(str(pdf_path))
    try:
        for i, page in enumerate(doc, start=1):
            out = work_dir / f"page_{i:03d}.png"
            page.get_pixmap(matrix=matrix).save(str(out))
            images.append(out)
    finally:
        doc.close()
    return images


def _apply_vision(quiz: dict, images: list[Path]) -> list[dict]:
    """Enhance the baseline in place using the isolated vision client. Returns a
    list of per-question warnings. Raises VisionUnavailable if not configured."""
    import vision_client

    review = vision_client.review_pages(images, quiz)  # may raise VisionUnavailable
    return vision_client.merge_into_baseline(quiz, review)


# --------------------------------------------------------------------------- #
# HTML sanitation across text fields
# --------------------------------------------------------------------------- #
def _sanitize_quiz_html(quiz: dict) -> None:
    for unit in pilot_validate.iter_units(quiz):
        if unit.get("prompt"):
            unit["prompt"] = html_format.sanitize(unit["prompt"])
        if unit.get("narrative_context"):
            unit["narrative_context"] = html_format.sanitize(unit["narrative_context"])
        for o in unit.get("options") or []:
            if o.get("text"):
                o["text"] = html_format.sanitize(o["text"])


# --------------------------------------------------------------------------- #
# Report + evaluation
# --------------------------------------------------------------------------- #
def _source_tuples(unit: dict) -> list[tuple]:
    return sorted((s.get("book"), s.get("chapter"), s.get("verse"), s.get("scope"))
                  for s in unit.get("primary_sources") or [])


def evaluate(quiz: dict, expected_path: str) -> dict:
    """Per-unit diff vs a golden JSON (whitespace- and emphasis-insensitive)."""
    import json
    golden = json.loads(Path(expected_path).read_text(encoding="utf-8"))
    gmap = {u.get("unit_id"): u for u in pilot_validate.iter_units(golden)}
    omap = {u.get("unit_id"): u for u in pilot_validate.iter_units(quiz)}

    diffs = []
    for uid in sorted(set(gmap) | set(omap)):
        g, o = gmap.get(uid), omap.get(uid)
        if g is None:
            diffs.append({"unit_id": uid, "issue": "extra question not in golden"})
            continue
        if o is None:
            diffs.append({"unit_id": uid, "issue": "missing question"})
            continue
        d = {}
        norm = html_format.normalize_for_compare
        if norm(g.get("prompt")) != norm(o.get("prompt")):
            d["prompt"] = {"expected": g.get("prompt"), "got": o.get("prompt")}
        gopts = [norm(x.get("text")) for x in g.get("options") or []]
        oopts = [norm(x.get("text")) for x in o.get("options") or []]
        if gopts != oopts:
            d["options"] = {"expected": gopts, "got": oopts}
        if g.get("correct_option") != o.get("correct_option"):
            d["correct_option"] = {"expected": g.get("correct_option"), "got": o.get("correct_option")}
        if _source_tuples(g) != _source_tuples(o):
            d["source"] = {"expected": _source_tuples(g), "got": _source_tuples(o)}
        if d:
            diffs.append({"unit_id": uid, **d})
    return {
        "golden": expected_path,
        "questions_compared": len(set(gmap) & set(omap)),
        "questions_with_diffs": len(diffs),
        "diffs": diffs,
    }


def build_report(quiz: dict, errors: list[str], warnings: list[dict],
                 images_kept: bool, vision_used: bool) -> dict:
    st = pilot_validate.stats(quiz)
    with_html = sum(
        1 for u in pilot_validate.iter_units(quiz)
        if any(html_format.has_html(t) for t in pilot_validate.unit_texts(u))
    )
    return {
        "questionnaire_id": quiz.get("questionnaire_id"),
        "vision_used": vision_used,
        "debug_images_kept": images_kept,
        **st,
        "with_html_formatting": with_html,
        "validation_errors": errors,
        "question_warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_pilot(*, url=None, file=None, output=None, report=None, expected=None,
              vision=False, keep_debug_images=False, force=False,
              expected_count=EXPECTED_QUESTION_COUNT) -> int:
    images: list[Path] = []
    work_dir: Path | None = None
    try:
        pdf_path, quiz_id, source_url, work_dir = _resolve_input(url, file, force)
        print(f"  pilot: {quiz_id}")

        quiz = _baseline_extract(pdf_path, quiz_id, source_url)

        warnings: list[dict] = []
        if vision:
            images = render_pages(pdf_path, work_dir)
            print(f"  rendered {len(images)} page image(s)")
            warnings = _apply_vision(quiz, images)

        # Deterministic emphasis from the PDF (bold font + underline rect),
        # applied last so it annotates the final text. Works without --vision.
        emphasized = pdf_emphasis.apply_emphasis(quiz, pdf_emphasis.detect_emphasis(pdf_path))
        print(f"  emphasis: wrapped {emphasized} word(s) with <b>/<u>")

        _sanitize_quiz_html(quiz)
        errors = pilot_validate.validate_quiz(quiz, expected_count=expected_count)

        out_path = Path(output) if output else OUTPUT_ROOT / f"{quiz_id}.json"
        extract.write_json(out_path, quiz)

        rep = build_report(quiz, errors, warnings, images_kept=keep_debug_images, vision_used=vision)
        if expected:
            rep["evaluation"] = evaluate(quiz, expected)
        rep_path = Path(report) if report else OUTPUT_ROOT / f"{quiz_id}.report.json"
        extract.write_json(rep_path, rep)

        # Summary
        print(f"  output: {out_path}")
        print(f"  report: {rep_path}")
        print(f"  questions: {rep['questions_detected']} | 4-answers: {rep['with_four_answers']} | "
              f"correct: {rep['with_correct_answer']} | source: {rep['with_source']} | "
              f"html: {rep['with_html_formatting']} | suspicious: {rep['suspected_rtl_or_corruption']}")
        if expected:
            ev = rep["evaluation"]
            print(f"  eval vs golden: {ev['questions_with_diffs']} question(s) differ "
                  f"of {ev['questions_compared']} compared")
        if errors:
            print(f"  VALIDATION ERRORS ({len(errors)}):")
            for e in errors[:10]:
                print(f"    - {e}")
            return 2
        return 0

    except Exception as e:  # noqa: BLE001
        # VisionUnavailable and any other failure: clear message, non-zero exit.
        print(f"  pilot failed: {type(e).__name__}: {e}")
        return 1
    finally:
        # Delete rendered images by default, even on exception. Never the PDF.
        if images and not keep_debug_images:
            for img in images:
                try:
                    img.unlink()
                except OSError:
                    pass
            print("  rendered images deleted (use --keep-debug-images to keep)")
        elif images:
            print(f"  rendered images kept in {work_dir}")


def run_batch(ids, *, vision=False, keep_debug_images=False, force=False) -> int:
    """Process a curated list of questionnaire ids (no archive crawl) to test how
    the pipeline generalises. Writes per-file output/report and a batch summary
    table. Question count is not gated (files differ in length)."""
    import json

    discovered = {e["base"]: e for e in extract.discover_files()}
    rows: list[dict] = []
    for qid in ids:
        entry = discovered.get(qid)
        url = entry["url"] if entry else (extract.FILE_BASE + qid + ".pdf")
        rep_path = OUTPUT_ROOT / f"{qid}.report.json"
        print(f"=== {qid} ===")
        run_pilot(url=url, output=str(OUTPUT_ROOT / f"{qid}.json"), report=str(rep_path),
                  expected_count=None, vision=vision, keep_debug_images=keep_debug_images, force=force)
        try:
            rows.append(json.loads(rep_path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            rows.append({"questionnaire_id": qid, "error": "no report produced"})

    extract.write_json(OUTPUT_ROOT / "batch_summary.json", {"count": len(rows), "results": rows})
    print("\n=== BATCH SUMMARY ===")
    print(f"{'id':30} {'q':>3} {'4ans':>4} {'corr':>4} {'src':>4} {'html':>4} {'susp':>4} {'furn':>4}")
    for r in rows:
        print(f"{(r.get('questionnaire_id') or '?'):30} "
              f"{r.get('questions_detected', 0):>3} {r.get('with_four_answers', 0):>4} "
              f"{r.get('with_correct_answer', 0):>4} {r.get('with_source', 0):>4} "
              f"{r.get('with_html_formatting', 0):>4} {r.get('suspected_rtl_or_corruption', 0):>4} "
              f"{r.get('page_furniture_contamination', 0):>4}")
    print(f"\nbatch summary -> {OUTPUT_ROOT / 'batch_summary.json'}")
    return 0
