"""Turn hand-collected examples into benchmark tasks.

Each input file follows manual_task.example.json: a question and where it
came from, column names, and one row per document with at least one of
doi / arxiv / pmcid / url for the document. The output is in the canonical
task format, so resolve_oa.py, fetch_docs.py, finalize.py and the browser
treat it like any other task (same download and identity checks).

  python3 import_manual.py <out.jsonl> <task.json> [<task.json> ...]
"""
import json, sys


def convert(m):
    cols = m["columns"]
    rows = []
    for i, r in enumerate(m["rows"]):
        d = r.get("document") or {}
        cells = [str(c) for c in r["cells"]] + [""] * (len(cols) - len(r["cells"]))
        rows.append({"i": i, "cells": cells[:len(cols)], "matched_by": "manual",
                     "ref_id": d.get("doi") or d.get("arxiv") or d.get("pmcid") or d.get("url"),
                     "n_refs_in_row": 1, "doi": (d.get("doi") or "").lower() or None, "pmid": d.get("pmid"),
                     "pmcid": d.get("pmcid"), "arxiv_id": d.get("arxiv"), "direct_url": d.get("url"),
                     "ref_title": d.get("title"), "ref_year": d.get("year"), "first_author": None,
                     "citation": d.get("title")})
    return {"task_id": m["task_id"], "source": "manual", "stratum": "manual", "pmcid": None,
            "url": m.get("source_url"), "title": m.get("title"), "journal": m.get("domain"),
            "year": m.get("year"), "doi": None, "license": m.get("license"),
            "question": {"text": m["question"], "provenance": "manual", "source": m.get("question_source"),
                         "prospero_id": None, "prospero_url": None, "version": None,
                         "changed_after_registration": False, "abstract_objective": None},
            "protocol": None, "registration": None,
            "gates": {"question": "ok" if len(m["question"].strip()) >= 20 else "fail:too_short",
                      "table": "ok" if len(rows) >= 4 and len(cols) >= 3 else "fail:too_small"},
            "table": {"label": "manual", "caption": m.get("title"), "columns": cols, "n_rows": len(rows),
                      "citation_col": m.get("citation_column", 0), "citation_coverage": 1.0,
                      "positive_caption": False, "from": "manual", "merged_from": None},
            "rows": rows}


if __name__ == "__main__":
    out = sys.argv[1]
    with open(out, "w", encoding="utf-8") as f:
        for p in sys.argv[2:]:
            f.write(json.dumps(convert(json.load(open(p, encoding="utf-8"))), ensure_ascii=False) + "\n")
    print(f"{len(sys.argv) - 2} manual tasks -> {out}")
