#!/usr/bin/env python3
"""
Grandmaster Almanac — monthly FIDE refresh script.

Downloads the latest FIDE standard rating list, extracts current Grandmasters
(title == 'GM'), merges the fresh ratings/federation/games/age data into the
existing enriched dataset (which carries Wikipedia bios, photos, play-style
tags, and historical rating series), detects month-over-month changes
(new GMs, federation transfers, deaths), and writes a refreshed data.json
for the dashboard.

This script intentionally does NOT re-scrape Wikipedia or regenerate photos —
those are treated as static enrichment data that only needs to be set once
per player and then carried forward.

Usage:
    python3 refresh_dashboard.py

Inputs:
    gm-dashboard/data.json          existing enriched dataset (baseline)
    data/standard_rating_list.txt   freshly downloaded FIDE standard list
                                     (downloaded automatically if missing/stale)

Outputs:
    gm-dashboard/data.json          overwritten with refreshed data
    data/prev_data.json             snapshot of data.json taken BEFORE overwrite
    data/refresh_log.json           full run summary incl. diff object
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

WORKSPACE = "/home/user/workspace"
DASHBOARD_DIR = os.path.join(WORKSPACE, "gm-dashboard")
DATA_DIR = os.path.join(WORKSPACE, "data")

DASHBOARD_JSON = os.path.join(DASHBOARD_DIR, "data.json")
PREV_SNAPSHOT = os.path.join(DATA_DIR, "prev_data.json")
REFRESH_LOG = os.path.join(DATA_DIR, "refresh_log.json")

FIDE_ZIP_URL = "http://ratings.fide.com/download/standard_rating_list.zip"
FIDE_ZIP_PATH = os.path.join(DATA_DIR, "standard_rating_list.zip")
FIDE_TXT_PATH = os.path.join(DATA_DIR, "standard_rating_list.txt")

# Fixed-width column boundaries for the FIDE standard_rating_list.txt format.
# Verified against the July 2026 list header:
#   ID Number(0:15) Name(15:76) Fed(76:80) Sex(80:84) Tit(84:89)
#   WTit(89:94) OTit(94:109) FOA(109:113) <PERIOD>(113:119)
#   Gms(119:123) K(123:126) B-day(126:132) Flag(132:)
COL = {
    "id": (0, 15),
    "name": (15, 76),
    "fed": (76, 80),
    "sex": (80, 84),
    "tit": (84, 89),
    "wtit": (89, 94),
    "otit": (94, 109),
    "foa": (109, 113),
    "rating": (113, 119),
    "gms": (119, 123),
    "k": (123, 126),
    "bday": (126, 132),
    "flag": (132, 200),
}

# Manually curated overlays for grandmasters whose FIDE title record needs a
# correction the raw rating list won't reflect on its own (e.g. contested or
# administratively revoked titles). Extend this dict as needed.
REVOKED_TITLE_IDS = {
    "14129574": "Caught cheating with smartphone at 2024 Spanish Team Championship; 3-year ban",  # Shevchenko, Kirill (2025)
    "1201271": "Rating manipulation via fabricated tournament results",  # Crisan, Alexandru (2015)
    "13603078": "Caught cheating with smartphone at 2015 Dubai Open; IM title retained",  # Nigalidze, Gaioz (2015)
    "11600098": "Caught cheating with smartphone at 2019 Strasbourg Open",  # Kasimi, Isa (2019)
}


def log(msg):
    print(f"[refresh_dashboard] {msg}", flush=True)


def download_fide_list():
    """Download and unzip the latest FIDE standard rating list."""
    log("Downloading latest FIDE standard rating list...")
    result = subprocess.run(
        ["curl", "-sL", "-o", FIDE_ZIP_PATH, FIDE_ZIP_URL, "-w", "%{http_code}"],
        capture_output=True, text=True, timeout=120,
    )
    http_code = result.stdout.strip()
    if http_code != "200" or not os.path.exists(FIDE_ZIP_PATH):
        raise RuntimeError(f"FIDE download failed (HTTP {http_code})")

    subprocess.run(["unzip", "-o", FIDE_ZIP_PATH, "-d", DATA_DIR],
                    capture_output=True, text=True, check=True)

    if not os.path.exists(FIDE_TXT_PATH):
        # FIDE occasionally renames the inner file; find any .txt that was just extracted
        for fname in os.listdir(DATA_DIR):
            if fname.lower().endswith(".txt") and "rating" in fname.lower():
                shutil.move(os.path.join(DATA_DIR, fname), FIDE_TXT_PATH)
                break
    if not os.path.exists(FIDE_TXT_PATH):
        raise RuntimeError("Could not locate extracted FIDE rating list .txt file")

    log(f"Downloaded and extracted: {FIDE_TXT_PATH}")


def parse_fide_list():
    """Parse the fixed-width FIDE list, return dict of GM-titled players by id, plus rating_period."""
    with open(FIDE_TXT_PATH, encoding="latin-1") as f:
        lines = f.readlines()

    header = lines[0].rstrip("\n\r")
    # The rating column header is the period code itself, e.g. "JUL26"
    rating_period = header[COL["rating"][0]:COL["rating"][1]].strip()

    gms = {}
    for line in lines[1:]:
        if len(line) < COL["bday"][1]:
            continue
        tit = line[COL["tit"][0]:COL["tit"][1]].strip()
        if tit != "GM":
            continue

        pid = line[COL["id"][0]:COL["id"][1]].strip()
        name = line[COL["name"][0]:COL["name"][1]].strip()
        fed = line[COL["fed"][0]:COL["fed"][1]].strip()
        sex = line[COL["sex"][0]:COL["sex"][1]].strip()
        rating_raw = line[COL["rating"][0]:COL["rating"][1]].strip()
        gms_raw = line[COL["gms"][0]:COL["gms"][1]].strip()
        bday_raw = line[COL["bday"][0]:COL["bday"][1]].strip()

        try:
            rating = int(rating_raw) if rating_raw else None
        except ValueError:
            rating = None
        try:
            games = int(gms_raw) if gms_raw else 0
        except ValueError:
            games = 0
        try:
            bday = int(bday_raw) if bday_raw else None
        except ValueError:
            bday = None

        flag = line[COL["flag"][0]:COL["flag"][1]].strip() if len(line) > COL["flag"][0] else ""
        is_inactive_flag = "i" in flag.lower()

        gms[pid] = {
            "id": pid,
            "name": name,
            "fed": fed,
            "sex": sex,
            "rating": rating,
            "games": games,
            "bday": bday,
            # FIDE's own "inactive" flag is the authoritative signal for whether a
            # player is currently active on the circuit — NOT just "present in
            # this month's list". Long-retired legends (e.g. Kasparov) still
            # appear in the list with a carried-forward rating but are flagged
            # inactive by FIDE itself.
            "active": not is_inactive_flag,
        }

    return gms, rating_period


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def next_history_axis(old_axis, new_period):
    """Append the new rating period (e.g. '2026-07') to the quarterly history axis if not already present."""
    yy = new_period[3:5]
    mmm = new_period[0:3].upper()
    month_map = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05",
                 "JUN": "06", "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10",
                 "NOV": "11", "DEC": "12"}
    mm = month_map.get(mmm, "01")
    axis_label = f"20{yy}-{mm}"
    axis = list(old_axis)
    if not axis or axis[-1] != axis_label:
        axis.append(axis_label)
    return axis, axis_label


def merge_and_diff(old_data, fide_gms, rating_period):
    old_players = {p["id"]: p for p in old_data["players"]}
    fed_names = dict(old_data.get("fedNames", {}))

    new_history_axis, axis_label = next_history_axis(old_data.get("historyAxis", []), rating_period)

    new_players = []
    new_gms = []
    transfers = []
    deaths = []

    old_ids = set(old_players.keys())
    fide_ids = set(fide_gms.keys())

    # Players who dropped out of the current FIDE GM list this period.
    # We treat "vanished from list + no longer appears at all" as a possible
    # death signal only if FIDE's flag data marks them deceased elsewhere;
    # since the plain standard list doesn't carry a deceased flag directly,
    # we conservatively keep dropped players in the dataset (marked inactive)
    # rather than guessing they died. Existing 'deceased'/'deathYear' fields
    # already set in prior enrichment are preserved as-is.
    dropped_ids = old_ids - fide_ids

    for pid, fide_rec in fide_gms.items():
        if pid in old_players:
            player = dict(old_players[pid])  # copy existing enrichment (photo, style, bios, etc.)

            prev_fed = player.get("fed")
            new_fed = fide_rec["fed"] or prev_fed

            if prev_fed and new_fed and prev_fed != new_fed:
                fed_hist = list(player.get("fedHistory", [prev_fed]))
                if fed_hist[-1] != new_fed:
                    fed_hist.append(new_fed)
                fed_hist_names = [fed_names.get(f, f) for f in fed_hist]
                transfers.append({
                    "id": pid, "name": player.get("name", fide_rec["name"]),
                    "from": prev_fed, "to": new_fed,
                })
                player["prevFed"] = prev_fed
                player["prevFedName"] = fed_names.get(prev_fed, prev_fed)
                player["fedHistory"] = fed_hist
                player["fedHistoryNames"] = fed_hist_names

            player["fed"] = new_fed
            player["fedName"] = fed_names.get(new_fed, new_fed)
            player["rating"] = fide_rec["rating"] if fide_rec["rating"] is not None else player.get("rating")
            player["games"] = fide_rec["games"]
            if fide_rec["rating"] is not None:
                player["peak"] = max(player.get("peak", fide_rec["rating"]), fide_rec["rating"])
                hist = list(player.get("history", []))
                hist.append(fide_rec["rating"])
                player["history"] = hist
            # Respect FIDE's own inactive flag rather than assuming every
            # player present in this month's list is "active" — long-retired
            # legends (e.g. Kasparov) still appear with a carried-forward
            # rating but are flagged inactive by FIDE itself.
            player["active"] = fide_rec.get("active", True)

        else:
            # Brand new GM not in prior dataset — minimal enrichment (no photo/bio/style yet)
            player = {
                "id": pid,
                "name": fide_rec["name"],
                "fed": fide_rec["fed"],
                "fedName": fed_names.get(fide_rec["fed"], fide_rec["fed"]),
                "birthCountry": fide_rec["fed"],
                "birthCountryName": fed_names.get(fide_rec["fed"], fide_rec["fed"]),
                "prevFed": fide_rec["fed"],
                "prevFedName": fed_names.get(fide_rec["fed"], fide_rec["fed"]),
                "sex": fide_rec["sex"],
                "title": "GM",
                "wtit": "",
                "rating": fide_rec["rating"],
                "peak": fide_rec["rating"],
                "games": fide_rec["games"],
                "bday": fide_rec["bday"],
                "age": (datetime.now().year - fide_rec["bday"]) if fide_rec["bday"] else None,
                "active": fide_rec.get("active", True),
                "history": [fide_rec["rating"]] if fide_rec["rating"] is not None else [],
                "style": {},
                "birthCity": "",
                "photo": "",
                "deceased": False,
                "deathYear": None,
                "fedHistory": [fide_rec["fed"]],
                "fedHistoryNames": [fed_names.get(fide_rec["fed"], fide_rec["fed"])],
                "gmYear": datetime.now().year,
            }
            new_gms.append({"id": pid, "name": fide_rec["name"], "fed": fide_rec["fed"], "rating": fide_rec["rating"]})

        # Apply the manually curated revoked-title overlay using the dashboard's
        # own field convention (revoked / revokedYear / revokedReason), matching
        # app.js's rendering logic. This does not overwrite an existing revoked
        # entry's revokedYear if already set from prior enrichment.
        if pid in REVOKED_TITLE_IDS:
            player["revoked"] = True
            player["revokedReason"] = REVOKED_TITLE_IDS[pid]

        new_players.append(player)

    # Players present before but dropped from this period's GM list: keep them
    # (mark inactive) so history/bio/photo isn't lost; do not fabricate deaths.
    # IMPORTANT: this dataset is a historical almanac that deliberately
    # includes long-deceased grandmasters (e.g. Capablanca, Alekhine) who will
    # NEVER appear in FIDE's live list. Only report a death in the diff if the
    # player was NOT already marked deceased in the prior snapshot — i.e. this
    # is a newly-detected death, not a pre-existing historical entry.
    for pid in dropped_ids:
        player = dict(old_players[pid])
        was_already_deceased = bool(player.get("deceased"))
        was_already_revoked = bool(player.get("revoked"))
        player["active"] = False
        if not was_already_deceased and not was_already_revoked:
            # Newly dropped from the live list and not previously known deceased.
            # This is a signal worth flagging for manual review, but we do NOT
            # auto-mark deceased=True without a confirmed source — FIDE's
            # standard list alone doesn't distinguish "deceased" from "title
            # lapsed/administrative removal". Surface it in the diff so a human
            # (or a follow-up enrichment step) can confirm and backfill deathYear.
            deaths.append({
                "id": pid, "name": player.get("name"),
                "fed": player.get("fed"), "deathYear": player.get("deathYear"),
                "note": "newly absent from FIDE list this period — unconfirmed, needs manual verification",
            })
        new_players.append(player)

    new_players.sort(key=lambda p: (p.get("rating") or 0), reverse=True)

    new_data = {
        "ratingPeriod": rating_period,
        "historyAxis": new_history_axis,
        "players": new_players,
        "feds": sorted(set(p["fed"] for p in new_players if p.get("fed"))),
        "fedNames": fed_names,
    }

    diff = {
        "new_gms_count": len(new_gms),
        "transfers_count": len(transfers),
        "deaths_count": len(deaths),
        "new_gms": new_gms,
        "transfers": transfers,
        "deaths": deaths,
        "dropped_from_list_count": len(dropped_ids),
    }

    return new_data, diff


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DASHBOARD_DIR, exist_ok=True)

    errors = []

    try:
        download_fide_list()
    except Exception as e:
        errors.append(f"download_fide_list failed: {e}")
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    old_data = load_json(DASHBOARD_JSON)
    if old_data is None:
        errors.append(f"No existing baseline dataset found at {DASHBOARD_JSON}")
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    # Snapshot BEFORE overwrite
    save_json(PREV_SNAPSHOT, old_data)

    try:
        fide_gms, rating_period = parse_fide_list()
    except Exception as e:
        errors.append(f"parse_fide_list failed: {e}")
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    new_data, diff = merge_and_diff(old_data, fide_gms, rating_period)

    save_json(DASHBOARD_JSON, new_data)

    # Top 5 should reflect current active competitors, matching the site's
    # existing convention (e.g. Kasparov carries a high legacy rating but is
    # inactive and should not appear in "current top ratings").
    top5 = sorted(
        [p for p in new_data["players"] if p.get("rating") and p.get("active")],
        key=lambda p: p["rating"], reverse=True
    )[:5]

    summary = {
        "status": "ok" if not errors else "error",
        "rating_period": rating_period,
        "total_players_published": len(new_data["players"]),
        "active_gm_count": sum(1 for p in new_data["players"] if p.get("active")),
        "diff": diff,
        "top5": [{"name": p["name"], "rating": p["rating"]} for p in top5],
        "errors": errors,
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(REFRESH_LOG, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
