"""Publisher full-text links registered in Crossref for text and data mining.

Only links whose intended application is "text-mining" or "unspecified" are
used; "similarity-checking" links exist for the plagiarism service and are
left alone. Results are cached per DOI.
  python3 crossref_links.py <tasks.jsonl> <manifest.jsonl> <out.jsonl> [budget_s]
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE, CONTACT_EMAIL
from fetch_docs import doc_key

CP = os.path.join(CACHE, "rescue", "crossref_links.json")


def links(doi):
    url = f"https://api.crossref.org/works/{doi}"
    if "<" not in CONTACT_EMAIL:
        url += f"?mailto={CONTACT_EMAIL}"
    st, body = http_get(url, tries=2, timeout=30)
    if st == 404:
        return doi, []
    if not body:
        return doi, None
    try:
        msg = json.loads(body)["message"]
    except Exception:
        return doi, None
    out = []
    for l in msg.get("link") or []:
        app, ct = l.get("intended-application"), (l.get("content-type") or "").lower()
        if app in ("text-mining", "unspecified") and ("pdf" in ct or "xml" in ct or ct == "unspecified"):
            out.append({"url": l["URL"], "type": ct})
    return doi, out


if __name__ == "__main__":
    inp, manp, outp = sys.argv[1:4]
    budget = float(sys.argv[4]) if len(sys.argv) > 4 else 200
    man = {}
    for l in open(manp):
        m = json.loads(l)
        man[m["key"]] = m
    cache = json.load(open(CP)) if os.path.exists(CP) else {}
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    dois = sorted({r["doi"] for t in T for r in t["rows"] if r.get("doi") and doc_key(r)
                   and (man.get(doc_key(r)) or {}).get("status") != "ok" and r["doi"] not in cache})
    t0 = time.time()
    for i in range(0, len(dois), 100):
        if time.time() - t0 > budget:
            print(f"budget reached, {len(dois) - i} DOIs left"); break
        with ThreadPoolExecutor(max_workers=5) as ex:
            for d, ls in ex.map(links, dois[i:i + 100]):
                if ls is not None:
                    cache[d] = ls
        json.dump(cache, open(CP, "w"))
    gained = 0
    for t in T:
        for r in t["rows"]:
            ls = cache.get(r.get("doi") or "")
            if ls:
                pdfs = [x["url"] for x in ls if "xml" not in x["type"]]
                xmls = [x["url"] for x in ls if "xml" in x["type"]]
                if pdfs:
                    r["extra_pdf_urls"] = sorted(set((r.get("extra_pdf_urls") or []) + pdfs))
                if xmls:
                    r["extra_xml_urls"] = sorted(set((r.get("extra_xml_urls") or []) + xmls))
                gained += 1
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in T))
    print(f"{len(cache)} DOIs in cache; {sum(1 for v in cache.values() if v)} have a text-mining link; {gained} rows gained one ({time.time()-t0:.0f}s)")
