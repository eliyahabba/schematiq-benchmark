"""LLM judge for table tasks, with Gemini.

The judge sees what the session judge (Claude) saw: the review title, the
question and where it came from, the table caption and columns, two rows
(preferring rows whose document was downloaded), the size of the table and
the grounding rate. It answers with the same fields as data/build/judgments.json.

  # 1. calibrate first: judge tasks that already have a verdict, report agreement
  python3 src/judge_tasks.py data/build/tasks.jsonl data/build/judgments.json --calibrate 60 --out runs/judge_calibration.json
  # 2. then judge the tasks that have no verdict yet (added to judgments.json)
  python3 src/judge_tasks.py data/build/tasks.jsonl data/build/judgments.json
Options: --model, --limit N, --task ID (one task), --rejudge (judge again tasks that have a verdict).
"""
import argparse, datetime, json, random, sys
from collections import Counter
from gemini_client import ask_json, DEFAULT_MODEL

VERDICTS = ("worthy", "worthy_with_issues", "partly", "not_worthy")
RUBRIC = """You judge candidate tasks for a benchmark. A task gives a system a research question and a set of
documents; the system must build the review's table, with one row per document (usually one study per row).

Accept a task only when all hold:
- The question is a research question, or a clear aim, that names its topic and can be understood without the paper.
  It is NOT usable when it is a methods sentence ("we searched PubMed..."), a results sentence ("we identified 33 studies"),
  a background or conclusion sentence, or names no topic.
- The table has one row per document (study, paper, dataset paper, case report). It is NOT one when rows are
  categories, taxonomies, technologies, paradigms, programs, products, comparisons of earlier surveys, or aggregate counts.
- The table is not a quality or risk-of-bias appraisal (e.g. Newcastle-Ottawa, AMSTAR, PEDro checklists), not a screening
  log, and not only bibliographic fields (author, year, title, journal).
- The table relates to the question.

Verdicts:
- "worthy": all hold, no notable problem.
- "worthy_with_issues": all hold, with problems worth noting, for example coded values, long free-text cells,
  rows are datasets or benchmarks, thin table (few informative columns), LaTeX leftovers, low grounding,
  one appraisal column mixed in, question needs the paper title for its topic.
- "partly": usable, but the table covers only part of the question.
- "not_worthy": any acceptance rule fails.
Give issues as short phrases (at most 6 words each), at most 3.

Answer with JSON only:
{"verdict": "...", "issues": ["..."], "question_usable": true, "table_relates": "yes|partly|no", "document_per_row": true}
"""


def view(t):
    cols = t["table"]["columns"]
    rows = sorted(t["rows"], key=lambda r: not r.get("document"))[:2]
    show = lambda r: {c: (r["cells"][i] if i < len(r["cells"]) else "")[:160] for i, c in enumerate(cols)}
    g = (t.get("grounding") or {}).get("rate")
    return (f"Review title: {t['title']}\n"
            f"Question ({t['question'].get('provenance')}): {t['question']['text'][:700]}\n"
            f"Table caption: {(t['table'].get('caption') or '')[:400]}\n"
            f"Table taken from: {t['table'].get('from')}; rows: {t['counts']['rows']}; documents downloaded: {t['counts']['documents_downloaded']}\n"
            f"Grounding (share of short cells found in their document): {g}\n"
            f"Columns: {json.dumps(cols, ensure_ascii=False)}\n"
            f"Two rows: {json.dumps([show(r) for r in rows], ensure_ascii=False)}\n")


def judge(t, model):
    a = ask_json(RUBRIC + "\nTask:\n" + view(t), model=model,
                 fake={"verdict": "worthy", "issues": [], "question_usable": True, "table_relates": "yes", "document_per_row": True})
    v = a.get("verdict")
    if v not in VERDICTS:
        raise RuntimeError(f"bad verdict {v!r} for {t['task_id']}")
    return {"verdict": v, "issues": [str(x)[:80] for x in (a.get("issues") or [])][:3],
            "question_usable": bool(a.get("question_usable", v != "not_worthy")),
            "table_relates": a.get("table_relates", "yes"), "scope_drift": "none",
            "document_per_row": bool(a.get("document_per_row", v != "not_worthy")),
            "note": "; ".join(a.get("issues") or []),
            "judged_by": f"Gemini {model or DEFAULT_MODEL} as judge, {datetime.date.today()}: same view as the session judge; not a human audit"}


def accept(v):
    return v in ("worthy", "worthy_with_issues", "partly")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks"); ap.add_argument("judgments")
    ap.add_argument("--model"); ap.add_argument("--limit", type=int); ap.add_argument("--task")
    ap.add_argument("--rejudge", action="store_true"); ap.add_argument("--calibrate", type=int, metavar="N")
    ap.add_argument("--out", default="runs/judge_calibration.json")
    a = ap.parse_args()
    T = [json.loads(l) for l in open(a.tasks, encoding="utf-8")]
    J = json.load(open(a.judgments, encoding="utf-8"))
    if a.calibrate:
        have = [t for t in T if (J.get(t["task_id"]) or {}).get("verdict")]
        random.Random(7).shuffle(have)
        pairs = []
        for t in have[:a.calibrate]:
            pairs.append((J[t["task_id"]]["verdict"], judge(t, a.model)["verdict"], t["task_id"]))
        n = len(pairs)
        agree = sum(1 for x, y, _ in pairs if accept(x) == accept(y)) / max(1, n)
        exact = sum(1 for x, y, _ in pairs if x == y) / max(1, n)
        po, pa = agree, sum(1 for x, _, _ in pairs if accept(x)) / max(1, n)
        pb = sum(1 for _, y, _ in pairs if accept(y)) / max(1, n)
        pe = pa * pb + (1 - pa) * (1 - pb)
        rep = {"tasks": n, "accept_reject_agreement": round(agree, 3), "exact_verdict_agreement": round(exact, 3),
               "cohen_kappa_accept_reject": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
               "confusion (existing -> Gemini)": dict(Counter(f"{x} -> {y}" for x, y, _ in pairs)),
               "disagreements": [{"task": i, "existing": x, "gemini": y} for x, y, i in pairs if accept(x) != accept(y)]}
        import os
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        json.dump(rep, open(a.out, "w"), indent=1)
        print(json.dumps({k: v for k, v in rep.items() if k != "disagreements"}, indent=1))
        sys.exit()
    todo = [t for t in T if (a.task is None or t["task_id"] == a.task) and (a.rejudge or not (J.get(t["task_id"]) or {}).get("verdict"))]
    todo = todo[:a.limit] if a.limit else todo
    for i, t in enumerate(todo, 1):
        J[t["task_id"]] = judge(t, a.model)
        if i % 10 == 0 or i == len(todo):
            json.dump(J, open(a.judgments, "w", encoding="utf-8"), indent=1, ensure_ascii=False)   # save as we go
            print(f"{i}/{len(todo)} judged", flush=True)
    print(f"judged {len(todo)}:", dict(Counter(J[t['task_id']]["verdict"] for t in todo)))
