"""Research-database tasks from the Comparative Constitutions Project
(Characteristics of National Constitutions v5, Elkins and Ginsburg 2025).

Each task takes its research question from a published CCP study, and its gold
columns from the CCP variables that study is about. Rows are the constitutions
in force in 2023; the documents are their texts from Constitute
(constituteproject.org), matched by country and year of promulgation.
Multi-select variables (for example amendment proposers) are joined into one
cell. Codes are turned into codebook labels.

  python3 ccp_tasks.py <ccpcnc_v5_small.dta> <docs_dir> <out.jsonl>
"""
import hashlib, html, json, os, re, sys, unicodedata
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from net import http_get

TASKS = [
 ("judicial_independence", "Melton and Ginsburg (2014), Does De Jure Judicial Independence Really Matter?",
  "How do national constitutions protect the independence of the judiciary, and how do these de jure protections differ across countries?",
  ["judind", "judsal"], [r"^highest court:"]),
 ("executive_term_limits", "Ginsburg, Melton and Elkins (2011), On the Evasion of Executive Term Limits",
  "How do national constitutions select heads of state and limit their time in office?",
  ["execnum", "emdecl"], [r"^head of state:"]),
 ("amendment_rules", "Ginsburg and Melton (2015), Does the Constitutional Amendment Rule Matter at All?",
  "How hard do national constitutions make it to amend them, and who takes part in amending them?",
  ["amend", "unamend", "referen"], [r"^amendment:"]),
 ("religion_and_rights", "Ahmed and Ginsburg (2014), Constitutional Islamization and Human Rights",
  "Do constitutions that give religion a formal role protect fewer human rights?",
  ["offrel", "offrelw", "freerel", "god", "equal", "express", "assem", "torture"], [r"^religion:\s+status of religious law"]),
 ("endurance", "Elkins, Ginsburg and Melton (2009), The Endurance of National Constitutions",
  "Which design features of national constitutions are associated with how long constitutions endure?",
  ["systyear", "length", "rghtwrds", "amend", "unamend", "referen", "amndapct", "execnum", "judind"], []),
]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s.replace("_", " "))


def lab(v):
    return re.sub(r"^\s*\d+\.\s*", "", str(v)).strip()


def text_of(cid):
    st, body = http_get(f"https://www.constituteproject.org/service/html?cons_id={cid}&lang=en", timeout=60)
    if not body:
        return None
    try:
        h = json.loads(body).get("html") or ""
    except ValueError:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<(br|/p|/div|/h\d)[^>]*>", "\n", h)))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()


if __name__ == "__main__":
    dta, docs, outp = sys.argv[1:4]
    it = pd.read_stata(dta, iterator=True)
    vlab, vl = it.value_labels(), it.variable_labels()
    df = it.read(convert_categoricals=False)
    last = int(df["year"].max())
    cur = df[(df["year"] == last) & (df["c_inforce"] == 1)].copy()
    st, body = http_get("https://www.constituteproject.org/service/constitutions?in_force=true&lang=en", timeout=60)
    cons = json.loads(body)
    by_country = {}
    for c in cons:
        by_country.setdefault(norm(c["country_id"]), []).append(c)
    match = {}
    for _, r in cur.iterrows():
        cands = by_country.get(norm(r["country"]), [])
        if pd.isna(r["systyear"]):
            continue
        best = [c for c in cands if str(c.get("year_enacted")) == str(int(r["systyear"]))]
        if best:
            match[r["country"]] = best[0]
    print(f"{len(cur)} constitutions in force in {last}; matched to a Constitute text: {len(match)}", flush=True)
    os.makedirs(os.path.join(docs, "constitutions"), exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        texts = dict(zip(match, ex.map(lambda k: text_of(match[k]["id"]), match)))
    documents = {}
    for country, c in match.items():
        t = texts.get(country)
        if not t or len(t) < 2000:
            continue
        b = t.encode("utf-8")
        fn = f"constitutions/{c['id']}.txt"
        open(os.path.join(docs, fn), "wb").write(b)
        documents[country] = {"document_id": "constitute:" + c["id"], "title": c.get("title_long") or c["title"], "kind": "txt",
                              "url": f"https://www.constituteproject.org/constitution/{c['id']}", "sha256": hashlib.sha256(b).hexdigest(),
                              "bytes": len(b), "file": fn, "licence": "Constitute (constituteproject.org); see its terms of use",
                              "identity_check": "matched by country and year of promulgation",
                              "version_note": c["title"]}
    print("texts downloaded:", len(documents), flush=True)
    out = []
    for tid, study, q, singles, prefixes in TASKS:
        cols = list(singles)
        for pre in prefixes:
            cols += [k for k, v in vl.items() if re.search(pre, v, re.I) and k not in cols and k in df.columns]
        # group multi-select dummies (name_1, name_2, ...) into one column
        groups, order = {}, []
        for k in cols:
            base = re.sub(r"_\d+$", "", k)
            if base not in groups:
                groups[base] = []; order.append(base)
            groups[base].append(k)
        names = {b: re.sub(r"\s+", " ", vl.get(groups[b][0], b)).strip() for b in order}
        rows = []
        for _, r in cur.iterrows():
            if r["country"] not in documents:
                continue
            cells = {"Constitution": documents[r["country"]]["title"]}
            for b in order:
                ks = groups[b]
                if len(ks) > 1 or re.search(r"_\d+$", ks[0]):
                    chosen = [lab(vlab.get(k, {}).get(1, k)) for k in ks if r.get(k) == 1 and not k.endswith(("_90", "_96", "_98", "_99"))]
                    cells[names[b]] = "; ".join(chosen)
                else:
                    v = r.get(ks[0])
                    if isinstance(v, str):
                        cells[names[b]] = {"ns": "not specified", "na": "not applicable"}.get(v.strip().lower(), v.strip())
                    elif pd.isna(v):
                        cells[names[b]] = ""
                    else:
                        L = vlab.get(ks[0]) or {}
                        cells[names[b]] = lab(L[int(v)]) if int(v) in L else (str(int(v)) if float(v).is_integer() else str(v))
            rows.append({"document_id": documents[r["country"]]["document_id"], "cells": cells})
        schema_cols = ["Constitution"] + [names[b] for b in order]
        out.append({
            "task_id": f"ccp:{tid}", "task_type": "database", "source": "ccp", "stratum": "ccp", "domain": "law and political science",
            "language": "en", "question": q, "question_provenance": "published_study+rewritten", "question_author_text": study,
            "paper": {"title": f"Comparative Constitutions Project: {study.split(', ', 1)[1]}", "journal": "CCP, Characteristics of National Constitutions v5",
                      "year": "2025", "id": f"ccp:{tid}", "url": "https://comparativeconstitutionsproject.org/download",
                      "licence": "CCP data: free for research with citation"},
            "schema": {"columns": schema_cols, "document_column": "Constitution",
                       "caption": f"{len(rows)} constitutions in force in {last}, coded by the CCP", "notes": "Codes are CCP codebook labels.",
                       "table_source": "ccp", "merged_from": None},
            "rows": rows, "documents": [documents[c] for c in documents],
            "counts": {"rows_in_published_table": len(cur), "rows_exported": len(rows), "documents": len(documents), "columns": len(schema_cols)},
            "quality": {"tier": "core", "grounding_rate": None, "suspect_rows": None, "judged": False, "verdict": None,
                        "issues": ["the Constitute text can be a later or earlier revision than the one the CCP coded"]},
        })
        print(f"{tid}: {len(rows)} rows, {len(schema_cols)} columns", flush=True)
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out))
