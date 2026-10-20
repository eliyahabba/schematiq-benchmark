"""Build tasks for a records file in time-boxed, resumable slices.

Accepted tasks go to <out>.tasks.jsonl, rejected reviews with their reason to
<out>.rejects.jsonl; a review already in either file is skipped on rerun.
  python3 process_epmc.py <records.jsonl> <out_prefix> [time_budget_s] [workers]
"""
import json, os, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import build_task


def done_ids(*paths):
    s = set()
    for p in paths:
        if os.path.exists(p):
            for l in open(p, encoding="utf-8"):
                try:
                    s.add(json.loads(l)["task_id"])
                except Exception:
                    pass
    return s


def one(rec):
    try:
        t, why = build_task.build(rec["pmcid"], rec.get("stratum"))
    except Exception as e:
        t, why = None, f"error:{type(e).__name__}:{str(e)[:120]}"
    return rec, t, why


if __name__ == "__main__":
    recp, prefix = sys.argv[1], sys.argv[2]
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 240
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    tp, rp = prefix + ".tasks.jsonl", prefix + ".rejects.jsonl"
    done = done_ids(tp, rp)
    todo = [json.loads(l) for l in open(recp, encoding="utf-8")]
    todo = [r for r in todo if r["pmcid"] not in done]
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    t0, n, it = time.time(), 0, iter(todo)
    with ThreadPoolExecutor(max_workers=workers) as ex, open(tp, "a", encoding="utf-8") as ft, \
            open(rp, "a", encoding="utf-8") as fr:
        futs = set()
        for _ in range(workers * 2):
            r = next(it, None)
            if r:
                futs.add(ex.submit(one, r))
        while futs:
            left = budget + 40 - (time.time() - t0)
            try:
                f = next(as_completed(futs, timeout=max(1, left)))
            except Exception:
                # hard stop: abandon slow in-flight reviews; they were not
                # written, so the next run picks them up again
                ft.flush(); fr.flush()
                print(f"processed {n} in {time.time()-t0:.0f}s; stopped with {len(futs)} in flight", flush=True)
                os._exit(0)
            futs.discard(f)
            rec, t, why = f.result()
            if t:
                ft.write(json.dumps(t, ensure_ascii=False) + "\n"); ft.flush()
            else:
                fr.write(json.dumps({"task_id": rec["pmcid"], "stratum": rec.get("stratum"), "reason": why}) + "\n"); fr.flush()
            n += 1
            if time.time() - t0 < budget:
                r = next(it, None)
                if r:
                    futs.add(ex.submit(one, r))
    print(f"processed {n} in {time.time()-t0:.0f}s; {len(todo)-n} left", flush=True)
