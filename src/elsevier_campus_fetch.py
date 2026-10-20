"""Run this on a computer inside the university network. Elsevier grants
full-text API access by the institution's IP range; from outside it answers
403 "Requestor configuration settings insufficient" even with a valid key.

  export ELSEVIER_API_KEY=<API_KEY>
  python3 elsevier_campus_fetch.py elsevier_dois.csv elsevier_pdfs
Then zip the elsevier_pdfs folder and upload it; import_manual_downloads.py
checks every file before it is used. One request per second.
"""
import csv, os, sys, time, urllib.request

key = os.environ["ELSEVIER_API_KEY"]
src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
log = open(os.path.join(out, "download_log.csv"), "w", newline="")
w = csv.writer(log); w.writerow(["priority", "task_id", "doc_key", "doi", "status", "method", "landed_url", "pdf_url", "file", "time"])
for i, r in enumerate(csv.DictReader(open(src, encoding="utf-8")), 1):
    doi = r["doi"]
    name = f"{i:04d}_{r['task_id']}_{doi.replace('/', '_')}.pdf"
    req = urllib.request.Request("https://api.elsevier.com/content/article/doi/" + doi,
                                 headers={"X-ELS-APIKey": key, "Accept": "application/pdf"})
    try:
        b = urllib.request.urlopen(req, timeout=60).read()
        ok = b[:5] == b"%PDF-"
        if ok:
            open(os.path.join(out, name), "wb").write(b)
        w.writerow([i, r["task_id"], r["doc_key"], doi, "ok" if ok else "failed", "elsevier-api", "", "", name if ok else "", time.time()])
    except Exception as e:
        w.writerow([i, r["task_id"], r["doc_key"], doi, "failed", f"elsevier-api {e}", "", "", "", time.time()])
    log.flush()
    time.sleep(1.0)
print("done; see", os.path.join(out, "download_log.csv"))
