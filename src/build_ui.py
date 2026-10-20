#!/usr/bin/env python3
"""Build the single-file task browser from the canonical task file.

Only formats what finalize.py already persisted; no metric is computed here.
  python3 src/build_ui.py data/build/tasks.jsonl ui/template.html ui/browser.html <extra export-format tasks.jsonl>
"""
import json, sys

ORDER = {"core": 0, "extended": 1, "excluded": 2}


def stage_text(reg):
    s = reg.get("stage_at_registration")
    if not s:
        return "The PROSPERO record has no stage-of-review table."
    ext = s.get("extraction") or {}
    scr = s.get("screening") or {}
    if ext.get("started") or ext.get("completed"):
        return "At registration the authors reported that data extraction had already started."
    if scr.get("started"):
        lead = "screening had started"
    elif s.get("any_started"):
        lead = "searching had started"
    else:
        return "At registration the authors reported that no stage of the review had started."
    return f"At registration the authors reported that {lead} and data extraction had not started."


SOURCE = {"frontiers_2026_first_sample": "Europe PMC", "campbell": "Campbell (social science)",
          "environmental_evidence": "Environmental Evidence", "cochrane": "Cochrane",
          "bmc_systematic_reviews": "BMC Systematic Reviews", "arxiv": "arXiv", "manual": "Added by hand",
          "scdb": "U.S. Supreme Court Database", "retraction_watch": "Retraction Watch database",
          "schematize": "Schematize study (Polish court judgments)", "ccp": "Comparative Constitutions Project"}


def source_label(t):
    s = t.get("stratum") or t.get("source") or ""
    if t.get("source") == "arxiv":
        import export_benchmark
        return "arXiv, " + export_benchmark.domain_of(t, s)
    return "Europe PMC" if s.startswith("biomed") else SOURCE.get(s, s or "unknown")



def slim(t):
    reg = t.get("registration") or {}
    q = t["question"]
    return {
        "id": t["task_id"], "title": t["title"], "journal": t["journal"], "year": t["year"],
        "license": t.get("license"),
        "source": source_label(t), "url": t.get("url"),
        "q": q["text"], "q_prov": q.get("provenance"), "q_source": q.get("source"),
        "q_author": q.get("author_text") if q.get("rewritten") else None,
        "q_changed": q.get("changed_after_registration"), "q_latest": q.get("latest_text"),
        "abs": q.get("abstract_objective") if q.get("provenance") != "abstract" else None,
        "q_registered": q.get("registered_text"),
        "prospero": {"id": q.get("prospero_id"), "url": q.get("prospero_url"),
                     "version": ".".join(str(x) for x in (q.get("version") or []))},
        "reg": ({"registered": reg.get("registered"), "received": reg.get("received"),
                 "gap": reg.get("days_registered_to_received"), "dates_from": reg.get("dates_from"),
                 "stage_text": stage_text(reg)} if reg and q.get("provenance") == "prospero_first_version" else None),
        "qf": t.get("question_first"),
        "table_from": t["table"].get("from", "article"), "merged_from": t["table"].get("merged_from") or [],
        "tier": t["tier"], "reasons": t["tier_reasons"], "judg": t.get("judgment"),
        "ground": t.get("grounding"),
        "counts": t["counts"], "columns": t["table"]["columns"], "caption": t["table"]["caption"],
        "cite": t["table"]["citation_col"], "protocol": t.get("protocol") or {},
        "rows": [{"c": r["cells"], "a": r["access"],
                  "k": (r.get("document") or {}).get("kind"), "u": (r.get("document") or {}).get("url"),
                  "d": r.get("doi")} for r in t["rows"]],
    }


def slim_export(e):
    """A task that exists only in export format (database and question-set tasks)."""
    cols = (e.get("schema") or {}).get("columns") or []
    j = {"verdict": e["quality"].get("verdict"), "issues": e["quality"].get("issues") or [],
         "judged_by": e["quality"].get("judged_by") or "Claude (AI)"}
    n = e["counts"].get("documents", 0)
    return {
        "id": e["task_id"], "title": e["paper"]["title"], "journal": e["paper"].get("journal"), "year": e["paper"].get("year"),
        "license": e["paper"].get("licence"), "source": SOURCE.get(e.get("source"), e.get("source")), "url": e["paper"].get("url"),
        "q": e["question"], "q_prov": e.get("question_provenance"), "q_source": None,
        "q_author": e.get("question_author_text") if e.get("question_author_text") != e["question"] else None,
        "q_changed": False, "q_latest": None, "abs": None, "q_registered": None,
        "prospero": {"id": None, "url": None, "version": ""}, "reg": None, "qf": None,
        "table_from": e.get("task_type"), "merged_from": [],
        "tier": "core", "reasons": [], "judg": j, "ground": None,
        "counts": {"rows": e["counts"].get("rows_exported", 0) or n, "columns": len(cols), "documents_downloaded": n,
                   "rows_downloaded": n, "by_access": {"downloaded": n}, "cell_fill": 1.0},
        "columns": cols, "caption": (e.get("schema") or {}).get("caption"), "cite": 0, "protocol": {},
        "rows": [{"c": [r["cells"].get(c, "") for c in cols], "a": "downloaded", "k": "txt", "u": None, "d": None}
                 for r in e.get("rows", [])],
        "task_type": e.get("task_type"), "language": e.get("language"),
        "q_tag": {"scdb": "Written from the database's stated purpose", "retraction_watch": "Written from a published study's question",
                  "ccp": "Written from a published CCP study",
                  "schematize": "Written from the researcher's request (Polish original below)"}.get(e.get("source")),
        "expert_questions": e.get("expert_questions"),
        "ref_schemas": {m: len(v) for m, v in (e.get("reference_schemas") or {}).items()},
        "dialogue": e.get("clarification_dialogue"),
        "analysis": e.get("analysis_questions") or [],
    }


if __name__ == "__main__":
    inp, tpl, outp = sys.argv[1:4]
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    T.sort(key=lambda t: (ORDER.get(t["tier"], 9), -t["counts"]["documents_downloaded"]))
    extra = []
    for p in sys.argv[4:]:
        extra += [slim_export(json.loads(l)) for l in open(p, encoding="utf-8")]
    data = json.dumps(extra + [slim(t) for t in T], ensure_ascii=False).replace("</", "<\\/")
    html = open(tpl, encoding="utf-8").read().replace("__DATA__", data)
    open(outp, "w", encoding="utf-8").write(html)
    print(f"{len(T)} tasks -> {outp} ({len(html)//1024} KB)")
