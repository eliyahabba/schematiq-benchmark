#!/usr/bin/env python3
"""Quality gates derived from reading all 65 tasks by hand.

Three failure modes were found, each now has a gate:
  A. questions that are background sentences or carry unresolved pronouns
  B. tables that are quality-appraisal or equipment tables, not study characteristics
  C. tables whose columns have nothing to do with the question
"""
import re

# ---------- A. question validation ----------
OBJ_VERB = re.compile(
    r"\b(aim(s|ed)?|objective|purpose|goal|sought|set out|conducted to|"
    r"assess(es|ed)?|evaluat(e|es|ed)|determin(e|es|ed)|compar(e|es|ed)|"
    r"examin(e|es|ed)|investigat(e|es|ed)|synthesi[sz](e|es|ed)|review(s|ed)?|"
    r"identif(y|ies|ied)|estimat(e|es|ed)|quantif(y|ies|ied)|explor(e|es|ed)|"
    r"summari[sz](e|es|ed)|map|clarif(y|ies|ied)|validat(e|es|ed))\b", re.I)

# a pronoun in the opening clause has no antecedent once the question stands alone
DANGLING = re.compile(r"^\W*(their|its|these|those|such|this drug|the above|hence|thus|therefore)\b", re.I)
INNER_PRONOUN = re.compile(r"\b(their|its)\s+(efficacy|safety|effect|performance|use|value|impact|accuracy)\b", re.I)
METHODS_TELL = re.compile(
    r"\b(we searched|were searched|following prisma|databases were|"
    r"data (from studies|were (pooled|extracted))|random-effects|"
    r"inclusion criteria were pooled)\b", re.I)


def check_question(q):
    """Return (ok, reason)."""
    if not q:
        return False, "missing"
    s = q.strip()
    if len(s) < 50:
        return False, "too_short"
    if len(s) > 450:
        return False, "too_long"
    if DANGLING.match(s):
        return False, "dangling_opening"
    if INNER_PRONOUN.search(s[:120]):
        return False, "unresolved_pronoun"
    if METHODS_TELL.search(s) and not OBJ_VERB.search(s[:160]):
        return False, "methods_sentence"
    if not OBJ_VERB.search(s):
        return False, "no_objective_verb"
    # a duplicated verb phrase signals a mangled extraction
    if re.search(r"\b(to evaluate the to evaluate|aimed to aimed|the the)\b", s, re.I):
        return False, "mangled"
    return True, "ok"


# ---------- B. table content classification ----------
APPRAISAL_COL = re.compile(
    r"^(randomi[sz]ation|allocation concealment|blinding|blinded|"
    r"incomplete outcome|selective reporting|attrition|"
    r"clearly stated objective|statistical analysis|presentation of results|"
    r"final score|total score|overall score|risk of bias|quality score|"
    r"operator details|outcome assessor details|item \d+|domain \d+|d\d+|q\d+)", re.I)

APPARATUS_COL = re.compile(
    r"^(sampling rate|impedance|electrode|channel|amplifier|probe frequency|"
    r"software version|firmware|equipment|device model|power type)", re.I)

STUDY_COL = re.compile(
    r"(stud(y|ies)|author|reference|year|country|region|design|sample|"
    r"participant|population|patient|subject|age|sex|gender|"
    r"intervention|control|comparator|outcome|finding|result|conclusion|"
    r"dose|duration|follow.?up|setting|criteria|measure|instrument|method)", re.I)


def check_table(columns, n_rows):
    cols = [(c or "").strip() for c in columns]
    if n_rows < 4:
        return False, "too_few_rows"
    if len(cols) < 4:
        return False, "too_few_columns"
    placeholder = sum(1 for c in cols if re.fullmatch(r"col\d+", c))
    if placeholder > len(cols) * 0.25:
        return False, "unnamed_columns"
    appraisal = sum(1 for c in cols if APPRAISAL_COL.match(c))
    if appraisal >= 3 or appraisal > len(cols) * 0.35:
        return False, "appraisal_table"
    if sum(1 for c in cols if APPARATUS_COL.match(c)) >= 2:
        return False, "apparatus_table"
    if sum(1 for c in cols if STUDY_COL.search(c)) < 2:
        return False, "not_study_descriptive"
    return True, "ok"


# ---------- C. question to table alignment ----------
STOP = set("""a an the of and or in on for to with without by from as at is are was were be been being
this that these those we our study studies review reviews systematic meta analysis analyses its their
between among among effects effect impact role using used use versus vs into over under more most
than then which whether what how many much aim aimed aims objective objectives purpose goal evaluate
evaluated assess assessed determine determined compare compared examine examined investigate synthesize
summarize identify explore conducted performed current evidence data results outcome outcomes
patients participants people adults children clinical significant associated association""".split())


def _stem(w):
    for suf in ("ational", "ization", "isation", "ically", "ities", "ingly",
                "ness", "ment", "tion", "sion", "ical", "ing", "ies", "ied",
                "als", "al", "ic", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def tokens(s, stem=True):
    ws = {w for w in re.findall(r"[a-z]{4,}", (s or "").lower()) if w not in STOP}
    return {_stem(w) for w in ws} if stem else ws


def alignment(question, columns):
    """How much of the column vocabulary is anchored in the question."""
    q = tokens(question)
    if not q:
        return 0.0, 0
    hits = 0
    for c in columns:
        if tokens(c) & q:
            hits += 1
    return round(hits / max(1, len(columns)), 3), hits


def check_alignment(question, columns, min_hits=1):
    """Hard-reject only a complete miss. A low but non-zero score means the
    schema is generic PICO rather than question-specific, which is worth
    labelling but not worth discarding."""
    score, hits = alignment(question, columns)
    if hits < min_hits:
        return False, f"no_overlap(score={score})"
    tag = "generic" if score < 0.15 else "specific"
    return True, f"ok(score={score},hits={hits},{tag})"


def grade(task_question, columns, n_rows):
    """Single entry point. Returns (passes, dict of per-gate results)."""
    a_ok, a = check_question(task_question)
    b_ok, b = check_table(columns, n_rows)
    c_ok, c = check_alignment(task_question, columns) if a_ok else (False, "skipped")
    return (a_ok and b_ok and c_ok), {"question": a, "table": b, "alignment": c}
