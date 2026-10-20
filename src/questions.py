"""Research question from the review's own abstract, for reviews without a
usable registry record. The question is written after the table; the
benchmark accepts that (decision of 2026-09-27) and labels it as such."""
import html, re
import quality

OBJ_TITLE = re.compile(r"^\s*(objectives?|aims?|aims? and objectives?|objectives? and aims?|purpose|goals?|"
                       r"research questions?|review questions?|study objectives?|aim of the (study|review))\b", re.I)
BG_TITLE = re.compile(r"^\s*(background|introduction|context|rationale|importance)", re.I)
AIM = re.compile(
    r"\b(this (systematic |scoping |umbrella |rapid |comprehensive )?(review|meta-analysis|study|paper|overview|map|survey|article|work)\b[^.;]{0,60}?"
    r"\b(aim|aims|aimed|seeks?|sought|evaluat|assess|examin|investigat|synthesi|summari|explor|compar|determin|identif|map|quantif|"
    r"present|provide|review|survey|categori|cover|discuss|analy)"
    r"|\bin this (survey|review|paper|article|work), we\b"
    r"|we (aimed|aim|sought|set out|systematically (review|evaluat|assess|examin|investigat|synthesi|summari))"
    r"|we (conducted|performed|undertook|carried out|present|report)\b[^.;]{0,40}\b(review|meta-analys|synthesis|overview|map)"
    r"|we (estimated|evaluated|assessed|examined|investigated|reviewed|compared|summari[sz]ed|synthesi[sz]ed|"
    r"determined|identified|quantified|explored|analy[sz]ed|mapped|describe[d]?)\b"
    r"|(was|were) (conducted|undertaken|performed|carried out|designed) to\b"
    r"|the (aim|objective|purpose|goal)s? of (this|the present|our|the current) (systematic |scoping |umbrella )?"
    r"(review|study|meta-analysis|analysis|overview|map)\s+(is|was|were|are)"
    r"|(to|we) (systematically )?(review|evaluate|assess|examine|investigate|synthesi[sz]e|summari[sz]e|compare|determine|identify|map|quantify|explore)\b)",
    re.I)


def _txt(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _sentences(t):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", t) if s.strip()]


def abstract_objective(xml):
    """Returns (question_text or None, how): the first candidate, in order of
    preference, that passes gate(). Candidates are listed by _candidates()."""
    first = None
    for q, how in _candidates(xml):
        if first is None:
            first = (q, how)
            if gate(q)[0]:
                return q, how
            continue
        # a later candidate must state an aim outright; otherwise conclusions and
        # limitations ("further studies are warranted to investigate ...") slip in
        if STRONG_AIM.search(q) and gate(q)[0]:
            return q, how
    return first if first else (None, "no_aim_found")


def _candidates(xml):
    """Yield (sentence, how) candidates in order of preference."""
    ab = None
    for m in re.finditer(r"<abstract\b([^>]*)>(.*?)</abstract>", xml or "", re.S):
        if re.search(r'abstract-type="(graphical|teaser|toc|video)"', m.group(1)):
            continue
        ab = m.group(2)
        break
    if not ab:
        return
    secs = re.findall(r"<sec[^>]*>\s*<title>(.*?)</title>(.*?)</sec>", ab, re.S)
    for title, body in secs:
        if OBJ_TITLE.match(_txt(title)):
            q = _txt(body)
            if q:
                # some "Objective" sections open with background; start at the aim
                ss = _sentences(q)
                for i, sent in enumerate(ss):
                    if AIM.search(sent):
                        yield " ".join(ss[i:i + 2]), "abstract_objective_section"
                yield q, "abstract_objective_section"
    # aim sentence in a background section, then anywhere in the abstract
    bgs = [_txt(b) for t, b in secs if BG_TITLE.match(_txt(t))]
    for pool in bgs + [_txt(ab)]:
        for s in _sentences(pool):
            if AIM.search(s) and not re.match(r"^(methods?|results?|conclusions?)\b", s, re.I):
                yield s, "abstract_aim_sentence"
    # structured abstracts often end the background with the aim, phrased freely
    for pool in bgs:
        ss = _sentences(pool)
        if ss and quality.OBJ_VERB.search(ss[-1]):
            yield ss[-1], "abstract_background_last_sentence"
    # inline labels without <sec>: "<bold>Objective</bold> To ..." or "Objective: To ..."
    flat = _txt(ab)
    m = re.search(r"\b(?:Objectives?|Aims?|Purpose|Goal)s?\s*[:.]?\s+((?:To|We)\s[^.]{15,400}\.)", flat)
    if m:
        yield m.group(1), "abstract_inline_label"
    for s in _sentences(flat):
        if INFINITIVE.match(s):
            yield s, "abstract_infinitive_sentence"


INFINITIVE = re.compile(r"^(?:Background:?\s+)?To\s+[a-z]+(?:e|ize|ise|ify|ine|ate|ore|ess|ide|ure)?\b", re.I)
AIM_START = re.compile(r"^(to\s+[a-z]+|our aim|the aim|the objective|the purpose|we aimed|this (systematic )?review aims?)\b", re.I)
STRONG_AIM = re.compile(r"\b(aim(s|ed)?|objectives?|purpose|goal)\b|^\s*to\s+[a-z]+\b|"
                        r"\b(this|the present|our) (systematic |scoping |umbrella )?(review|meta-analysis|study|map)\s+"
                        r"(aims?|seeks?|sought|was designed|evaluat|assess|examin|investigat|synthesi|compar)|"
                        r"\bwe (aimed|sought|set out)\b", re.I)
METHODS = re.compile(r"\b(PRISMA|databases?|searched|MEDLINE|Embase|PubMed|Web of Science|Scopus|random[- ]effects?|"
                     r"fixed[- ]effects?|when feasible|according to (the )?(PRISMA|guidelines))\b", re.I)
AIM_TO = re.compile(r"\bto (assess|evaluate|determine|examine|investigate|compare|identify|explore|estimate|"
                    r"synthesi[sz]e|summari[sz]e|review|quantify|characteri[sz]e|describe|map|analy[sz]e)\b", re.I)
RESULTS = re.compile(r"\bwe (identified|included|found|retrieved|screened|obtained|located) (a total of )?\d+|^\s*(most|all|few|\d+%?) (of the )?studies\b", re.I)
GENERIC = set("""this that these those with from into were have been which their there about study studies review reviews
systematic literature report reports case cases present presented paper article meta analysis analyses data using used
performed conducted undertook carried statement guidelines research evidence""".split())
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def gate(q):
    """quality.check_question, which was built for mined sentences, plus two
    corrections found on the stratified sample: non-English abstracts are
    rejected, and an aim phrased as "To <verb> ..." passes even when the verb
    is not in quality.py's list ("To give an overview of ...")."""
    if not q:
        return False, "missing"
    if len(CJK.findall(q)) > 5:
        return False, "non_english"
    if METHODS.search(q) and not AIM_TO.search(q):
        return False, "methods_sentence"
    if RESULTS.search(q):
        return False, "results_sentence"
    if len([w for w in re.findall(r"[a-z]{4,}", q.lower()) if w not in GENERIC]) < 3:
        return False, "no_topic"
    ok, why = quality.check_question(q)
    if not ok and why == "no_objective_verb" and AIM_START.match(q.strip()) and 50 <= len(q) <= 450:
        return True, "ok"
    return ok, why
