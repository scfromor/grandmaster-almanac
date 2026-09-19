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
import concurrent.futures as cf
import csv
import datetime as dt
import io
import json
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
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



# ---------------------------------------------------------------------------
# Profile-link checking
# ---------------------------------------------------------------------------
#
# Only SIX of the ten link platforms can be checked from a server. The rest
# answer identically for a real page and a nonsense one, so any "dead link"
# we reported for them would be a coin toss. Measured from this sandbox with
# a known-good and a known-bad URL for each platform:
#
#   chesscom        good 200   bad 404   -> usable
#   chesscomPlayer  good 200   bad 404   -> usable
#   chessgames      good 200   bad 404   -> usable
#   lichess         good 200   bad 404   -> usable
#   x               good 200   bad 404   -> usable
#   website         good 200   bad DNS failure -> usable
#
#   facebook        good 400   bad 400   -> UNUSABLE (blocks all bots)
#   instagram       good 200   bad 200   -> UNUSABLE (login wall answers 200)
#   youtube         good 200   bad 200   -> UNUSABLE (consent page answers 200)
#   twitch          good 200   bad 200   -> UNUSABLE (app shell answers 200)
#
# Facebook is the important one: every facebook.com request returns HTTP 400
# to an automated client while the page is perfectly alive in a browser. A
# naive checker reports all 69 Facebook links as dead, every month, forever.
# We never flag those four platforms — we report them as unchecked instead.

CHECKABLE = ("chesscom", "chesscomPlayer", "chessgames", "lichess", "x", "website")
UNCHECKABLE = {
    "facebook": "returns HTTP 400 to all automated requests",
    "instagram": "login wall answers 200 for missing profiles",
    "youtube": "consent page answers 200 for missing channels",
    "twitch": "app shell answers 200 for missing channels",
}

LINK_TEMPLATES = {
    "chesscom": "https://www.chess.com/member/{}",
    "chesscomPlayer": "https://www.chess.com/players/{}",
    "chessgames": "https://www.chessgames.com/perl/chessplayer?pid={}",
    "lichess": "https://lichess.org/@/{}",
    "x": "https://x.com/{}",
}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# How many links of each platform to check per month.
#
# These are sized by measured rot rate, not by how many links exist. A full
# audit of the whole set found:
#
#   website          18.3% dead   user-owned domain      -> rots
#   lichess          16.7% dead   user-chosen handle     -> rots
#   x                 8.2% dead   user-chosen handle     -> rots
#   chesscom          3.2% dead   user-chosen handle     -> rots slowly
#   chesscomPlayer    0.2% dead   site-assigned slug     -> stable
#   chessgames        0.0% dead   site-assigned id       -> stable
#
# Handles people choose get renamed and abandoned; ids a site assigns do not.
# The two stable platforms are also the two largest (3,862 of 5,585 links) and
# the two that rate-limit hardest, so checking them in bulk burned most of the
# monthly budget to find almost nothing. They now get a small canary sample
# that would still catch a site-wide URL change, and the volatile platforms
# get full or near-full coverage every month.
PLATFORM_BUDGET = {
    "website": 90,          # all of them
    "x": 190,               # all of them
    "lichess": 200,         # ~1.6 month cycle
    "chesscom": 300,        # ~4 month cycle
    "chesscomPlayer": 80,   # canary only
    "chessgames": 80,       # canary only
}
SAMPLE_SIZE = sum(PLATFORM_BUDGET.values())


def link_url(column: str, value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if column == "website":
        return value
    return LINK_TEMPLATES[column].format(value)


def probe(url: str, timeout: int = 20) -> tuple[str, str]:
    """Return (verdict, detail). Verdict is 'alive', 'dead' or 'unknown'.

    'unknown' is the safe default and covers rate limiting, server errors and
    timeouts. Only an explicit 404/410, or a DNS failure on a personal
    website, is ever treated as dead.
    """
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return "alive", f"{resp.status}"
        except urllib.error.HTTPError as e:
            # Some servers reject HEAD but serve GET, so retry before judging.
            if method == "HEAD" and e.code in (400, 403, 405, 501):
                continue
            if e.code in (404, 410):
                return "dead", f"HTTP {e.code}"
            if e.code == 429:
                return "unknown", "rate limited (HTTP 429)"
            return "unknown", f"HTTP {e.code}"
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, socket.gaierror):
                return "dead", "domain does not resolve"
            if method == "HEAD":
                continue
            return "unknown", f"{type(reason).__name__}"
        except Exception as e:  # noqa: BLE001
            if method == "HEAD":
                continue
            return "unknown", f"{type(e).__name__}"
    return "unknown", "no response"


def check_links(roster: list[dict], today: dt.date,
                warnings: list[str], sample_size: int = SAMPLE_SIZE) -> dict:
    targets = []
    unchecked_counts = {k: 0 for k in UNCHECKABLE}
    for r in roster:
        for col in UNCHECKABLE:
            if (r.get(col) or "").strip():
                unchecked_counts[col] += 1
        for col in CHECKABLE:
            url = link_url(col, r.get(col, ""))
            if url:
                targets.append({"id": r.get("id", ""), "name": r.get("name", ""),
                                "column": col, "url": url})

    total = len(targets)
    if not total:
        return {"checked": 0, "total_links": 0, "dead": [], "unchecked": unchecked_counts}

    # Deterministic rotating window, taken PER PLATFORM so a big stable
    # platform cannot crowd out a small volatile one. Each slice advances every
    # month and wraps, so every link is eventually visited without ever
    # checking all of them at once. Sorting first keeps the walk stable.
    month_index = today.year * 12 + today.month
    scale = sample_size / SAMPLE_SIZE if SAMPLE_SIZE else 1.0
    window = []
    for col, budget in PLATFORM_BUDGET.items():
        pool = sorted((t for t in targets if t["column"] == col),
                      key=lambda t: t["id"])
        if not pool:
            continue
        take = min(len(pool), max(1, round(budget * scale)))
        start = (month_index * take) % len(pool)
        window.extend(pool[(start + i) % len(pool)] for i in range(take))

    # Per-host pacing, measured rather than guessed. A full-speed sweep of all
    # 5,585 links returned HTTP 429 for 1,826 Chess.com and 1,782 Chessgames
    # requests; at these intervals the same hosts answer cleanly. Rate-limited
    # requests are never counted as dead, so the cost of pacing too fast is a
    # wasted month of coverage rather than a wrong answer.
    HOST_DELAY = {
        "www.chess.com": 1.3,
        "www.chessgames.com": 1.3,
        "lichess.org": 1.0,
    }
    lock = threading.Lock()
    last_hit: dict[str, float] = {}

    def polite(target):
        host = urllib.parse.urlsplit(target["url"]).netloc
        delay = HOST_DELAY.get(host, 0.4)
        with lock:
            wait = last_hit.get(host, 0.0) + delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            last_hit[host] = time.monotonic()
        verdict, detail = probe(target["url"])
        return target, verdict, detail

    suspects, rate_limited, unknown = [], 0, 0
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for target, verdict, detail in pool.map(polite, window):
            if verdict == "dead":
                suspects.append((target, detail))
            elif verdict == "unknown":
                unknown += 1
                if "429" in detail:
                    rate_limited += 1

    # Second pass. A single 404 can come from a blip or a redirect loop, and a
    # false "this link is dead" costs him a pointless manual check. Anything
    # reported has failed twice, a few seconds apart.
    dead = []
    for target, first_detail in suspects:
        time.sleep(1.5)
        verdict, detail = probe(target["url"])
        if verdict == "dead":
            dead.append({**target, "status": detail})
    dead.sort(key=lambda d: (d["column"], d["name"]))

    if rate_limited:
        warnings.append(
            f"{rate_limited} link checks hit a rate limit and were skipped, not flagged."
        )
    return {
        "checked": len(window),
        "total_links": total,
        "checked_by_platform": {c: sum(1 for w in window if w["column"] == c)
                                for c in CHECKABLE},
        "dead": dead,
        "rechecked": len(suspects),
        "inconclusive": unknown,
        "unchecked": unchecked_counts,
        "unchecked_reasons": UNCHECKABLE,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roster", default=RAW_ROSTER)
    ap.add_argument("--period", default=None)
    ap.add_argument("--links", type=int, default=SAMPLE_SIZE,
                    help="How many profile links to check. 0 disables the check.")
    args = ap.parse_args()

    warnings: list[str] = []
    result: dict = {"ok": False, "generatedAt": dt.datetime.now(dt.UTC).isoformat()}

    try:
        roster = load_roster(args.roster)
        by_id = {r["id"].strip(): r for r in roster if r.get("id", "").strip()}

        # Run this FIRST and independently of FIDE. The FIDE download is the
        # fragile part of this script; the link check needs none of it, so a
        # failed title-list fetch must not also cost him the link report.
        link_report: dict = {"checked": 0, "skipped": "disabled"}
        if args.links > 0:
            try:
                link_report = check_links(roster, dt.date.today(), warnings,
                                          sample_size=args.links)
            except Exception as e:  # noqa: BLE001
                link_report = {"checked": 0, "error": f"{type(e).__name__}: {e}"}
                warnings.append(f"Link check failed ({type(e).__name__}).")

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
            result["link_check"] = link_report
            result["warnings"] = warnings
            print(json.dumps(result, indent=2, ensure_ascii=False))
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
            "link_check": link_report,
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
