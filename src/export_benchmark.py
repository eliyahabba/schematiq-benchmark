"""Export accepted tasks in a method-neutral format for comparing table
extraction systems (question + documents -> table).

Every exported row has its document: rows whose document was not downloaded
and identified are left out of the evaluation table (the full published table
stays in the canonical file). Numbering columns (1, 2, 3, ...) are dropped.

  python3 export_benchmark.py <tasks.jsonl> <out_dir> [tiers=core]
Writes <out_dir>/tasks.jsonl, <out_dir>/tables/<id>.csv and a README.
"""
import csv, json, os, re, sys
import epmc

DOMAIN = {"arxiv": "computer science", "campbell": "social science", "environmental_evidence": "environment",
          "manual": "as given"}


ARXIV_DOMAIN = {"cs": "computer science", "eess": "electrical engineering and systems", "stat": "statistics",
                "astro-ph": "astrophysics", "hep-ex": "physics", "hep-ph": "physics", "hep-th": "physics",
                "quant-ph": "physics", "cond-mat": "physics", "nucl-th": "physics", "nucl-ex": "physics",
                "physics": "physics", "q-fin": "economics and finance", "econ": "economics and finance",
                "q-bio": "biology", "math": "mathematics"}
_CATS = None


def arxiv_category(tid):
    global _CATS
    if _CATS is None:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "arxiv_categories.json")
        _CATS = json.load(open(p)) if os.path.exists(p) else {}
    return _CATS.get(tid)


def domain_of(t, src):
    if t.get("source") == "arxiv":
        c = arxiv_category(t["task_id"]) or "cs"
        return ARXIV_DOMAIN.get(c.split(".")[0], ARXIV_DOMAIN.get(c, "other"))
    return DOMAIN.get(src, DOMAIN.get(t.get("source"), "biomedicine and health"))


def safe(tid):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tid)


def numbering(values):
    v = [x.strip() for x in values if x.strip()]
    return len(v) >= 4 and all(re.fullmatch(r"[A-Z]?\d{1,3}\.?", x) for x in v) and \
        [int(re.sub(r"\D", "", x)) for x in v] == sorted(int(re.sub(r"\D", "", x)) for x in v)


def table_notes(t):
    if t.get("source") != "europepmc" or t["table"].get("from") != "article":
        return None
    x = epmc.xml(t["task_id"]) or ""
    lab = t["table"]["label"]
    for m in re.finditer(r"<table-wrap\b.*?</table-wrap>", x, re.S):
        if lab and re.search(r"<label>\s*" + re.escape(lab) + r"\s*</label>", m.group(0)):
            foot = re.search(r"<table-wrap-foot>(.*?)</table-wrap-foot>", m.group(0), re.S)
            return epmc.strip(foot.group(1))[:3000] if foot else None
    return None


def export(t, tables_dir):
    cols = t["table"]["columns"]
    cc = t["table"]["citation_col"]
    rows = [r for r in t["rows"] if r.get("document")]
    keep = [j for j in range(len(cols)) if j == cc or not numbering([r["cells"][j] if j < len(r["cells"]) else "" for r in rows])]
    docs, out_rows = {}, []
    for r in rows:
        d = r["document"]
        did = r["doc_key"]
        docs.setdefault(did, {"document_id": did, "title": r.get("ref_title"), "doi": r.get("doi"),
                              "arxiv": r.get("arxiv_id"), "pmcid": r.get("pmcid"), "kind": d["kind"],
                              "url": d["url"], "sha256": d["sha256"], "bytes": d["bytes"], "file": d["file"],
                              "licence": d.get("licence"), "identity_check": d["identity"]})
        out_rows.append({"document_id": did,
                         "cells": {cols[j]: (r["cells"][j] if j < len(r["cells"]) else "") for j in keep}})
    q = t["question"]
    src = t.get("stratum") or t.get("source")
    rec = {
        "task_id": t["task_id"], "source": t.get("source"), "stratum": src,
        "domain": domain_of(t, src), "arxiv_category": arxiv_category(t["task_id"]) if t.get("source") == "arxiv" else None,
        "question": q["text"], "question_provenance": q.get("provenance") + ("+rewritten" if q.get("rewritten") else ""),
        "question_author_text": q.get("author_text") or q["text"],
        "question_rewrite": q.get("rewritten"),
        # arXiv aims often lean on the title ("this survey maps ... that gap"); the
        # paper's own title and its own aim sentence together are self-contained
        "question_with_topic": (q["text"] if q.get("rewritten") else f"{q['topic']}. {q['text']}" if q.get("topic") else q["text"]),
        "question_registered_before_table": t.get("question_first"),
        "paper": {"title": t.get("title"), "journal": t.get("journal"), "year": t.get("year"),
                  "id": t["task_id"], "url": t.get("url") or (f"https://europepmc.org/article/PMC/{t['task_id'][3:]}"
                                                              if t["task_id"].startswith("PMC") else None),
                  "licence": t.get("license")},
        "schema": {"columns": [cols[j] for j in keep], "document_column": cols[cc] if cc < len(cols) else None,
                   "caption": t["table"].get("caption"), "notes": table_notes(t),
                   "table_source": t["table"].get("from"), "merged_from": t["table"].get("merged_from")},
        "rows": out_rows, "documents": list(docs.values()),
        "counts": {"rows_in_published_table": t["counts"]["rows"], "rows_exported": len(out_rows),
                   "documents": len(docs), "columns": len(keep)},
        "quality": {"tier": t["tier"], "grounding_rate": (t.get("grounding") or {}).get("rate"),
                    "suspect_rows": (t.get("grounding") or {}).get("suspect_rows"),
                    "judged": bool(t.get("judgment") and t["judgment"].get("verdict")),
                    "verdict": (t.get("judgment") or {}).get("verdict"),
                    "issues": (t.get("judgment") or {}).get("issues")},
    }
    with open(os.path.join(tables_dir, safe(t["task_id"]) + ".csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["document_id"] + rec["schema"]["columns"])
        for r in out_rows:
            w.writerow([r["document_id"]] + [r["cells"][c] for c in rec["schema"]["columns"]])
    return rec


if __name__ == "__main__":
    inp, out = sys.argv[1], sys.argv[2]
    tiers = set((sys.argv[3] if len(sys.argv) > 3 else "core").split(","))
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    n = 0
    with open(os.path.join(out, "tasks.jsonl"), "w", encoding="utf-8") as f:
        for l in open(inp, encoding="utf-8"):
            t = json.loads(l)
            if t["tier"] in tiers:
                f.write(json.dumps(export(t, os.path.join(out, "tables")), ensure_ascii=False) + "\n")
                n += 1
    print(f"{n} tasks exported to {out}")
