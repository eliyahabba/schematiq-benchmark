"""Download the documents of the benchmark and check each file's SHA-256.

  python3 src/fetch_documents.py data/benchmark [--manual-dir DIR] [--limit N]

- Documents whose text ships with the repo (database and question-set tasks,
  in documents_text/) are skipped.
- Wiley text-and-data-mining documents (url "wiley-tdm:<doi>") need
  WILEY_TDM_TOKEN in the environment; Wiley allows about 60 requests per
  10 minutes, so they are fetched one every 11 seconds.
- Elsevier API documents (url "elsevier-api:<doi>") need ELSEVIER_API_KEY and,
  outside the university network, ELSEVIER_INSTTOKEN.
- Documents first saved by hand (url "manual:<file name>") are copied from
  --manual-dir, the folder of hand-downloaded PDFs.
- arXiv is limited to one request every 3 seconds.
Files land in <export>/documents/. Failures are listed in <export>/documents/failed.csv.
"""
import argparse, csv, hashlib, json, os, shutil, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "ScheMatiQ-benchmark-fetch/1.0 (research use)"}
ap = argparse.ArgumentParser()
ap.add_argument("export"); ap.add_argument("--manual-dir"); ap.add_argument("--limit", type=int)
a = ap.parse_args()

docs = {}
for l in open(os.path.join(a.export, "tasks.jsonl"), encoding="utf-8"):
    for d in json.loads(l)["documents"]:
        docs[d["file"]] = d
dest = os.path.join(a.export, "documents")
os.makedirs(dest, exist_ok=True)
last = {"arxiv": 0.0, "wiley": 0.0, "elsevier": 0.0}
counts = {"in place": 0, "shipped as text": 0, "downloaded": 0, "hash differs": 0, "failed": 0}
failed = []


def wait(kind, gap):
    time.sleep(max(0.0, gap - (time.time() - last[kind])))
    last[kind] = time.time()


def get(d):
    u = d["url"]
    if u.startswith("manual:"):
        if not a.manual_dir:
            raise RuntimeError("downloaded by hand: pass --manual-dir")
        src = os.path.join(a.manual_dir, u[len("manual:"):])
        if not os.path.exists(src):
            raise RuntimeError(f"not in --manual-dir: {u[len('manual:'):]}")
        return open(src, "rb").read()
    if u.startswith("wiley-tdm:"):
        tok = os.environ.get("WILEY_TDM_TOKEN")
        if not tok:
            raise RuntimeError("needs WILEY_TDM_TOKEN")
        wait("wiley", 11.0)
        req = urllib.request.Request("https://api.wiley.com/onlinelibrary/tdm/v1/articles/" + urllib.parse.quote(u[10:], safe=""),
                                     headers={**UA, "Wiley-TDM-Client-Token": tok})
        return urllib.request.urlopen(req, timeout=60).read()
    if u.startswith("elsevier-api:"):
        key = os.environ.get("ELSEVIER_API_KEY")
        if not key:
            raise RuntimeError("needs ELSEVIER_API_KEY")
        h = {**UA, "X-ELS-APIKey": key, "Accept": "application/pdf"}
        if os.environ.get("ELSEVIER_INSTTOKEN"):
            h["X-ELS-Insttoken"] = os.environ["ELSEVIER_INSTTOKEN"]
        wait("elsevier", 1.0)
        return urllib.request.urlopen(urllib.request.Request("https://api.elsevier.com/content/article/doi/" + u[13:], headers=h), timeout=60).read()
    if "arxiv.org" in u:
        wait("arxiv", 3.0)
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()


todo = sorted(docs.items())
if a.limit:
    todo = todo[:a.limit]
for i, (name, d) in enumerate(todo, 1):
    if os.path.exists(os.path.join(a.export, "documents_text", name)):
        counts["shipped as text"] += 1; continue
    p = os.path.join(dest, name)
    if os.path.exists(p) and hashlib.sha256(open(p, "rb").read()).hexdigest() == d["sha256"]:
        counts["in place"] += 1; continue
    try:
        b = get(d)
    except Exception as e:
        counts["failed"] += 1; failed.append((name, d["url"], str(e)[:200])); continue
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(b)
    if hashlib.sha256(b).hexdigest() != d["sha256"]:
        counts["hash differs"] += 1        # the source changed the file since the export (common for XML)
    counts["downloaded"] += 1
    if i % 200 == 0:
        print(f"{i}/{len(todo)}", counts, flush=True)
with open(os.path.join(dest, "failed.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["file", "url", "reason"]); w.writerows(failed)
print(counts)
