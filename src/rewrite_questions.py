"""Rewrite task questions into research questions, with Gemini (rules: docs/QUESTIONS.md).

The model sees only the paper title, the abstract and the authors' own aim
sentence, never the table. Every rewrite gets the same checks as the session
rewrites (src/question_checks.py): grounding in title, abstract and aim, and
how many gold column names it spells out. A rewrite is kept only if it ends
with "?", its grounding is at least 0.6, and it names at most 2 more gold
columns than the authors' text; otherwise the authors' text stays.

  python3 src/rewrite_questions.py data/build/tasks.jsonl data/build/questions_rewritten.json data/build/judgments.json
Rewrites tasks that are core or accepted by the judge, whose question is not
already a question and that have no rewrite yet. Options: --model, --limit N, --task ID.
After it, run finalize.py again: it applies the rewrites.
"""
import argparse, datetime, json, re
import question_checks as C
from gemini_client import ask_json, DEFAULT_MODEL

PROMPT = open(__file__.replace("rewrite_questions.py", "rewrite_prompt.txt"), encoding="utf-8").read()


def abstract(t):
    tid = t["task_id"]
    try:
        if tid.startswith("PMC"):
            import epmc
            x = epmc.xml(tid) or ""
            m = re.search(r'<abstract\b(?![^>]*abstract-type="(graphical|teaser)")[^>]*>(.*?)</abstract>', x, re.S)
            return epmc.strip(m.group(2)) if m else ""
        if tid.startswith("arXiv:"):
            import arxiv_src
            st, body = arxiv_src.arxiv_get("http://export.arxiv.org/api/query?id_list=" + tid.split(":", 1)[1])
            m = re.search(r"<summary>(.*?)</summary>", body or "", re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    except Exception:
        return ""
    return ""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks"); ap.add_argument("rewrites"); ap.add_argument("judgments")
    ap.add_argument("--model"); ap.add_argument("--limit", type=int); ap.add_argument("--task")
    a = ap.parse_args()
    T = [json.loads(l) for l in open(a.tasks, encoding="utf-8")]
    R = json.load(open(a.rewrites, encoding="utf-8"))
    J = json.load(open(a.judgments, encoding="utf-8"))
    ok = lambda t: t["tier"] == "core" or (J.get(t["task_id"]) or {}).get("verdict") in ("worthy", "worthy_with_issues", "partly")
    todo = [t for t in T if (a.task is None or t["task_id"] == a.task) and ok(t) and t["task_id"] not in R
            and not t["question"]["text"].strip().endswith("?")]
    todo = todo[:a.limit] if a.limit else todo
    kept = refused = 0
    for t in todo:
        ab, author = abstract(t), t["question"]["text"]
        ans = ask_json(PROMPT + "\n\nAnswer with JSON only: {\"question\": \"...\"}\n\n"
                       f"Title: {t['title']}\nAbstract: {ab[:3000]}\nAuthors' statement of aim: {author[:1000]}",
                       model=a.model, fake={"question": f"What does the review '{t['title'][:80]}' find?"})
        q = str(ans.get("question", "")).strip()
        cols = t["table"]["columns"]
        checks = {"grounded": C.grounded(q, t["title"], ab, author), "columns_named_before": C.leakage(author, cols),
                  "columns_named_after": C.leakage(q, cols)}
        if q.endswith("?") and checks["grounded"] >= 0.6 and checks["columns_named_after"] <= checks["columns_named_before"] + 2:
            R[t["task_id"]] = {"question": q, "author_text": author,
                               "based_on": "paper title, abstract and the authors' own aim sentence; the table was not shown to the writer",
                               "by": f"Gemini {a.model or DEFAULT_MODEL}, {datetime.date.today()}; rules in docs/QUESTIONS.md", "checks": checks}
            kept += 1
        else:
            refused += 1
            print("kept the authors' text for", t["task_id"], "| rewrite failed the checks:", q[:100], checks)
        json.dump(R, open(a.rewrites, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{kept} rewrites kept, {refused} refused by the checks, out of {len(todo)}")
