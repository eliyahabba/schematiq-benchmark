"""Check that gold cells are grounded in the downloaded documents.

For every row whose document was downloaded, each short cell is tested
against the document's text: every number in the cell must occur in the
document, and a short text cell (at most 4 words) must occur as a phrase.
Long cells (paraphrase and summaries) and the citation column are skipped.
A row with at least 3 checkable cells and none found is flagged as a
suspected wrong document link.

  python3 grounding.py <tasks.jsonl> <docs_dir> <out.jsonl> [time_budget_s]
"""
import html, json, os, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from net import CACHE

TXT = os.path.join(CACHE, "doctext")
os.makedirs(TXT, exist_ok=True)
NUM = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


def norm(s):
    s = html.unescape(s or "").lower().replace("\u2212", "-")
    # thousands separators: "1,318" and "1 318" must both become 1318, in the
    # document and in the cell, or large sample sizes never match
    s = re.sub(r"(?<=\d)[,\u2009\u202f](?=\d{3}(?!\d))", "", s)
    return re.sub(r"[^a-z0-9.%]+", " ", s)


def doc_text(path):
    cp = os.path.join(TXT, os.path.basename(path) + ".txt")
    if os.path.exists(cp):
        return open(cp, encoding="utf-8").read()
    t = ""
    try:
        if path.endswith(".xml"):
            x = open(path, encoding="utf-8", errors="replace").read()
            x = re.sub(r"<ref-list\b.*?</ref-list>", " ", x, flags=re.S)
            t = re.sub(r"<[^>]+>", " ", x)
        else:
            p = subprocess.run(["pdftotext", "-q", path, "-"], capture_output=True, timeout=60)
            t = p.stdout.decode("utf-8", "replace")
    except Exception:
        t = ""
    t = norm(t)
    open(cp, "w", encoding="utf-8").write(t)
    return t


def check_cell(cell, text, nums):
    c = (cell or "").strip()
    if not c or len(c) > 80 or c.lower() in {"nr", "na", "n/a", "-", "yes", "no", "not reported"}:
        return None
    ns = [n.replace(",", ".") for n in NUM.findall(norm(c))]
    if ns:
        return all(n in nums or n.rstrip("0").rstrip(".") in nums for n in ns)
    words = norm(c).split()
    if 1 <= len(words) <= 4 and len(" ".join(words)) >= 3:
        return f" {' '.join(words)} " in f" {text} "
    return None


if __name__ == "__main__":
    inp, docs, outp = sys.argv[1:4]
    budget = float(sys.argv[4]) if len(sys.argv) > 4 else 240
    T = [json.loads(l) for l in open(inp, encoding="utf-8")]
    files = sorted({r["document"]["file"] for t in T for r in t["rows"] if r.get("document")})
    t0 = time.time()
    todo = [f for f in files if not os.path.exists(os.path.join(TXT, f + ".txt"))]
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda f: doc_text(os.path.join(docs, f)) if time.time() - t0 < budget else None, todo))
    missing = sum(1 for f in files if not os.path.exists(os.path.join(TXT, f + ".txt")))
    for t in T:
        cc = t["table"]["citation_col"]
        tot_c = tot_f = rows = suspect = 0
        for r in t["rows"]:
            d = r.get("document")
            if not d:
                continue
            cp = os.path.join(TXT, d["file"] + ".txt")
            if not os.path.exists(cp):
                continue
            text = open(cp, encoding="utf-8").read()
            nums = {n.replace(",", ".") for n in NUM.findall(text)}
            checked = found = 0
            for j, cell in enumerate(r["cells"]):
                if j == cc:
                    continue
                res = check_cell(cell, text, nums)
                if res is None:
                    continue
                checked += 1
                found += bool(res)
            r["grounding"] = {"checkable": checked, "found": found,
                              "suspect_link": checked >= 3 and found == 0}
            rows += 1; tot_c += checked; tot_f += found; suspect += r["grounding"]["suspect_link"]
        t["grounding"] = {"rows_checked": rows, "cells_checkable": tot_c, "cells_found": tot_f,
                          "rate": round(tot_f / tot_c, 3) if tot_c else None, "suspect_rows": suspect}
    open(outp, "w", encoding="utf-8").write("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in T))
    print(f"{len(files)} documents ({missing} not yet extracted), {time.time()-t0:.0f}s -> {outp}")
