"""Build one benchmark task from any Europe PMC open-access article.

Question, in order of preference:
  1. PROSPERO review question, first registered version, when the article's
     own text carries exactly one CRD that PROSPERO confirms belongs to it;
  2. otherwise the objective stated in the article's abstract.
Both are stored when both exist. The benchmark accepts questions written
after the table; question_provenance records which one this is.
"""
import json, re
import epmc, prospero, questions, tables
from verify_registration import verify
from registration_rules import check_registered_question, pick_ref

LIC = [("by-nc-nd", "cc by-nc-nd"), ("by-nc-sa", "cc by-nc-sa"), ("by-nc", "cc by-nc"),
       ("by-sa", "cc by-sa"), ("by-nd", "cc by-nd"), ("/by/", "cc by"), ("publicdomain/zero", "cc0")]
NOMINAL_AIM = re.compile(r"^(investigation|evaluation|assessment|comparison|analysis|exploration|examination|"
                         r"identification|estimation|quantification|determination|"
                         r"(the )?(effects?|efficacy|effectiveness|safety|prognostic|predictive|diagnostic|association|"
                         r"role|impact|prevalence|incidence|risk|accuracy|value)\b)", re.I)
OTHER_REG = re.compile(r"\b(INPLASY\s?\d{8,}|osf\.io/[a-z0-9]{5}\b|reviewregistry\d+)", re.I)


def licence(x):
    m = re.search(r'<license[^>]*xlink:href="([^"]+)"', x) or re.search(r'<ali:license_ref[^>]*>([^<]+)<', x)
    if not m:
        return None
    u = m.group(1).lower()
    for k, v in LIC:
        if k in u:
            return v
    return "other"


def meta(x):
    j = re.search(r"<journal-title>(.*?)</journal-title>", x, re.S)
    y = re.search(r"<pub-date[^>]*>.*?<year>(\d{4})</year>", x, re.S)
    d = re.search(r'<article-id pub-id-type="doi">([^<]+)</article-id>', x)
    return {"title": epmc.title(x), "journal": epmc.strip(j.group(1)) if j else None,
            "year": y.group(1) if y else None, "doi": d.group(1).lower() if d else None,
            "license": licence(x)}


def build(pmcid, stratum=None):
    x = epmc.xml(pmcid)
    if not x:
        return None, "no_xml"
    m = meta(x)
    own = sorted({c["id"] for c in epmc.crd_mentions(x) if c["region"] != "ref-list"})
    reg, first, latest = None, None, None
    if len(own) == 1:
        reg = verify({"task_id": pmcid, "prospero": own[0]})
        if reg.get("owned"):
            rec = prospero.fetch(own[0])
            first, latest = prospero.summarize(rec, "first"), prospero.summarize(rec)
        else:
            reg = None
    abs_q, abs_how = questions.abstract_objective(x)
    abs_ok, abs_why = questions.gate(abs_q) if abs_q else (False, abs_how)
    reg_q = first["review_question"] if first else None
    reg_ok, reg_why = check_registered_question(reg_q) if reg_q else (False, "none")
    if reg_q and not reg_ok and reg_why == "no_objective_or_question" and NOMINAL_AIM.match(reg_q.strip()):
        reg_ok, reg_why = True, "ok_noun_phrase"
    # many reviews (Environmental Evidence in particular) put the question in the title:
    # "What evidence exists on ...? A systematic map"
    tq = re.match(r"^\s*((?:What|How|Which|Does|Do|Is|Are|Can|Should|Why|To what extent)\b[^?]{15,300}\?)", m["title"] or "")
    if not tq and (m["title"] or "").strip().endswith("?") and len(m["title"]) <= 300:
        tq = re.match(r"^\s*(.+\?)\s*$", m["title"])
    if reg_q and reg_ok:
        q, prov = reg_q, "prospero_first_version"
    elif tq:
        q, prov = tq.group(1).strip(), "title_question"
    elif abs_q and abs_ok:
        q, prov = abs_q, "abstract"
    else:
        return None, f"no_usable_question({abs_why})"
    g, refs = tables.gold_table(x, q, pmcid)
    if not g:
        return None, "no_document_per_row_table"
    task = {
        "task_id": pmcid, "source": "europepmc", "stratum": stratum, "pmcid": pmcid, **m,
        "question": {
            "text": q, "provenance": prov,
            "source": ("PROSPERO registration, first version" if prov.startswith("prospero")
                       else "title of the review" if prov == "title_question" else "abstract of the review"),
            "prospero_id": own[0] if first else None,
            "prospero_url": prospero.PAGE.format(crd=own[0]) if first else None,
            "version": first["version"] if first else None,
            "caption": first["review_question_caption"] if first else None,
            "changed_after_registration": bool(first and reg.get("question_changed")),
            "latest_text": latest["review_question"] if first and reg.get("question_changed") else None,
            "abstract_objective": abs_q, "abstract_how": abs_how,
            "other_registrations": sorted({r.group(0) for r in OTHER_REG.finditer(x)})[:3],
        },
        "protocol": {k: first.get(k) for k in (
            "title", "rationale", "condition", "population", "intervention", "comparator",
            "study_design", "context", "main_outcomes", "additional_outcomes", "data_extraction")} if first else None,
        "registration": {k: reg.get(k) for k in (
            "verdict", "owned", "crd_regions", "title_sim", "n_article_authors",
            "registered", "first_submitted", "received", "accepted", "dates_from",
            "days_registered_to_received", "stage_at_registration", "n_versions", "template")} if reg else None,
        "gates": {"question": (reg_why if prov.startswith("prospero") else "ok" if prov == "title_question" else abs_why),
                  "table": g["table_gate"],
                  "lexical_alignment": {"score": g["alignment"], "hits": g["alignment_hits"]}},
        "table": {"label": g["label"], "caption": g["caption"], "columns": g["columns"],
                  "n_rows": len(g["rows"]), "citation_col": g["citation_col"],
                  "citation_coverage": g["citation_coverage"], "positive_caption": g["positive_caption"],
                  "from": g.get("from", "article"), "merged_from": g.get("merged_from")},
    }
    rows = []
    for i, r in enumerate(g["rows"]):
        k, n = pick_ref(r)
        ref = r["refs"][k] if k is not None else {}
        rows.append({"i": i, "cells": r["cells"], "matched_by": r["matched_by"],
                     "ref_id": r["ref_ids"][k] if k is not None else None, "n_refs_in_row": n,
                     "doi": (ref.get("doi") or "").lower() or None, "pmid": ref.get("pmid"),
                     "pmcid": ref.get("pmcid"), "ref_title": ref.get("title"),
                     "ref_year": ref.get("year"), "first_author": ref.get("first_author"),
                     "citation": ref.get("raw")})
    task["rows"] = rows
    return task, "ok"
