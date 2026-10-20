"""List open-access documents the pipeline could not download (publisher
blocks, 401/403, HTML walls), ranked by how much a manual download would help:
documents of tasks that are 1 to 4 documents short of the 5-document minimum
come first. A person can open these links in a normal browser, save the files
into one folder, and run import_local_docs.py on it.

  python3 blocked_list.py <tasks.jsonl> <manifest.jsonl> <out.csv>
"""
import csv, json, sys
from collections import defaultdict
from urllib.parse import urlparse
from fetch_docs import doc_key

tasks_p, man_p, out_p = sys.argv[1:4]
man = {}
for l in open(man_p):
    m = json.loads(l)
    man[m["key"]] = m
need = defaultdict(list)
info = {}
for l in open(tasks_p, encoding="utf-8"):
    t = json.loads(l)
    j = t.get("judgment") or {}
    if j.get("verdict") == "not_worthy":
        continue
    have = t["counts"]["documents_downloaded"]
    short = max(0, 5 - have)
    for r in t["rows"]:
        k = doc_key(r)
        m = man.get(k) or {}
        if not k or m.get("status") != "failed":
            continue
        oa = (r.get("openalex") or {}).get("is_oa") or r.get("arxiv_id")
        if not oa:
            continue
        need[k].append((t["task_id"], short))
        last = m["tried"][-1]
        info[k] = {"doi": r.get("doi"), "title": r.get("ref_title") or (r.get("openalex") or {}).get("title"),
                   "url": last["url"], "host": urlparse(last["url"]).netloc, "http": last.get("http"),
                   "landing": next((l.get("landing") for l in (r.get("openalex") or {}).get("locations", []) if l.get("landing")), None)}
rows = []
for k, ts in need.items():
    short = [s for _, s in ts if s > 0]
    rows.append({"key": k, **info[k], "tasks": " ".join(sorted({t for t, _ in ts})),
                 "helps_task_reach_5": bool(short), "smallest_gap": min(short) if short else 0})
rows.sort(key=lambda r: (not r["helps_task_reach_5"], r["smallest_gap"] or 99, r["host"]))
with open(out_p, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
print(f"{len(rows)} blocked open-access documents -> {out_p}; {sum(r['helps_task_reach_5'] for r in rows)} of them belong to tasks below 5 documents")
