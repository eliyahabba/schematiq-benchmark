"""Open-access metadata for every linked row, from OpenAlex and Europe PMC.

OpenAlex gives OA status, licence and every known PDF location for a DOI or
PMID. Europe PMC says whether it holds the full text (inEPMC / isOpenAccess),
which is what decides whether its fullTextXML endpoint will answer.
Results are cached per identifier so the step is resumable.

  python3 resolve_oa.py <tasks.jsonl> <out.jsonl>
"""
import json, os, re, sys, time, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from net import http_get, CACHE

OA = "https://api.openalex.org/works"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CDIR = os.path.join(CACHE, "oa_meta")
os.makedirs(CDIR, exist_ok=True)


def _load(name):
    p = os.path.join(CDIR, name)
    return json.load(open(p)) if os.path.exists(p) else {}


def _save(name, d):
    json.dump(d, open(os.path.join(CDIR, name), "w"))


def openalex(kind, ids):
    """kind 'doi' or 'pmid'. Returns id -> compact work record (or None if unknown)."""
    cache = _load(f"openalex_{kind}.json")
    todo = [i for i in ids if i not in cache]
    def batch(chunk):
        flt = f"{kind}:" + "|".join(chunk)
        url = (f"{OA}?filter={urllib.parse.quote(flt, safe=':|/.')}&per-page=50"
               "&select=id,doi,ids,title,publication_year,open_access,best_oa_location,locations,type")
        st, body = http_get(url, timeout=60)
        if body is None:
            return {}
        try:
            res = json.loads(body).get("results", [])
        except Exception:
            return {}
        out = {i: None for i in chunk}
        for w in res:
            key = ((w.get("doi") or "").replace("https://doi.org/", "").lower() if kind == "doi"
                   else ((w.get("ids") or {}).get("pmid") or "").rstrip("/").split("/")[-1])
            if key not in out:
                continue
            locs = []
            for l in w.get("locations") or []:
                if l.get("pdf_url") or l.get("is_oa"):
                    locs.append({"pdf_url": l.get("pdf_url"), "landing": l.get("landing_page_url"),
                                 "license": l.get("license"), "version": l.get("version"),
                                 "is_oa": l.get("is_oa"),
                                 "source": ((l.get("source") or {}).get("display_name"))})
            best = w.get("best_oa_location") or {}
            ids_ = w.get("ids") or {}
            # OpenAlex no longer lists pmcid under ids (checked 2026-09-27); the
            # PubMed Central location's landing URL still carries it.
            pmc_loc = None
            for l in w.get("locations") or []:
                m = re.search(r"/pmc/articles/(?:PMC)?(\d+)|europepmc\.org/articles?/(?:PMC)?(\d+)",
                              l.get("landing_page_url") or "", re.I)
                if m:
                    pmc_loc = "PMC" + (m.group(1) or m.group(2))
                    break
            out[key] = {
                "openalex": w.get("id"), "title": w.get("title"), "year": w.get("publication_year"),
                "type": w.get("type"),
                "doi": (w.get("doi") or "").replace("https://doi.org/", "").lower() or None,
                "pmid": (ids_.get("pmid") or "").rstrip("/").split("/")[-1] or None,
                "pmcid": ("PMC" + (ids_.get("pmcid") or "").rstrip("/").split("/")[-1].replace("PMC", ""))
                         if ids_.get("pmcid") else pmc_loc,
                "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
                "oa_status": (w.get("open_access") or {}).get("oa_status"),
                "best_license": best.get("license"), "best_pdf": best.get("pdf_url"),
                "locations": locs}
        return out
    chunks = [todo[i:i + 50] for i in range(0, len(todo), 50)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for part in ex.map(batch, chunks):
            cache.update(part)
    _save(f"openalex_{kind}.json", cache)
    return {i: cache.get(i) for i in ids}


IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={ids}&format=json&tool=schematiq-benchmark"


def idconv(ids):
    """NCBI ID converter: PMID or DOI -> PMCID. Authoritative for PMC membership."""
    cache = _load("idconv.json")
    todo = [i for i in ids if i not in cache]
    for k in range(0, len(todo), 150):
        chunk = todo[k:k + 150]
        st, body = http_get(IDCONV.format(ids=urllib.parse.quote(",".join(chunk))), timeout=60)
        if body is None:
            continue
        got = {}
        try:
            for rec in json.loads(body).get("records", []):
                key = rec.get("requested-id") or rec.get("pmid") or rec.get("doi")
                if rec.get("pmcid"):
                    got[str(key).lower()] = rec["pmcid"]
        except Exception:
            continue
        for i in chunk:
            cache[i] = got.get(i.lower())
        time.sleep(0.4)
    _save("idconv.json", cache)
    return {i: cache.get(i) for i in ids}


def europepmc(pmcids):
    """PMCID -> {inEPMC, isOpenAccess, license, hasPDF}. OR-queries of 40 ids."""
    cache = _load("europepmc_pmcid.json")
    todo = [i for i in pmcids if i not in cache]
    def batch(chunk):
        q = " OR ".join(f"PMCID:{c}" for c in chunk)
        url = (f"{EPMC_SEARCH}?query={urllib.parse.quote(q)}&resultType=core&format=json"
               f"&pageSize={len(chunk)}")
        st, body = http_get(url, timeout=60)
        out = {c: None for c in chunk}
        if body is None:
            return {}
        for r in json.loads(body).get("resultList", {}).get("result", []):
            c = r.get("pmcid")
            if c in out:
                out[c] = {"inEPMC": r.get("inEPMC"), "isOpenAccess": r.get("isOpenAccess"),
                          "license": r.get("license"), "hasPDF": r.get("hasPDF"),
                          "doi": (r.get("doi") or "").lower() or None, "title": r.get("title")}
        return out
    chunks = [todo[i:i + 40] for i in range(0, len(todo), 40)]
    with ThreadPoolExecutor(max_workers=3) as ex:
        for part in ex.map(batch, chunks):
            cache.update(part)
    _save("europepmc_pmcid.json", cache)
    return {i: cache.get(i) for i in pmcids}


if __name__ == "__main__":
    inp, outp = sys.argv[1:3]
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    rows = [r for t in T for r in t["rows"]]
    t0 = time.time()
    by_doi = openalex("doi", sorted({r["doi"] for r in rows if r["doi"]}))
    by_pmid = openalex("pmid", sorted({r["pmid"] for r in rows if r["pmid"] and not r["doi"]}))
    for r in rows:
        w = (by_doi.get(r["doi"]) if r["doi"] else None) or (by_pmid.get(r["pmid"]) if r["pmid"] else None)
        r["openalex"] = w
        if w:
            r["pmcid"] = r["pmcid"] or w.get("pmcid")
            r["doi"] = r["doi"] or w.get("doi")
    need = sorted({(r["pmid"] or r["doi"]) for r in rows if not r["pmcid"] and (r["pmid"] or r["doi"])})
    conv = idconv(need)
    for r in rows:
        if not r["pmcid"]:
            r["pmcid"] = conv.get(r["pmid"] or r["doi"] or "")
    pm = europepmc(sorted({r["pmcid"] for r in rows if r["pmcid"]}))
    for r in rows:
        r["europepmc"] = pm.get(r["pmcid"]) if r["pmcid"] else None
    with open(outp, "w", encoding="utf-8") as f:
        for t in T:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    n = len(rows)
    print(f"{n} rows in {time.time()-t0:.0f}s | openalex hit {sum(1 for r in rows if r['openalex'])} "
          f"| is_oa {sum(1 for r in rows if (r['openalex'] or {}).get('is_oa'))} "
          f"| pmcid {sum(1 for r in rows if r['pmcid'])} "
          f"| in Europe PMC full text {sum(1 for r in rows if (r['europepmc'] or {}).get('inEPMC')=='Y')} "
          f"| EPMC OA {sum(1 for r in rows if (r['europepmc'] or {}).get('isOpenAccess')=='Y')} "
          f"| any pdf url {sum(1 for r in rows if any(l.get('pdf_url') for l in (r['openalex'] or {}).get('locations', [])))}")
