"""PROSPERO registry access and parsing.

API (reverse-engineered from the public web app, verified 2026-09-27):
  GET https://www.crd.york.ac.uk/PROSPERO/api/view/{CRD}/{major}/{minor}
  header prospero-auth-token: base64(now_ms)
  major=minor=0 returns the latest version; the version history field lists
  the others as showrecord('CRD', major, minor).
Human-readable record URL: https://www.crd.york.ac.uk/PROSPERO/view/{CRD}
(the old display_record.php?ID= URL redirects there).
"""
import html, json, re
from net import cached_text, prospero_headers

API = "https://www.crd.york.ac.uk/PROSPERO/api/view/{crd}/{major}/{minor}"
PAGE = "https://www.crd.york.ac.uk/PROSPERO/view/{crd}"
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _ok(body):
    try:
        d = json.loads(body)
    except Exception:
        return False
    return isinstance(d, dict) and isinstance(d.get("json"), list)


def fetch(crd, major=0, minor=0):
    body = cached_text("prospero", f"{crd}_{major}_{minor}",
                       API.format(crd=crd, major=major, minor=minor),
                       headers_fn=prospero_headers, ext=".json", validate=_ok)
    if body is None:
        return None
    return json.loads(EMAIL.sub("<EMAIL>", body))


def html_text(h):
    h = re.sub(r"<br\s*/?>|</p>|</li>|</tr>|</div>|</h\d>", "\n", h or "")
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h).replace("\xa0", " ").replace("\u200f", "")
    lines = [re.sub(r"[ \t]+", " ", x).strip() for x in h.split("\n")]
    return "\n".join(x for x in lines if x)


def version_keys(rec):
    """All (major, minor) versions whose content is embedded in this response."""
    ks = set()
    for b in rec.get("json") or []:
        for c in b.get("blockcontent") or []:
            for p in c.get("PublishedHTML") or []:
                ks.add((int(p.get("VersionID") or 0), int(p.get("MinorVersionID") or 0)))
    return sorted(ks)


def fields(rec, version=None):
    """TemplateSection -> {'caption', 'html', 'text', 'version'} for one version.

    A latest-version response embeds every earlier version of every field, one
    PublishedHTML entry per version. version=None picks the latest, "first"
    picks the earliest, or pass a (major, minor) tuple."""
    keys = version_keys(rec)
    if not keys:
        return {}
    want = keys[-1] if version is None else (keys[0] if version == "first" else tuple(version))
    out = {}
    for b in rec.get("json") or []:
        for c in b.get("blockcontent") or []:
            sec = c.get("TemplateSection")
            if not sec:
                continue
            ents = c.get("PublishedHTML") or []
            pick = [p for p in ents if (int(p.get("VersionID") or 0), int(p.get("MinorVersionID") or 0)) == want]
            if not pick:
                # a field that did not exist in that version
                continue
            h = pick[0].get("PublishedHTML") or ""
            out[sec] = {"caption": (c.get("caption") or "").strip(), "html": h,
                        "text": html_text(h), "version": want}
    return out


def versions(f):
    h = (f.get("TemplateVersions") or {}).get("html", "")
    out, seen = [], set()
    for m in re.finditer(r"showrecord\('([^']+)',\s*(\d+),\s*(\d+)\)\"?>([^<]*)<", h):
        key = (int(m.group(2)), int(m.group(3)))
        if key in seen:
            continue
        seen.add(key)
        date = re.search(r"published\s+(?:on\s+)?(.+)$", m.group(4).strip())
        out.append({"major": key[0], "minor": key[1],
                    "label": m.group(4).strip(), "published": date.group(1) if date else None})
    return sorted(out, key=lambda x: (x["major"], x["minor"]))


def stage_table(f):
    """Parse 'Stage of the review at this submission' into {stage: {started, completed}}.
    A ticked cell carries class preview-green, an empty one preview-blank
    (verified on 70 records). Returns None when the field is absent."""
    sec = f.get("TemplateReviewStage")
    if not sec or "<table" not in sec["html"]:
        return None
    out = {}
    for row in re.findall(r"<tr class=\"preview-row\">(.*?)</tr>", sec["html"], re.S):
        tds = re.findall(r"<td([^>]*)>(.*?)</td>", row, re.S)
        if len(tds) < 3:
            continue
        name = html_text(tds[0][1])
        out[name] = {"started": "preview-green" in tds[1][0],
                     "completed": "preview-green" in tds[2][0]}
    return out


KEEP = {  # sections copied into the benchmark record, by PROSPERO template name
    "TemplateTitle": "title",
    "TemplateReviewQuestion": "review_question",
    "TemplateRationale": "rationale",
    "TemplateCondition": "condition",
    "TemplatePopulation": "population",
    "TemplateIntervention": "intervention",
    "TemplateComparator": "comparator",
    "TemplateStudyDesign": "study_design",
    "TemplateContext": "context",
    "TemplateOutcomesMain": "main_outcomes",
    "TemplateOutcomesAdditional": "additional_outcomes",
    "TemplateDataExtraction": "data_extraction",
    "TemplateDataSynthesis": "data_synthesis",
    "TemplateFirstSubmitted": "first_submitted",
    "TemplateFirstPublished": "registered",
    "TemplateReviewTimeline": "timeline",
    "TemplatePeerReview": "peer_review_note",
    "TemplateRevisionNote": "revision_note",
}


LEGACY = {  # older templates use different section names for the same field
    "review_question": ["TemplateReviewQuestionLegacyAnimal"],
    "condition": ["TemplateConditionLegacyAnimal"],
    "population": ["TemplatePopulationLegacyAnimal"],
    "intervention": ["TemplateInterventionLegacyAnimal"],
    "comparator": ["TemplateComparatorLegacyAnimal"],
    "main_outcomes": ["TemplateOutcomesMainLegacyAnimal"],
    "data_extraction": ["TemplateDataExtractionLegacy", "TemplateDataExtractionLegacyAnimal"],
    "data_synthesis": ["TemplateDataSynthesisLegacy", "TemplateDataSynthesisLegacyAnimal"],
}


def summarize(rec, version=None):
    f = fields(rec, version)
    s = {v: (f.get(k) or {}).get("text") for k, v in KEEP.items()}
    for name, alts in LEGACY.items():
        if not s.get(name):
            for a in alts:
                if (f.get(a) or {}).get("text"):
                    s[name] = f[a]["text"]
                    break
    s["version"] = list(next(iter(f.values()))["version"]) if f else None
    s["review_question_caption"] = (f.get("TemplateReviewQuestion") or f.get("TemplateReviewQuestionLegacyAnimal") or {}).get("caption")
    cit = (f.get("TemplateProsperoCitation") or {}).get("html", "")
    s["authors"] = [html_text(a) for a in re.findall(
        r'<span class="prosperocitation-author">(.*?)</span>', cit, re.S)]
    if not s["authors"]:
        # older records: "A Author, B Author. Title. PROSPERO 2022 CRD..."
        full = (f.get("TemplateProsperoFullCitation") or {}).get("text") or ""
        head = full.split(". ")[0] if ". " in full else ""
        s["authors"] = [a.strip() for a in re.split(r",| and ", head) if a.strip()]
    s["stage"] = stage_table(f)
    st = (f.get("TemplateReviewStage") or {}).get("text") or ""
    m = re.search(r"Review status\s*(.+?)(?:\nReview stage|$)", st, re.S)
    s["review_status"] = m.group(1).strip() if m else None
    s["versions"] = versions(f)
    meta = rec.get("record") or {}
    s["template"] = meta.get("TemplateName")
    s["template_variant"] = meta.get("TemplateVariantCaption")
    s["publication_status"] = meta.get("PublicationStatus")
    return s
