"""Score a system's database against a database task.

The gold database is meant to be queried, so the score has two parts:
  cells    : per mapped column, share of rows (matched by document_id) whose
             value agrees with the gold value (normalised text, numbers within
             1%, multi-valued ';' cells by set overlap >= 0.5)
  answers  : the analysis questions of the task (shares of each category and
             means of numeric columns), computed on both databases; reported
             as the mean absolute error of the shares and the relative error
             of the means
Columns are mapped with a JSON file {gold column: system column}; without one,
names are matched after normalisation.

  python3 evaluate_database.py <task.json> <system.csv> [mapping.json]
  python3 evaluate_database.py --questions <task.json>     (print the analysis questions with gold answers)
"""
import csv, json, re, statistics, sys
from collections import Counter

NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def norm(v):
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def kind(values):
    v = [x for x in values if x]
    if v and sum(1 for x in v if NUM.match(x)) / len(v) >= 0.9:
        return "number"
    if v and len(set(v)) <= 12:
        return "category"
    return "text"


def same(a, b):
    a, b = norm(a), norm(b)
    if NUM.match(a) and NUM.match(b):
        x, y = float(a), float(b)
        return abs(x - y) <= 0.01 * max(1.0, abs(x))
    if ";" in a or ";" in b:
        A, B = {x.strip() for x in a.split(";") if x.strip()}, {x.strip() for x in b.split(";") if x.strip()}
        return bool(A | B) and len(A & B) / len(A | B) >= 0.5
    return a == b


def questions(task):
    cols = task["schema"]["columns"][1:]
    rows = [r["cells"] for r in task["rows"]]
    out = []
    for c in cols:
        vals = [norm(r.get(c, "")) for r in rows]
        k = kind(vals)
        items = Counter(x.strip() for v in vals for x in v.split(";") if x.strip()) if any(";" in v for v in vals) else None
        if items and len(items) > 1 and k != "number":
            n = sum(1 for v in vals if v)
            top = {x: round(cnt / n, 4) for x, cnt in items.most_common(10)} if n else {}
            out.append({"column": c, "kind": "share_multi",
                        "question": f"What share of the documents mentions each of the most common values of '{c}'?", "gold": top})
        elif k == "category":
            n = sum(1 for v in vals if v)
            dist = {v: round(cnt / n, 4) for v, cnt in Counter(v for v in vals if v).most_common()} if n else {}
            out.append({"column": c, "kind": "share", "question": f"What share of the documents falls in each value of '{c}'?", "gold": dist})
        elif k == "number":
            nums = [float(v) for v in vals if NUM.match(v)]
            if nums:
                out.append({"column": c, "kind": "mean", "question": f"What is the mean of '{c}'?", "gold": round(statistics.mean(nums), 4)})
    return out


def answer(q, rows, col):
    vals = [norm(r.get(col, "")) for r in rows] if col else []
    if q["kind"] == "share_multi":
        n = sum(1 for v in vals if v)
        return {k: sum(1 for v in vals if k in {x.strip() for x in v.split(";")}) / n for k in q["gold"]} if n else {}
    if q["kind"] == "share":
        n = sum(1 for v in vals if v)
        return {v: cnt / n for v, cnt in Counter(v for v in vals if v).items()} if n else {}
    nums = [float(v) for v in vals if NUM.match(v)]
    return statistics.mean(nums) if nums else None


if __name__ == "__main__":
    if sys.argv[1] == "--questions":
        print(json.dumps(questions(json.load(open(sys.argv[2]))), indent=1, ensure_ascii=False)); sys.exit()
    task = json.load(open(sys.argv[1]))
    sysrows = list(csv.DictReader(open(sys.argv[2], encoding="utf-8")))
    gcols = task["schema"]["columns"][1:]
    if len(sys.argv) > 3:
        mapping = json.load(open(sys.argv[3]))
    else:
        scols = {norm(c): c for c in (sysrows[0].keys() if sysrows else [])}
        mapping = {c: scols[norm(c)] for c in gcols if norm(c) in scols}
    by_doc = {r.get("document_id"): r for r in sysrows}
    cells = {}
    for c in gcols:
        if c not in mapping:
            cells[c] = None; continue
        pairs = [(g["cells"].get(c, ""), by_doc[g["document_id"]].get(mapping[c], "")) for g in task["rows"] if g["document_id"] in by_doc]
        pairs = [(a, b) for a, b in pairs if a]
        cells[c] = round(sum(1 for a, b in pairs if same(a, b)) / len(pairs), 4) if pairs else None
    share_err, mean_err = [], []
    for q in questions(task):
        col = mapping.get(q["column"])
        got = answer(q, sysrows, col) if col else None
        if q["kind"] in ("share", "share_multi"):
            keys = set(q["gold"]) | set(got or {})
            share_err.append(sum(abs(q["gold"].get(k, 0) - (got or {}).get(k, 0)) for k in keys) / max(1, len(keys)))
        elif q["kind"] == "mean":
            mean_err.append(abs((got if got is not None else 0) - q["gold"]) / max(1e-9, abs(q["gold"])) if got is not None else 1.0)
    mapped = [v for v in cells.values() if v is not None]
    print(json.dumps({"columns_mapped": f"{len(mapping)}/{len(gcols)}",
                      "rows_matched": sum(1 for g in task["rows"] if g["document_id"] in by_doc), "rows_gold": len(task["rows"]),
                      "cell_accuracy_mean": round(statistics.mean(mapped), 4) if mapped else None,
                      "share_questions": len(share_err), "share_mean_abs_error": round(statistics.mean(share_err), 4) if share_err else None,
                      "mean_questions": len(mean_err), "mean_relative_error": round(statistics.mean(mean_err), 4) if mean_err else None,
                      "cell_accuracy_by_column": cells}, indent=1, ensure_ascii=False))
