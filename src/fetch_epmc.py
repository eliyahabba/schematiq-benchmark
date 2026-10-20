import json, sys, time
from concurrent.futures import ThreadPoolExecutor
import epmc
ids = set()
for p in sys.argv[1:]:
    for l in open(p, encoding="utf-8"):
        ids.add(json.loads(l)["task_id"])
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    res = list(ex.map(lambda i: (i, epmc.xml(i) is not None), sorted(ids)))
print(sum(ok for _, ok in res), "/", len(res), f"in {time.time()-t0:.0f}s", [i for i, ok in res if not ok])
