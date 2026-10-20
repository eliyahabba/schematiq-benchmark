"""Stratified sample of Europe PMC open-access reviews, to break the
Frontiers-2026 monoculture of the first sample.

Strata: biomedical systematic reviews per publication year (2012-2026, at most
2 per journal and 6 Frontiers titles per year), plus Campbell Systematic
Reviews (social science), Environmental Evidence (environment), Cochrane
(open-access full texts) and BMC Systematic Reviews.

  python3 search_epmc.py <out_records.jsonl> [per_year] [per_journal_stratum]
"""
import json, random, sys, time, urllib.parse
from net import http_get

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
BASE = 'OPEN_ACCESS:y AND HAS_FT:y AND HAS_REFLIST:y'
SR = 'PUB_TYPE:"Systematic Review"'


def fetch(query, pages=2):
    out, cursor = [], "*"
    for _ in range(pages):
        url = (f"{API}?query={urllib.parse.quote(query)}&format=json&pageSize=1000"
               f"&resultType=lite&cursorMark={urllib.parse.quote(cursor)}")
        st, body = http_get(url, timeout=90)
        if not body:
            break
        d = json.loads(body)
        res = d.get("resultList", {}).get("result", [])
        out += [r for r in res if r.get("pmcid")]
        nxt = d.get("nextCursorMark")
        if not res or not nxt or nxt == cursor:
            break
        cursor = nxt
        time.sleep(0.5)
    return out


def sample(recs, n, rng, per_journal=2, frontiers_cap=None):
    rng.shuffle(recs)
    out, per, fr = [], {}, 0
    for r in recs:
        j = (r.get("journalTitle") or "").lower()
        if per.get(j, 0) >= per_journal:
            continue
        if frontiers_cap is not None and j.startswith("front") and fr >= frontiers_cap:
            continue
        per[j] = per.get(j, 0) + 1
        fr += j.startswith("front")
        out.append(r)
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    outp = sys.argv[1]
    per_year = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    per_j = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    rng = random.Random(20260927)
    strata = [(f"biomed_{y}", f"{SR} AND {BASE} AND PUB_YEAR:{y}", per_year, 2, 6) for y in range(2012, 2027)]
    strata += [("campbell", f'JOURNAL:"Campbell Syst Rev" AND {BASE}', per_j, 10**6, None),
               ("environmental_evidence", f'JOURNAL:"Environ Evid" AND {BASE}', per_j, 10**6, None),
               ("cochrane", f'JOURNAL:"Cochrane Database Syst Rev" AND {SR} AND {BASE}', per_j, 10**6, None),
               ("bmc_systematic_reviews", f'JOURNAL:"Syst Rev" AND {SR} AND {BASE}', 40, 10**6, None)]
    seen, n = set(), 0
    with open(outp, "w", encoding="utf-8") as f:
        for name, q, k, pj, fc in strata:
            recs = [r for r in fetch(q) if r["pmcid"] not in seen]
            got = sample(recs, k, rng, pj, fc)
            for r in got:
                seen.add(r["pmcid"])
                f.write(json.dumps({"pmcid": r["pmcid"], "stratum": name, "journal": r.get("journalTitle"),
                                    "year": r.get("pubYear"), "title": r.get("title")}, ensure_ascii=False) + "\n")
            n += len(got)
            print(f"{name:26s} pool {len(recs):5d} -> {len(got)}", flush=True)
    print("total", n)
