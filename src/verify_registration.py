"""Check, for every task, that its PROSPERO record belongs to the review and was
registered before data extraction began. Writes one JSON line per task.

Evidence used (all documentary):
  * where the CRD appears in the review's own JATS XML (never the reference list)
  * PROSPERO title vs article title, PROSPERO authors vs article authors
  * PROSPERO 'stage of the review' table in the FIRST registered version
  * PROSPERO registration date vs the journal's received date (JATS history)

  python3 verify_registration.py <tasks.jsonl>... > registration.jsonl
"""
import datetime as dt, difflib, json, re, sys, unicodedata
import epmc, prospero

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def pdate(s):
    """'21 April 2026' / '28 Dec 2024' -> ISO date."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", s)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    except (KeyError, ValueError):
        return None


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower())


def title_sim(a, b):
    a, b = fold(a).split(), fold(b).split()
    if not a or not b:
        return 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    sa, sb = set(a), set(b)
    jac = len(sa & sb) / len(sa | sb)
    return round(max(seq, jac), 3)


def author_overlap(article_authors, prospero_authors):
    ptoks = set(fold(" ".join(prospero_authors)).split())
    hits = [a["surname"] for a in article_authors
            if fold(a["surname"]).split() and all(t in ptoks for t in fold(a["surname"]).split())]
    return hits


def days(a, b):
    if not a or not b:
        return None
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def stage_flags(stage):
    if stage is None:
        return None
    def get(prefix):
        for k, v in stage.items():
            if k.lower().startswith(prefix):
                return v
        return {"started": None, "completed": None}
    return {"screening": get("screening"), "extraction": get("data extraction"),
            "synthesis": get("data synthesis"),
            "any_started": any(v["started"] for v in stage.values())}


def verify(task):
    tid = task["task_id"]
    crd = task.get("prospero") or (task.get("research_question") or {}).get("prospero_id")
    x = epmc.xml(tid) or ""
    mentions = epmc.crd_mentions(x)
    own_regions = sorted({m["region"] for m in mentions if m["id"] == crd})
    others = sorted({m["id"] for m in mentions if m["id"] != crd})
    rec = prospero.fetch(crd) if crd else None
    out = {"task_id": tid, "crd": crd, "crd_regions": own_regions, "other_crds": others,
           "prospero_url": prospero.PAGE.format(crd=crd) if crd else None}
    if rec is None:
        out["verdict"] = "no_record"
        return out
    first, latest = prospero.summarize(rec, "first"), prospero.summarize(rec)
    art_title, art_auth = epmc.title(x), epmc.authors(x)
    tsim = max(title_sim(art_title, first["title"]), title_sim(art_title, latest["title"]))
    ahits = author_overlap(art_auth, latest["authors"] + first["authors"])
    hist = epmc.history_any(tid)
    reg = pdate(first["registered"]) or pdate((first["versions"] or [{}])[0].get("published"))
    received = hist.get("received")
    sf = stage_flags(first["stage"])
    out.update({
        "prospero_title": first["title"], "article_title": art_title, "title_sim": tsim,
        "n_article_authors": len(art_auth), "author_hits": ahits,
        "registered": reg, "first_submitted": pdate(first["first_submitted"]),
        "received": received, "accepted": hist.get("accepted"), "dates_from": hist.get("source"),
        "days_registered_to_received": days(reg, received),
        "n_versions": len(latest["versions"]),
        "first_version": first["version"], "latest_version": latest["version"],
        "stage_at_registration": sf,
        "question_changed": (fold(first["review_question"]) != fold(latest["review_question"])),
        "template": latest["template"],
    })
    # ---- verdicts ----
    owned = bool(own_regions) and not others and (tsim >= 0.5 or len(ahits) >= 2 or (tsim >= 0.3 and ahits))
    out["owned"] = owned
    if not owned:
        out["verdict"] = "ownership_unconfirmed"
    elif sf is None:
        out["verdict"] = "no_stage_table"
    elif sf["extraction"]["started"] or sf["extraction"]["completed"]:
        out["verdict"] = "registered_after_extraction_started"
    elif received and reg and reg >= received:
        out["verdict"] = "registered_after_submission"
    elif not (received and reg):
        out["verdict"] = "preregistered_by_stage_only"
    else:
        out["verdict"] = "preregistered"
    return out


if __name__ == "__main__":
    seen = set()
    for p in sys.argv[1:]:
        for l in open(p, encoding="utf-8"):
            t = json.loads(l)
            if t["task_id"] in seen:
                continue
            seen.add(t["task_id"])
            print(json.dumps(verify(t), ensure_ascii=False), flush=True)
