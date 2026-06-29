"""Build the vendored Tanach corpus used to clean embedded verse quotes.

Reads a full source JSONL (one verse per line with `text_with_niqqud`, `book`,
`chapter`, `verse`) and writes a trimmed, repo-committed corpus to
`data/tanach_verses.jsonl` (only the fields the resolver needs). The output is
committed so the extraction pipeline runs offline on any machine / CI.

Usage:
    python tools/build_tanach_corpus.py [SOURCE_JSONL]
Source defaults to the TANACH_CORPUS_SOURCE env var.

The Hebrew Bible text is public domain.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "tanach_verses.jsonl"


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TANACH_CORPUS_SOURCE")
    if not src or not Path(src).exists():
        print("source corpus not found; pass a path or set TANACH_CORPUS_SOURCE", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with OUT.open("w", encoding="utf-8") as out:
        for line in Path(src).open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            niqqud = (v.get("text_with_niqqud") or "").replace("׃", "").strip()
            if not niqqud:
                continue
            rec = {"book": v["book"], "chapter": v["chapter"], "verse": v["verse"], "niqqud": niqqud}
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} verses -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
