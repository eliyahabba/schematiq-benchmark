"""Run ScheMatiQ (schematiq-lib) on one benchmark task and score it.

Steps, each written to <work>/ so a failed run can be resumed:
  1. documents -> <work>/docs/<stem>.txt  (the library's loaders read text files:
     PDFs go through pdftotext, JATS XML is stripped to text); stem_map.json
     maps each stem back to its document_id
  2. schema discovery   (python -m schematiq.core.schematiq --config ...)
  3. value extraction   (python -m schematiq.value_extraction.main ...)
  4. rows -> <work>/system.csv  (document_id from the row's _papers)
  5. column mapping -> <work>/mapping.json  (sentence-transformers when installed,
     otherwise word overlap of names and values; edit the file to correct it)
  6. score -> <work>/score.json  (evaluate_database.py: cells and analysis questions)
Question-set tasks stop after step 2 and are scored by coverage: the same LLM
answers, for each expert question, whether the schema's fields can answer it.

  python3 run_schematiq_benchmark.py --export benchmark_export --task ccp:amendment_rules --work runs/ccp_amend \\
      [--docs benchmark_export/documents] [--provider gemini --model <model> --api-key-env GEMINI_API_KEY]
      [--max-keys 25] [--batch 4] [--from-step N]
Requires schematiq-lib installed (pip install -e schematiq-lib) for steps 2-3.
"""
import argparse, csv, json, os, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import evaluate_database as ev


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)[:120]


def to_text(src: Path) -> str:
    b = src.read_bytes()
    if b[:5] == b"%PDF-":
        r = subprocess.run(["pdftotext", "-layout", str(src), "-"], capture_output=True)
        return r.stdout.decode("utf-8", "replace")
    t = b.decode("utf-8", "replace")
    if src.suffix.lower() in (".xml", ".nxml") or t.lstrip().startswith("<"):
        t = re.sub(r"<(ref-list|table-wrap-foot)\b.*?</\1>", " ", t, flags=re.S)
        t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"[ \t]+", " ", t)


def prepare(task, export, docs_dir, work):
    d = work / "docs"; d.mkdir(parents=True, exist_ok=True)
    stems, missing = {}, 0
    base = Path(docs_dir) if docs_dir else export / ("documents_text" if task.get("task_type") in ("database", "question_set") else "documents")
    for doc in task["documents"]:
        src = base / doc["file"]
        if not src.exists():
            missing += 1; continue
        stem = safe(doc["document_id"])
        (d / f"{stem}.txt").write_text(to_text(src), encoding="utf-8")
        stems[stem] = doc["document_id"]
    json.dump(stems, open(work / "stem_map.json", "w"), indent=1)
    print(f"step 1: {len(stems)} documents written, {missing} not found in {base}")


def backend(a):
    b = {"provider": a.provider}
    if a.model:
        b["model"] = a.model
    if a.api_key_env and os.environ.get(a.api_key_env):
        b["api_key"] = os.environ[a.api_key_env]
    return b


def discovery(task, a, work):
    cfg = {"query": task["question"], "docs_path": str(work / "docs"), "backend": backend(a),
           "max_keys_schema": a.max_keys, "documents_batch_size": a.batch, "output_path": str(work / "schema.json")}
    (work / "discovery.json").write_text(json.dumps(cfg, indent=1))
    subprocess.run([sys.executable, "-m", "schematiq.core.schematiq", "--config", str(work / "discovery.json")], check=True)


def extraction(a, work):
    cfg = {"schema_path": str(work / "schema.json"), "docs_directory": str(work / "docs"),
           "output_path": str(work / "extraction.jsonl"), "backend_cfg": backend(a), "mode": "all", "max_workers": 4}
    (work / "extraction.json").write_text(json.dumps(cfg, indent=1))
    subprocess.run([sys.executable, "-m", "schematiq.value_extraction.main", str(work / "extraction.json")], check=True)


def value(v):
    if isinstance(v, dict):
        v = v.get("answer", v.get("value", ""))
    if isinstance(v, list):
        v = "; ".join(str(x.get("answer", x) if isinstance(x, dict) else x) for x in v)
    return "" if v is None else str(v)


def rows_to_csv(work):
    stems = json.load(open(work / "stem_map.json"))
    rows = [json.loads(l) for l in open(work / "extraction.jsonl", encoding="utf-8") if l.strip()]
    cols = sorted({k for r in rows for k in r if not k.startswith("_") and k != "document_directory"})
    n = 0
    with open(work / "system.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["document_id"] + cols)
        for r in rows:
            for p in r.get("_papers") or []:          # one line per source document of the row
                did = stems.get(p) or stems.get(safe(p))
                if did:
                    w.writerow([did] + [value(r.get(c)) for c in cols]); n += 1
    print(f"step 4: {n} system rows, {len(cols)} system columns")


def words(s):
    return {w for w in re.findall(r"[a-z0-9]{3,}", s.lower())}


def map_columns(task, work):
    sysrows = list(csv.DictReader(open(work / "system.csv", encoding="utf-8")))
    scols = [c for c in (sysrows[0].keys() if sysrows else []) if c != "document_id"]
    gcols = task["schema"]["columns"][1:]
    gtxt = {c: c + " " + " ".join(r["cells"].get(c, "") for r in task["rows"][:30]) for c in gcols}
    stxt = {c: c + " " + " ".join(r.get(c, "") for r in sysrows[:30]) for c in scols}
    try:
        from sentence_transformers import SentenceTransformer, util
        m = SentenceTransformer("all-MiniLM-L6-v2")
        G, S = m.encode([gtxt[c] for c in gcols]), m.encode([stxt[c] for c in scols])
        sim = util.cos_sim(G, S).tolist(); how = "sentence-transformers"; thr = 0.45
    except Exception:
        sim = [[len(words(gtxt[g]) & words(stxt[s])) / max(1, len(words(gtxt[g]) | words(stxt[s]))) for s in scols] for g in gcols]
        how = "word overlap"; thr = 0.12
    pairs = sorted(((sim[i][j], gcols[i], scols[j]) for i in range(len(gcols)) for j in range(len(scols))), reverse=True)
    mapping, used = {}, set()
    for s, g, c in pairs:                     # greedy one-to-one assignment
        if s >= thr and g not in mapping and c not in used:
            mapping[g] = c; used.add(c)
    json.dump(mapping, open(work / "mapping.json", "w"), indent=1, ensure_ascii=False)
    print(f"step 5: {len(mapping)}/{len(gcols)} gold columns mapped ({how}); check mapping.json")


def score(task, work):
    (work / "task.json").write_text(json.dumps(task, ensure_ascii=False))
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "evaluate_database.py"),
                        str(work / "task.json"), str(work / "system.csv"), str(work / "mapping.json")], capture_output=True, text=True)
    (work / "score.json").write_text(r.stdout)
    print("step 6:", r.stdout[:600] or r.stderr[-600:])


def coverage(task, a, work):
    from schematiq.core import utils
    schema = json.load(open(work / "schema.json"))
    fields = json.dumps(schema.get("schema", schema), ensure_ascii=False)[:30000]
    llm = utils.build_llm(backend(a))
    out = {}
    for expert, qs in task["expert_questions"].items():
        hits = []
        for q in qs:
            ans = llm.generate(f"Extraction schema (fields and descriptions):\n{fields}\n\nQuestion: {q}\n"
                               "Could data extracted with this schema answer the question? Reply with yes or no only.")
            hits.append(str(ans).strip().lower().startswith("yes"))
        out[expert] = {"covered": sum(hits), "questions": len(qs), "coverage": round(sum(hits) / max(1, len(qs)), 4)}
    out["mean_coverage"] = round(sum(v["coverage"] for v in out.values()) / len(out), 4)
    (work / "coverage.json").write_text(json.dumps(out, indent=1))
    print("coverage:", out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True); ap.add_argument("--task", required=True); ap.add_argument("--work", required=True)
    ap.add_argument("--docs"); ap.add_argument("--provider", default="gemini"); ap.add_argument("--model")
    ap.add_argument("--api-key-env", default="GEMINI_API_KEY"); ap.add_argument("--max-keys", type=int, default=25)
    ap.add_argument("--batch", type=int, default=4); ap.add_argument("--from-step", type=int, default=1)
    ap.add_argument("--to-step", type=int, default=99)
    a = ap.parse_args()
    export, work = Path(a.export), Path(a.work); work.mkdir(parents=True, exist_ok=True)
    task = next(json.loads(l) for l in open(export / "tasks.jsonl", encoding="utf-8") if json.loads(l)["task_id"] == a.task)
    steps = {1: lambda: prepare(task, export, a.docs, work), 2: lambda: discovery(task, a, work)}
    if task.get("task_type") == "question_set":
        steps[3] = lambda: coverage(task, a, work)
    else:
        steps.update({3: lambda: extraction(a, work), 4: lambda: rows_to_csv(work), 5: lambda: map_columns(task, work), 6: lambda: score(task, work)})
    for k in sorted(steps):
        if a.from_step <= k <= a.to_step:
            steps[k]()
