"""Resolve raw citation strings (references with no DOI/PMID/PMCID) via Crossref.
A match is accepted only if the Crossref title is found in the citation string
and the years agree, so a wrong DOI is not silently attached.

  python3 crossref.py <in.jsonl> <out.jsonl>
"""
import json, os, re, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE, CONTACT_EMAIL
from fetch_docs import title_found

API = "https://api.crossref.org/works?query.bibliographic={q}&rows=3&select=DOI,title,issued"
CP = os.path.join(CACHE, "oa_meta", "crossref.json")


def one(raw):
    url = API.format(q=urllib.parse.quote(raw[:300]))
    if "<" not in CONTACT_EMAIL:
        url += "&mailto=" + urllib.parse.quote(CONTACT_EMAIL)
    st, body = http_get(url, timeout=45)
    if body is None:
        return raw, None
    try:
        items = json.loads(body)["message"]["items"]
    except Exception:
        return raw, None
    years = set(re.findall(r"\b(19\d{2}|20\d{2})\b", raw))
    for it in items:
        t = (it.get("title") or [""])[0]
        y = str(((it.get("issued") or {}).get("date-parts") or [[None]])[0][0])
        if t and title_found(t, raw) and (not years or y in years):
            return raw, {"doi": it["DOI"].lower(), "title": t, "year": y}
    return raw, {}


if __name__ == "__main__":
    inp, outp = sys.argv[1:3]
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    cache = json.load(open(CP)) if os.path.exists(CP) else {}
    raws = sorted({r["citation"] for t in T for r in t["rows"]
                   if r.get("citation") and not (r.get("doi") or r.get("pmid") or r.get("pmcid"))})
    todo = [x for x in raws if x not in cache]
    with ThreadPoolExecutor(max_workers=3) as ex:
        for raw, res in ex.map(one, todo):
            if res is not None:
                cache[raw] = res
    json.dump(cache, open(CP, "w"))
    got = 0
    for t in T:
        for r in t["rows"]:
            hit = cache.get(r.get("citation") or "")
            if hit and not (r.get("doi") or r.get("pmid") or r.get("pmcid")):
                r["doi"], r["doi_source"] = hit["doi"], "crossref"
                r["ref_title"] = r.get("ref_title") or hit["title"]
                got += 1
    with open(outp, "w", encoding="utf-8") as f:
        for t in T:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"{len(raws)} raw-only citations, {len(todo)} queried, {got} rows given a DOI")
