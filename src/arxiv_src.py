"""arXiv source: review papers whose LaTeX tables cite one study per row.

Pilot scope (2026-09-27): systematic literature reviews and mapping studies
in cs.*. The question is the paper's own research questions (RQ1, RQ2, ...),
or its stated aim; it is written after the table, which the benchmark accepts.
arXiv asks automated clients for one request every 3 seconds; every arXiv
call here goes through one throttled function.

  python3 arxiv_src.py <out.tasks.jsonl> [max_papers]
"""
import gzip, io, json, os, re, sys, tarfile, threading, time, urllib.parse
from net import http_get, _path
import quality, questions

API = "http://export.arxiv.org/api/query?search_query={q}&start={start}&max_results={n}&sortBy=submittedDate"
_LOCK, _LAST = threading.Lock(), [0.0]


def arxiv_get(url, binary=False, timeout=60):
    from net import arxiv_wait
    with _LOCK:
        arxiv_wait()
        return http_get(url, binary=binary, tries=2, timeout=timeout)


def search(query, n, start=0):
    st, body = arxiv_get(API.format(q=urllib.parse.quote(query), n=n, start=start))
    out = []
    for e in re.findall(r"<entry>(.*?)</entry>", body or "", re.S):
        aid = re.search(r"<id>https?://arxiv.org/abs/([^<]+)</id>", e).group(1)
        title = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", e, re.S).group(1)).strip()
        summ = re.sub(r"\s+", " ", re.search(r"<summary>(.*?)</summary>", e, re.S).group(1)).strip()
        year = re.search(r"<published>(\d{4})", e).group(1)
        out.append({"id": re.sub(r"v\d+$", "", aid), "title": title, "abstract": summ, "year": year})
    return out


def source_files(aid):
    p = _path("arxiv_src", aid, ".bin")
    if os.path.exists(p):
        b = open(p, "rb").read()
    else:
        st, b = arxiv_get(f"https://arxiv.org/e-print/{aid}", binary=True, timeout=120)
        if not b:
            return {}
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").write(b)
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(b), mode="r:*") as tf:
            for m in tf.getmembers():
                if m.isfile() and m.name.lower().endswith((".tex", ".bbl", ".bib")) and m.size < 5_000_000:
                    files[m.name] = tf.extractfile(m).read().decode("utf-8", "replace")
    except tarfile.ReadError:
        try:
            files["main.tex"] = gzip.decompress(b).decode("utf-8", "replace")
        except Exception:
            if b[:1] in (b"\\", b"%"):
                files["main.tex"] = b.decode("utf-8", "replace")
    return files


# ---------------- LaTeX helpers ----------------
def strip_comments(s):
    return re.sub(r"(?<!\\)%.*", "", s)


def cite_keys(s):
    keys = []
    for m in re.finditer(r"\\(?!citestyle)[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}", s):
        keys += [k.strip() for k in m.group(1).split(",") if k.strip()]
    return keys


def latex_text(s):
    s = re.sub(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:textbf|textit|emph|texttt|textsc|underline|mathrm|mathbf|text|makecell|shortstack|hl)\{", "{", s)
    s = re.sub(r"\\(?:multirow|multicolumn)\{[^}]*\}\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:href|url)\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:textcolor|color|colorbox)\{[^}]*\}", "", s)
    s = re.sub(r"\\(?:checkmark|cmark|ding\{51\})", "yes", s)
    s = re.sub(r"\\(?:xmark|ding\{55\})", "no", s)
    s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("~", " ")
    s = re.sub(r"[{}$]", "", s)
    s = re.sub(r"(?:(?<=\s)|^)-?\d+(?:\.\d+)?(?:em|ex|cm|mm|pt|in)(?=[A-Z\s]|$)", " ", s)   # "0.6emARNOLD", "2.4cm..."
    s = re.sub(r"=\[-?\d+(?:\.\d+)?(?:em|ex|pt)\]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_top(s, sep):
    """Split on sep at brace depth 0 (so \\& and {a & b} are kept)."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(s):
        ch = s[i]
        # the separator is checked first: the row separator is itself a backslash pair
        if depth == 0 and s.startswith(sep, i):
            out.append("".join(cur)); cur = []; i += len(sep); continue
        if ch == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2]); i += 2; continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        cur.append(ch); i += 1
    out.append("".join(cur))
    return out


RULE = re.compile(r"\\(toprule|midrule|bottomrule|hline|cline\{[^}]*\}|cmidrule(\([^)]*\))?\{[^}]*\}|specialrule\{[^}]*\}\{[^}]*\}\{[^}]*\}|endhead|endfirsthead|endfoot|endlastfoot)")


def parse_tabular(body):
    """Rows of cells (raw LaTeX) and the index of the first body row."""
    body = re.sub(r"\\(?:rowcolor|cellcolor|columncolor)(?:\[[^\]]*\])?\{[^}]*\}", "", body)
    body = re.sub(r"\\caption(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\}", "", body)
    body = re.sub(r"\\label\{[^}]*\}", "", body)
    raw_rows = split_top(body, "\\\\")
    rows, header_end = [], None
    for rr in raw_rows:
        had_mid = bool(re.search(r"\\midrule|\\hline", rr))
        rr = RULE.sub(" ", rr).strip()
        rr = re.sub(r"^\[[^\]]*\]", "", rr).strip()
        if had_mid and rows and header_end is None:
            header_end = len(rows)
        if not rr:
            continue
        cells = []
        for c in split_top(rr, "&"):
            m = re.match(r"\s*\\multicolumn\{(\d+)\}\{[^}]*\}\{(.*)\}\s*$", c, re.S)
            if m:
                cells += [m.group(2)] + [""] * (int(m.group(1)) - 1)
            else:
                cells.append(c)
        rows.append(cells)
    return rows, header_end if header_end is not None else 1


def tables_in(tex):
    tex = strip_comments(tex)
    out = []
    for env in re.finditer(r"\\begin\{(table\*?|longtable|sidewaystable\*?)\}(.*?)\\end\{\1\}", tex, re.S):
        block = env.group(2)
        cap = re.search(r"\\caption(?:\[[^\]]*\])?\{((?:[^{}]|\{[^{}]*\})*)\}", block)
        caption = latex_text(cap.group(1)) if cap else ""
        if env.group(1) == "longtable":
            # drop the column spec that opens the environment
            tab = re.sub(r"^\s*(?:\[[^\]]*\])?\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}", "", block, count=1)
        else:
            m = re.search(r"\\begin\{(tabular\*?|tabularx|tabulary|xltabular|supertabular|tblr)\}(?:\{[^}]*\})?(?:\[[^\]]*\])?\{(?:[^{}]|\{[^{}]*\})*\}(.*?)\\end\{\1\}", block, re.S)
            if not m:
                continue
            tab = m.group(2)
        rows, h = parse_tabular(tab)
        if len(rows) >= 6:
            out.append({"caption": caption, "rows": rows, "header_end": h})
    return out


# ---------------- bibliography ----------------
def bib_entries(files):
    ent = {}
    for name, s in files.items():
        if name.endswith(".bib"):
            for m in re.finditer(r"@\w+\s*\{\s*([^,\s]+)\s*,(.*?)\n\s*\}\s*(?=@|\Z)", s, re.S):
                f = {k.lower(): re.sub(r"[{}\s]+", " ", v).strip() for k, v in re.findall(
                    r"(\w+)\s*=\s*[{\"]((?:[^{}\"]|\{[^{}]*\})*)[}\"]", m.group(2))}
                ent[m.group(1)] = {"title": f.get("title"), "year": (re.search(r"\d{4}", f.get("year", "")) or [None])[0],
                                   "doi": f.get("doi"), "arxiv": _arxiv_id(" ".join(f.get(k, "") for k in ("eprint", "url", "journal", "note", "howpublished", "archiveprefix")))}
        elif name.endswith(".bbl"):
            for m in re.finditer(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}(.*?)(?=\\bibitem|\\end\{thebibliography\})", s, re.S):
                seg = [latex_text(x) for x in re.split(r"\\newblock", m.group(2))]
                title = seg[1] if len(seg) > 1 else None
                ent.setdefault(m.group(1), {"title": title.rstrip(". ") if title else None,
                                            "year": (re.search(r"\b(19|20)\d{2}\b", m.group(2)) or [None])[0],
                                            "doi": (re.search(r"10\.\d{4,9}/[^\s}\\]+", m.group(2)) or [None])[0],
                                            "arxiv": _arxiv_id(m.group(2))})
    return ent


def _arxiv_id(s):
    m = re.search(r"(?:arxiv[:\s/]*(?:abs/)?|abs/)(\d{4}\.\d{4,5})", s or "", re.I)
    return m.group(1) if m else None


# ---------------- research questions ----------------
def research_questions(tex, abstract):
    t = latex_text(strip_comments(tex))
    rqs = []
    for m in re.finditer(r"\bRQ\s?(\d)\s*[:.)\-–]?\s*((?:What|How|Which|Why|To what|Is|Are|Do|Does|Can|In what|Where|When|Who)[^?]{10,300}\?)", t):
        n = int(m.group(1))
        if n not in [x[0] for x in rqs]:
            rqs.append((n, m.group(2).strip()))
    rqs.sort()
    if rqs:
        return " ".join(f"RQ{n}: {q}" for n, q in rqs[:4]), "paper_research_questions"
    best, best_score = None, 1
    for s in re.split(r"(?<=[.!?])\s+", abstract or ""):
        score = 0
        if SURVEY_SENT.search(s):
            score += 2
        if questions.AIM.search(s) or questions.INFINITIVE.match(s):
            score += 1
        if BAD_START.match(s):
            score -= 3
        if VAGUE.search(s):
            score -= 2
        if 60 <= len(s) <= 350:
            score += 1
        if score > best_score:
            best, best_score = s, score
    if best and best_score >= 3:
        return best, "abstract"
    return None, None


SURVEY_SENT = re.compile(r"\b(this|our|the present) (survey|review|paper|article|work|chapter)\b|\bin this (survey|review|paper|article|work|chapter)\b|"
                         r"\bwe (survey|review|systematically|present a (comprehensive |systematic |structured |brief )?(survey|review|overview))\b|"
                         r"\bhere,? we (review|summari[sz]e|discuss|present|provide|describe|outline|overview)\b|"
                         r"\bwe (summari[sz]e|discuss|provide an? (overview|review|summary)|give an? (overview|review))\b", re.I)
BAD_START = re.compile(r"^(finally|to fill (this|the) gap|beyond|cutting across|additionally|moreover|furthermore|lastly|"
                       r"in addition|we also|then|however|thus|hence|these|such)\b", re.I)
VAGUE = re.compile(r"\b(this|the) (topic|gap|area|field|problem|direction)\b", re.I)


APPRAISAL = re.compile(r"quality (assess|score)|risk of bias|\bQA\d|\bQ\d+\b|criteria met", re.I)
COLSPEC = re.compile(r"^(?:\s|[@|>*<]|\d+(?=[>\s])|\b[lcrXSmb]\b|\bp\s?\d*\.?\d+(?:cm|mm|in|pt|em)?\b)+(?=\S)")
DEBRIS_ROW = re.compile(r"table\s*\\?\s*continued|continued (on|from) (the )?(next|previous) page|^l?table\s+tab:|tab:[a-z]", re.I)
BIBLIO = re.compile(r"^(title|paper title|year|venue|publication( forum| venue| year)?|forum|database|citation(s| count)?|"
                    r"cites|ref\.?|reference|id|sid|pid|no\.?|#|\\#|authors?|doi|url|link|source|type|article type|publisher)$", re.I)


def build(paper):
    files = source_files(paper["id"])
    tex = "\n".join(v for k, v in files.items() if k.endswith(".tex"))
    if not tex:
        return None, "no_latex_source"
    bib = bib_entries(files)
    q, prov = research_questions(tex, paper["abstract"])
    if not q:
        return None, "no_question"
    best = None
    for tb in tables_in(tex):
        rows, h = tb["rows"], tb["header_end"]
        head, body = rows[:h], rows[h:]
        if len(body) < 5:
            continue
        ncol = max(len(r) for r in rows)
        if ncol < 3:
            continue
        cov = [sum(1 for r in body if j < len(r) and cite_keys(r[j])) / len(body) for j in range(ncol)]
        cc = max(range(ncol), key=lambda j: cov[j])
        if cov[cc] < 0.6:
            continue
        cols = []
        for j in range(ncol):
            name = " - ".join(dict.fromkeys(latex_text(r[j]) for r in head if j < len(r) and latex_text(r[j])))
            name = COLSPEC.sub("", name).strip(" -")
            cols.append(name or f"col{j}")
        half = ncol // 2
        if ncol % 2 == 0 and half >= 2 and [c.lower() for c in cols[:half]] == [c.lower() for c in cols[half:]]:
            # two copies of the same table side by side: one study per half-row
            body = [r[:half] for r in body] + [r[half:] for r in body if any(latex_text(x) for x in r[half:])]
            cols, ncol = cols[:half], half
            cov = [sum(1 for r in body if j < len(r) and cite_keys(r[j])) / len(body) for j in range(ncol)]
            cc = max(range(ncol), key=lambda j: cov[j])
            if cov[cc] < 0.6:
                continue
        head_txt = [c.lower() for c in cols]
        body = [r for r in body
                if [latex_text(x).lower() for x in r[:ncol]] != head_txt[:len(r)]
                and not DEBRIS_ROW.search(" ".join(latex_text(x) for x in r))
                and sum(1 for x in r if latex_text(x)) >= 2]
        if len(body) < 5:
            continue
        content = [c for j, c in enumerate(cols) if j != cc]
        if content and sum(1 for c in content if BIBLIO.match(c.strip())) >= 0.7 * len(content):
            continue  # a list of papers (title, year, venue), nothing to extract
        filled = sum(1 for r in body for j in range(ncol) if j != cc and j < len(r) and latex_text(r[j]))
        if filled < 0.4 * len(body) * max(1, ncol - 1):
            continue  # cells are icons or empty: nothing to extract
        if sum(1 for c in cols if re.fullmatch(r"col\d+", c)) > ncol * 0.25 or APPRAISAL.search(" ".join(cols) + " " + tb["caption"]):
            continue
        linked = []
        for r in body:
            keys = cite_keys(r[cc]) if cc < len(r) else []
            ent = bib.get(keys[0], {}) if keys else {}
            linked.append((r, keys, ent))
        n_bib = sum(1 for _, k, e in linked if e.get("title") or e.get("arxiv") or e.get("doi"))
        cand = (n_bib, len(body), tb, cols, cc, linked, cov[cc])
        if best is None or cand[:2] > best[:2]:
            best = cand
    if not best or best[0] < 5:
        return None, "no_citation_table"
    n_bib, nb, tb, cols, cc, linked, cov = best
    rows = []
    for i, (r, keys, ent) in enumerate(linked):
        cells = [latex_text(c) for c in r] + [""] * (len(cols) - len(r))
        if not cells[cc]:
            cells[cc] = keys[0] if keys else ""
        rows.append({"i": i, "cells": cells[:len(cols)], "matched_by": "latex_cite" if keys else None,
                     "ref_id": keys[0] if keys else None, "n_refs_in_row": len(keys),
                     "doi": (ent.get("doi") or "").lower().rstrip(".") or None, "pmid": None, "pmcid": None,
                     "arxiv_id": ent.get("arxiv"), "ref_title": ent.get("title"), "ref_year": ent.get("year"),
                     "first_author": None, "citation": ent.get("title")})
    ok_q, why_q = questions.gate(q) if prov == "abstract" else (True, "ok")
    if not ok_q and why_q == "no_objective_verb" and SURVEY_SENT.search(q):
        ok_q, why_q = True, "ok"   # "This survey covers ..." states the aim without an objective verb
    return {"task_id": "arXiv:" + paper["id"], "source": "arxiv", "stratum": "arxiv", "pmcid": None,
            "url": f"https://arxiv.org/abs/{paper['id']}", "title": paper["title"], "journal": "arXiv",
            "year": paper["year"], "doi": None, "license": "see arXiv record",
            "question": {"text": q, "provenance": prov, "topic": paper["title"],
                         "source": "research questions stated in the paper" if prov != "abstract" else "abstract of the paper",
                         "prospero_id": None, "prospero_url": None, "version": None,
                         "changed_after_registration": False, "abstract_objective": None},
            "protocol": None, "registration": None,
            "gates": {"question": why_q if ok_q else "fail:" + why_q, "table": "ok"},
            "table": {"label": "LaTeX table", "caption": tb["caption"], "columns": cols, "n_rows": len(rows),
                      "citation_col": cc, "citation_coverage": round(cov, 3), "positive_caption": False,
                      "from": "latex", "merged_from": None},
            "rows": rows}, "ok"


if __name__ == "__main__":
    outp = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else 230
    t0 = time.time()
    done = set()
    if os.path.exists(outp + ".log"):
        done = {json.loads(l)["id"] for l in open(outp + ".log")}
    query = sys.argv[4] if len(sys.argv) > 4 else '(ti:"systematic literature review" OR ti:"systematic mapping") AND cat:cs.*'
    start = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    papers = search(query, n, start)
    with open(outp, "a") as f, open(outp + ".log", "a") as lg:
        for p in papers:
            if p["id"] in done:
                continue
            if time.time() - t0 > budget:
                break
            try:
                t, why = build(p)
            except Exception as e:
                t, why = None, f"error:{type(e).__name__}"
            if t:
                f.write(json.dumps(t, ensure_ascii=False) + "\n"); f.flush()
            lg.write(json.dumps({"id": p["id"], "result": why, "rows": len(t["rows"]) if t else 0}) + "\n"); lg.flush()
    res = [json.loads(l) for l in open(outp + ".log")]
    from collections import Counter
    print(f"{len(res)} papers tried; {Counter(r['result'] for r in res)}; {time.time()-t0:.0f}s")
