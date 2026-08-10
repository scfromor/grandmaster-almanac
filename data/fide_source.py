#!/usr/bin/env python3
"""
Resolve a reachable copy of the current FIDE standard rating list ZIP.

Why this exists
---------------
ratings.fide.com runs an IP-reputation firewall that accepts the TCP
connection from cloud/datacenter ranges and then RSTs the TLS ClientHello
(curl exit 35, "Recv failure: Connection reset by peer"). GitHub Actions
runners live in Azure and are affected, so the official host is simply not
reachable from CI most months. Verified again 2026-08-10.

Rather than requiring a human to mirror the file by hand every month, this
module walks an ordered chain of sources and returns the first one that
yields a byte-valid ZIP:

  1. GM_FIDE_LIST_URL         -- explicit operator override, always wins
  2. ratings.fide.com         -- the official host, in case the block lifts
  3. Wayback Machine replay   -- an existing archived snapshot of the ZIP
  4. Wayback Save Page Now    -- ask the Archive to fetch it fresh, then replay

Sources 3 and 4 work because the Internet Archive's crawler is not subject
to FIDE's datacenter block, and web.archive.org itself is reachable from CI.
The Archive rate-limits aggressively per client IP (HTTP 429 with header
`x-rl: 0`), so every Archive request uses exponential backoff.

Everything here is free: no proxy service, no VPS, no API keys.

Validation
----------
A 200 response is NOT sufficient. Rate-limit pages, Cloudflare interstitials
and Archive error pages are all served with 2xx in some paths, and the old
code happily wrote those to disk as "the rating list". Every candidate is
checked for the PK\\x03\\x04 local-file-header magic, a plausible size, and
at least one .txt member before being accepted.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import time
import urllib.parse
import zipfile

# A desktop Chrome UA. FIDE's block is IP-based so this does not defeat it,
# but the Archive and any operator-supplied mirror behave better with it.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# FIDE names monthly lists like standard_aug26frl.zip.
FIDE_HOST = "https://ratings.fide.com"
MONTH_ABBR = ("jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec")

# A ZIP smaller than this is certainly an error page, not ~1M rated players.
MIN_ZIP_BYTES = 500_000

# Archive politeness. The Archive returns 429 far more often than it returns
# the file on a busy shared IP, so we retry patiently rather than giving up.
ARCHIVE_ATTEMPTS = 5
ARCHIVE_BACKOFF_BASE = 8  # seconds; 8, 16, 32, 64, 128


def log(msg: str) -> None:
    print(f"[fide_source] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Month helpers
# ---------------------------------------------------------------------------

def month_code(when: _dt.date) -> str:
    """'aug26' for August 2026 -- the token FIDE embeds in list filenames."""
    return f"{MONTH_ABBR[when.month - 1]}{when.year % 100:02d}"


def candidate_months(today: _dt.date | None = None) -> list[_dt.date]:
    """This month first, then the two prior months.

    Early in a month FIDE may not have published yet, and a refresh can also
    be catching up after a failed window, so falling back to recent months
    keeps us moving instead of failing outright. check_freshness.py is the
    component that decides whether the result is new enough to ship.
    """
    today = today or _dt.date.today()
    out = [today.replace(day=1)]
    cursor = out[0]
    for _ in range(2):
        cursor = (cursor - _dt.timedelta(days=1)).replace(day=1)
        out.append(cursor)
    return out


def official_url(when: _dt.date) -> str:
    return f"{FIDE_HOST}/download/standard_{month_code(when)}frl.zip"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def looks_like_rating_zip(path: str) -> tuple[bool, str]:
    """True only for a real, readable rating-list ZIP.

    Guards against the failure mode where an HTML error page (Archive 429,
    Cloudflare 'Just a moment', nginx 500) is written to disk and then blows
    up much later during parsing with a confusing traceback.
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return False, f"cannot stat file: {exc}"

    if size < MIN_ZIP_BYTES:
        # Show the head so a human sees *what* came back instead of guessing.
        try:
            with open(path, "rb") as fh:
                head = fh.read(160)
        except OSError:
            head = b""
        printable = head.decode("utf-8", "replace").replace("\n", " ")[:120]
        return False, f"too small ({size} bytes); starts with: {printable!r}"

    with open(path, "rb") as fh:
        if fh.read(4) != b"PK\x03\x04":
            return False, "missing PK\\x03\\x04 ZIP magic (not a ZIP)"

    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad is not None:
                return False, f"corrupt ZIP member: {bad}"
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        return False, f"unreadable ZIP: {exc}"

    if not any(n.lower().endswith(".txt") for n in names):
        return False, f"no .txt member; contains {names[:5]}"

    return True, f"ok ({size} bytes, members={names[:3]})"


# ---------------------------------------------------------------------------
# Fetch primitive
# ---------------------------------------------------------------------------

def fetch(url: str, dest: str, timeout: int = 300) -> tuple[bool, str]:
    """curl `url` to `dest`. Returns (ok, detail). Never raises."""
    if os.path.exists(dest):
        os.remove(dest)
    cmd = [
        "curl", "-sS", "-L", "-o", dest, url,
        "-A", UA,
        "-H", "Accept: application/zip,application/octet-stream,*/*",
        "--connect-timeout", "30",
        "--max-time", str(timeout),
        "-w", "%{http_code}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        return False, "curl wall-clock timeout"

    code = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    code = code[0]
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().replace("\n", " ")[:200]
        return False, f"curl exit {proc.returncode} ({stderr})"
    if code != "200":
        return False, f"HTTP {code}"
    return True, f"HTTP 200"


# ---------------------------------------------------------------------------
# Source 3: existing Wayback snapshot
# ---------------------------------------------------------------------------

def wayback_lookup(target_url: str) -> str | None:
    """Ask the availability API for the closest snapshot of target_url.

    Returns a raw-bytes replay URL (the `id_` modifier suppresses the
    Archive's HTML rewriting so we get the original ZIP octets) or None.
    """
    api = ("https://archive.org/wayback/available?url="
           + urllib.parse.quote(target_url, safe=""))
    for attempt in range(1, ARCHIVE_ATTEMPTS + 1):
        tmp = "/tmp/_wb_avail.json"
        ok, detail = fetch(api, tmp, timeout=60)
        if ok:
            try:
                with open(tmp, encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                log(f"  availability API returned unparseable JSON: {exc}")
                return None
            snap = (payload.get("archived_snapshots") or {}).get("closest") or {}
            if snap.get("available") and snap.get("timestamp"):
                ts = snap["timestamp"]
                return f"https://web.archive.org/web/{ts}id_/{target_url}"
            log("  no snapshot on record")
            return None
        log(f"  availability attempt {attempt}/{ARCHIVE_ATTEMPTS}: {detail}")
        if attempt < ARCHIVE_ATTEMPTS:
            time.sleep(ARCHIVE_BACKOFF_BASE * (2 ** (attempt - 1)))
    return None


def try_wayback(target_url: str, dest: str) -> bool:
    replay = wayback_lookup(target_url)
    if not replay:
        return False
    log(f"  snapshot: {replay}")
    for attempt in range(1, ARCHIVE_ATTEMPTS + 1):
        ok, detail = fetch(replay, dest)
        if ok:
            valid, why = looks_like_rating_zip(dest)
            if valid:
                log(f"  archived copy validated: {why}")
                return True
            log(f"  archived copy rejected: {why}")
            # A 429 HTML body is retryable; a genuinely bad archive is not.
            if "too small" not in why:
                return False
        else:
            log(f"  replay attempt {attempt}/{ARCHIVE_ATTEMPTS}: {detail}")
        if attempt < ARCHIVE_ATTEMPTS:
            time.sleep(ARCHIVE_BACKOFF_BASE * (2 ** (attempt - 1)))
    return False


# ---------------------------------------------------------------------------
# Source 4: Save Page Now
# ---------------------------------------------------------------------------

def try_save_page_now(target_url: str, dest: str) -> bool:
    """Ask the Archive to crawl target_url now, then replay it.

    The Archive's crawler reaches FIDE fine; we are only using it as a
    free fetch-on-behalf-of service. SPN is slow and heavily rate limited,
    so this is the last resort and its failure is not fatal.
    """
    log(f"  requesting fresh archive of {target_url}")
    ok, detail = fetch(f"https://web.archive.org/save/{target_url}",
                       "/tmp/_spn_out", timeout=240)
    if not ok:
        log(f"  Save Page Now failed: {detail}")
        return False
    # SPN is asynchronous for large binaries; give the write time to land.
    log("  save requested; waiting 45s for the snapshot to become replayable")
    time.sleep(45)
    return try_wayback(target_url, dest)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def resolve(dest: str) -> tuple[str, str]:
    """Fetch a valid rating-list ZIP to `dest`.

    Returns (source_label, url). Raises RuntimeError if every source fails.
    """
    attempts: list[str] = []

    # 1. Operator override wins outright.
    override = (os.environ.get("GM_FIDE_LIST_URL") or "").strip()
    if override:
        log(f"GM_FIDE_LIST_URL override: {override}")
        ok, detail = fetch(override, dest)
        if ok:
            valid, why = looks_like_rating_zip(dest)
            if valid:
                log(f"override accepted: {why}")
                return "override", override
            attempts.append(f"override -> {why}")
            log(f"override rejected: {why}")
        else:
            attempts.append(f"override -> {detail}")
            log(f"override fetch failed: {detail}")

    months = candidate_months()

    # 2. Official host. Cheap to try and instantly correct if the block lifts.
    for when in months:
        url = official_url(when)
        log(f"official host: {url}")
        ok, detail = fetch(url, dest, timeout=180)
        if ok:
            valid, why = looks_like_rating_zip(dest)
            if valid:
                log(f"official download accepted: {why}")
                return "fide", url
            attempts.append(f"fide {month_code(when)} -> {why}")
        else:
            attempts.append(f"fide {month_code(when)} -> {detail}")
            log(f"  unreachable: {detail}")
            # A TLS reset is the IP block; it will fail identically for every
            # month, so stop hammering it and move to the Archive.
            if "exit 35" in detail or "exit 7" in detail or "exit 28" in detail:
                log("  datacenter-IP block signature; skipping remaining months")
                break

    # 3. Existing Archive snapshots, newest month first.
    for when in months:
        url = official_url(when)
        log(f"Wayback snapshot for {month_code(when)}")
        if try_wayback(url, dest):
            return "wayback", url
        attempts.append(f"wayback {month_code(when)} -> no usable snapshot")

    # 4. Ask the Archive to fetch this month's file on our behalf.
    newest = official_url(months[0])
    log(f"Save Page Now for {month_code(months[0])}")
    if try_save_page_now(newest, dest):
        return "wayback-spn", newest
    attempts.append(f"spn {month_code(months[0])} -> failed")

    raise RuntimeError(
        "Could not obtain a valid FIDE rating list from any source.\n  "
        + "\n  ".join(attempts)
        + "\n\nTo refresh manually: download the current standard list from "
          "https://ratings.fide.com/download_lists.phtml on a residential "
          "connection, host it anywhere reachable, and re-run this workflow "
          "with the list_url input set to that URL."
    )


def main() -> int:
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/fide_list.zip"
    try:
        source, url = resolve(dest)
    except RuntimeError as exc:
        log(f"FAILED: {exc}")
        return 1
    log(f"SUCCESS via {source}: {url} -> {dest}")
    print(json.dumps({"source": source, "url": url, "path": dest}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
