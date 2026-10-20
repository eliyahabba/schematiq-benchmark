"""Write the overview at the top of the README: one square per task, grouped by
domain (docs/assets/overview.svg), and the numbers behind it. The README part
between the overview markers is replaced; the rest is left alone.

  python3 src/make_overview.py data/benchmark/tasks.jsonl README.md docs/assets/overview.svg
"""
import json, os, re, sys
from collections import Counter, defaultdict

tasks_p, readme_p, svg_p = sys.argv[1:4]
E = [json.loads(l) for l in open(tasks_p, encoding="utf-8")]
kind = lambda e: e.get("task_type") or "table"
ORDER = ["table", "database", "question_set"]
NAMES = {"table": "Table", "database": "Database", "question_set": "Question set"}
SOURCE = {"europepmc": "Europe PMC systematic reviews", "arxiv": "arXiv surveys and reviews",
          "scdb": "U.S. Supreme Court Database", "ccp": "Comparative Constitutions Project",
          "retraction_watch": "Retraction Watch database", "schematize": "Schematize study (Polish judgments)"}
by_dom = defaultdict(list)
for e in E:
    by_dom[e["domain"]].append(e)
doms = sorted(by_dom.items(), key=lambda x: -len(x[1]))
rows = sum(len(e.get("rows") or []) for e in E)
docs = sum(len(e.get("documents") or []) for e in E)
kinds = Counter(kind(e) for e in E)
verdicts = Counter((e.get("quality") or {}).get("verdict") for e in E)
rewritten = sum(1 for e in E if e.get("question_rewrite") or (e.get("question_provenance") or "").endswith("rewritten"))

# ---- SVG: label column, then squares that wrap at PER_LINE
PER_LINE, CELL, GAP, LABEL_W, ROW_GAP = 46, 11, 3, 230, 12
y, parts = 8, []
for d, es in doms:
    es = sorted(es, key=lambda e: ORDER.index(kind(e)))
    lines = (len(es) + PER_LINE - 1) // PER_LINE
    parts.append(f'<text x="0" y="{y + 9}" class="lab">{d[0].upper() + d[1:]} <tspan class="n">{len(es)}</tspan></text>')
    for i, e in enumerate(es):
        cx, cy = LABEL_W + (i % PER_LINE) * (CELL + GAP), y + (i // PER_LINE) * (CELL + GAP)
        parts.append(f'<rect x="{cx}" y="{cy}" width="{CELL}" height="{CELL}" rx="2" class="{kind(e)}"/>')
    y += lines * (CELL + GAP) + ROW_GAP
lx = 0
for k in ORDER:
    parts.append(f'<rect x="{lx}" y="{y + 6}" width="{CELL}" height="{CELL}" rx="2" class="{k}"/>'
                 f'<text x="{lx + CELL + 6}" y="{y + 15}" class="key">{NAMES[k]} ({kinds[k]})</text>')
    lx += 150
W, H = LABEL_W + PER_LINE * (CELL + GAP), y + 26
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img"
 aria-label="One square per task, grouped by domain: {len(E)} tasks">
<style>
 text{{font:500 13px -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;fill:#1F2328}} .n{{fill:#59636E;font-weight:600}} .key{{font-size:12px;fill:#59636E}}
 .table{{fill:#0E6B6B}} .database{{fill:#3D5A9E}} .question_set{{fill:#9A6412}}
 @media (prefers-color-scheme: dark){{ text{{fill:#E6EDF3}} .n,.key{{fill:#9198A1}} .table{{fill:#5CC2BD}} .database{{fill:#93AEEB}} .question_set{{fill:#E0B062}} }}
</style>
{"".join(parts)}
</svg>
'''
os.makedirs(os.path.dirname(svg_p) or ".", exist_ok=True)
open(svg_p, "w", encoding="utf-8").write(svg)

# ---- README section
src = Counter(e["source"] for e in E)
section = f"""<!-- overview:start (written by src/make_overview.py; edit the script, not this part) -->
![One square per task, grouped by domain]({os.path.relpath(svg_p, os.path.dirname(os.path.abspath(readme_p)) or ".")})

**{len(E)} research questions**, each with the documents it is asked of and the data a researcher built from them: {rows:,} gold rows and {docs:,} verified documents (counted per task), across {len(doms)} domains.

| Kind | Tasks | Rows are | Gold |
|---|---|---|---|
| Table | {kinds['table']} | The studies included in a published review | The review's study table |
| Database | {kinds['database']} | Units of analysis: court cases, constitutions, retracted papers | A coded research database, with analysis questions and gold answers |
| Question set | {kinds['question_set']} | None | Expert questions the data must be able to answer |

| Source | Tasks |
|---|---|
""" + "\n".join(f"| {SOURCE.get(s, s)} | {n} |" for s, n in src.most_common()) + f"""

**Checks.** {sum(n for v, n in verdicts.items() if v)} of {len(E)} tasks were judged by an LLM: {verdicts.get('worthy', 0)} accepted, and {verdicts.get('worthy_with_issues', 0)} accepted with notes. {rewritten} questions were rewritten from the paper's title and abstract, and the authors' text is kept. No person has reviewed the verdicts yet.

Open `ui/browser.html` to explore every task. It needs no server.
<!-- overview:end -->"""
r = open(readme_p, encoding="utf-8").read()
if "<!-- overview:start" in r:
    r = re.sub(r"<!-- overview:start.*?<!-- overview:end -->", lambda m: section, r, flags=re.S)
else:
    # first run: the overview takes the place of the "What is in it" section
    r = re.sub(r"## What is in it\n.*?(?=\n## Layout)", lambda m: "## What is in it\n\n" + section + "\n", r, flags=re.S)
open(readme_p, "w", encoding="utf-8").write(r)
print(f"{len(E)} tasks; wrote {svg_p} ({W}x{H}) and the README overview")
