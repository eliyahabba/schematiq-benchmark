"""Automatic checks for rewritten research questions.

  grounded : share of the question's content words (stemmed) that occur in the
             paper's title, abstract or the authors' own aim text; a rewrite
             must not add scope the authors did not state (target >= 0.8)
  leakage  : how many gold column names are spelled out in the question,
             before and after the rewrite (a rewrite must not add any)
"""
import re
import quality

STOP = quality.STOP | set("""which what how does do is are there their they them into have been used using
whether more most over such other than then also each between within across about""".split())


def content(s):
    return {quality._stem(w) for w in re.findall(r"[a-z][a-z\-]{3,}", (s or "").lower()) if w not in STOP}


def grounded(question, *sources):
    q = content(question)
    src = set()
    for s in sources:
        src |= content(s)
    return round(len(q & src) / len(q), 3) if q else 0.0


def leakage(question, columns):
    return quality.alignment(question, columns)[1]
