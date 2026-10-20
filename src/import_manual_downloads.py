"""Import a folder of PDFs that a person (or their own script) downloaded from
manual_downloads_priority.csv.

Each file is matched to a document by the download log's doc_key when there is
one (download_log.csv with columns file, task_id, doc_key), otherwise to any
document of the task named in the file name (NNN_<task_id>_...). A file is
accepted only if the expected DOI is printed in it or the expected title is
found in its text; macOS "._" files, HTML error pages and scanned PDFs without
text are skipped and counted.

  python3 import_manual_downloads.py <folder> <tasks.jsonl> <docs_dir>
"""
import collections, csv, glob, hashlib, json, os, shutil, sys
from fetch_docs import pdf_text, doi_found, title_found, doc_key

folder, tasks_p, docs = sys.argv[1:4]
logs = glob.glob(os.path.join(folder, "**", "download_log.csv"), recursive=True)
by_file = {}
for lp in logs:
    for r in csv.DictReader(open(lp, encoding="utf-8", errors="replace")):
        if r.get("file"):
            by_file[os.path.basename(r["file"])] = r
exp, task_keys = {}, collections.defaultdict(set)
for l in open(tasks_p, encoding="utf-8"):
    t = json.loads(l)
    for r in t["rows"]:
        k = doc_key(r)
        if k:
            exp[k] = (r.get("doi"), r.get("ref_title") or (r.get("openalex") or {}).get("title") or "")
            task_keys[t["task_id"]].add(k)
man_p = os.path.join(docs, "manifest.jsonl")
have = {}
for l in open(man_p):
    m = json.loads(l)
    have[m["key"]] = m.get("status")
res, lines = collections.Counter(), []
for p in sorted(glob.glob(os.path.join(folder, "**", "*"), recursive=True)):
    name = os.path.basename(p)
    if not os.path.isfile(p) or name.startswith("._") or name == "download_log.csv":
        continue
    b = open(p, "rb").read()
    if b[:5] != b"%PDF-":
        res["not a PDF (error page or other file)"] += 1; continue
    text = pdf_text(b)
    if not text.strip():
        res["PDF without a text layer"] += 1; continue
    lg = by_file.get(name) or {}
    task = lg.get("task_id") or (name.split("_")[1] if name.count("_") >= 2 else None)
    hint = lg.get("doc_key")
    hit = None
    for k in ([hint] if hint else []) + sorted(task_keys.get(task, set()) - {hint}):
        d, ti = exp.get(k, (None, ""))
        if d and doi_found(d, text):
            hit = (k, "doi"); break
        if ti and title_found(ti, text):
            hit = (k, "title"); break
    if not hit:
        res["wrong paper or not verifiable"] += 1; continue
    k, how = hit
    if have.get(k) == "ok":
        res["already downloaded"] += 1; continue
    fn = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in k)[:90] + ".pdf"
    shutil.copy(p, os.path.join(docs, fn))
    lines.append(json.dumps({"key": k, "status": "ok", "kind": "pdf", "url": "manual:" + name, "identity": how,
                             "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "file": fn,
                             "tried": [{"kind": "pdf", "url": "manual:" + name, "result": how}]}))
    have[k] = "ok"
    res["imported"] += 1
open(man_p, "a").write("".join(x + "\n" for x in lines))
print(dict(res))
