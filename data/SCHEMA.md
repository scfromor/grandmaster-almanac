# Grandmaster Almanac — data contract (post-ratings redesign, Sept 2026)

## Why this changed

The site used to rebuild itself every month from FIDE's published rating list.
FIDE blocks datacenter IPs, GitHub Actions runs on datacenter IPs, and the
workarounds (Internet Archive replay, Save Page Now) were unreliable enough
that the site silently served stale data twice. Ratings are now removed
entirely and the roster is a hand-maintained CSV.

**`data/roster.csv` is the single source of truth.** Editing it on GitHub
triggers a rebuild and deploy. Nothing fetches FIDE at build time. Ever.

## `data/roster.csv` columns

| column | type | required | notes |
|---|---|---|---|
| `id` | string | yes | FIDE ID. Unique. Primary key. |
| `name` | string | yes | `Surname, Forename` — the comma matters for display splitting. |
| `fed` | 3-letter code | yes | Current federation. Must exist in `FED_NAMES`. |
| `birthCountry` | 3-letter code | no | Blank allowed. |
| `sex` | `M` / `F` | yes | |
| `title` | string | yes | Normally `GM`. |
| `wtit` | string | no | Women's title, e.g. `WGM`. |
| `bday` | integer year | no | e.g. `1990`. Blank if unknown. |
| `birthCity` | string | no | |
| `gmYear` | integer year | no | Year the GM title was awarded. |
| `deceased` | `true`/`false` | yes | |
| `deathYear` | integer year | no | Only meaningful when `deceased` is true. |
| `revoked` | `true`/`false` | yes | FIDE stripped the title. Replaces the old rating-derived status. |
| `revokedYear` | integer year | no | |
| `revokedReason` | string | no | Shown as a note on the player card. |
| `photo` | URL | no | Usually Wikimedia Commons. |
| `photoSource` | URL | no | Attribution link for the photo. |
| `bio` | string | no | One or two sentences. Quote if it contains commas. |
| `bioSource` | URL | no | Attribution link for the bio. |
| `fedHistory` | pipe-separated codes | no | e.g. `RUS\|FID\|RUS`. Oldest first. |
| `style_aggressive` | int 15–95 | no | Playstyle radar axis. |
| `style_defense` | int 15–95 | no | |
| `style_endgame` | int 15–95 | no | |
| `style_opening` | int 15–95 | no | |
| `style_positional` | int 15–95 | no | |
| `style_tactical` | int 15–95 | no | |

Style axes were originally estimated from rating. That model is gone, so the
values are now **static data**: they are preserved as-is for existing players
and left blank for anyone added later. A player with blank style renders
without a radar chart rather than with a broken one.

## `gm-dashboard/data.json` (build output — do not edit by hand)

```jsonc
{
  "generatedAt": "2026-09-05T14:12:00Z",
  "source": "data/roster.csv",
  "playerCount": 2164,
  "players": [
    {
      "id": "1503014",
      "name": "Carlsen, Magnus",
      "fed": "NOR",
      "fedName": "Norway",              // derived from fed
      "birthCountry": "NOR",
      "birthCountryName": "Norway",     // derived
      "prevFed": "NOR",                 // derived: second-to-last fedHistory entry
      "prevFedName": "Norway",          // derived
      "sex": "M",
      "title": "GM",
      "wtit": "",
      "bday": 1990,
      "age": 36,                        // derived from bday at build time
      "birthCity": "Tønsberg",
      "gmYear": 2004,
      "deceased": false,
      "deathYear": null,
      "revoked": false,
      "revokedYear": null,
      "revokedReason": "",
      "photo": "https://upload.wikimedia.org/...",
      "bio": "...",
      "fedHistory": ["NOR"],
      "fedHistoryNames": ["Norway"],    // derived
      "style": { "aggressive": 78, "defense": 85, "endgame": 95,
                 "opening": 70, "positional": 92, "tactical": 88 }
    }
  ],
  "feds": ["NOR", "USA", ...],          // sorted unique federation codes present
  "fedNames": { "NOR": "Norway", ... }
}
```

### Fields deliberately REMOVED

`ratingPeriod`, `historyAxis`, and per-player `rating`, `peak`, `history`,
`games`, `active`. Nothing in the frontend may reference these. A player's
strength is no longer represented anywhere on the site.

`active` is replaced by `deceased` and `revoked`, which are facts about the
player rather than facts about a monthly rating list. `revoked` already
existed in the dataset and keeps its name and its companion fields
(`revokedYear`, `revokedReason`) so the existing player-card rendering keeps
working untouched.

`bioFull` and `titleYearRevoked` are also dropped: nothing in the frontend
read them, and they duplicated `bio` and `revokedYear` respectively.
