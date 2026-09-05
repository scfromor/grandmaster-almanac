"""
Wikipedia enrichment for new grandmasters: bio extract, thumbnail, and full
image URL. Shares the same conservative philosophy as the birth-country
lookup already in `refresh_dashboard.py`:

  * Never fabricate. On any failure, return None/empty and let the caller
    fall back to blank fields.
  * Never crash the monthly refresh. All network paths are wrapped so a
    Wikipedia API blip does not derail the FIDE data update.
  * Deterministic-enough: prefer a Wikipedia page title that clearly matches
    the searched name over the first search hit (avoids picking a
    disambiguation page over a real player article).

The bio is the Wikipedia article's lead paragraph, taken verbatim from the
`extract` field of the REST summary endpoint. Truncated to a small number of
sentences for the site card. We do NOT LLM-summarise: the extract is already
the community's edited lead, and Wikipedia has editorial oversight we do not.
"""

import json
import re
import subprocess
import time


UA = "GrandmasterAlmanac/1.0 (personal chess dashboard project)"

# Trim bio to this many sentences on the site card. Full Wikipedia extract is
# stored as `bioFull` so a longer variant is available for future use.
BIO_SENTENCE_LIMIT = 3


def _curl_json(url, timeout=20, min_interval=1.2):
    """Fetch JSON with a browser-ish UA. Returns None on any failure."""
    time.sleep(min_interval)  # be gentle on Wikipedia's rate limiter
    try:
        result = subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout), "-A", UA, url],
            capture_output=True, text=True, timeout=timeout + 5,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _reformat_fide_name(fide_name):
    if "," in fide_name:
        last, first = [x.strip() for x in fide_name.split(",", 1)]
        return f"{first} {last}"
    return fide_name


def _pick_best_hit(hits, search_name):
    """
    Prefer an exact title match, then a title that contains the searched name
    and isn't a disambiguation page. Falls back to the first hit.
    """
    lowered = search_name.lower()
    for hit in hits:
        if hit["title"].lower() == lowered:
            return hit
    for hit in hits:
        title = hit["title"].lower()
        if lowered in title and "disambiguation" not in title:
            return hit
    return hits[0] if hits else None


def find_wikipedia_summary(fide_name):
    """
    Resolve a FIDE-format name ("Lastname, Firstname") to a Wikipedia REST
    summary payload for that player's article. Returns None if no confident
    match is found.
    """
    search_name = _reformat_fide_name(fide_name)
    quoted = search_name.replace(" ", "%20")
    search_url = (
        "https://en.wikipedia.org/w/api.php?action=query&list=search"
        f"&srsearch={quoted}%20chess%20grandmaster&format=json&srlimit=5"
    )
    search = _curl_json(search_url)
    if not search:
        return None
    hits = search.get("query", {}).get("search", []) or []
    chosen = _pick_best_hit(hits, search_name)
    if not chosen:
        return None

    page_title = chosen["title"].replace(" ", "_")
    summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}"
    summary = _curl_json(summary_url)
    if not summary:
        return None

    # Guard: only trust the summary when the article obviously refers to a
    # chess-playing person. Otherwise the returned extract could be about a
    # namesake footballer / academic / etc.
    if not _looks_like_chess_article(summary):
        return None
    return summary


def _looks_like_chess_article(summary):
    """
    Cheap keyword gate to reduce wrong-person matches. The extract is short
    enough that "chess" appearing anywhere is a strong signal we've landed on
    a chess-related article.
    """
    text = (summary.get("extract") or "").lower()
    description = (summary.get("description") or "").lower()
    if "chess" in text or "chess" in description:
        return True
    if "grandmaster" in text or "grandmaster" in description:
        return True
    return False


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'])")


def truncate_extract(extract, max_sentences=BIO_SENTENCE_LIMIT):
    if not extract:
        return ""
    parts = _SENTENCE_SPLIT.split(extract.strip())
    return " ".join(parts[:max_sentences]).strip()


def enrich_from_wikipedia(fide_name):
    """
    Best-effort bio + photo enrichment for a brand-new GM.

    Returns a dict with keys:
        bio         short bio (first ~3 sentences of the Wikipedia extract)
        bioFull     the full extract, for future longer displays
        bioSource   canonical Wikipedia URL, used for attribution
        photo       image URL (Wikimedia Commons) or ""
        photoSource same canonical Wikipedia URL used for attribution

    Any field that can't be resolved comes back empty ("") rather than as a
    guess. The caller can trust these fields to be either accurate or blank.
    """
    blank = {"bio": "", "bioFull": "", "bioSource": "",
             "photo": "", "photoSource": ""}
    try:
        summary = find_wikipedia_summary(fide_name)
    except Exception:
        return blank
    if not summary:
        return blank

    extract = summary.get("extract") or ""
    canonical = (
        summary.get("content_urls", {}).get("desktop", {}).get("page")
        or f"https://en.wikipedia.org/wiki/{summary.get('titles', {}).get('canonical', '')}"
    )

    # Prefer originalimage (full-res) but fall back to thumbnail. Wikimedia
    # image URLs are stable long-term; we store the URL rather than downloading
    # so the dashboard's static-only footprint doesn't grow with each new GM.
    img = ""
    original = summary.get("originalimage") or {}
    thumb = summary.get("thumbnail") or {}
    if original.get("source"):
        img = original["source"]
    elif thumb.get("source"):
        img = thumb["source"]

    return {
        "bio": truncate_extract(extract),
        "bioFull": extract,
        "bioSource": canonical,
        "photo": img,
        "photoSource": canonical if img else "",
    }
