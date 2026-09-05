#!/usr/bin/env python3
"""
Stamp a content hash onto every local asset reference in the site's HTML.

Why this exists
---------------
On 5 September 2026 the site broke for anyone who had visited before with:

    Failed to load data: Cannot set properties of null (setting 'textContent')

The server files were correct. The problem was purely browser cache. The
ratings redesign rewrote both index.html and app.js, but the script tag still
read `app.js?v=20260810b` -- the same string as the previous release. Browsers
treat that as the same URL, so they served the OLD cached app.js against the
NEW html. The old code looked for the rating-period element, which no longer
exists, got null, and threw.

`player.js` and `style.css` were worse: they had no version string at all.

Hand-maintained version strings fail the moment someone forgets to bump one,
and the failure is invisible to whoever shipped it, because their own browser
usually fetches fresh. So the build now derives the version from the file's
own contents. Change a file and its URL changes; leave it alone and the URL
stays stable so the cache still does its job.

Run this after build_pages.py. It is idempotent.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "gm-dashboard"
ASSETS = ("app.js", "player.js", "style.css")

# Matches href="style.css", src="../player.js?v=abc123", etc.
REF = re.compile(
    r'(?P<attr>\b(?:href|src)=")'
    r'(?P<path>(?:\.\./)?(?:' + "|".join(re.escape(a) for a in ASSETS) + r'))'
    r'(?:\?v=[^"]*)?'
    r'(?P<close>")'
)


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def main() -> int:
    hashes: dict[str, str] = {}
    for a in ASSETS:
        p = ROOT / a
        if not p.exists():
            print(f"warning: {a} not found, skipping", file=sys.stderr)
            continue
        hashes[a] = digest(p)

    if not hashes:
        print("error: no assets found to stamp", file=sys.stderr)
        return 1

    for a, h in sorted(hashes.items()):
        print(f"  {a:12} -> {h}")

    def sub(m: re.Match[str]) -> str:
        name = m.group("path").rsplit("/", 1)[-1]
        h = hashes.get(name)
        if not h:
            return m.group(0)
        return f'{m.group("attr")}{m.group("path")}?v={h}{m.group("close")}'

    targets = sorted(ROOT.glob("*.html")) + sorted((ROOT / "player").glob("*.html"))
    changed = 0
    for f in targets:
        src = f.read_text(encoding="utf-8")
        out, n = REF.subn(sub, src)
        if n and out != src:
            f.write_text(out, encoding="utf-8")
            changed += 1

    print(f"  stamped {len(targets)} html files, {changed} updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
