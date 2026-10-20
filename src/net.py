"""Small HTTP layer shared by the pipeline scripts: retries, polite delays, disk cache.

Every network result is cached under cache/ so that a killed run resumes
without refetching, and so that results can be re-derived offline.
"""
import base64, gzip, hashlib, json, os, time, urllib.request, urllib.error

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "<CONTACT_EMAIL>")
UA = f"ScheMatiQ-benchmark/2.0 (research use; mailto:{CONTACT_EMAIL})"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")


def _path(ns, key, ext):
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in key)
    if len(safe) > 120:
        safe = safe[:80] + "_" + hashlib.sha1(key.encode()).hexdigest()[:16]
    return os.path.join(CACHE, ns, safe + ext)


OPENALEX_API_KEY = os.environ.get("OPENALEX_API_KEY")


def http_get(url, headers=None, tries=3, timeout=60, binary=False):
    """Returns (status, body) where body is bytes or str; status None on network failure.
    OpenAlex now limits anonymous use to a small daily budget per IP address (found
    2026-09-27: HTTP 429 "Insufficient budget"); set OPENALEX_API_KEY (free) to lift it."""
    if OPENALEX_API_KEY and "api.openalex.org" in url and "api_key=" not in url:
        url += ("&" if "?" in url else "?") + "api_key=" + OPENALEX_API_KEY
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    last = (None, None)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return r.status, (b if binary else b.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = (e.code, None)
            if e.code in (400, 401, 403, 404, 410, 451):
                return last
        except Exception:
            last = (None, None)
        time.sleep(1.5 * (i + 1))
    return last


def cached_text(ns, key, url, headers_fn=None, ext=".txt", validate=None):
    """Fetch url once and store it. validate(body)->bool decides whether to cache."""
    p = _path(ns, key, ext)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    st, body = http_get(url, headers=headers_fn() if headers_fn else None)
    if body is None or (validate and not validate(body)):
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return body


def prospero_headers():
    # The public PROSPERO web app sends this header on every anonymous request:
    # the base64 of the current time in milliseconds. It is not a credential.
    return {"prospero-auth-token": base64.b64encode(str(int(time.time() * 1000)).encode()).decode()}


def cached_bytes(ns, key, url, ext=".bin", validate=None, headers=None, timeout=90, tries=3):
    """Binary twin of cached_text."""
    p = _path(ns, key, ext)
    if os.path.exists(p):
        with open(p, "rb") as f:
            return f.read()
    st, body = http_get(url, headers=headers, binary=True, timeout=timeout, tries=tries)
    if body is None or (validate and not validate(body)):
        return None
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(body)
    return body


def arxiv_wait(min_gap=3.1):
    """One request every ~3 s to arxiv.org across ALL processes of this
    pipeline (the downloader and the LaTeX-source fetcher may run together).
    Coordinated through a lock file holding the time of the last request."""
    import fcntl
    lp = os.path.join(CACHE, ".arxiv_throttle")
    with open(lp, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        try:
            last = float(f.read().strip() or 0)
        except ValueError:
            last = 0.0
        wait = min_gap - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
        f.seek(0); f.truncate(); f.write(str(time.time())); f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
