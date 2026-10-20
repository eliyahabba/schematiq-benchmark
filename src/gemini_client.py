"""Minimal Gemini client for the judge and question-rewrite steps.

REST call to generateContent with JSON output. The key comes from
GEMINI_API_KEY; the model from --model or GEMINI_MODEL (default
gemini-3.8-flash, ScheMatiQ's default schema-creation model in
schematiq-lib/schematiq/core/model_specs.py). No temperature, top_p or top_k
is sent: model_specs.py notes that newer Gemini models ignore them and will
reject them. GEMINI_FAKE=1 returns a canned answer, for testing without a key.
"""
import json, os, time, urllib.error, urllib.request

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def ask_json(prompt, model=None, fake=None, tries=5):
    """Send one prompt, return the parsed JSON object the model answered with."""
    if os.environ.get("GEMINI_FAKE"):
        return fake if fake is not None else {}
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set (see README, Credentials)")
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode()
    req = urllib.request.Request(URL.format(model=model or DEFAULT_MODEL), data=body,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read().decode())
            text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
            return json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and i < tries - 1:
                time.sleep(2 ** i * 5); continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {e.read()[:300]!r}")
        except (KeyError, IndexError, ValueError) as e:
            if i < tries - 1:
                time.sleep(2); continue
            raise RuntimeError(f"unreadable Gemini answer: {e}")
