"""Find more legitimate download routes for documents that failed or had none.

Routes added (none of them works around a block; a 403 stays a 403):
  1. Europe PMC DOI lookup: the paper may be in the PMC open-access subset under
     a PMCID that OpenAlex and the NCBI converter did not report.
  2. Semantic Scholar openAccessPdf for the DOI.
  3. The citation_pdf_url meta tag (Highwire Press convention) on the landing
     pages OpenAlex lists, and on HTML pages that were returned instead of a PDF.
Results are cached; rows get pmcid or extra_pdf_urls, and fetch_docs.py
--retry then tries only the new routes (plus transient 5xx/timeouts again).

  python3 rescue_docs.py <tasks.jsonl> <manifest.jsonl> <out.jsonl> [budget_s]
"""
import html, json, os, re, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE
from fetch_docs import doc_key

CD = os.path.join(CACHE, "rescue")
os.makedirs(CD, exist_ok=True)


def _load(n):
    p = os.path.join(CD, n)
    return json.load(open(p)) if os.path.exists(p) else {}


def _save(n, d):
    json.dump(d, open(os.path.join(CD, n), "w"))


def epmc_by_doi(dois):
    cache = _load("epmc_doi.json")
    todo = [d for d in dois if d not in cache]
    def batch(chunk):
        q = " OR ".join(f'DOI:"{d}"' for d in chunk)
        url = ("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=" + urllib.parse.quote(q) +
               f"&format=json&resultType=lite&pageSize={len(chunk)}")
        st, body = http_get(url, timeout=60)
        out = {d: None for d in chunk}
        if not body:
            return {}
        for r in json.loads(body).get("resultList", {}).get("result", []):
            d = (r.get("doi") or "").lower()
            if d in out and r.get("pmcid") and r.get("isOpenAccess") == "Y":
                out[d] = r["pmcid"]
        return out
    with ThreadPoolExecutor(max_workers=3) as ex:
        for part in ex.map(batch, [todo[i:i + 30] for i in range(0, len(todo), 30)]):
            cache.update(part)
    _save("epmc_doi.json", cache)
    return cache


def s2_pdfs(dois):
    cache = _load("s2.json")
    todo = [d for d in dois if d not in cache]
    for i in range(0, len(todo), 300):
        chunk = todo[i:i + 300]
        body = json.dumps({"ids": [f"DOI:{d}" for d in chunk]}).encode()
        import urllib.request
        req = urllib.request.Request("https://api.semanticscholar.org/graph/v1/paper/batch?fields=openAccessPdf,externalIds",
                                     data=body, headers={"Content-Type": "application/json",
                                                         "User-Agent": "ScheMatiQ-benchmark/2.0 (research use)"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                res = json.loads(r.read().decode())
        except Exception:
            time.sleep(5)
            continue
        for d, item in zip(chunk, res or []):
            pdf = ((item or {}).get("openAccessPdf") or {}).get("url")
            ax = ((item or {}).get("externalIds") or {}).get("ArXiv")
            cache[d] = {"pdf": pdf or None, "arxiv": ax}
        time.sleep(1.5)
    _save("s2.json", cache)
    return cache


# hosts that answered 403 to this pipeline on PDF requests; their landing pages do the same
BLOCKING = {"onlinelibrary.wiley.com", "www.sciencedirect.com", "academic.oup.com", "www.nejm.org",
            "www.tandfonline.com", "www.ahajournals.org", "dl.acm.org", "journals.sagepub.com"}
META = re.compile(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']', re.I)
META2 = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']', re.I)


def landing_pdf(url):
    cache = _load_landing()
    if url in cache:
        return cache[url]
    st, body = http_get(url, tries=1, timeout=30)
    pdf = None
    if body and st == 200:
        m = META.search(body) or META2.search(body)
        if m:
            pdf = urllib.parse.urljoin(url, html.unescape(m.group(1)))
    cache[url] = pdf
    return pdf


_LAND = None


def _load_landing():
    global _LAND
    if _LAND is None:
        _LAND = _load("landing.json")
    return _LAND


if __name__ == "__main__":
    inp, manp, outp = sys.argv[1:4]
    budget = float(sys.argv[4]) if len(sys.argv) > 4 else 220
    t0 = time.time()
    man = {}
    for l in open(manp):
        m = json.loads(l)
        man[m["key"]] = m
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    need = [r for t in T for r in t["rows"] if doc_key(r) and (man.get(doc_key(r)) or {}).get("status") != "ok"]
    dois = sorted({r["doi"] for r in need if r.get("doi")})
    print(f"{len(need)} rows without a downloaded document ({len(dois)} DOIs)", flush=True)
    pm = epmc_by_doi([d for d in dois])
    print(f"  Europe PMC open-access PMCID found for {sum(1 for d in dois if pm.get(d))} DOIs ({time.time()-t0:.0f}s)", flush=True)
    s2 = s2_pdfs(dois) if time.time() - t0 < budget * 0.5 else {}
    print(f"  Semantic Scholar PDF url for {sum(1 for d in dois if (s2.get(d) or {}).get('pdf'))} DOIs, arXiv id for {sum(1 for d in dois if (s2.get(d) or {}).get('arxiv'))} ({time.time()-t0:.0f}s)", flush=True)
    # landing pages: OpenAlex landing URLs of open works, and HTML answers seen before
    pages = set()
    for r in need:
        w = r.get("openalex") or {}
        if w.get("is_oa"):
            for l in w.get("locations", []):
                u = l.get("landing")
                if u and "doi.org" not in u and "arxiv.org" not in u and "pubmed" not in u:
                    pages.add(u)
        m = man.get(doc_key(r)) or {}
        for tr in m.get("tried", []):
            if tr.get("result") == "not_pdf":
                pages.add(tr["url"])
    pages = sorted(p for p in pages if urllib.parse.urlparse(p).netloc not in BLOCKING)
    cache = _load_landing()
    todo = [u for u in pages if u not in cache]
    for i in range(0, len(todo), 80):              # save after every batch; stop at the budget
        if time.time() - t0 > budget:
            print(f"  budget reached, {len(todo) - i} landing pages left for the next run", flush=True)
            break
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(landing_pdf, todo[i:i + 80]))
        _save("landing.json", cache)
    got = {u: cache.get(u) for u in pages if u in cache}
    print(f"  landing pages read {len(got)} of {len(pages)}, citation_pdf_url on {sum(1 for v in got.values() if v)} ({time.time()-t0:.0f}s)", flush=True)
    added = 0
    for t in T:
        for r in t["rows"]:
            k = doc_key(r)
            if not k or (man.get(k) or {}).get("status") == "ok":
                continue
            d = r.get("doi")
            extra = []
            if d and pm.get(d) and not r.get("pmcid"):
                r["pmcid"] = pm[d]; added += 1
            if d and (s2.get(d) or {}).get("pdf"):
                extra.append(s2[d]["pdf"])
            if d and (s2.get(d) or {}).get("arxiv") and not r.get("arxiv_id"):
                r["arxiv_id"] = s2[d]["arxiv"]
            w = r.get("openalex") or {}
            for l in w.get("locations", []):
                if got.get(l.get("landing")):
                    extra.append(got[l["landing"]])
            for tr in (man.get(k) or {}).get("tried", []):
                if got.get(tr["url"]):
                    extra.append(got[tr["url"]])
            if extra:
                r["extra_pdf_urls"] = sorted(set(extra))
                added += 1
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in T))
    print(f"{added} rows gained a new route -> {outp} ({time.time()-t0:.0f}s)")
