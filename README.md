# Grandmaster Almanac

A chess dashboard listing all FIDE grandmasters (active, inactive, deceased, and
title-revoked), with ratings history, federation transfer tracking, and photo/bio
enrichment sourced from Wikipedia.

## Structure

- `gm-dashboard/` — the static site (`index.html`, `app.js`, `style.css`, `data.json`)
  deployed to the live pplx.app URL.
- `data/refresh_dashboard.py` — the monthly refresh script. Downloads the latest
  FIDE standard rating list, merges it into `gm-dashboard/data.json` while
  preserving existing enrichment (photos, bios, play-style tags, history), and
  computes a diff of new GMs / federation transfers / possible deaths since the
  last run.

## Monthly refresh

Run:

```bash
python3 data/refresh_dashboard.py
```

This will:
1. Download the latest FIDE standard rating list.
2. Snapshot the current `gm-dashboard/data.json` to `data/prev_data.json`.
3. Re-parse, re-merge, and apply known federation-transfer / revoked-title overlays.
4. Write a fresh `gm-dashboard/data.json` and a `data/refresh_log.json` summary.

Known revoked GM titles are hardcoded in `REVOKED_TITLE_IDS` inside the script —
extend that dict if FIDE strips another title.

## Why this repo exists

The refresh script previously lived only inside a single AI agent sandbox with no
backup. That sandbox expired, which meant the monthly automation silently failed
with nothing to fall back on. This repo is the durable backup: the dashboard site,
the enriched dataset, and the refresh script all now live here so a lost sandbox
can never wipe out the project again.
