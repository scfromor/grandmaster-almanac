#!/usr/bin/env python3
"""Build gm-dashboard/data.json from data/roster.csv.

This replaces refresh_dashboard.py's FIDE download entirely. Nothing here
touches the network: the roster is hand-maintained, so a build is a pure
function of files already in the repo. That is the whole point of the
redesign -- the site can no longer break because an external host blocked us.

Derived fields (country display names, age, previous federation) are computed
here rather than stored in the CSV, so there is exactly one place they can be
wrong.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roster_io  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FED_NAMES_PATH = os.path.join(HERE, "fed_names.json")
OUT_PATH = os.path.join(HERE, "..", "gm-dashboard", "data.json")


def build() -> dict:
    rows = roster_io.read_roster()
    with open(FED_NAMES_PATH, encoding="utf-8") as fh:
        fed_names: dict[str, str] = json.load(fh)

    this_year = _dt.date.today().year
    players = []

    for r in rows:
        fed_history = r["fedHistory"]
        # "Previous federation" is the entry before the current one. Players
        # who never transferred have a single-entry history and no previous
        # federation; the UI filter treats that as "same as current".
        prev_fed = fed_history[-2] if len(fed_history) >= 2 else r["fed"]

        # Age is derived, not stored: storing it would silently rot every
        # January. Deceased players' ages are frozen at their death year.
        age = None
        if r["bday"]:
            end = r["deathYear"] if (r["deceased"] and r["deathYear"]) else this_year
            age = end - r["bday"]

        # Build the finished URLs here rather than in the browser, so the page
        # builder and the front end can never disagree about a handle.
        #
        # Emitted as compact [key, url] pairs. Repeating the label and the bare
        # handle on all ~5,800 links added about 280 KB to a file every visitor
        # downloads; the labels ship once in `linkLabels` instead.
        links = [[x["key"], x["url"]] for x in roster_io.links_for(r)]

        players.append({
            "id": r["id"],
            "name": r["name"],
            "fed": r["fed"],
            "fedName": fed_names.get(r["fed"], r["fed"]),
            "birthCountry": r["birthCountry"],
            "birthCountryName": fed_names.get(r["birthCountry"], r["birthCountry"]),
            "prevFed": prev_fed,
            "prevFedName": fed_names.get(prev_fed, prev_fed),
            "sex": r["sex"],
            "title": r["title"],
            "wtit": r["wtit"],
            "bday": r["bday"],
            "age": age,
            "birthCity": r["birthCity"],
            "gmYear": r["gmYear"],
            "deceased": r["deceased"],
            "deathYear": r["deathYear"],
            "revoked": r["revoked"],
            "revokedYear": r["revokedYear"],
            "revokedReason": r["revokedReason"],
            "photo": r["photo"],
            "photoSource": r["photoSource"],
            "bio": r["bio"],
            "bioSource": r["bioSource"],
            "fedHistory": fed_history,
            "fedHistoryNames": [fed_names.get(c, c) for c in fed_history],
            "links": links,
        })

    players.sort(key=lambda p: (p["name"] or "").lower())

    # Only ship names for federations actually present, so the filter
    # dropdowns don't list 60 countries with no grandmasters.
    present = sorted({p["fed"] for p in players}
                     | {p["birthCountry"] for p in players if p["birthCountry"]}
                     | {c for p in players for c in p["fedHistory"]})

    return {
        "generatedAt": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "data/roster.csv",
        "playerCount": len(players),
        "players": players,
        "feds": sorted({p["fed"] for p in players}),
        "fedNames": {c: fed_names.get(c, c) for c in present},
        # Display names for the link keys, shipped once instead of on every
        # link. Order here is the order links render in.
        "linkLabels": {
            c: roster_io.LINK_TEMPLATES[c][0] for c in roster_io.LINK_COLUMNS
        },
    }


def main() -> int:
    data = build()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(OUT_PATH)
    living = sum(1 for p in data["players"] if not p["deceased"])
    print(f"wrote {OUT_PATH}")
    print(f"  players    : {data['playerCount']} ({living} living)")
    print(f"  federations: {len(data['feds'])}")
    print(f"  with photo : {sum(1 for p in data['players'] if p['photo'])}")
    print(f"  with bio   : {sum(1 for p in data['players'] if p['bio'])}")
    print(f"  with links : {sum(1 for p in data['players'] if p['links'])} "
          f"({sum(len(p['links']) for p in data['players'])} links)")
    print(f"  size       : {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
