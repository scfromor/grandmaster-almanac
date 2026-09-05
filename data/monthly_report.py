#!/usr/bin/env python3
"""
Monthly roster drift report for the Grandmaster Almanac.

This does NOT touch the website. It only compares data/roster.csv against
FIDE's current title list and prints what a human should consider editing.
The site is built from roster.csv by hand; this script just tells you what
changed so you know which rows to look at.

Output is JSON on stdout:

    {
      "ok": true,
      "period": "SEP26",
      "source": "direct" | "wayback" | "wayback-old",
      "roster_count": 2164,
      "fide_gm_count": 1789,
      "new_gms":      [ {id, name, fed, sex, bday}, ... ],
      "missing":      [ {id, name, fed} ],
      "fed_changes":  [ {id, name, from, to} ],
      "title_lost":   [ {id, name, now} ],
      "warnings":     [ "..." ]
    }

On failure it still prints valid JSON with "ok": false and an "error", so a
caller can report the failure instead of crashing.

Usage:
    python3 monthly_report.py                 # uses ./roster.csv or ../data/roster.csv
    python3 monthly_report.py --roster URL_OR_PATH
    python3 monthly_report.py --period SEP26
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import subprocess
import sys
import urllib.request
import zipfile

TIMEOUT = 180
UA = "Mozilla/5.0 (compatible; grandmaster-almanac-report/1.0)"

RAW_ROSTER = (
    "https://raw.githubusercontent.com/scfromor/"
    "grandmaster-almanac/master/data/roster.csv"
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def period_label(d: dt.date) -> str:
    return d.strftime("%b%y").lower()


def candidate_periods(today: dt.date) -> list[str]:
    """Current month first, then the two before it."""
    out, d = [], today.replace(day=1)
    for _ in range(3):
        out.append(period_label(d))
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return out


def _get(url: str, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_list(period: str, warnings: list[str]) -> tuple[bytes, str] | tuple[None, None]:
    """
    Try to get the FIDE standard rating list ZIP for `period`.

    Order matters. FIDE blocks many datacenter IPs, so a direct hit may fail
    even though the file exists. The Internet Archive is used as a fallback,
    and Save Page Now is asked to create a snapshot if none exists yet.
    """
    url = f"https://ratings.fide.com/download/standard_{period}frl.zip"

    # 1. Straight from FIDE.
    try:
        data = _get(url)
        if data[:2] == b"PK":
            return data, "direct"
        warnings.append("FIDE returned a non-ZIP response; falling back to the archive.")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Direct FIDE download failed ({type(e).__name__}); trying the archive.")

    # 2. An existing Wayback snapshot of THIS month.
    try:
        meta = json.loads(_get(f"https://archive.org/wayback/available?url={url}", 60))
        snap = meta.get("archived_snapshots", {}).get("closest") or {}
        if snap.get("available"):
            data = _get(f"https://web.archive.org/web/{snap['timestamp']}id_/{url}")
            if data[:2] == b"PK":
                return data, "wayback"
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Wayback lookup failed ({type(e).__name__}).")

    # 3. Ask the Archive to fetch it now. The Archive's crawler is not blocked
    #    by FIDE, so this usually succeeds where a direct download does not.
    try:
        subprocess.run(
            ["curl", "-sS", "--max-time", "180", "-o", "/dev/null",
             f"https://web.archive.org/save/{url}"],
            check=False,
        )
        meta = json.loads(_get(f"https://archive.org/wayback/available?url={url}", 60))
        snap = meta.get("archived_snapshots", {}).get("closest") or {}
        if snap.get("available"):
            data = _get(f"https://web.archive.org/web/{snap['timestamp']}id_/{url}")
            if data[:2] == b"PK":
                return data, "wayback"
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Save Page Now failed ({type(e).__name__}).")

    return None, None


def parse_fide(zip_bytes: bytes) -> tuple[list[dict], str]:
    """
    Parse the fixed-width FIDE list.

    Column offsets are derived from the header line rather than hardcoded,
    because FIDE has shifted them before when adding columns.
    """
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    name = next((n for n in zf.namelist() if n.lower().endswith(".txt")), None)
    if not name:
        raise ValueError(f"no .txt inside the archive (members: {zf.namelist()})")

    with zf.open(name) as fh:
        raw = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        header = raw.readline().rstrip("\n")

        def start(label: str) -> int:
            i = header.find(label)
            if i < 0:
                raise ValueError(f"column {label!r} missing from FIDE header")
            return i

        cuts = sorted({
            start("ID Number"), start("Name"), start("Fed"), start("Sex"),
            start("Tit"), start("WTit"), start("OTit"),
        })
        i_id, i_name, i_fed, i_sex, i_tit = cuts[0], cuts[1], cuts[2], cuts[3], cuts[4]
        i_wtit = cuts[5]
        m = re.search(r"\b([A-Z]{3}\d{2})\b", header)
        period = m.group(1) if m else "?"

        bday_i = header.find("B-day")
        rows = []
        for line in raw:
            if not line.strip():
                continue
            fid = line[i_id:i_name].strip()
            if not fid:
                continue
            bday = ""
            if bday_i >= 0:
                mb = re.search(r"\b(1[89]\d{2}|20\d{2})\b", line[bday_i - 4:])
                bday = mb.group(1) if mb else ""
            rows.append({
                "id": fid,
                "name": line[i_name:i_fed].strip(),
                "fed": line[i_fed:i_sex].strip(),
                "sex": line[i_sex:i_tit].strip(),
                "tit": line[i_tit:i_wtit].strip(),
                "bday": bday,
            })
    return rows, period


def load_roster(src: str) -> list[dict]:
    if src.startswith(("http://", "https://")):
        text = _get(src, 120).decode("utf-8")
    else:
        text = open(src, encoding="utf-8").read()
    return list(csv.DictReader(io.StringIO(text)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default=RAW_ROSTER)
    ap.add_argument("--period", default=None)
    args = ap.parse_args()

    warnings: list[str] = []
    result: dict = {"ok": False, "generatedAt": dt.datetime.now(dt.UTC).isoformat()}

    try:
        roster = load_roster(args.roster)
        by_id = {r["id"].strip(): r for r in roster if r.get("id", "").strip()}

        periods = [args.period.lower()] if args.period else candidate_periods(dt.date.today())
        zip_bytes = source = used = None
        for i, p in enumerate(periods):
            zip_bytes, source = fetch_list(p, warnings)
            if zip_bytes:
                used = p
                if i > 0:
                    source = "wayback-old"
                    warnings.append(
                        f"Could not get the current list; fell back to {p.upper()}."
                    )
                break

        if not zip_bytes:
            result["error"] = (
                "Could not download the FIDE title list from FIDE directly or "
                "from the Internet Archive."
            )
            result["warnings"] = warnings
            print(json.dumps(result, indent=2))
            return 1

        fide_rows, period = parse_fide(zip_bytes)
        gms = {r["id"]: r for r in fide_rows if r["tit"] == "GM"}
        all_fide = {r["id"]: r for r in fide_rows}

        new_gms = [
            {"id": i, "name": g["name"], "fed": g["fed"], "sex": g["sex"], "bday": g["bday"]}
            for i, g in sorted(gms.items()) if i not in by_id
        ]

        # Players on the site that FIDE no longer lists at all. FIDE removes
        # entries some time after a death, so this is the main death signal --
        # but it also catches ID changes, so it is a prompt to check, not a
        # fact to act on blindly.
        missing = [
            {"id": i, "name": r["name"], "fed": r["fed"]}
            for i, r in sorted(by_id.items())
            if i not in all_fide and r.get("deceased", "").lower() != "true"
        ]

        def living(r: dict) -> bool:
            return r.get("deceased", "").strip().lower() != "true"

        # Deceased players are excluded from the two checks below. FIDE
        # re-codes historic federations (URS -> LAT, YUG -> SRB) and drops the
        # title field for long-dead players, which generated ~20 rows of noise
        # a month about people who died decades ago.
        fed_changes = [
            {"id": i, "name": r["name"], "from": r["fed"], "to": all_fide[i]["fed"]}
            for i, r in sorted(by_id.items())
            if living(r) and i in all_fide and all_fide[i]["fed"]
            and r["fed"] != all_fide[i]["fed"]
        ]

        title_lost = [
            {"id": i, "name": r["name"], "now": all_fide[i]["tit"] or "(none)"}
            for i, r in sorted(by_id.items())
            if living(r) and i in all_fide and all_fide[i]["tit"] != "GM"
            and r.get("revoked", "").strip().lower() != "true"
        ]

        result.update({
            "ok": True,
            "period": period,
            "period_requested": (used or "").upper(),
            "source": source,
            "roster_count": len(by_id),
            "fide_gm_count": len(gms),
            "new_gms": new_gms,
            "missing": missing,
            "fed_changes": fed_changes,
            "title_lost": title_lost,
            "warnings": warnings,
        })
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        result["warnings"] = warnings
        print(json.dumps(result, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
