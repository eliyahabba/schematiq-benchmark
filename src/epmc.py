"""Europe PMC full-text access and the JATS facts the registration check needs."""
import datetime as dt, re, html
from net import cached_text

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CRD = re.compile(r"CRD\s?4\d{9,11}")


def xml(pmcid):
    return cached_text("epmc", pmcid, f"{EPMC}/{pmcid}/fullTextXML", ext=".xml",
                       validate=lambda b: "<article" in b[:5000])


def strip(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _date(block):
    y = re.search(r"<year>(\d{4})</year>", block)
    m = re.search(r"<month>(\d{1,2})</month>", block)
    d = re.search(r"<day>(\d{1,2})</day>", block)
    if not y:
        return None
    try:
        return dt.date(int(y.group(1)), int(m.group(1)) if m else 1, int(d.group(1)) if d else 1).isoformat()
    except ValueError:
        return None


def history(x):
    out = {}
    for m in re.finditer(r'<date date-type="([^"]+)"[^>]*>(.*?)</date>', x, re.S):
        out[m.group(1)] = _date(m.group(2))
    for m in re.finditer(r'<pub-date[^>]*pub-type="([^"]+)"[^>]*>(.*?)</pub-date>', x, re.S):
        out.setdefault("pub_" + m.group(1), _date(m.group(2)))
    for m in re.finditer(r'<pub-date[^>]*date-type="([^"]+)"[^>]*>(.*?)</pub-date>', x, re.S):
        out.setdefault("pub_" + m.group(1), _date(m.group(2)))
    return out


def authors(x):
    """Article authors. Publishers mark authorship either on each <contrib>
    (contrib-type="author") or on the enclosing <contrib-group content-type="author">."""
    front = re.search(r"<article-meta>.*?</article-meta>", x, re.S)
    f = front.group(0) if front else ""
    blocks = []
    for g in re.finditer(r"<contrib-group\b([^>]*)>(.*?)</contrib-group>", f, re.S):
        group_is_author = 'content-type="author"' in g.group(1)
        for c in re.finditer(r"<contrib\b([^>]*)>(.*?)</contrib>", g.group(2), re.S):
            ctype = re.search(r'contrib-type="([^"]+)"', c.group(1))
            if (ctype and ctype.group(1) == "author") or (not ctype and group_is_author) \
                    or (not ctype and 'content-type=' not in g.group(1)):
                blocks.append(c.group(2))
    out = []
    for c in blocks:
        sn = re.search(r"<surname>(.*?)</surname>", c, re.S)
        gn = re.search(r"<given-names[^>]*>(.*?)</given-names>", c, re.S)
        if sn:
            out.append({"surname": strip(sn.group(1)), "given": strip(gn.group(1)) if gn else ""})
    return out


def title(x):
    m = re.search(r"<article-title[^>]*>(.*?)</article-title>", x, re.S)
    return strip(m.group(1)) if m else ""


def crd_mentions(x):
    """Every CRD ID in the article with the region it sits in. A CRD inside the
    reference list or in running text about other reviews is not the article's
    own registration."""
    spans = {}
    for tag in ("abstract", "ref-list", "body", "back", "article-meta"):
        spans[tag] = [(m.start(), m.end()) for m in re.finditer(rf"<{tag}\b.*?</{tag}>", x, re.S)]
    out = []
    for m in CRD.finditer(x):
        pos = m.start()
        where = [t for t, ss in spans.items() if any(a <= pos < b for a, b in ss)]
        # innermost meaningful region
        if "ref-list" in where:
            reg = "ref-list"
        elif "abstract" in where:
            reg = "abstract"
        elif "body" in where:
            reg = "body"
        elif "back" in where:
            reg = "back"
        elif "article-meta" in where:
            reg = "front"
        else:
            reg = "other"
        ctx = strip(x[max(0, pos - 300):pos + 60])[-160:]
        out.append({"id": m.group(0).replace(" ", ""), "region": reg, "context": ctx})
    return out


NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={num}"


def ncbi_xml(pmcid):
    """NCBI's copy of the same JATS article. Europe PMC drops <history> for
    some articles (34 of 70 in the first sample); NCBI keeps it."""
    import time
    num = pmcid.replace("PMC", "")
    time.sleep(0.4)  # E-utilities allows 3 requests/s without a key
    return cached_text("ncbi", pmcid, NCBI.format(num=num), ext=".xml",
                       validate=lambda b: "<article" in b[:5000])


def history_any(pmcid):
    h = history(xml(pmcid) or "")
    src = "europepmc"
    if "received" not in h:
        h2 = history(ncbi_xml(pmcid) or "")
        if "received" in h2:
            h, src = {**h2, **{k: v for k, v in h.items() if k not in h2}}, "ncbi"
    h["source"] = src
    return h
