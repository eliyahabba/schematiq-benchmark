"""Fetch latest and first-registered versions for every CRD in the task files."""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import prospero

def crds(paths):
    ids = set()
    for p in paths:
        for l in open(p, encoding="utf-8"):
            t = json.loads(l)
            c = t.get("prospero") or (t.get("research_question") or {}).get("prospero_id")
            if c: ids.add(c)
    return sorted(ids)

def one(crd):
    rec = prospero.fetch(crd)
    if rec is None:
        return crd, None, None
    s = prospero.summarize(rec)
    v = s["versions"]
    first = None
    if v:
        lo = min(v, key=lambda x: (x["major"], x["minor"]))
        if (lo["major"], lo["minor"]) != (max(v, key=lambda x: (x["major"], x["minor"]))["major"], max(v, key=lambda x: (x["major"], x["minor"]))["minor"]):
            r1 = prospero.fetch(crd, lo["major"], lo["minor"])
            first = prospero.summarize(r1) if r1 else None
    return crd, s, first

if __name__ == "__main__":
    ids = crds(sys.argv[1:]) if len(sys.argv) > 1 else []
    extra = [x for x in sys.stdin.read().split()] if not sys.stdin.isatty() else []
    ids = sorted(set(ids) | set(extra))
    t0 = time.time()
    ok = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for crd, s, first in ex.map(one, ids):
            ok += s is not None
            if s is None:
                print("FAIL", crd)
    print(f"{ok}/{len(ids)} records in {time.time()-t0:.0f}s")
