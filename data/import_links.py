#!/usr/bin/env python3
"""
One-off (but re-runnable) import of profile links from Wikidata into roster.csv.

Wikidata stores the FIDE player ID as property P1440, which gives a clean join
key to our roster. We read the handle or ID for each platform and let the site
build the URL at render time, so the CSV stays short and hand-editable.

This never overwrites a value that is already in roster.csv. The CSV is the
source of truth; Wikidata only fills blanks. That way any correction Sean makes
by hand survives a re-run.

Usage:
    python3 data/import_links.py            # dry run, prints what would change
    python3 data/import_links.py --write    # actually writes roster.csv
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import roster_io  # noqa: E402
from roster_io import read_roster, write_roster  # noqa: E402

ROSTER = pathlib.Path(__file__).resolve().parent / "roster.csv"
ENDPOINT = "https://query.wikidata.org/sparql"
UA = "grandmaster-almanac/1.0 (https://scfromor.com/chess/grandmaster_almanac/)"

# Wikidata property -> roster column.
PROPS = {
    "site": ("P856", "website"),
    "x": ("P2002", "x"),
    "insta": ("P2003", "instagram"),
    "yt": ("P2397", "youtube"),
    "twitch": ("P5797", "twitch"),
    "fb": ("P2013", "facebook"),
    "ccom": ("P3654", "chesscom"),        # member account: chess.com/member/<v>
    "ccomp": ("P11065", "chesscomPlayer"),  # editorial page: chess.com/players/<v>
    "lichess": ("P8976", "lichess"),
    "cg": ("P1665", "chessgames"),
}

QUERY = """SELECT ?fide %s WHERE {
  ?p wdt:P1440 ?fide .
%s
}""" % (
    " ".join(f"?{k}" for k in PROPS),
    "\n".join(f"  OPTIONAL {{ ?p wdt:{p} ?{k} }}" for k, (p, _) in PROPS.items()),
)

# Shared with the validator so an imported value and a hand-typed one are held
# to exactly the same standard.
PATTERNS = {k: re.compile(v) for k, v in roster_io.LINK_PATTERNS.items()}

# Handles sometimes arrive as a full URL or with a leading @. Strip that here
# rather than storing it, so every row is consistent and the renderer stays dumb.
STRIP_PREFIX = (
    "https://", "http://", "www.", "x.com/", "twitter.com/", "instagram.com/",
    "facebook.com/", "twitch.tv/", "lichess.org/@/", "chess.com/member/",
    "chess.com/players/", "youtube.com/",
)


def clean(col: str, value: str) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if col != "website":
        changed = True
        while changed:
            changed = False
            for pre in STRIP_PREFIX:
                if v.lower().startswith(pre):
                    v = v[len(pre):]
                    changed = True
        v = v.lstrip("@").rstrip("/")
        if "/" in v or " " in v:
            return None
    pat = PATTERNS.get(col)
    if pat and not pat.match(v):
        return None
    return v


def fetch() -> list[dict]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["results"]["bindings"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    players = read_roster(ROSTER)
    by_id = {p["id"]: p for p in players}
    print(f"roster: {len(players)} players")

    rows = fetch()
    print(f"wikidata: {len(rows)} rows with a FIDE id")

    # Collect every distinct value per player per column.
    found: dict[str, dict[str, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    rejected = collections.Counter()
    for r in rows:
        fide = r.get("fide", {}).get("value", "")
        if fide not in by_id:
            continue
        for key, (_prop, col) in PROPS.items():
            raw = r.get(key, {}).get("value")
            if not raw:
                continue
            v = clean(col, raw)
            if v is None:
                rejected[col] += 1
                continue
            found[fide][col].add(v)

    filled = collections.Counter()
    conflicts = collections.Counter()
    skipped_existing = collections.Counter()
    touched = set()

    for fide, cols in found.items():
        p = by_id[fide]
        for col, values in cols.items():
            if p.get(col):
                skipped_existing[col] += 1
                continue
            if len(values) > 1:
                # Wikidata disagrees with itself. Taking a coin-flip value would
                # publish a link we cannot stand behind, so leave it blank for
                # a human to resolve.
                conflicts[col] += 1
                continue
            p[col] = next(iter(values))
            filled[col] += 1
            touched.add(fide)

    print(f"\nplayers gaining at least one link: {len(touched)}")
    print(f"{'column':16} {'filled':>7} {'conflict':>9} {'kept':>6} {'rejected':>9}")
    for _key, (_prop, col) in PROPS.items():
        print(f"{col:16} {filled[col]:7} {conflicts[col]:9} "
              f"{skipped_existing[col]:6} {rejected[col]:9}")

    any_link = sum(
        1 for p in players
        if any(p.get(c) for _k, (_pp, c) in PROPS.items())
    )
    print(f"\nplayers with at least one link after import: "
          f"{any_link} ({any_link / len(players) * 100:.1f}%)")

    if args.write:
        write_roster(players, ROSTER)
        print(f"\nwrote {ROSTER}")
    else:
        print("\ndry run — pass --write to save")
    return 0


if __name__ == "__main__":
    sys.exit(main())
