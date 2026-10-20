"""Which blocked open-access documents would complete a task if a person
downloaded them by hand: tasks excluded only because they have 3 or 4 of the
5 required documents, with their blocked open-access documents listed.
  python3 manual_priority.py <tasks.jsonl> <manifest.jsonl> <judgments.json> <out.csv>
"""
import csv, json, sys
from fetch_docs import doc_key

tp, mp, jp, out = sys.argv[1:5]
J = json.load(open(jp))
M = {}
for l in open(mp):
    m = json.loads(l)
    M[m["key"]] = m
plan = []
for l in open(tp, encoding="utf-8"):
    t = json.loads(l)
    if t["tier"] != "excluded" or (J.get(t["task_id"]) or {}).get("verdict") == "not_worthy":
        continue
    if [r for r in t["tier_reasons"] if not r.startswith("only")]:
        continue
    need = 5 - t["counts"]["documents_downloaded"]
    if not 1 <= need <= 2:
        continue
    docs = {}
    for r in t["rows"]:
        k = doc_key(r)
        m = M.get(k) or {}
        if k and m.get("status") == "failed" and ((r.get("openalex") or {}).get("is_oa") or r.get("arxiv_id") or r.get("extra_pdf_urls")):
            d = r.get("doi")
            docs[k] = (d, r.get("ref_title") or "", ("https://doi.org/" + d) if d else m["tried"][-1]["url"])
    if len(docs) >= need:
        plan.append((need, t, list(docs.items())[:need + 1]))
plan.sort(key=lambda x: (x[0], -x[1]["counts"]["rows"]))
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["priority", "task_id", "task_title", "documents_missing", "doc_key", "doi", "paper_title", "open_this_link"])
    for i, (need, t, docs) in enumerate(plan, 1):
        for k, (d, ti, link) in docs:
            w.writerow([i, t["task_id"], t["title"][:120], need, k, d, ti[:150], link])
print(f"{len(plan)} tasks can be completed by hand ({sum(1 for p in plan if p[0] == 1)} need one document)")
