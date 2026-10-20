"""Concatenate task files, keeping the first task seen for each task_id.
  python3 concat_unique.py <out.jsonl> <in.jsonl> [<in.jsonl> ...]"""
import json, sys
seen = {}
for p in sys.argv[2:]:
    for l in open(p, encoding="utf-8"):
        t = json.loads(l)
        seen.setdefault(t["task_id"], t)
open(sys.argv[1], "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in seen.values()))
print(f"{len(seen)} tasks -> {sys.argv[1]}")
