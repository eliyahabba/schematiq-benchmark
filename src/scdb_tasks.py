"""Research-database tasks from the U.S. Supreme Court Database (SCDB 2025 Release 01)
with the opinions from the Caselaw Access Project (static.case.law).

The SCDB was built to classify every justice's vote in argued cases so that
judicial decision-making can be studied; one task per Chief Justice era asks
that question of a random sample of the era's cases. Rows are cases; the gold
cells are SCDB codes turned into their codebook labels. Only cases whose
opinion text was found and downloaded are kept.

  python3 scdb_tasks.py <scdb_case_centered.csv> <docs_dir> <out.jsonl> [per_era]
"""
import csv, hashlib, json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE

L = {
 "decisionType": {"1": "opinion of the court (orally argued)", "2": "per curiam (no oral argument)", "4": "decree",
                  "5": "equally divided vote", "6": "per curiam (orally argued)", "7": "judgment of the Court (orally argued)",
                  "8": "seriatim"},
 "issueArea": {"1": "Criminal Procedure", "2": "Civil Rights", "3": "First Amendment", "4": "Due Process", "5": "Privacy",
               "6": "Attorneys", "7": "Unions", "8": "Economic Activity", "9": "Judicial Power", "10": "Federalism",
               "11": "Interstate Relations", "12": "Federal Taxation", "13": "Miscellaneous", "14": "Private Action"},
 "decisionDirection": {"1": "conservative", "2": "liberal", "3": "unspecifiable"},
 "caseDisposition": {"1": "stay, petition, or motion granted", "2": "affirmed", "3": "reversed", "4": "reversed and remanded",
                     "5": "vacated and remanded", "6": "affirmed and reversed (or vacated) in part",
                     "7": "affirmed and reversed (or vacated) in part and remanded", "8": "vacated",
                     "9": "petition denied or appeal dismissed", "10": "certification to or from a lower court", "11": "no disposition"},
 "partyWinning": {"0": "petitioning party lost", "1": "petitioning party won", "2": "unclear"},
 "precedentAlteration": {"0": "no", "1": "yes"},
 "declarationUncon": {"1": "none", "2": "act of Congress unconstitutional", "3": "state or territorial law unconstitutional",
                      "4": "municipal or local ordinance unconstitutional"},
}
COLS = [("Case", None), ("Date of decision", "dateDecision"), ("Term", "term"), ("Decision type", "decisionType"),
        ("Issue area", "issueArea"), ("Ideological direction of the decision", "decisionDirection"),
        ("Disposition", "caseDisposition"), ("Winning party", "partyWinning"), ("Precedent altered", "precedentAlteration"),
        ("Declared unconstitutional", "declarationUncon"), ("Votes in the majority", "majVotes"),
        ("Votes in dissent", "minVotes")]
ERAS = {"Vinson": "1946-1952", "Warren": "1953-1968", "Burger": "1969-1985", "Rehnquist": "1986-2004", "Roberts": "2005-2024"}
CAP = "https://static.case.law/us/{vol}/"


import threading
_VOL, _VLOCK = {}, threading.Lock()


def _save(p, d):
    # atomic write: several threads may want the same file
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{threading.get_ident()}.part"
    json.dump(d, open(tmp, "w"))
    os.replace(tmp, p)


def volume(vol):
    with _VLOCK:
        lock = _VOL.setdefault(("lock", vol), threading.Lock())
    with lock:
        if vol in _VOL:
            return _VOL[vol]
        p = os.path.join(CACHE, "cap", f"us_{vol}.json")
        d = None
        if os.path.exists(p):
            try:
                d = json.load(open(p))
            except ValueError:
                d = None
        if d is None:
            st, body = http_get(CAP.format(vol=vol) + "CasesMetadata.json", timeout=60)
            if body and st == 200:
                try:
                    d = json.loads(body); _save(p, d)
                except ValueError:
                    d = None
        _VOL[vol] = d
        return d


def opinion_text(vol, file_name):
    p = os.path.join(CACHE, "cap", f"us_{vol}_{file_name}.json")
    d = None
    if os.path.exists(p):
        try:
            d = json.load(open(p))
        except ValueError:
            d = None
    if d is None:
        st, body = http_get(CAP.format(vol=vol) + f"cases/{file_name}.json", timeout=60)
        if not body or st != 200:
            return None
        try:
            d = json.loads(body)
        except ValueError:
            return None
        _save(p, d)
    cb = d.get("casebody") or {}
    parts = [cb.get("head_matter") or ""]
    for o in cb.get("opinions") or []:
        parts.append(f"[{o.get('type', 'opinion')}] {o.get('author') or ''}\n{o.get('text') or ''}")
    return "\n\n".join(x for x in parts if x).strip()


def fetch_case(r):
    m = re.match(r"(\d+) U\.S\. (\d+)", r.get("usCite") or "")
    if not m:
        return r, None
    vol, page = m.group(1), m.group(2)
    meta = volume(vol)
    if not meta:
        return r, None
    hit = next((c for c in meta if any(x.get("cite") == r["usCite"] for x in c.get("citations", []))), None)
    if not hit:
        return r, None
    return r, opinion_text(vol, hit["file_name"])


if __name__ == "__main__":
    src, docs, outp = sys.argv[1:4]
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 200
    R = [r for r in csv.DictReader(open(src, encoding="latin-1")) if r.get("usCite")]
    rng = random.Random(20260929)
    os.makedirs(os.path.join(docs, "scdb"), exist_ok=True)
    out = []
    for chief, years in ERAS.items():
        pool = [r for r in R if r["chief"] == chief]
        rng.shuffle(pool)
        rows, documents, tried = [], [], 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for k in range(0, len(pool), 60):
                if len(rows) >= per:
                    break
                for r, text in ex.map(fetch_case, pool[k:k + 60]):
                    tried += 1
                    if not text or len(text) < 1500 or len(rows) >= per:
                        continue
                    b = text.encode("utf-8")
                    fn = f"scdb/{r['caseId']}.txt"
                    open(os.path.join(docs, fn), "wb").write(b)
                    did = "scdb:" + r["caseId"]
                    documents.append({"document_id": did, "title": r["caseName"][:200], "kind": "txt",
                                      "url": "https://static.case.law/", "sha256": hashlib.sha256(b).hexdigest(),
                                      "bytes": len(b), "file": fn, "licence": "public domain (U.S. Reports, via the Caselaw Access Project)",
                                      "identity_check": "matched by U.S. Reports citation " + r["usCite"]})
                    cells = {}
                    for name, var in COLS:
                        if var is None:
                            cells[name] = f"{r['caseName'].title()}, {r['usCite']}"
                        else:
                            v = r.get(var) or ""
                            cells[name] = L.get(var, {}).get(v, v)
                    rows.append({"document_id": did, "cells": cells})
        q = (f"How did the U.S. Supreme Court under Chief Justice {chief} ({years}) decide its cases: which issue areas "
             f"did it rule on, in which ideological direction did it decide, and how divided were its votes?")
        out.append({
            "task_id": f"scdb:{chief.lower()}", "task_type": "database", "source": "scdb", "stratum": "scdb",
            "domain": "law", "language": "en", "question": q, "question_provenance": "database_purpose+rewritten",
            "question_author_text": "The original aim of the database was to include and classify every single vote by a Supreme Court justice in all argued cases (Spaeth).",
            "paper": {"title": f"U.S. Supreme Court Database, {chief} Court sample", "journal": "SCDB 2025 Release 01",
                      "year": "2025", "id": f"scdb:{chief.lower()}", "url": "https://scdb.la.psu.edu/",
                      "licence": "SCDB: free for research use with citation"},
            "schema": {"columns": [c for c, _ in COLS], "document_column": "Case",
                       "caption": f"Random sample of {len(rows)} {chief} Court cases, coded by the SCDB", "notes": "Codes are SCDB codebook labels.",
                       "table_source": "scdb", "merged_from": None},
            "rows": rows, "documents": documents,
            "counts": {"rows_in_published_table": len(pool), "rows_exported": len(rows), "documents": len(documents), "columns": len(COLS)},
            "quality": {"tier": "core", "grounding_rate": None, "suspect_rows": None, "judged": False, "verdict": None,
                        "issues": [f"sample of {len(rows)} of the era's {len(pool)} cases"]},
        })
        print(f"{chief}: {len(rows)} cases with opinions ({tried} tried, era has {len(pool)})", flush=True)
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out))
