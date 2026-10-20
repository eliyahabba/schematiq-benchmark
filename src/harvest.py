"""Minimal re-implementation of the harvest.py functions that table_layer.py
imports. The original harvest.py was not available in this session.

Only the pieces the table layer needs are implemented and tested:
  strip, ref_list, row_citations, build_name_index, match_row_by_name, get.
search() and extract_rq() are deliberately not implemented: search is done
elsewhere, and the question now comes from PROSPERO (see prospero.py).
"""
import html, re, unicodedata
from net import http_get

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def get(url):
    st, body = http_get(url)
    return body


def strip(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]+", "", s.lower())


def _attr(tag, name):
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def ref_list(xml):
    """<ref id> -> {raw, first_author, doi, pmid, pmcid, title, year}.
    Works for element-citation and mixed-citation, and falls back to DOIs
    written as ext-links or plain text when there is no <pub-id>."""
    out = {}
    lists = re.findall(r"<ref-list\b.*?</ref-list>", xml, re.S)
    # <ref(?=[\s>]) and not <ref\b: \b also matches inside "<ref-list", which
    # swallowed the first reference of every list.
    for m in re.finditer(r"<ref(?=[\s>])([^>]*)>(.*?)</ref>", "\n".join(lists), re.S):
        rid = _attr(m.group(1), "id")
        body = m.group(2)
        if not rid:
            continue
        r = {"raw": strip(re.sub(r"<label>.*?</label>", "", body, flags=re.S))}
        sn = re.search(r"<surname>(.*?)</surname>", body, re.S)
        if sn:
            r["first_author"] = strip(sn.group(1)).lower()
        else:
            coll = re.search(r"<collab>(.*?)</collab>", body, re.S)
            first = strip(coll.group(1)) if coll else r["raw"].split(" ")[0]
            r["first_author"] = first.lower().strip(".,")
        for t in ("doi", "pmid", "pmcid"):
            p = re.search(rf'<pub-id[^>]*pub-id-type="{t}"[^>]*>(.*?)</pub-id>', body, re.S)
            if p:
                r[t] = strip(p.group(1))
        if "doi" not in r:
            d = re.search(r"(?:doi\.org/|doi:\s*)(10\.\d{4,9}/[^\s\"<>]+)", body, re.I) \
                or re.search(r"\b(10\.\d{4,9}/[^\s\"<>]+)", r["raw"])
            if d:
                r["doi"] = d.group(1).rstrip(".,;)")
        if "pmcid" in r and not r["pmcid"].upper().startswith("PMC"):
            r["pmcid"] = "PMC" + r["pmcid"]
        ti = re.search(r"<article-title[^>]*>(.*?)</article-title>", body, re.S)
        if ti:
            r["title"] = strip(ti.group(1))
        yr = re.search(r"<year[^>]*>(\d{4})([a-z]?)</year>", body) or re.search(r"\((\d{4})([a-z]?)\)", r["raw"])
        if yr:
            r["year"] = yr.group(1)
            if yr.group(2):
                r["year_suffix"] = yr.group(2)
        lab = re.search(r"<label>\s*\[?(\d{1,4})[.\]]?\s*</label>", body)
        if lab:
            r["label"] = lab.group(1)
        gn = re.search(r"<given-names[^>]*>(.*?)</given-names>", body, re.S)
        if gn:
            r["first_given"] = strip(gn.group(1))
        out[rid] = r
    return out


def row_citations(row_xml):
    """Reference ids cited in one table row, in order, attribute order independent."""
    ids = []
    for tag in re.findall(r"<xref\b[^>]*>", row_xml or ""):
        if _attr(tag, "ref-type") != "bibr":
            continue
        for rid in (_attr(tag, "rid") or "").split():
            if rid not in ids:
                ids.append(rid)
    return ids


def build_name_index(refs):
    idx = {}
    for rid, r in refs.items():
        fa, yr = fold(r.get("first_author", "")), r.get("year")
        if fa and yr:
            idx.setdefault((fa, yr), []).append(rid)
    return idx


NAME_YEAR = re.compile(r"([A-Z\u00C0-\u024F][\w\u00C0-\u024F'\-]+(?:\s+[a-z]{1,3}\s+[A-Z][\w'\-]+)?)"
                       r"(?:\s+et\s+al\.?|\s+and\s+[A-Z][\w'\-]+|\s*&\s*[A-Z][\w'\-]+)?"
                       r"[\s,]*\(?\s*((?:19|20)\d{2})[a-z]?\)?")


def match_row_by_name(cells, name_idx):
    """Surname + year in the first two cells -> reference ids. Unique matches only."""
    for c in cells[:2]:
        for m in NAME_YEAR.finditer(c or ""):
            key = (fold(m.group(1).split()[-1] if " " in m.group(1) else m.group(1)), m.group(2))
            hits = name_idx.get(key)
            if hits and len(hits) == 1:
                return hits
            key2 = (fold(m.group(1)), m.group(2))
            hits = name_idx.get(key2)
            if hits and len(hits) == 1:
                return hits
    return []


def search(*a, **k):
    raise NotImplementedError("search lives in the runner; not needed by the table layer")


def extract_rq(*a, **k):
    raise NotImplementedError("the question now comes from PROSPERO (prospero.py)")


# ---------------- row linking (for tables without <xref>) ----------------
def label_index(refs):
    return {r["label"]: rid for rid, r in refs.items() if r.get("label")}


def _names(text):
    """Folded capitalised words in a row, used to confirm a numeric link."""
    return {fold(w) for w in re.findall(r"[A-Z\u00C0-\u024F][\w\u00C0-\u024F'\-]+", text or "") if len(w) > 1}


def _confirm(rid, refs, text):
    fa = fold((refs.get(rid) or {}).get("first_author", ""))
    return bool(fa) and (fa in _names(text) or fa in fold(text))


NAME_YEAR2 = re.compile(
    r"([A-Z\u00C0-\u024F][\w\u00C0-\u024F'\-]+(?:\s+(?:[a-z]{1,3}\s+)?[A-Z\u00C0-\u024F][\w\u00C0-\u024F'\-]+)?)"
    r"(?:,?\s+(?:[A-Z]\.\s?){1,3})?"
    r"(?:\s+et\s+al\.?|\s+(?:and|&)\s+[A-Z][\w'\-]+)?"
    r"[\s,;]*\(?\s*((?:19|20)\d{2})([a-z]?)\)?")
CODE = re.compile(r"\b([A-Z]{2,})_[A-Z]+_((?:19|20)\d{2})\b")


def link_row(cells, refs, name_idx, lab_idx, cite_col=None, header=None):
    """Reference ids for a table row that carries no <xref>. Returns (ids, how).
    Every numeric link must be confirmed by the reference's first author
    appearing in the row, unless the column is explicitly a reference column."""
    probe = list(cells[:3])
    if cite_col is not None and cite_col < len(cells) and cite_col >= 3:
        probe.append(cells[cite_col])
    text = " ".join(probe)
    # 1. bracketed or parenthesised reference numbers: "Braun 2011 [4]"
    for m in re.finditer(r"[\[(]\s*(\d{1,4})(?:\s*[,\u2013\-]\s*\d{1,4})*\s*[\])]", text):
        rid = lab_idx.get(m.group(1))
        if rid and _confirm(rid, refs, text):
            return [rid], "ref_number"
    # 2. surname (+ initials, particles, "et al.", a co-author) + year (+ a/b suffix)
    for c in probe:
        for m in NAME_YEAR2.finditer(c or ""):
            name, year, suf = m.group(1), m.group(2), m.group(3)
            for key in (fold(name.split()[-1]), fold(name), fold(name.split()[0])):
                hits = name_idx.get((key, year))
                if not hits:
                    continue
                if len(hits) == 1:
                    return hits, "name_year"
                if suf:
                    same = [h for h in hits if refs[h].get("year_suffix") == suf]
                    if len(same) == 1:
                        return same, "name_year_suffix"
                    order = sorted(hits, key=lambda h: list(refs).index(h))
                    k = ord(suf) - ord("a")
                    if 0 <= k < len(order):
                        return [order[k]], "name_year_suffix_order"
    # 2b. first capitalised word + first year in the same cell; the year may be
    #     off by one (online versus print year), accepted only if unique
    STOP = {"the", "study", "author", "authors", "total", "trial", "group", "table", "western", "eastern"}
    for c in probe[:2]:
        m = re.match(r"\s*(?:\d{1,4}[.)]?\s+)?([A-Z\u00C0-\u024F][\w\u00C0-\u024F'\-]+)\b.*?\b((?:19|20)\d{2})", c or "")
        if not m or fold(m.group(1)) in STOP:
            continue
        sur, year = fold(m.group(1)), int(m.group(2))
        for dy in (0, -1, 1):
            hits = name_idx.get((sur, str(year + dy)))
            if hits and len(hits) == 1:
                return hits, "name_year" if dy == 0 else "name_year_pm1"
    # 3. database codes such as HAYASHI_KOJI_1999
    for c in probe:
        m = CODE.search(c or "")
        if m:
            hits = name_idx.get((fold(m.group(1)), m.group(2)))
            if hits and len(hits) == 1:
                return hits, "name_year_code"
    # 4. a bare number in the first cells that is a reference label, confirmed by name
    for c in probe[:2]:
        m = re.fullmatch(r"\s*\[?(\d{1,4})\]?\.?\s*", c or "")
        if m:
            rid = lab_idx.get(m.group(1))
            if rid and _confirm(rid, refs, " ".join(cells)):
                return [rid], "ref_number"
    # 5. surname with given name or initial, no year: unique match only
    for c in probe[:2]:
        m = re.match(r"\s*([A-Z][a-z]+)\s+([A-Z][\w'\-]+)\s+et\s+al", c or "")
        if m:
            given, sur = m.group(1), fold(m.group(2))
            hits = [rid for rid, r in refs.items() if fold(r.get("first_author", "")) == sur
                    and fold(r.get("first_given", ""))[:1] == fold(given)[:1]]
            if len(hits) == 1:
                return hits, "name_given"
    return [], None
