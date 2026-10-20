"""Add database and question-set tasks (already in export format) to an export
folder: append them to tasks.jsonl and write their tables as CSV.
  python3 merge_task_types.py <export_dir> <tasks.jsonl> [<tasks.jsonl> ...]
"""
import csv, json, os, re, sys

VERDICT = {  # task-level judgment, Claude (LLM), 2026-09-29
    "scdb": ("worthy", ["ideological direction and issue area are SCDB coder judgments; the opinion text supports them but does not state them"]),
    "retraction_watch": ("worthy_with_issues", ["some reasons come from investigations, not from the notice text"]),
    "ccp": ("worthy_with_issues", ["the Constitute text can be a different revision from the one the CCP coded"]),
    "schematize": ("worthy_with_issues", ["no gold table: score by coverage of the expert questions", "documents chosen by keyword, not by the study's retrieval"]),
}
out_dir = sys.argv[1]
os.makedirs(os.path.join(out_dir, "tables"), exist_ok=True)
added = 0
with open(os.path.join(out_dir, "tasks.jsonl"), "a", encoding="utf-8") as f:
    for p in sys.argv[2:]:
        for l in open(p, encoding="utf-8"):
            t = json.loads(l)
            v, iss = VERDICT.get(t["source"], (None, []))
            t["quality"].update({"judged": bool(v), "verdict": v, "issues": sorted(set((t["quality"].get("issues") or []) + iss)),
                                 "judged_by": "Claude (AI), task level; not reviewed by a person"})
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
            if t.get("rows"):
                cols = t["schema"]["columns"]
                with open(os.path.join(out_dir, "tables", re.sub(r"[^A-Za-z0-9._-]+", "_", t["task_id"]) + ".csv"), "w",
                          newline="", encoding="utf-8") as g:
                    w = csv.writer(g); w.writerow(["document_id"] + cols)
                    for r in t["rows"]:
                        w.writerow([r["document_id"]] + [r["cells"].get(c, "") for c in cols])
            added += 1
print(f"added {added} tasks to {out_dir}")
