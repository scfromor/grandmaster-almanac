#!/usr/bin/env python3
"""Validate data/roster.csv before it is allowed to build the site.

This is the safety net for hand-editing. roster.csv is edited directly in
GitHub's web UI, so a typo is a normal, expected event -- it must fail the
build loudly with a message that says which row and what to fix, rather than
publishing a broken site.

Exit code 0 = safe to build. Exit code 1 = do not build.
"""

from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roster_io  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FED_NAMES_PATH = os.path.join(HERE, "fed_names.json")

# A GM roster shrinking by more than this in one edit almost certainly means
# rows were deleted by accident (a bad paste, a truncated file) rather than
# deliberately. Deliberate mass deletion can still be done by editing this
# number or passing --allow-shrink.
MAX_SHRINK = 25

CURRENT_YEAR = 2026
EARLIEST_BIRTH_YEAR = 1850
EARLIEST_GM_YEAR = 1950  # the GM title was created in 1950
FED_RE = re.compile(r"^[A-Z]{3}$")


def main() -> int:
    allow_shrink = "--allow-shrink" in sys.argv
    errors: list[str] = []
    warnings: list[str] = []

    try:
        rows = roster_io.read_roster()
    except (ValueError, FileNotFoundError) as exc:
        print(f"FATAL: could not parse roster.csv\n  {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("FATAL: roster.csv has no data rows", file=sys.stderr)
        return 1

    with open(FED_NAMES_PATH, encoding="utf-8") as fh:
        fed_names = json.load(fh)

    seen_ids: dict[str, int] = {}

    for r in rows:
        n = r["_row"]
        who = r.get("name") or "(no name)"

        # --- identity -----------------------------------------------------
        if not r["id"]:
            errors.append(f"row {n}: id is empty")
        elif r["id"] in seen_ids:
            errors.append(
                f"row {n}: duplicate id {r['id']} (already used on row {seen_ids[r['id']]})"
            )
        else:
            seen_ids[r["id"]] = n

        if not r["name"]:
            errors.append(f"row {n}: name is empty")
        # Deliberately NOT warning about names without a "Surname, Forename"
        # comma. Around 60 players -- mostly Indian and Vietnamese -- are
        # listed mononymously or in a different order by FIDE itself, so the
        # check produced far more false positives than real catches and would
        # have trained us to ignore this output.

        # --- federations --------------------------------------------------
        if not r["fed"]:
            errors.append(f"row {n} ({who}): fed is empty")
        elif not FED_RE.match(r["fed"]):
            errors.append(f"row {n} ({who}): fed {r['fed']!r} is not a 3-letter code")
        elif r["fed"] not in fed_names:
            errors.append(
                f"row {n} ({who}): fed {r['fed']!r} is not in fed_names.json -- "
                f"add it there first so the site can show a country name"
            )

        if r["birthCountry"] and r["birthCountry"] not in fed_names:
            warnings.append(
                f"row {n} ({who}): birthCountry {r['birthCountry']!r} not in fed_names.json"
            )

        for code in r["fedHistory"]:
            if not FED_RE.match(code):
                errors.append(
                    f"row {n} ({who}): fedHistory entry {code!r} is not a 3-letter code"
                )

        # --- enumerations -------------------------------------------------
        if r["sex"] not in ("M", "F"):
            errors.append(f"row {n} ({who}): sex must be M or F, got {r['sex']!r}")

        if not r["title"]:
            errors.append(f"row {n} ({who}): title is empty")

        # --- years --------------------------------------------------------
        for field, lo in (("bday", EARLIEST_BIRTH_YEAR), ("gmYear", EARLIEST_GM_YEAR),
                          ("deathYear", EARLIEST_BIRTH_YEAR),
                          ("revokedYear", EARLIEST_GM_YEAR)):
            v = r[field]
            if v is not None and not (lo <= v <= CURRENT_YEAR):
                errors.append(
                    f"row {n} ({who}): {field}={v} is outside {lo}-{CURRENT_YEAR}"
                )

        if r["bday"] and r["gmYear"] and r["gmYear"] < r["bday"]:
            errors.append(
                f"row {n} ({who}): gmYear {r['gmYear']} is before birth year {r['bday']}"
            )
        if r["bday"] and r["deathYear"] and r["deathYear"] < r["bday"]:
            errors.append(
                f"row {n} ({who}): deathYear {r['deathYear']} is before birth year {r['bday']}"
            )

        # --- flag consistency ---------------------------------------------
        if r["deathYear"] and not r["deceased"]:
            errors.append(
                f"row {n} ({who}): deathYear is set but deceased is false -- "
                f"set deceased to true"
            )
        if r["revokedYear"] and not r["revoked"]:
            errors.append(
                f"row {n} ({who}): revokedYear is set but revoked is false -- "
                f"set revoked to true"
            )

        # --- urls ---------------------------------------------------------
        for field in ("photo", "photoSource", "bioSource"):
            v = r[field]
            if v and not v.startswith(("http://", "https://")):
                errors.append(f"row {n} ({who}): {field} is not a URL: {v!r}")

        # --- style radar ----------------------------------------------------
        present = [r[f"style_{a}"] is not None for a in roster_io.STYLE_AXES]
        if any(present) and not all(present):
            errors.append(
                f"row {n} ({who}): style axes are partially filled -- "
                f"provide all six or leave all six blank"
            )
        for a in roster_io.STYLE_AXES:
            v = r[f"style_{a}"]
            if v is not None and not (0 <= v <= 100):
                errors.append(f"row {n} ({who}): style_{a}={v} is outside 0-100")

    # --- whole-file sanity checks -----------------------------------------
    prev_count = None
    data_json = os.path.join(HERE, "..", "gm-dashboard", "data.json")
    if os.path.exists(data_json):
        try:
            with open(data_json, encoding="utf-8") as fh:
                prev_count = len(json.load(fh).get("players", []))
        except (json.JSONDecodeError, OSError):
            pass

    if prev_count and not allow_shrink:
        shrink = prev_count - len(rows)
        if shrink > MAX_SHRINK:
            errors.append(
                f"roster dropped from {prev_count} to {len(rows)} players "
                f"({shrink} removed). That is more than {MAX_SHRINK} and is "
                f"usually an accident. If it is intentional, re-run the "
                f"workflow with the allow_shrink option checked."
            )

    # --- report ------------------------------------------------------------
    for w in warnings:
        print(f"WARNING  {w}")
    for e in errors:
        print(f"ERROR    {e}", file=sys.stderr)

    print()
    print(f"roster.csv: {len(rows)} players, {len(errors)} errors, {len(warnings)} warnings")
    if prev_count:
        print(f"previous build had {prev_count} players")

    if errors:
        print("\nRefusing to build. Fix the errors above in data/roster.csv.",
              file=sys.stderr)
        return 1
    print("Validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
