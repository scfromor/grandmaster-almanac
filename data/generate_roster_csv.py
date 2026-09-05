#!/usr/bin/env python3
"""One-shot migration: turn the last rating-derived data.json into roster.csv.

This runs ONCE, to seed data/roster.csv from the final FIDE-derived dataset
(SEP26). After that, roster.csv is hand-maintained and this script is only
kept for reference / disaster recovery.

Rating-derived fields (rating, peak, history, games, active) are dropped.
The `style` radar values are carried across verbatim: they were originally
estimated from rating, and with ratings gone they can no longer be
recomputed, so they become static data.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roster_io  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(HERE, "..", "gm-dashboard", "data.json")


def flatten(text: str) -> str:
    """Collapse embedded newlines/tabs so every player is exactly one CSV row.

    CSV quoting technically permits newlines inside a quoted field, but a file
    that is edited by hand in a browser should have one row per line -- it
    makes diffs readable and makes it far harder to corrupt the file with a
    stray keystroke.
    """
    return " ".join((text or "").split())


def main() -> int:
    with open(DATA_JSON, encoding="utf-8") as fh:
        data = json.load(fh)

    players = data["players"]
    records = []
    for p in players:
        rec = {
            "id": p.get("id", ""),
            "name": flatten(p.get("name", "")),
            "fed": p.get("fed", ""),
            "sex": p.get("sex", ""),
            "title": p.get("title", ""),
            "wtit": p.get("wtit", ""),
            "bday": p.get("bday") or None,
            "gmYear": p.get("gmYear") or None,
            "deceased": bool(p.get("deceased")),
            "deathYear": p.get("deathYear") or None,
            "revoked": bool(p.get("revoked")),
            "revokedYear": p.get("revokedYear") or None,
            "revokedReason": flatten(p.get("revokedReason") or ""),
            "birthCountry": p.get("birthCountry") or "",
            "birthCity": flatten(p.get("birthCity") or ""),
            "fedHistory": p.get("fedHistory") or [],
            "photo": p.get("photo") or "",
            "photoSource": p.get("photoSource") or "",
            "bio": flatten(p.get("bio") or ""),
            "bioSource": p.get("bioSource") or "",
        }
        style = p.get("style") or {}
        for axis in roster_io.STYLE_AXES:
            v = style.get(axis)
            rec[f"style_{axis}"] = int(v) if isinstance(v, (int, float)) else None
        records.append(rec)

    # Sort by name so the CSV has a stable, human-navigable order. Anyone
    # hand-editing this file will be looking for a person alphabetically.
    records.sort(key=lambda r: (r["name"] or "").lower())

    roster_io.write_roster(records)

    # Preserve the federation-code -> display-name table. It isn't per-player
    # data so it doesn't belong in roster.csv, but the build needs it and we
    # no longer have FIDE to regenerate it from.
    fed_names = data.get("fedNames") or {}
    with open(os.path.join(HERE, "fed_names.json"), "w", encoding="utf-8") as fh:
        json.dump(fed_names, fh, ensure_ascii=False, indent=2, sort_keys=True)

    styled = sum(1 for r in records if r["style_aggressive"] is not None)
    print(f"wrote {roster_io.ROSTER_CSV}: {len(records)} players")
    print(f"  with style radar : {styled}")
    print(f"  deceased         : {sum(1 for r in records if r['deceased'])}")
    print(f"  title revoked    : {sum(1 for r in records if r['revoked'])}")
    print(f"  with photo       : {sum(1 for r in records if r['photo'])}")
    print(f"  with bio         : {sum(1 for r in records if r['bio'])}")
    print(f"wrote fed_names.json: {len(fed_names)} federations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
