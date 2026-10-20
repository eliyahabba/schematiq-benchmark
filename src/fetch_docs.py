"""Download every row's source document and verify it is the right paper.

A row counts as downloadable only if a file was actually fetched AND its
identity was confirmed: the DOI printed in the file matches, or the expected
title is found in it. A candidate URL alone does not count.

Order of routes: Europe PMC full-text XML (by PMCID), then every PDF URL that
OpenAlex knows, best OA location first. The User-Agent identifies this as a
research bot; publisher blocks are respected, not worked around.

Resumable: one manifest line per document key; rerun until it reports 0 left.
  python3 fetch_docs.py <tasks.jsonl> <docs_dir> [time_budget_s]
"""
import hashlib, json, os, re, subprocess, sys, tempfile, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from net import http_get

EPMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def title_tokens(t):
    return [w for w in fold(t).split() if len(w) >= 4]


def title_found(title, text):
    toks = title_tokens(title)
    if len(toks) < 3:
        return False
    hay = " " + fold(text) + " "
    hit = sum(1 for w in toks if f" {w} " in hay)
    return hit / len(toks) >= 0.7


def doi_found(doi, text):
    if not doi:
        return False
    t = re.sub(r"\s+", "", (text or "").lower())
    return doi.lower() in t


def doc_key(r):
    if r.get("direct_url") and not (r.get("arxiv_id") or r.get("pmcid") or r.get("doi")):
        return "url:" + r["direct_url"]
    if r.get("arxiv_id"):
        return "arxiv:" + r["arxiv_id"]
    return r.get("pmcid") or (("doi:" + r["doi"]) if r.get("doi") else None)


def expected_title(r):
    return r.get("ref_title") or (r.get("openalex") or {}).get("title") or ""


WILEY_DOI = re.compile(r"^10\.(1002|1111|1113|1046|1034|1348|1096)/")
ELSEVIER_DOI = re.compile(r"^10\.1016/")


def routes(r):
    """Order: a URL given by hand, the PMC XML, publisher or repository PDFs,
    publisher TDM APIs (with the researcher's keys), and arXiv last, because
    arXiv is throttled to one request per 3 seconds."""
    out, seen = [], set()
    def add(kind, u):
        if u and u not in seen:
            seen.add(u); out.append((kind, u))
    if r.get("direct_url"):
        add("pdf", r["direct_url"])
    if r.get("pmcid"):
        add("xml", EPMC_XML.format(pmcid=r["pmcid"]))
    w = r.get("openalex") or {}
    pdfs = [w.get("best_pdf")] + [l.get("pdf_url") for l in w.get("locations", [])]
    for u in pdfs:
        if u and "arxiv.org" not in u:
            add("pdf", u)
    for u in r.get("extra_pdf_urls") or []:
        if "arxiv.org" not in u:
            add("pdf", u)
    for u in r.get("extra_xml_urls") or []:
        add("xml", u)
    d = (r.get("doi") or "").lower()
    if d and WILEY_DOI.match(d) and os.environ.get("WILEY_TDM_TOKEN") and \
            ((r.get("openalex") or {}).get("is_oa") or not os.environ.get("WILEY_ONLY_OA")):
        add("pdf", "wiley-tdm:" + d)
    if d and ELSEVIER_DOI.match(d) and os.environ.get("ELSEVIER_API_KEY") and os.environ.get("ELSEVIER_TRY"):
        add("pdf", "elsevier-api:" + d)
    if r.get("arxiv_id"):
        add("pdf", f"https://arxiv.org/pdf/{r['arxiv_id']}")
    for u in pdfs:
        if u and "arxiv.org" in u:
            add("pdf", u)
    return out


def verify_xml(body, r):
    if "<article" not in body[:5000]:
        return None
    d = re.search(r'<article-id pub-id-type="doi">([^<]+)</article-id>', body)
    ti = re.search(r"<article-title[^>]*>(.*?)</article-title>", body, re.S)
    t = re.sub(r"<[^>]+>", " ", ti.group(1)) if ti else ""
    has_body = "<body" in body
    if r.get("doi") and d and d.group(1).strip().lower() == r["doi"].lower():
        return "doi", has_body
    if title_found(expected_title(r), t) or title_found(t, expected_title(r)):
        return "title", has_body
    return "mismatch", has_body


def pdf_text(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        try:
            p = subprocess.run(["pdftotext", "-l", "3", "-q", f.name, "-"],
                               capture_output=True, timeout=40)
            return p.stdout.decode("utf-8", "replace")
        except Exception:
            return ""


def verify_pdf(b, r):
    if b[:5] != b"%PDF-":
        return None
    txt = pdf_text(b)
    if not txt.strip():
        return "no_text"
    if doi_found(r.get("doi"), txt):
        return "doi"
    if title_found(expected_title(r), txt):
        return "title"
    return "mismatch"


import threading
_ARXIV_LOCK, _ARXIV_LAST = threading.Lock(), [0.0]


def tdm_wait(name, gap):
    """Cross-process spacing for a publisher API (same mechanism as arxiv_wait)."""
    import fcntl
    from net import CACHE
    lp = os.path.join(CACHE, f".{name}_throttle")
    with open(lp, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read().strip() or 0)
        except ValueError:
            last = 0.0
        w = gap - (time.time() - last)
        if w > 0:
            time.sleep(w)
        f.seek(0); f.truncate(); f.write(str(time.time())); f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def polite_get(url):
    """arxiv.org asks automated clients for one request every 3 seconds.
    wiley-tdm: and elsevier-api: are the publishers' text-and-data-mining APIs,
    called with the researcher's own token or key, at a conservative pace."""
    import urllib.parse as _up
    if url.startswith("wiley-tdm:"):
        # Wiley answers HTTP 500 "Rate limit quota violation" above about 60
        # requests per 10 minutes (measured 2026-09-27), so one every 11 s
        tdm_wait("wiley", 11.0)
        return http_get("https://api.wiley.com/onlinelibrary/tdm/v1/articles/" + _up.quote(url[10:], safe=""),
                        headers={"Wiley-TDM-Client-Token": os.environ["WILEY_TDM_TOKEN"]},
                        tries=1, timeout=60, binary=True)
    if url.startswith("elsevier-api:"):
        tdm_wait("elsevier", 1.0)
        h = {"X-ELS-APIKey": os.environ["ELSEVIER_API_KEY"], "Accept": "application/pdf"}
        if os.environ.get("ELSEVIER_INSTTOKEN"):
            # institutional token issued by Elsevier to the university; lets the
            # API grant the institution's full-text rights outside its network
            h["X-ELS-Insttoken"] = os.environ["ELSEVIER_INSTTOKEN"]
        return http_get("https://api.elsevier.com/content/article/doi/" + url[13:],
                        headers=h, tries=1, timeout=60, binary=True)
    if "arxiv.org" in url:
        from net import arxiv_wait
        with _ARXIV_LOCK:
            arxiv_wait()
            return http_get(url, tries=1, timeout=45, binary=True)
    return http_get(url, tries=2, timeout=45, binary=True)


def fetch_one(key, r, dest):
    tried = []
    for kind, url in routes(r):
        st, b = polite_get(url)
        tried.append({"kind": kind, "url": url, "http": st, "bytes": len(b) if b else 0})
        if not b:
            continue
        if kind == "xml":
            v = verify_xml(b.decode("utf-8", "replace"), r)
            if v is None:
                tried[-1]["result"] = "not_xml"; continue
            ident, has_body = v
            tried[-1]["result"] = ident
            if ident == "mismatch" or not has_body:
                if not has_body:
                    tried[-1]["result"] = ident + "_no_body"
                continue
        else:
            ident = verify_pdf(b, r)
            tried[-1]["result"] = ident or "not_pdf"
            if ident in (None, "mismatch", "no_text"):
                continue
        ext = "xml" if kind == "xml" else "pdf"
        name = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:90] + "." + ext
        with open(os.path.join(dest, name), "wb") as f:
            f.write(b)
        if os.environ.get("BENCH_TEXT_ONLY") == "1":
            # keep the extracted text (all later steps need only that) and drop the
            # file: PDFs with figures filled a 20 GB disk during this session
            import grounding
            grounding.doc_text(os.path.join(dest, name))
            os.remove(os.path.join(dest, name))
        return {"key": key, "status": "ok", "kind": kind, "url": url, "identity": ident,
                "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "file": name, "tried": tried}
    return {"key": key, "status": "failed" if tried else "no_route", "tried": tried}


if __name__ == "__main__":
    inp, dest = sys.argv[1], sys.argv[2]
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 240
    os.makedirs(dest, exist_ok=True)
    man_p = os.path.join(dest, "manifest.jsonl")
    retry = "--retry" in sys.argv
    last = {}
    if os.path.exists(man_p):
        for l in open(man_p):
            m = json.loads(l)
            last[m["key"]] = m
    done = set(last)
    TRANSIENT = {None, 429, 500, 502, 503, 504}
    todo = {}
    for l in open(inp, encoding="utf-8"):
        for r in json.loads(l)["rows"]:
            k = doc_key(r)
            if not k or k in todo:
                continue
            if k not in done:
                todo[k] = r
            elif retry and last[k].get("status") != "ok":
                tried = {x["url"] for x in last[k].get("tried", [])}
                new_routes = [u for _, u in routes(r) if u not in tried]
                transient = any(x.get("http") in TRANSIENT and not x.get("result") and "europepmc" not in x["url"]
                                for x in last[k].get("tried", []))
                if new_routes or transient:
                    todo[k] = r
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    t0 = time.time()
    n = 0
    with ThreadPoolExecutor(max_workers=8) as ex, open(man_p, "a") as man:
        futs = {}
        it = iter(todo.items())
        def submit():
            try:
                k, r = next(it)
            except StopIteration:
                return False
            futs[ex.submit(fetch_one, k, r, dest)] = k
            return True
        for _ in range(16):
            submit()
        while futs:
            left_s = budget + 40 - (time.time() - t0)
            try:
                f = next(as_completed(list(futs), timeout=max(1, left_s)))
            except Exception:
                man.flush()
                print(f"fetched {n} in {time.time()-t0:.0f}s, {len(todo)-n} left (stopped with {len(futs)} in flight)", flush=True)
                os._exit(0)
            del futs[f]
            man.write(json.dumps(f.result()) + "\n"); man.flush()
            n += 1
            if time.time() - t0 < budget:
                submit()
    left = len(todo) - n
    print(f"fetched {n} in {time.time()-t0:.0f}s, {left} left", flush=True)
