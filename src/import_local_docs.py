"""Add documents that a person downloaded by hand (for example the ones in
blocked_oa.csv) to the pipeline, with the same identity check as automatic
downloads: the file must print the expected DOI, or contain the expected title.

  python3 import_local_docs.py <folder_with_pdfs_or_xml> <blocked_oa.csv> <docs_dir>
Appends one manifest line per matched file; finalize.py picks them up.
"""
import csv, hashlib, json, os, shutil, sys
from fetch_docs import pdf_text, doi_found, title_found

folder, csv_p, docs = sys.argv[1:4]
want = list(csv.DictReader(open(csv_p, encoding="utf-8")))
man_p = os.path.join(docs, "manifest.jsonl")
matched = unmatched = 0
with open(man_p, "a") as man:
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        b = open(p, "rb").read()
        text = pdf_text(b) if b[:5] == b"%PDF-" else b.decode("utf-8", "replace")
        hit = None
        for w in want:
            if w["doi"] and doi_found(w["doi"], text):
                hit, how = w, "doi"; break
        if not hit:
            for w in want:
                if w["title"] and title_found(w["title"], text):
                    hit, how = w, "title"; break
        if not hit:
            print("no match:", name); unmatched += 1; continue
        ext = "pdf" if b[:5] == b"%PDF-" else "xml"
        fn = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in hit["key"])[:90] + "." + ext
        shutil.copy(p, os.path.join(docs, fn))
        man.write(json.dumps({"key": hit["key"], "status": "ok", "kind": ext, "url": "manual:" + name,
                              "identity": how, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(),
                              "file": fn, "tried": [{"kind": ext, "url": "manual:" + name, "result": how}]}) + "\n")
        matched += 1
        print(f"matched {name} -> {hit['key']} by {how}")
print(f"{matched} files matched, {unmatched} not matched")
