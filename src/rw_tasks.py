"""Research-database tasks from the Retraction Watch database (open via Crossref,
gitlab.com/crossref/retraction-watch-data).

Research question, after Fang, Steen and Casadevall (2012, PNAS), who coded
retraction notices to find out why papers are retracted: what are the reasons
for retraction, and how often do they involve misconduct rather than error?
One task per journal group. Documents are the retraction notices themselves,
from the PMC open-access subset (Europe PMC full text). Gold cells are the
database's fields, including the multi-valued "Reason" and the free-text
"Notes"; the database's coders also used information beyond the notice.

  python3 rw_tasks.py <retraction_watch.csv> <docs_dir> <out.jsonl> [per_task]
"""
import csv, hashlib, html, json, os, random, re, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import epmc
from net import http_get, CACHE

csv.field_size_limit(sys.maxsize)
GROUPS = {
    "plos_one": ("PLOS ONE", lambda r: r["Journal"] == "PLoS One"),
    "hindawi": ("Hindawi journals", lambda r: "Hindawi" in r["Publisher"]),
    "frontiers_scirep": ("Frontiers journals and Scientific Reports",
                         lambda r: r["Journal"].startswith("Frontiers") or r["Journal"] == "Scientific Reports"),
}
COLS = [("Retracted article", "Title"), ("Journal", "Journal"), ("Subject", "Subject"), ("Country", "Country"),
        ("Article type", "ArticleType"), ("Original paper date", "OriginalPaperDate"), ("Retraction date", "RetractionDate"),
        ("Retraction nature", "RetractionNature"), ("Reasons", "Reason"), ("Notes", "Notes")]


def idconv(pmids):
    p = os.path.join(CACHE, "oa_meta", "idconv_pmid.json")
    cache = json.load(open(p)) if os.path.exists(p) else {}
    todo = [x for x in pmids if x not in cache]
    for k in range(0, len(todo), 150):
        chunk = todo[k:k + 150]
        st, body = http_get("https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?format=json&tool=schematiq-benchmark&ids="
                            + ",".join(chunk), timeout=60)
        got = {}
        if body:
            try:
                for rec in json.loads(body).get("records", []):
                    if rec.get("pmcid"):
                        got[str(rec.get("pmid"))] = rec["pmcid"]
            except ValueError:
                pass
        for x in chunk:
            cache[x] = got.get(x)
        time.sleep(0.4)
    json.dump(cache, open(p, "w"))
    return cache


def notice_text(pmcid):
    x = epmc.xml(pmcid)
    if not x:
        return None
    body = re.search(r"<body\b.*?</body>", x, re.S)
    t = epmc.strip((epmc.title(x) or "") + " \n" + (body.group(0) if body else re.sub(r"<front\b.*?</front>", "", x, flags=re.S)))
    return t if re.search(r"retract", t, re.I) else None


def clean_date(s):
    m = re.match(r"(\d+)/(\d+)/(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else (s or "")


if __name__ == "__main__":
    src, docs, outp = sys.argv[1:4]
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    R = list(csv.DictReader(open(src, encoding="utf-8", errors="replace")))
    rng = random.Random(20260929)
    os.makedirs(os.path.join(docs, "retractions"), exist_ok=True)
    out = []
    for gid, (gname, f) in GROUPS.items():
        pool = [r for r in R if f(r) and r["RetractionNature"] == "Retraction" and r["RetractionPubMedID"] not in ("", "0")]
        rng.shuffle(pool)
        conv = idconv([r["RetractionPubMedID"] for r in pool[:per * 3]])
        cand = [r for r in pool[:per * 3] if conv.get(r["RetractionPubMedID"])]
        rows, documents = [], []
        with ThreadPoolExecutor(max_workers=6) as ex:
            for r, text in zip(cand, ex.map(lambda r: notice_text(conv[r["RetractionPubMedID"]]), cand)):
                if not text or len(rows) >= per:
                    continue
                b = text.encode("utf-8")
                pmc = conv[r["RetractionPubMedID"]]
                fn = f"retractions/{pmc}.txt"
                open(os.path.join(docs, fn), "wb").write(b)
                did = "pmc:" + pmc
                documents.append({"document_id": did, "title": "Retraction: " + r["Title"][:180], "kind": "txt",
                                  "url": f"https://europepmc.org/article/PMC/{pmc[3:]}", "pmcid": pmc,
                                  "doi": r["RetractionDOI"] or None, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b),
                                  "file": fn, "licence": "PMC open-access subset", "identity_check": "PubMed id of the notice"})
                cells = {}
                for name, var in COLS:
                    v = html.unescape(r.get(var) or "").strip().strip(";")
                    if var in ("OriginalPaperDate", "RetractionDate"):
                        v = clean_date(v)
                    if var in ("Reason", "Subject"):
                        v = "; ".join(x.strip().lstrip("+") for x in v.split(";") if x.strip())
                    cells[name] = v
                rows.append({"document_id": did, "cells": cells})
        q = (f"What are the reasons for retraction of articles in {gname}, and how often do they involve misconduct "
             f"(fabrication, falsification, plagiarism, fake peer review, paper mills) rather than honest error?")
        out.append({
            "task_id": f"retractions:{gid}", "task_type": "database", "source": "retraction_watch", "stratum": "retraction_watch",
            "domain": "meta-research", "language": "en", "question": q, "question_provenance": "published_study+rewritten",
            "question_author_text": "Fang, Steen and Casadevall (2012, PNAS): Misconduct accounts for the majority of retracted scientific publications.",
            "paper": {"title": f"Retraction Watch database, {gname} sample", "journal": "Retraction Watch / Crossref", "year": "2026",
                      "id": f"retractions:{gid}", "url": "https://gitlab.com/crossref/retraction-watch-data", "licence": "open (Crossref)"},
            "schema": {"columns": [c for c, _ in COLS], "document_column": "Retracted article",
                       "caption": f"Random sample of {len(rows)} retractions in {gname}, as coded by Retraction Watch",
                       "notes": "Reasons are Retraction Watch's categories; the coders also use information beyond the notice.",
                       "table_source": "retraction_watch", "merged_from": None},
            "rows": rows, "documents": documents,
            "counts": {"rows_in_published_table": len(pool), "rows_exported": len(rows), "documents": len(documents), "columns": len(COLS)},
            "quality": {"tier": "core", "grounding_rate": None, "suspect_rows": None, "judged": False, "verdict": None,
                        "issues": ["some reasons come from investigations, not from the notice text"]},
        })
        print(f"{gid}: {len(rows)} notices with text (pool {len(pool)}, {len(cand)} with a PMC notice)", flush=True)
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out))
