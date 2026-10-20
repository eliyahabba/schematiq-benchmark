"""Merge download results, licences, registration evidence and judgments into
the canonical task file, and assign tiers.

  python3 finalize.py <tasks_oa.jsonl> <docs/manifest.jsonl> <judgments.json|-> <out.jsonl>

Rules (questions written after the table are accepted and labelled):
  * core: usable question, table gate ok, one row per document, and at least
    MIN_DOCS documents actually downloaded and identified;
  * extended: as core, but judged to cover the question only partly;
  * excluded: anything else, with reasons.
Whether the question was registered before the table is a label
(question_first), not a gate. A registered question that the published review
drifted away from is replaced by the review's own abstract objective.
"""
import json, os, sys
from collections import Counter
from fetch_docs import doc_key

MIN_GAP_DAYS, MIN_DOCS = 60, 5
EMPTY = {"", "-", "\u2013", "\u2014", "NA", "N/A", "NR", "N/S", "NS"}


def access(r, m):
    if m and m.get("status") == "ok":
        return "downloaded"
    if not r.get("ref_id") and not r.get("arxiv_id") and not r.get("doi"):
        return "unlinked"
    if not (r.get("doi") or r.get("pmid") or r.get("pmcid") or r.get("arxiv_id")):
        return "unresolved_citation"
    ep, oa = r.get("europepmc") or {}, r.get("openalex") or {}
    if r.get("pmcid") and ep.get("isOpenAccess") == "N":
        return "free_to_read_not_oa"
    if (oa.get("is_oa") or r.get("arxiv_id")) and m and m.get("status") == "failed":
        return "oa_but_blocked"
    if oa.get("is_oa"):
        return "oa_no_file_url"
    if oa:
        return "not_oa"
    return "no_metadata"


def licence(r, m):
    if not m or m.get("status") != "ok":
        return None
    if m["url"].startswith(("wiley-tdm:", "elsevier-api:")) and not (r.get("openalex") or {}).get("is_oa"):
        return "subscription (publisher TDM API; do not redistribute)"
    if m["kind"] == "xml":
        return (r.get("europepmc") or {}).get("license")
    for l in (r.get("openalex") or {}).get("locations", []):
        if l.get("pdf_url") == m["url"]:
            return l.get("license")
    return (r.get("openalex") or {}).get("best_license") or ("arxiv" if "arxiv.org" in m["url"] else None)


def question_first(t):
    reg = t.get("registration")
    if not reg or t["question"].get("provenance") != "prospero_first_version":
        return None
    v, gap = reg.get("verdict"), reg.get("days_registered_to_received")
    if v == "preregistered" and gap is not None and gap >= MIN_GAP_DAYS:
        return "verified"
    return "short_gap" if v == "preregistered" else "registered_late"


def one_row_per_document(rows):
    keys = [r["doc_key"] for r in rows if r["doc_key"]]
    dup = sum(c - 1 for c in Counter(keys).values() if c > 1)
    multi = sum(1 for r in rows if r.get("n_refs_in_row", 1) > 1)
    n = max(1, len(rows))
    return dup / n <= 0.2 and multi / n <= 0.2, {"duplicate_document_rows": dup, "multi_reference_rows": multi}


if __name__ == "__main__":
    inp, manp, judgp, outp = sys.argv[1:5]
    man = {}
    for l in open(manp):
        m = json.loads(l)
        man[m["key"]] = m
    judg = json.load(open(judgp)) if judgp != "-" else {}
    rq_p = os.path.join(os.path.dirname(os.path.abspath(judgp)) if judgp != "-" else ".", "questions_rewritten.json")
    rewritten = json.load(open(rq_p)) if os.path.exists(rq_p) else {}
    import re as _re
    EMAIL_COL = _re.compile(r"e-?mail|corresponding author e", _re.I)
    EMAIL_VAL = _re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    out = []
    for l in open(inp, encoding="utf-8"):
        t = json.loads(l)
        rows = t["rows"]
        # some coded databases carry the authors' e-mail addresses: never keep them
        cols = t["table"]["columns"]
        drop = {j for j, c in enumerate(cols) if EMAIL_COL.search(c) or
                sum(1 for r in rows if j < len(r["cells"]) and EMAIL_VAL.search(r["cells"][j] or "")) > 0.3 * max(1, len(rows))}
        if drop:
            keep = [j for j in range(len(cols)) if j not in drop]
            cc = t["table"]["citation_col"]
            t["table"]["columns"] = [cols[j] for j in keep]
            t["table"]["citation_col"] = keep.index(cc) if cc in keep else 0
            for r in rows:
                r["cells"] = [r["cells"][j] if j < len(r["cells"]) else "" for j in keep]
        for r in rows:
            r["cells"] = [EMAIL_VAL.sub("[e-mail removed]", c or "") for c in r["cells"]]
        for r in rows:
            k = doc_key(r)
            m = man.get(k) if k else None
            r["access"] = access(r, m)
            r["document"] = ({"kind": m["kind"], "url": m["url"], "identity": m["identity"],
                              "sha256": m["sha256"], "bytes": m["bytes"], "file": m["file"],
                              "licence": licence(r, m)} if r["access"] == "downloaded" else None)
            r["doc_key"] = k
        down = [r for r in rows if r["access"] == "downloaded"]
        nc = len(t["table"]["columns"])
        filled = sum(1 for r in rows for j in range(nc)
                     if j < len(r["cells"]) and str(r["cells"][j]).strip() not in EMPTY)
        dpr, dpr_stats = one_row_per_document(rows)
        t["counts"] = {"rows": len(rows), "columns": nc, "rows_downloaded": len(down),
                       "documents_downloaded": len({r["doc_key"] for r in down}),
                       "by_access": dict(Counter(r["access"] for r in rows)),
                       "cell_fill": round(filled / (len(rows) * nc), 3) if rows and nc else 0.0,
                       **dpr_stats}
        t["question_first"] = question_first(t)
        rw = rewritten.get(t["task_id"])
        if rw and rw.get("author_text", "").strip() == t["question"]["text"].strip():
            # a research question rewritten from the paper's title and abstract (rules in QUESTIONS.md);
            # the authors' own text stays alongside it
            t["question"]["author_text"] = t["question"]["text"]
            t["question"]["text"] = rw["question"]
            t["question"]["rewritten"] = {k: rw[k] for k in ("by", "based_on", "checks") if k in rw}
        j = judg.get(t["task_id"])
        if j:
            t["judgment"] = j
            if j["scope_drift"] == "major" and t["question"].get("abstract_objective"):
                q = t["question"]
                q["registered_text"], q["text"] = q["text"], q["abstract_objective"]
                q["provenance"], q["source"] = "abstract", "abstract of the review (registered question drifted)"
                t["question_first"] = None
            dpr = j["document_per_row"]
        reasons = []
        judged_ok = bool(j and j.get("verdict") in ("worthy", "worthy_with_issues", "partly"))
        if not judged_ok and not str(t["gates"].get("question", "")).startswith(("ok", "long")):
            # the regex gate was built on biomedical abstracts; a judge's reading overrides it
            reasons.append("question failed the gate: " + str(t["gates"].get("question")))
        if j and j.get("verdict") == "not_worthy":
            reasons.append("judged not worthy: " + "; ".join(j.get("issues") or []))
        elif j and not j["question_usable"]:
            reasons.append("question not usable")
        if t["gates"].get("table") != "ok":
            reasons.append("table gate: " + str(t["gates"].get("table")))
        if not dpr:
            reasons.append("table is not one row per document")
        if t["counts"]["documents_downloaded"] < MIN_DOCS:
            reasons.append(f"only {t['counts']['documents_downloaded']} documents downloaded")
        partly = bool(j and (j["table_relates"] == "partly" or j.get("verdict") == "partly"))
        t["tier"] = "excluded" if reasons else ("extended" if partly else "core")
        if partly:
            reasons.append("table only partly covers the question")
        t["tier_reasons"] = reasons
        out.append(t)
    with open(outp, "w", encoding="utf-8") as f:
        for t in out:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"{len(out)} tasks -> {outp}; tiers {dict(Counter(t['tier'] for t in out))}")
