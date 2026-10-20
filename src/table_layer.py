#!/usr/bin/env python3
"""Second-generation table layer. Fixes four verified defects in harvest.py:

1. colspan/rowspan were ignored, so cells drifted out of alignment (21% of tasks)
2. multi-row headers were captured as data rows (13% of tasks)
3. 'risk-of-bias' with hyphens escaped the exclusion regex (2%)
4. no rejection when a review has no genuine characteristics table at all

Reuses the parts of harvest.py that were verified to work: search, reference
parsing, question extraction, and the three-stage row-to-document linking.
"""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest import (get, strip, search, ref_list, extract_rq, build_name_index,
                     match_row_by_name, row_citations, EPMC)
from quality import grade, check_table, check_alignment

# ---------- fix 3: hyphen-tolerant exclusion, plus the rest of the boilerplate ----------
NEG = re.compile(
    r"risk[\s\-]*of[\s\-]*bias|quality (assess|apprais)|methodological quality|"
    r"ROBINS|newcastle[\s\-]*ottawa|jadad|GRADE|PEDro|AMSTAR|CASP|bias judg|"
    r"search (strateg|string|term|quer)|inclusion and exclusion|eligibility criteria|"
    r"PRISMA|PICO|certainty of (the )?evidence|summary of findings|"
    r"abbreviation|glossary|excluded stud", re.I)

POS = re.compile(
    r"characteristic|included stud|study characteristic|"
    r"summary of (the )?(included |eligible )?(stud|trial|articl|paper)|"
    r"overview of (the )?(included )?(stud|trial|articl)|"
    r"data extraction|extracted data|study details|descriptive summary|"
    r"details of (the )?(included )?stud", re.I)

GENERIC = re.compile(
    r"^(treatment|control|experimental|intervention|comparison|baseline|"
    r"mean|median|sd|se|ci|n|n\d|no\.?|total|yes|no|eg|cg|ig|e|c|i|"
    r"pre|post|before|after|male|female|group\s*\d?)\s*$", re.I)


# ---------- fix 1: expand colspan so cell index equals column index ----------
CELL = re.compile(r"<t([dh])\b([^>]*?)/>|<t([dh])\b([^>]*)>(.*?)</t\3>", re.S)

def expand_row(row_xml, is_header=False, carry=None):
    """Expand colspan, and apply any rowspan carried down from earlier rows.

    In a header, a cell spanning several columns names all of them, so its text
    is propagated into the spanned slots. In the body a spanned slot is empty.
    """
    out = []
    cells = []
    # A self-closing empty cell (<td/>, <th colspan="1"/>) has no </td>. The old
    # pattern opened a cell at "<td .../>" and ran on to the NEXT cell's </td>,
    # so every empty cell swallowed its right neighbour and shifted the rest of
    # the row one column left (39 of 218 tables in the 70-review sample).
    for m in CELL.finditer(row_xml):
        if m.group(1):
            attrs, content = m.group(2), ""
        else:
            attrs, content = m.group(4), m.group(5)
        cs = re.search(r'colspan="(\d+)"', attrs)
        rs = re.search(r'rowspan="(\d+)"', attrs)
        cells.append({"xml": content, "text": strip(content),
                      "cspan": min(int(cs.group(1)) if cs else 1, 24),
                      "rspan": min(int(rs.group(1)) if rs else 1, 60)})
    carry = carry if carry is not None else {}
    j = 0
    ci = 0
    while ci < len(cells) or j in carry:
        if j in carry:
            held, left = carry[j]
            out.append({"xml": held["xml"], "text": held["text"], "spanned": True})
            if left - 1 > 0:
                carry[j] = (held, left - 1)
            else:
                del carry[j]
            j += 1
            continue
        c = cells[ci]; ci += 1
        for k in range(c["cspan"]):
            out.append({"xml": c["xml"] if k == 0 else ("" if not is_header else c["xml"]),
                        "text": c["text"] if (k == 0 or is_header) else "",
                        "spanned": k > 0})
            if c["rspan"] > 1:
                carry[j] = (c, c["rspan"] - 1)
            j += 1
    return out


def parse_tables(xml):
    tabs = []
    for m in re.finditer(r"<table-wrap\b.*?</table-wrap>", xml, re.S):
        t = m.group(0)
        lab = re.search(r"<label>(.*?)</label>", t, re.S)
        cap = re.search(r"<caption>(.*?)</caption>", t, re.S)
        thead = re.search(r"<thead\b.*?</thead>", t, re.S)
        tbody = re.search(r"<tbody\b.*?</tbody>", t, re.S)
        head_rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", thead.group(0), re.S) if thead else []
        body_src = tbody.group(0) if tbody else t
        body_rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", body_src, re.S)
        if not thead and body_rows:
            head_rows, body_rows = body_rows[:1], body_rows[1:]
        hcarry, bcarry = {}, {}
        head_exp = [expand_row(r, is_header=True, carry=hcarry) for r in head_rows]
        body_exp = [expand_row(r, is_header=False, carry=bcarry) for r in body_rows]
        tabs.append({
            "label": strip(lab.group(1)) if lab else "",
            "caption": strip(cap.group(1)) if cap else "",
            "head": head_exp,
            "body": body_exp,
            "body_xml": body_rows,
            "raw": t,
        })
    return tabs


# ---------- fix 2: merge multi-row headers into one column name per index ----------
def merge_header(head_rows, ncol):
    cols, last = [], ""
    for j in range(ncol):
        parts = []
        for hr in head_rows:
            if j < len(hr):
                txt = hr[j]["text"]
                if txt and txt not in parts:
                    parts.append(txt)
        name = " - ".join(parts)
        if not name:
            name = last  # a header cell left blank belongs to the group on its left
        if not name:
            name = f"col{j}"
        cols.append(name)
        if parts:
            last = parts[0]
    # de-duplicate repeated names so columns stay addressable
    seen = {}
    out = []
    for c in cols:
        if c in seen:
            seen[c] += 1
            out.append(f"{c} ({seen[c]})")
        else:
            seen[c] = 1
            out.append(c)
    return out


def looks_like_header(cells):
    """A tbody row that is really a second header line."""
    txts = [c["text"] for c in cells if c["text"]]
    if len(txts) < 2:
        return False
    gen = sum(1 for c in txts if GENERIC.match(c))
    return gen / len(txts) >= 0.5


def classify(tab, min_rows=4):
    body = [r for r in tab["body"] if any(c["text"] for c in r)]
    head = list(tab["head"])
    # absorb leading header-looking body rows into the header
    while body and looks_like_header(body[0]) and not any(
            'ref-type="bibr"' in c["xml"] for c in body[0]):
        head.append(body.pop(0))
        tab["body_xml"] = tab["body_xml"][1:]
    n = len(body)
    if n < min_rows:
        return None
    ncol = max(len(r) for r in body + head) if (body or head) else 0
    if ncol < 2:
        return None
    cov = []
    for j in range(ncol):
        k = sum(1 for r in body if j < len(r) and 'ref-type="bibr"' in r[j]["xml"])
        cov.append(k / n)
    best = max(range(ncol), key=lambda j: cov[j])
    others = [cov[j] for j in range(ncol) if j != best]
    single = (not others) or (max(others) < 0.4)
    cols = merge_header(head, ncol)

    # fix 4: gate on what the table actually is
    text = f"{tab['label']} {tab['caption']}"
    if NEG.search(text):
        return None
    numeric_cols = sum(1 for c in cols if re.fullmatch(r"\s*(col)?\d+\s*", c or ""))
    if POS.search(text):
        ok = n >= min_rows
    else:
        ok = (cov[best] >= 0.6 and single and ncol >= 4 and numeric_cols == 0)
    if not ok or numeric_cols > ncol / 3:
        return None
    return {"columns": cols, "citation_col": best, "coverage": round(cov[best], 3),
            "body": body, "n_rows": n}


def build_task(rec):
    pmcid = rec.get("pmcid")
    if not pmcid:
        return None
    xml = get(f"{EPMC}/{pmcid}/fullTextXML")
    if not xml or "<article" not in xml:
        return None
    tabs = parse_tables(xml)
    if not tabs:
        return None
    refs = ref_list(xml)
    name_idx = build_name_index(refs)
    cands = []
    for t in tabs:
        c = classify(t)
        if not c:
            continue
        rows = []
        for i, r in enumerate(c["body"]):
            cells = [x["text"] for x in r]
            rxml = t["body_xml"][i] if i < len(t["body_xml"]) else ""
            rids = row_citations(rxml)
            how = "xref" if rids else None
            if not rids:
                rids = match_row_by_name(cells, name_idx)
                how = "name_year" if rids else None
            rows.append({"cells": cells, "matched_by": how, "ref_ids": rids,
                         "refs": [refs.get(x, {}) for x in rids]})
        linked = sum(1 for r in rows if any(
            x.get("doi") or x.get("pmid") or x.get("pmcid") or x.get("raw") for x in r["refs"]))
        cands.append({
            "label": t["label"], "caption": t["caption"], "columns": c["columns"],
            "n_rows": c["n_rows"], "citation_col": c["citation_col"],
            "citation_coverage": c["coverage"],
            "rows_with_resolvable_ref": linked,
            "positive_caption": bool(POS.search(f"{t['label']} {t['caption']}")),
            "rows": rows,
        })
    if not cands:
        return None
    rq = extract_rq(xml, rec.get("abstractText"), [])
    reg = re.findall(r"\bCRD\d{6,}\b", xml)
    if reg and not rq.get("prospero_id"):
        rq["prospero_id"] = sorted(set(reg))[0]
    qtext = rq.get("objective_section") or rq.get("objective_sentence")
    # drop tables that are appraisal or apparatus tables, by column content
    kept = []
    for c in cands:
        ok, why = check_table(c["columns"], c["n_rows"])
        c["table_gate"] = why
        if ok:
            kept.append(c)
    if not kept:
        return None
    # rank by question alignment first, then caption, then linked rows
    for c in kept:
        _, c["alignment"] = __import__("quality").alignment(qtext, c["columns"])
    kept.sort(key=lambda c: (c["alignment"], c["positive_caption"],
                             c["rows_with_resolvable_ref"], c["n_rows"]), reverse=True)
    cands = kept
    return {
        "task_id": pmcid, "source": "europepmc", "pmcid": pmcid,
        "pmid": rec.get("pmid"), "doi": rec.get("doi"), "title": rec.get("title"),
        "journal": ((rec.get("journalInfo") or {}).get("journal") or {}).get("title"),
        "year": rec.get("pubYear"), "license": rec.get("license"),
        "research_question": rq, "n_refs": len(refs), "references": refs,
        "gold_tables": cands[:3],
    }
