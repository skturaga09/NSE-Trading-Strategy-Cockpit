"""Re-open every DOC URL in docs/verified-facts.md and check the row's quote is still on the page.

Read-only GETs. Output: one JSON line per fact row (id, url, http status, quote_found). MEASURED rows
are listed as SKIPPED_MEASURED (they are re-measured by running the engine, not by a URL).
Usage: python3 scripts/reverify_facts.py > docs/phase-15-evidence/facts-reverify.jsonl
"""
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) fact-reverify/1.0", "Accept-Language": "en"}
URL_RE = re.compile(r"https?://[^\s)|>`\"]+")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[`*_\"'…]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def page_text(url: str, cache: dict) -> tuple[int | str, str]:
    if url in cache:
        return cache[url]
    try:
        session = requests.Session()
        if "nseindia.com" in url:  # NSE sets cookies on the home page first
            session.get("https://www.nseindia.com", headers=UA, timeout=20)
        r = session.get(url, headers=UA, timeout=30)
        if url.lower().endswith(".pdf") or r.headers.get("content-type", "").startswith("application/pdf"):
            from pypdf import PdfReader
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
        elif "html" in r.headers.get("content-type", ""):
            text = BeautifulSoup(r.text, "html.parser").get_text(" ")
        else:
            text = r.text
        cache[url] = (r.status_code, text)
    except Exception as e:  # network failure is reported, never hidden
        cache[url] = (f"ERROR {type(e).__name__}: {e}", "")
    return cache[url]


def quote_found(quote: str, text: str) -> bool:
    q, t = norm(quote), norm(text)
    if not q:
        return False
    # quotes use "…" to elide; every fragment must be on the page
    return all(frag.strip() in t for frag in re.split(r"\s*(?:…|\.\.\.)\s*", q) if len(frag.strip()) > 3)


def main(path: str = "docs/verified-facts.md") -> None:
    cache: dict = {}
    for line in Path(path).read_text().splitlines():
        if not line.startswith("| F-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        fid, source = cells[0], cells[2] if len(cells) > 2 else ""
        quote = cells[4] if len(cells) > 4 else ""
        # a quote cell holds one or more "…" fragments; a cell without quote marks is a description, checked by hand
        fragments = re.findall(r'"([^"]+)"', quote)
        urls = [u.rstrip(".,;") for u in URL_RE.findall(source) if "api.kite.trade" not in u]
        if not urls:
            print(json.dumps({"id": fid, "result": "SKIPPED_MEASURED", "source": source[:120]}))
            continue
        for url in urls:
            status, text = page_text(url, cache)
            if status != 200:
                result = "FETCH_FAILED"
            elif not fragments:
                result = "NO_QUOTE_TO_CHECK"
            else:
                missing = [f for f in fragments if not quote_found(f, text)]
                result = "OK" if not missing else "QUOTE_NOT_FOUND"
            print(json.dumps({"id": fid, "url": url, "http": status, "quote": quote[:160], "result": result,
                              "missing": [] if result != "QUOTE_NOT_FOUND" else missing}))
            sys.stdout.flush()


if __name__ == "__main__":
    main(*sys.argv[1:])
