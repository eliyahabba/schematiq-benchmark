"""Gold-table extraction on top of table_layer.py.

Uses table_layer.parse_tables / classify and quality.check_table unchanged, with
one fix: the table layer filtered empty body rows out of the parsed rows but not out
of the parallel list of row XML, so after an empty spacer row every row read
its citations from the wrong <tr>. Rows and their XML are now filtered together.
"""
import re
import harvest, table_layer as harvest2, quality


def candidate_tables(xml, question):
    tabs = harvest2.parse_tables(xml)
    refs = harvest.ref_list(xml)
    name_idx = harvest.build_name_index(refs)
    lab_idx = harvest.label_index(refs)
    cands = []
    for t in tabs:
        pairs = [(r, rx) for r, rx in zip(t["body"], t["body_xml"]) if any(c["text"] for c in r)]
        t["body"], t["body_xml"] = [p[0] for p in pairs], [p[1] for p in pairs]
        c = harvest2.classify(t)
        if not c:
            continue
        rows = []
        for i, r in enumerate(c["body"]):
            cells = [x["text"] for x in r]
            rxml = t["body_xml"][i] if i < len(t["body_xml"]) else ""
            rids = [x for x in harvest.row_citations(rxml) if x in refs]
            how = "xref" if rids else None
            carried = False
            if not rids:
                # a study cell with rowspan>1 lives in the first <tr> only; the
                # expanded row still carries its XML, so read the citation there
                held = "".join(x["xml"] for x in r if x.get("spanned"))
                rids = [x for x in harvest.row_citations(held) if x in refs]
                if rids:
                    how, carried = "xref_rowspan", True
            if not rids:
                rids, how = harvest.link_row(cells, refs, name_idx, lab_idx, c["citation_col"])
            if not rids and sum(1 for v in cells if v) <= 1:
                continue  # a section label spanning the row ("Randomised trials"), not a study
            if carried and rows and rows[-1]["ref_ids"][:1] == rids[:1]:
                # continuation of the same study: fold into its first row
                prev = rows[-1]["cells"]
                for j, v in enumerate(cells):
                    if j < len(prev) and v and v not in prev[j].split(" | "):
                        prev[j] = (prev[j] + " | " + v) if prev[j] else v
                continue
            rows.append({"cells": cells, "matched_by": how, "ref_ids": rids,
                         "refs": [refs.get(x, {}) for x in rids]})
        c["n_rows"] = len(rows)
        linked = sum(1 for r in rows if any(
            x.get("doi") or x.get("pmid") or x.get("pmcid") or x.get("raw") for x in r["refs"]))
        ok, why = quality.check_table(c["columns"], c["n_rows"])
        cand = {"label": t["label"], "caption": t["caption"], "columns": c["columns"],
                "n_rows": c["n_rows"], "citation_col": c["citation_col"],
                "citation_coverage": c["coverage"], "rows_with_resolvable_ref": linked,
                "positive_caption": bool(harvest2.POS.search(f"{t['label']} {t['caption']}")),
                "table_gate": why, "rows": rows}
        _, cand["alignment_hits"] = quality.alignment(question, c["columns"])
        cand["alignment"] = quality.alignment(question, c["columns"])[0]
        if ok:
            cands.append(cand)
    cands.sort(key=lambda c: (c["alignment"], c["positive_caption"],
                              c["rows_with_resolvable_ref"], c["n_rows"]), reverse=True)
    return cands, refs


def _refset(c):
    return {r["ref_ids"][0] for r in c["rows"] if r["ref_ids"]}


def _linked(c):
    return sum(1 for r in c["rows"] if r["ref_ids"])


def merge(primary, other):
    """Append other's columns to primary, joining rows on their first reference id.
    other's citation column is dropped; its column names are prefixed with its label."""
    by_ref = {}
    for r in other["rows"]:
        if r["ref_ids"] and r["ref_ids"][0] not in by_ref:
            by_ref[r["ref_ids"][0]] = r
    have = {re.sub(r"\W+", " ", c).strip().lower() for c in primary["columns"]}
    keep = [j for j in range(len(other["columns"])) if j != other["citation_col"]
            and re.sub(r"\W+", " ", other["columns"][j]).strip().lower() not in have]
    label = (other["label"] or "table").split("#")[0]
    cols = primary["columns"] + [f"{label}: {other['columns'][j]}" for j in keep]
    rows = []
    for r in primary["rows"]:
        o = by_ref.get(r["ref_ids"][0]) if r["ref_ids"] else None
        extra = [(o["cells"][j] if o and j < len(o["cells"]) else "") for j in keep]
        rows.append({**r, "cells": list(r["cells"]) + extra})
    out = dict(primary, columns=cols, rows=rows)
    out["merged_from"] = primary.get("merged_from", [primary["label"]]) + [other["label"]]
    return out


def gold_table(xml, question, pmcid=None, use_supplements=True):
    """Choose the gold table and enrich it.

    1. Candidates: article tables (above) plus supplement tables.
    2. Primary: the top article table, unless a supplement table links at least
       1.5 times as many rows (the article often shows a subset).
    3. Every other candidate whose rows mostly cite the same studies is merged
       in as extra columns (e.g. a characteristics table plus an outcomes table).
    """
    import supplements
    cands, refs = candidate_tables(xml, question)
    for c in cands:
        c.setdefault("from", "article")
    supp = supplements.candidates(pmcid, xml, refs, question) if (use_supplements and pmcid) else []
    if not cands and not supp:
        return None, refs
    primary = cands[0] if cands else None
    if supp:
        best = max(supp, key=_linked)
        if primary is None or _linked(best) >= 1.5 * max(1, _linked(primary)):
            primary = best
    others = [c for c in cands + supp if c is not primary]
    base = _refset(primary)
    for c in others:
        rs = _refset(c)
        if len(rs) >= 4 and base and len(rs & base) / len(rs) >= 0.5:
            primary = merge(primary, c)
    primary.setdefault("merged_from", [primary["label"]])
    return primary, refs
