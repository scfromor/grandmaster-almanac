"""Shared CSV <-> record helpers for the Grandmaster Almanac roster.

`data/roster.csv` is the hand-maintained source of truth for the site. This
module is the single place that knows its column layout, so the generator,
the validator, and the builder can never drift apart.

See data/SCHEMA.md for the documented contract.
"""

from __future__ import annotations

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROSTER_CSV = os.path.join(HERE, "roster.csv")

STYLE_AXES = ("aggressive", "defense", "endgame", "opening", "positional", "tactical")

# Column order is deliberate: identity first, then the fields a human is most
# likely to edit by hand, then the long/rare ones, then the six style axes.
# Editing happens in GitHub's web UI, so the useful columns should be visible
# without scrolling all the way right.
COLUMNS = (
    "id",
    "name",
    "fed",
    "sex",
    "title",
    "wtit",
    "bday",
    "gmYear",
    "deceased",
    "deathYear",
    "revoked",
    "revokedYear",
    "revokedReason",
    "birthCountry",
    "birthCity",
    "fedHistory",
    "photo",
    "photoSource",
    "bio",
    "bioSource",
) + tuple(f"style_{a}" for a in STYLE_AXES)

BOOL_COLUMNS = ("deceased", "revoked")
INT_COLUMNS = ("bday", "gmYear", "deathYear", "revokedYear") + tuple(
    f"style_{a}" for a in STYLE_AXES
)

# fedHistory is a single cell holding an ordered list; pipe avoids clashing
# with the CSV comma and with names like "Saint Kitts".
LIST_SEP = "|"


def parse_bool(raw: str, *, field: str, row_num: int) -> bool:
    v = (raw or "").strip().lower()
    if v in ("true", "yes", "y", "1"):
        return True
    if v in ("false", "no", "n", "0", ""):
        return False
    raise ValueError(f"row {row_num}: {field}={raw!r} is not a boolean (use true/false)")


def parse_int(raw: str, *, field: str, row_num: int) -> int | None:
    v = (raw or "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"row {row_num}: {field}={raw!r} is not a whole number")


def read_roster(path: str = ROSTER_CSV) -> list[dict]:
    """Read roster.csv into typed dicts. Raises ValueError on malformed data."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                "roster.csv is missing required column(s): " + ", ".join(missing)
            )
        rows = []
        # row_num counts the way a human sees it in a spreadsheet: header is 1.
        for row_num, raw in enumerate(reader, start=2):
            rec = {c: (raw.get(c) or "").strip() for c in COLUMNS}
            for c in BOOL_COLUMNS:
                rec[c] = parse_bool(rec[c], field=c, row_num=row_num)
            for c in INT_COLUMNS:
                rec[c] = parse_int(rec[c], field=c, row_num=row_num)
            rec["fedHistory"] = [
                s.strip() for s in (rec["fedHistory"] or "").split(LIST_SEP) if s.strip()
            ]
            rec["_row"] = row_num
            rows.append(rec)
    return rows


def write_roster(records: list[dict], path: str = ROSTER_CSV) -> None:
    """Write typed dicts back out in the canonical column order."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        for rec in records:
            out = {}
            for c in COLUMNS:
                v = rec.get(c)
                if c in BOOL_COLUMNS:
                    # Do NOT use plain truthiness here. The string "false" is
                    # truthy in Python, so `"true" if v else "false"` silently
                    # flipped false -> true for any caller that passed strings
                    # instead of bools. Parse strings properly and reject
                    # anything ambiguous rather than guessing.
                    if isinstance(v, str):
                        v = parse_bool(v, field=c, row_num=-1)
                    elif v is None:
                        v = False
                    elif not isinstance(v, bool):
                        raise TypeError(
                            f"{c} must be a bool or a true/false string, got {v!r}"
                        )
                    out[c] = "true" if v else "false"
                elif c == "fedHistory":
                    out[c] = LIST_SEP.join(v or [])
                elif v is None:
                    out[c] = ""
                else:
                    out[c] = v
            writer.writerow(out)
