#!/usr/bin/env python3
"""
Enrich gm-dashboard/data.json in place, independent of the FIDE download.

The monthly refresh runs in two phases:

  1. refresh_dashboard.py pulls the latest FIDE list and merges new/departed
     GMs. This can fail entirely when FIDE blocks datacenter IPs.
  2. Regardless of step 1, we still want to progressively fill in the roster
     with Wikipedia bios, playstyle radars for anyone still missing one,
     and queued photo candidates for human review.

This script does step 2. It reads the current gm-dashboard/data.json,
applies enrichment functions from refresh_dashboard.py, and writes the file
back. If nothing changes, it exits cleanly without touching the file.

Usage:  python3 data/enrich_dataset.py
Env vars honoured (same as refresh_dashboard.py):
  GM_BIO_BACKFILL_BUDGET       (default 50 per run)
  GM_PHOTO_CANDIDATE_BUDGET    (default 40 per run)
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Reuse the pipeline functions from refresh_dashboard.py.
import refresh_dashboard as R  # noqa: E402
from style_model import compute_style  # noqa: E402


def load_dataset():
    if not os.path.exists(R.DASHBOARD_JSON):
        print(f"ERROR: {R.DASHBOARD_JSON} not found", file=sys.stderr)
        sys.exit(1)
    with open(R.DASHBOARD_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def backfill_missing_style(players):
    """Compute a playstyle radar for any player still missing one.

    Runs offline (no network), deterministic. Only touches players whose
    style is empty or missing.
    """
    fixed = 0
    for p in players:
        if p.get("style") and isinstance(p["style"], dict) and p["style"]:
            continue
        rating = p.get("rating") or p.get("peak") or 2500
        p["style"] = compute_style(p["id"], rating, p.get("bday"))
        fixed += 1
    return fixed


def main():
    data = load_dataset()
    players = data.get("players", [])
    if not players:
        print("No players in dataset; nothing to do.")
        return

    # 1. Playstyle radars for anyone still missing one (offline, cheap).
    style_fixed = backfill_missing_style(players)

    # 2. Apply any human-approved photo candidates BEFORE new lookups.
    try:
        approvals = R.load_approvals()
        photos_applied = R.apply_photo_approvals(players, approvals)
    except Exception as exc:
        print(f"[enrich] apply_photo_approvals failed: {exc}", file=sys.stderr)
        photos_applied = 0

    # 3. Queue new photo candidates for review (small monthly budget).
    try:
        candidates = R.collect_photo_candidates(players)
    except Exception as exc:
        print(f"[enrich] collect_photo_candidates failed: {exc}", file=sys.stderr)
        candidates = []

    # 4. Backfill bios for a small monthly batch of active/rated players.
    try:
        bios_attempted = R.backfill_bios(players)
    except Exception as exc:
        print(f"[enrich] backfill_bios failed: {exc}", file=sys.stderr)
        bios_attempted = 0
    bios_filled = sum(1 for p in players if p.get("bio"))

    # Save if anything changed.
    with open(R.DASHBOARD_JSON, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)

    summary = {
        "style_backfilled": style_fixed,
        "photos_applied_from_approvals": photos_applied,
        "photo_candidates_total": len(candidates),
        "bios_attempted_this_run": bios_attempted,
        "bios_total_in_dataset": bios_filled,
    }
    print(json.dumps({"status": "ok", "enrichment": summary}))


if __name__ == "__main__":
    main()
