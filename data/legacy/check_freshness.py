#!/usr/bin/env python3
"""
Grandmaster Almanac — data freshness guard.

Background
----------
The 2026-08-03 scheduled run reported SUCCESS while publishing stale JUL26
data. The refresh step is `continue-on-error` and exits 0 on every path, so a
total FIDE outage was indistinguishable from a clean run: green check, no
email, and a commit message that read "Monthly refresh + page rebuild: JUL26"
because the period was read back out of a *stale* refresh_log.json.

This script is the thing that makes that impossible. It compares the rating
period actually committed in gm-dashboard/data.json against the period we
expect to be live right now, and exits non-zero if we are behind.

Modes
-----
  --check    Exit 0 if data.json is current, 1 if stale. Always prints a
             one-line verdict. Used to FAIL the job after a refresh attempt.

  --is-current
             Same comparison, but prints "yes"/"no" to stdout and always
             exits 0. Used by the catch-up schedule to skip as a cheap no-op
             on days when the data is already up to date.

Expected period
---------------
FIDE publishes the new standard list on the 1st of each month. Before the 3rd
we tolerate the previous month still being current (the list may not have
landed yet); from the 3rd onward the current month is required.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.environ.get("GM_ALMANAC_ROOT") or os.path.dirname(SCRIPT_DIR)
DASHBOARD_JSON = os.path.join(WORKSPACE, "gm-dashboard", "data.json")

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def period_code(dt):
    """datetime -> FIDE period code, e.g. 'AUG26'."""
    return f"{MONTHS[dt.month - 1]}{dt.year % 100:02d}"


def previous_period(dt):
    year, month = (dt.year - 1, 12) if dt.month == 1 else (dt.year, dt.month - 1)
    return f"{MONTHS[month - 1]}{year % 100:02d}"


def acceptable_periods(now):
    """Periods we're willing to call 'current' as of `now`."""
    current = period_code(now)
    # Grace window: on the 1st and 2nd, FIDE may not have published yet, so
    # last month's list is still legitimately the newest one available.
    if now.day < 3:
        return {current, previous_period(now)}
    return {current}


def read_committed_period():
    if not os.path.exists(DASHBOARD_JSON):
        return None, f"data.json not found at {DASHBOARD_JSON}"
    try:
        with open(DASHBOARD_JSON, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"could not read data.json: {exc}"
    period = (data.get("ratingPeriod") or "").strip().upper()
    if not period:
        return None, "data.json has no ratingPeriod field"
    return period, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--is-current", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    expected = acceptable_periods(now)
    period, err = read_committed_period()

    if args.is_current:
        # Never fail this mode — a read error just means "not provably
        # current", so the caller should go ahead and run the refresh.
        print("yes" if (period and period in expected) else "no")
        return 0

    expected_str = " or ".join(sorted(expected))

    if err:
        print(f"::error::Freshness check failed — {err}")
        return 1

    if period in expected:
        print(f"Data is current: data.json ratingPeriod={period} (expected {expected_str})")
        return 0

    print(
        f"::error::STALE DATA — data.json ratingPeriod={period}, expected {expected_str}. "
        "The FIDE refresh did not produce a new rating list, so the site would "
        "publish last month's ratings. Failing the job instead of deploying stale data."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
