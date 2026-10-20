"""Assemble task records: registered question + registration evidence +
gold table from the current table layer + one linked document per row.

  python3 registration_rules.py <registration.jsonl> <old files...> > tasks_base.jsonl
"""
import json, re, sys
import epmc, prospero, quality, tables

OBJ = quality.OBJ_VERB
PLACEHOLDER = re.compile(r"^\W*(n/?a|none|not applicable|to be (confirmed|completed|added)|tbc|tbd)\W*$", re.I)


def check_registered_question(q):
    """Light gate for the registry field. The regex gates in quality.py were
    built for sentences mined from abstracts; a registry field has different
    failure modes (empty, placeholder, background text instead of an aim)."""
    s = (q or "").strip()
    if len(s) < 40:
        return False, "too_short"
    if PLACEHOLDER.match(s):
        return False, "placeholder"
    if not (OBJ.search(s) or "?" in s):
        return False, "no_objective_or_question"
    return True, "long" if len(s) > 700 else "ok"


def pick_ref(row):
    """One document per row. If a row cites several references, prefer the one
    whose first author appears in the first cells."""
    refs = row["refs"]
    if not refs:
        return None, 0
    head = " ".join(row["cells"][:2]).lower()
    for i, r in enumerate(refs):
        fa = (r.get("first_author") or "").lower()
        if fa and fa in head:
            return i, len(refs)
    return 0, len(refs)


def old_question(old):
    if "question" in old:
        return old["question"]
    rq = old.get("research_question") or {}
    return rq.get("objective_section") or rq.get("objective_sentence")


def build(reg, old):
    tid, crd = reg["task_id"], reg["crd"]
    rec = prospero.fetch(crd)
    first, latest = prospero.summarize(rec, "first"), prospero.summarize(rec)
    q = first["review_question"]
    x = epmc.xml(tid)
    cands, refs = tables.candidate_tables(x, q)
    t = cands[0] if cands else None
    q_ok, q_why = check_registered_question(q)
    task = {
        "task_id": tid, "pmcid": tid, "doi": old.get("doi"), "title": old.get("title"),
        "journal": old.get("journal"), "year": old.get("year"), "license": old.get("license"),
        "question": {
            "text": q, "source": "PROSPERO registration, first version",
            "prospero_id": crd, "prospero_url": reg["prospero_url"],
            "version": first["version"], "caption": first["review_question_caption"],
            "changed_after_registration": reg["question_changed"],
            "latest_text": latest["review_question"] if reg["question_changed"] else None,
            "abstract_objective": old_question(old),
        },
        "protocol": {k: first.get(k) for k in (
            "title", "rationale", "condition", "population", "intervention", "comparator",
            "study_design", "context", "main_outcomes", "additional_outcomes", "data_extraction")},
        "registration": {k: reg.get(k) for k in (
            "verdict", "owned", "crd_regions", "title_sim", "author_hits", "n_article_authors",
            "registered", "first_submitted", "received", "accepted", "dates_from",
            "days_registered_to_received", "stage_at_registration", "n_versions", "template")},
        "gates": {"question": q_why if q_ok else "fail:" + q_why},
    }
    task["registration"]["author_hits"] = len(reg.get("author_hits") or [])
    if not t:
        task["gates"]["table"] = "fail:no_table"
        task["table"], task["rows"] = None, []
        return task
    task["table"] = {k: t[k] for k in ("label", "caption", "columns", "n_rows", "citation_col",
                                       "citation_coverage", "positive_caption")}
    task["gates"]["table"] = t["table_gate"]
    task["gates"]["lexical_alignment"] = {"score": t["alignment"], "hits": t["alignment_hits"]}
    rows = []
    for i, r in enumerate(t["rows"]):
        k, n = pick_ref(r)
        ref = r["refs"][k] if k is not None else {}
        rid = r["ref_ids"][k] if k is not None else None
        rows.append({"i": i, "cells": r["cells"], "matched_by": r["matched_by"],
                     "ref_id": rid, "n_refs_in_row": n,
                     "doi": (ref.get("doi") or "").lower() or None, "pmid": ref.get("pmid"),
                     "pmcid": ref.get("pmcid"), "ref_title": ref.get("title"),
                     "ref_year": ref.get("year"), "first_author": ref.get("first_author"),
                     "citation": ref.get("raw")})
    task["rows"] = rows
    return task


if __name__ == "__main__":
    regs = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
    old = {}
    for p in sys.argv[2:]:
        for l in open(p, encoding="utf-8"):
            o = json.loads(l)
            old.setdefault(o["task_id"], o)
    for reg in regs:
        print(json.dumps(build(reg, old[reg["task_id"]]), ensure_ascii=False))
