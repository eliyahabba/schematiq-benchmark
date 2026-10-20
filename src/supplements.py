"""Study-level tables that live in Word or Excel supplements.

In the first 70 reviews, 28 had a study-level table in a Word supplement
(1,225 rows) that the article-table pipeline never looked at; in one review
the article showed 12 "representative examples" and the supplement all 126.
Europe PMC serves supplements only as one zip per article (the direct file
URLs return 403 to scripts), so the zip is fetched only when the JATS lists
a .docx/.xlsx/.csv supplement.
"""
import io, re, zipfile
from net import cached_bytes
import harvest, table_layer as harvest2, quality

ZIP = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles"
WANT = (".docx", ".xlsx", ".csv")
TITLE_COL = re.compile(r"^(article |study |paper |publication |document )?title( of (the )?(article|study|paper))?$", re.I)
MAX_TITLE_ROWS = 120
ADMIN_COL = re.compile(r"author|title|year|journal|volume|issue|page|doi|url|link|issn|isbn|abstract|keyword|"
                       r"\bid\b|^#|key|source|publisher|language|email|citation|reference|pub[._ ]|publication|"
                       r"screen|includ|exclu|decision|status|duplicate|reason|notes?$|search|database|rayyan|"
                       r"month|day|eid|wos|affiliation|country of author|corresponding|resource type|doc type", re.I)   # a coded map can list thousands of studies; the benchmark keeps the first 120
# supplements are often appraisal sheets whose only label is the column text
APPRAISAL = re.compile(r"risk[\s\-]*of[\s\-]*bias|\bRoB\b|newcastle|ottawa|quality (assess|apprais|score)|"
                       r"\bJBI\b|\bGRADE\b|\bAMSTAR\b|\bNOS\b|\bMMAT\b|\(0[–-]\d points?\)|checklist|"
                       r"randomi[sz]ation process|deviations from intended|missing outcome data|"
                       r"measurement of the outcome|selection of the reported result", re.I)


def listed(xml):
    out = []
    for m in re.finditer(r"<supplementary-material\b.*?</supplementary-material>", xml or "", re.S):
        for h in re.findall(r'xlink:href="([^"]+)"', m.group(0)):
            if h.lower().endswith(WANT):
                out.append(h)
    return out


def fetch_zip(pmcid):
    return cached_bytes("supp", pmcid, ZIP.format(pmcid=pmcid), ext=".zip",
                        validate=lambda b: b[:2] == b"PK", timeout=45, tries=1)


def _docx_tables(b, name):
    import docx
    try:
        d = docx.Document(io.BytesIO(b))
    except Exception:
        return []
    # caption: the paragraph right before each table, if any
    body = d.element.body
    caps, last = {}, ""
    for el in body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            txt = "".join(t.text or "" for t in el.iter() if t.tag.endswith("}t")).strip()
            if txt:
                last = txt
        elif tag == "tbl":
            caps[id(el)] = last
    out = []
    for k, t in enumerate(d.tables):
        rows = []
        for r in t.rows:
            seen, cells = set(), []
            for c in r.cells:
                key = id(c._tc)
                dup = key in seen
                seen.add(key)
                cells.append({"text": "" if dup else re.sub(r"\s+", " ", c.text).strip(), "xml": "", "spanned": dup})
            rows.append(cells)
        out.append({"label": f"{name}#{k + 1}", "caption": caps.get(id(t._tbl), "")[:300], "rows": rows})
    return out


def _xlsx_tables(b, name):
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
    except Exception:
        return []
    out = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            vals = ["" if v is None else re.sub(r"\s+", " ", str(v)).strip() for v in r]
            if any(vals):
                rows.append([{"text": v, "xml": "", "spanned": False} for v in vals])
            if len(rows) > 3000:
                break
        if rows:
            w = max(len(r) for r in rows)
            keep = [j for j in range(w) if any(j < len(r) and r[j]["text"] for r in rows)]
            rows = [[r[j] if j < len(r) else {"text": "", "xml": "", "spanned": False} for j in keep] for r in rows]
            out.append({"label": f"{name}#{ws.title}", "caption": ws.title, "rows": rows})
    return out


def raw_tables(pmcid, xml):
    names = listed(xml)
    if not names:
        return []
    z = fetch_zip(pmcid)
    if not z:
        return []
    try:
        zf = zipfile.ZipFile(io.BytesIO(z))
    except Exception:
        return []
    out = []
    for n in zf.namelist():
        low = n.lower()
        if low.endswith(".docx"):
            out += _docx_tables(zf.read(n), n)
        elif low.endswith(".xlsx"):
            out += _xlsx_tables(zf.read(n), n)
    return out


def candidates(pmcid, xml, refs, question, min_rows=4):
    """Supplement tables that pass the same gates as article tables. Rows are
    linked to references by surname plus year (there are no <xref> here)."""
    name_idx = harvest.build_name_index(refs)
    lab_idx = harvest.label_index(refs)
    out = []
    for t in raw_tables(pmcid, xml):
        rows = [r for r in t["rows"] if any(c["text"] for c in r)]
        if len(rows) < min_rows + 1:
            continue
        head, body = [rows[0]], rows[1:]
        while body and harvest2.looks_like_header(body[0]):
            head.append(body.pop(0))
        if len(body) < min_rows:
            continue
        ncol = max(len(r) for r in head + body)
        cols = harvest2.merge_header(head, ncol)
        text = f"{t['label']} {t['caption']}"
        if harvest2.NEG.search(text) or APPRAISAL.search(text + " " + " ".join(cols)):
            continue
        linked = []
        for r in body:
            cells = [c["text"] for c in r]
            rids, _ = harvest.link_row(cells, refs, name_idx, lab_idx, 0)
            linked.append((cells, rids))
        cov = sum(1 for _, rids in linked if rids) / len(linked)
        title_col = None
        if cov < 0.6:
            # coded databases of systematic maps list their studies by title, and
            # most of those studies are not in the article's reference list
            for j, c in enumerate(cols):
                if TITLE_COL.match(c.strip()):
                    vals = [r[j]["text"] if j < len(r) else "" for r in body]
                    if sum(1 for v in vals if len(v) >= 20) >= 0.6 * len(vals):
                        title_col = j
                        break
            if title_col is None:
                continue
            # most such spreadsheets are search or screening logs; keep only coded databases
            coded = [c for c in cols if not ADMIN_COL.search(c)]
            if len(coded) < 3 or len(coded) < 0.4 * len(cols):
                continue
            year_col = next((j for j, c in enumerate(cols) if re.match(r"^(publication )?year", c.strip(), re.I)), None)
            linked = [([c["text"] for c in r],
                       [("title", r[title_col]["text"] if title_col < len(r) else "",
                         r[year_col]["text"] if year_col is not None and year_col < len(r) else "")])
                      for r in body[:MAX_TITLE_ROWS]]
            cov = 1.0
        ok, why = quality.check_table(cols, len(body))
        if not ok:
            continue
        rws = []
        for cells, rids in linked:
            if rids and isinstance(rids[0], tuple):          # identified by its title, resolved later
                _, title, year = rids[0]
                rws.append({"cells": cells, "matched_by": "title_column", "ref_ids": ["title:" + title[:200]],
                            "refs": [{"title": title, "year": (re.search(r"(19|20)\d{2}", year) or [None])[0],
                                      "raw": title}]})
            else:
                rws.append({"cells": cells, "matched_by": "name_year" if rids else None, "ref_ids": rids,
                            "refs": [refs.get(x, {}) for x in rids]})
        score, hits = quality.alignment(question, cols)
        out.append({"label": t["label"], "caption": t["caption"], "columns": cols, "n_rows": len(body),
                    "citation_col": 0, "citation_coverage": round(cov, 3),
                    "rows_with_resolvable_ref": sum(1 for r in rws if r["ref_ids"]),
                    "positive_caption": bool(harvest2.POS.search(text)), "table_gate": why,
                    "alignment": score, "alignment_hits": hits, "rows": rws, "from": "supplement",
                    "citation_col": title_col if title_col is not None else 0})
    return out
