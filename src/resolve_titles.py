"""Give a DOI or arXiv id to rows that only have a reference title, via
OpenAlex title search. Accepted only when the titles match closely.
  python3 resolve_titles.py <in.jsonl> <out.jsonl>
"""
import json, os, re, sys, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE
from verify_registration import title_sim

CP = os.path.join(CACHE, "oa_meta", "openalex_title.json")


_S2_LOCK = __import__("threading").Lock()
_S2_LAST = [0.0]


def s2_match(title):
    """Semantic Scholar title match: the fallback when OpenAlex refuses (429).
    Unauthenticated use is limited to about one request per second."""
    import time as _t
    with _S2_LOCK:
        wait = 1.1 - (_t.time() - _S2_LAST[0])
        if wait > 0:
            _t.sleep(wait)
        _S2_LAST[0] = _t.time()
        st, body = http_get("https://api.semanticscholar.org/graph/v1/paper/search/match?query=" +
                            urllib.parse.quote(title[:250]) + "&fields=title,externalIds", timeout=20, tries=1)
    if st == 404:
        return {}
    if not body:
        return None
    try:
        d = (json.loads(body).get("data") or [{}])[0]
    except Exception:
        return None
    if d.get("title") and title_sim(d["title"], title) >= 0.85:
        ext = d.get("externalIds") or {}
        return {"doi": (ext.get("DOI") or "").lower() or None, "arxiv": ext.get("ArXiv")}
    return {}


def crossref_match(title):
    st, body = http_get("https://api.crossref.org/works?rows=3&select=DOI,title&query.bibliographic=" +
                        urllib.parse.quote(title[:250]), timeout=25, tries=1)
    if not body:
        return None
    try:
        items = json.loads(body)["message"]["items"]
    except Exception:
        return None
    for it in items:
        t = (it.get("title") or [""])[0]
        if t and title_sim(t, title) >= 0.85:
            return {"doi": it["DOI"].lower(), "arxiv": None}
    return {}


def one(title):
    url = ("https://api.openalex.org/works?search=" + urllib.parse.quote(title[:250]) +
           "&per-page=3&select=doi,title,locations,ids")
    st, body = http_get(url, timeout=20, tries=1)
    if st == 429 or not body:
        hit = crossref_match(title)
        if hit:
            return title, hit
        return title, s2_match(title)
    try:
        res = json.loads(body).get("results", [])
    except Exception:
        return title, None
    for w in res:
        if w.get("title") and title_sim(w["title"], title) >= 0.85:
            ax = None
            for l in w.get("locations") or []:
                m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", l.get("landing_page_url") or "")
                if m:
                    ax = m.group(1); break
            return title, {"doi": (w.get("doi") or "").replace("https://doi.org/", "").lower() or None, "arxiv": ax}
    return title, {}


if __name__ == "__main__":
    inp, outp = sys.argv[1:3]
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    cache = json.load(open(CP)) if os.path.exists(CP) else {}
    todo = sorted({r["ref_title"] for t in T for r in t["rows"]
                   if r.get("ref_title") and not (r.get("doi") or r.get("arxiv_id")) and r["ref_title"] not in cache})
    import time
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 200
    t0 = time.time()
    for k in range(0, len(todo), 60):          # save the cache after every batch
        if time.time() - t0 > budget:
            print(f"time budget reached; {len(todo) - k} titles left for the next run")
            break
        with ThreadPoolExecutor(max_workers=6) as ex:
            for title, res in ex.map(one, todo[k:k + 60]):
                if res is not None:
                    cache[title] = res
        json.dump(cache, open(CP, "w"))
    got = 0
    for t in T:
        for r in t["rows"]:
            hit = cache.get(r.get("ref_title") or "")
            if hit and not (r.get("doi") or r.get("arxiv_id")) and (hit.get("doi") or hit.get("arxiv")):
                r["doi"], r["arxiv_id"], r["resolved_by"] = hit.get("doi"), hit.get("arxiv"), "openalex_title"
                got += 1
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in T))
    print(f"{len(todo)} titles searched; {got} rows resolved")
