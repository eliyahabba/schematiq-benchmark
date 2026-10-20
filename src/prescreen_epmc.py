"""Pick Europe PMC reviews that are likely to become complete tasks, before the
expensive steps. Measured on the first 70 reviews: tasks with 5 or more table
rows whose reference already carries a PMCID reached 5 downloaded documents
in 15 of 17 cases, the others in 26 of 53. The reference list is available
before any table parsing, so a review is kept when at least MIN_PMC of its
references carry a PMCID.

  python3 prescreen_epmc.py <out_records.jsonl> <per_year> [min_pmc] [budget_s]
"""
import json, os, random, re, sys, time
from concurrent.futures import ThreadPoolExecutor
import epmc
from search_epmc import fetch, sample

BASE = 'PUB_TYPE:"Systematic Review" AND OPEN_ACCESS:y AND HAS_FT:y AND HAS_REFLIST:y'


def done_ids():
    ids = set()
    for p in os.listdir("."):
        if p.endswith(".tasks.jsonl") or p.endswith(".rejects.jsonl") or p.startswith("records_"):
            try:
                for l in open(p, encoding="utf-8"):
                    d = json.loads(l)
                    ids.add(d.get("task_id") or d.get("pmcid"))
            except Exception:
                pass
    return ids


def pmc_refs(pmcid):
    x = epmc.xml(pmcid) or ""
    rl = "".join(re.findall(r"<ref-list\b.*?</ref-list>", x, re.S))
    return pmcid, len(re.findall(r'pub-id-type="pmcid"', rl)), len(re.findall(r"<ref(?=[\s>])", rl))


if __name__ == "__main__":
    outp, per_year = sys.argv[1], int(sys.argv[2])
    min_pmc = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    budget = float(sys.argv[4]) if len(sys.argv) > 4 else 220
    rng = random.Random(20260928)
    seen = done_ids()
    cands = []
    for y in range(2014, 2027):
        recs = [r for r in fetch(f"{BASE} AND PUB_YEAR:{y}", pages=1) if r["pmcid"] not in seen]
        cands += [dict(r, stratum=f"biomed_{y}_prescreened") for r in sample(recs, per_year, rng, 2, 6)]
    print(f"{len(cands)} candidates", flush=True)
    t0, kept, res = time.time(), [], {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for pmcid, n_pmc, n_ref in ex.map(pmc_refs, [c["pmcid"] for c in cands]):
            res[pmcid] = (n_pmc, n_ref)
            if time.time() - t0 > budget:
                break
    with open(outp, "w", encoding="utf-8") as f:
        for c in cands:
            n_pmc, n_ref = res.get(c["pmcid"], (0, 0))
            if n_pmc >= min_pmc:
                kept.append(c)
                f.write(json.dumps({"pmcid": c["pmcid"], "stratum": c["stratum"], "journal": c.get("journalTitle"),
                                    "year": c.get("pubYear"), "pmc_refs": n_pmc, "refs": n_ref}) + "\n")
    print(f"screened {len(res)}; kept {len(kept)} with at least {min_pmc} references carrying a PMCID ({time.time()-t0:.0f}s)")
