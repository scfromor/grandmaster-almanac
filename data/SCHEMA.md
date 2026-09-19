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
| `chesscom` | handle | no | Chess.com member account. |
| `chesscomPlayer` | slug | no | Chess.com editorial player page. |
| `lichess` | handle | no | Lichess username. |
| `chessgames` | numeric id | no | Chessgames.com player id. |
| `website` | full URL | no | Personal or official site. Store the whole URL. |
| `x` | handle | no | X / Twitter, without the `@`. |
| `instagram` | handle | no | |
| `youtube` | channel id or handle | no | `UC…` channel id, or `@handle`. |
| `twitch` | handle | no | |
| `facebook` | page name | no | The part after `facebook.com/`. |

### Link columns: store handles, not URLs

Every link column except `website` holds a **bare handle or id**, never a
pasted URL. The build assembles the URL from a fixed template, so a stored
handle stays correct if a platform changes its URL shape, and the same value
cannot be written two different ways.

| Column | URL built |
| --- | --- |
| `chesscom` | `https://www.chess.com/member/{handle}` |
| `chesscomPlayer` | `https://www.chess.com/players/{slug}` |
| `lichess` | `https://lichess.org/@/{handle}` |
| `chessgames` | `https://www.chessgames.com/perl/chessplayer?pid={id}` |
| `website` | used exactly as stored |
| `x` | `https://x.com/{handle}` |
| `instagram` | `https://www.instagram.com/{handle}/` |
| `youtube` | `https://www.youtube.com/channel/{id}` for `UC…`, else `https://www.youtube.com/{@handle}` |
| `twitch` | `https://www.twitch.tv/{handle}` |
| `facebook` | `https://www.facebook.com/{name}` |

`validate_roster.py` rejects a pasted URL in a handle column and tells you
which part to keep. Links were seeded from Wikidata (joined on property
P1440, the FIDE player id) and cover 1,952 of 2,164 players. The remaining
212 players show no links section at all rather than an empty box.

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
      // Finished URLs as compact [key, url] pairs — the frontend never
      // rebuilds them. Empty array when the player has no links.
      "links": [["chesscom", "https://www.chess.com/member/MagnusCarlsen"],
                ["lichess",  "https://lichess.org/@/DrNykterstein"]]
    }
  ],
  "feds": ["NOR", "USA", ...],          // sorted unique federation codes present
  "fedNames": { "NOR": "Norway", ... },
  // One shared label map instead of repeating labels on 5,804 links.
  "linkLabels": { "chesscom": "Chess.com", "lichess": "Lichess", ... }
}
```

### Fields deliberately REMOVED

`ratingPeriod`, `historyAxis`, per-player `rating`, `peak`, `history`,
`games`, `active`, and `style` (the playstyle radar, removed with its six
`style_*` columns). Nothing in the frontend may reference these. A player's
strength is no longer represented anywhere on the site.

`active` is replaced by `deceased` and `revoked`, which are facts about the
player rather than facts about a monthly rating list. `revoked` already
existed in the dataset and keeps its name and its companion fields
(`revokedYear`, `revokedReason`) so the existing player-card rendering keeps
working untouched.

`bioFull` and `titleYearRevoked` are also dropped: nothing in the frontend
read them, and they duplicated `bio` and `revokedYear` respectively.
