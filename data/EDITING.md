# How to update the Grandmaster Almanac

The site is built from one file: **`data/roster.csv`**. You edit that file on
GitHub, commit, and about four minutes later the live site reflects the change.
Nothing else needs to be touched, and nothing runs on your laptop.

---

## The short version

1. Open [`data/roster.csv` on GitHub](https://github.com/scfromor/grandmaster-almanac/blob/master/data/roster.csv)
2. Click the pencil icon (**Edit this file**)
3. Make your change
4. Scroll down, click **Commit changes**
5. Wait ~4 minutes, then reload https://scfromor.com/chess/grandmaster_almanac/

If you make a mistake, the build **stops before anything is published** and
emails you what is wrong and which row it is on. The live site is never left
broken. Fix the row, commit again.

---

## Adding a new grandmaster

Add one line at the end of the file. Only six values are actually required:

| Column | Required? | Example |
|---|---|---|
| `id` | **yes** | `1503014` (their FIDE ID) |
| `name` | **yes** | `Carlsen, Magnus` — surname first |
| `fed` | **yes** | `NOR` — three-letter code, must exist in `fed_names.json` |
| `sex` | **yes** | `M` or `F` |
| `title` | **yes** | `GM` |
| `bday` | **yes** | `1990` |
| `gmYear` | recommended | `2004` |
| everything else | optional | leave blank |

A minimal valid row looks like this:

```
1503014,"Carlsen, Magnus",NOR,M,GM,,1990,2004,false,,false,,,NOR,Tønsberg,NOR,https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Magnus_Carlsen_in_2025.jpg/250px-Magnus_Carlsen_in_2025.jpg,,,,MagnusCarlsen,magnus-carlsen,DrNykterstein,52948,https://magnuscarlsen.com,MagnusCarlsen,magnus_carlsen,UCbdcpQ5uPPymv7Ea0nnFfOw,,magnuschess
```

**If the name contains a comma — and it usually will — wrap it in double
quotes.** `"Carlsen, Magnus"`. This is the single most common mistake.

Leaving the ten link columns blank is fine. That player simply shows no
"Profiles & Links" box, rather than an empty one.

## Recording a death

Find the player's row and set two columns:

- `deceased` → `true`
- `deathYear` → e.g. `2026`

The validator will reject `deathYear` without `deceased`, and vice versa, so
you cannot half-finish it.

## Recording a revoked title

- `revoked` → `true`
- `revokedYear` → e.g. `2026`
- `revokedReason` → short text, quoted if it contains a comma

## Changing a federation

Update `fed` to the new code. If you want the site to show their previous
federation too, append to `fedHistory`, which is a `|`-separated chain in
chronological order:

```
DEN|SCO|DEN
```

## Removing a player

Delete the whole line.

Deleting **more than 25 players at once** is blocked on purpose — that is
almost always an accidental copy-paste or a truncated file rather than a real
edit. If you genuinely mean it, go to the **Actions** tab, choose **Build and
deploy site**, click **Run workflow**, and tick **allow_shrink**.

---

## All 26 columns

| Column | Meaning | Notes |
|---|---|---|
| `id` | FIDE ID | must be unique |
| `name` | `Surname, Forename` | quote it if it has a comma |
| `fed` | current federation | 3-letter code in `fed_names.json` |
| `sex` | `M` or `F` | |
| `title` | usually `GM` | |
| `wtit` | women's title | e.g. `WGM`, often blank |
| `bday` | birth year | 1850–2026 |
| `gmYear` | year GM title awarded | 1950–2026, not before `bday` |
| `deceased` | `true` / `false` | |
| `deathYear` | year of death | requires `deceased=true` |
| `revoked` | `true` / `false` | |
| `revokedYear` | year title revoked | requires `revoked=true` |
| `revokedReason` | short text | |
| `birthCountry` | 3-letter code | may differ from `fed` |
| `birthCity` | free text | |
| `fedHistory` | `DEN\|SCO\|DEN` | chronological, `\|`-separated |
| `photo` | image URL | must start with `http` |
| `photoSource` | credit URL | |
| `bio` | one paragraph | quote it if it has a comma |
| `bioSource` | source URL | |
| `chesscom` | `MagnusCarlsen` | handle only |
| `chesscomPlayer` | `magnus-carlsen` | slug only |
| `lichess` | `DrNykterstein` | handle only |
| `chessgames` | `52948` | numeric id only |
| `website` | `https://magnuscarlsen.com` | the **full** URL |
| `x` | `MagnusCarlsen` | no `@` |
| `instagram` | `magnus_carlsen` | no `@` |
| `youtube` | `UCbdcpQ5uPPymv7Ea0nnFfOw` | channel id, or `@handle` |
| `twitch` | `magnuscarlsen` | |
| `facebook` | `magnuschess` | |

## Adding a link

**Paste the handle, not the address.** `website` is the one exception: it
takes the whole URL. Everywhere else the build assembles the address for you,
so it stays correct if a platform changes its URL shape.

| You found | You paste |
| --- | --- |
| `https://www.chess.com/member/MagnusCarlsen` | `MagnusCarlsen` |
| `https://lichess.org/@/DrNykterstein` | `DrNykterstein` |
| `https://x.com/MagnusCarlsen` | `MagnusCarlsen` |
| `https://www.youtube.com/@GothamChess` | `@GothamChess` |
| `https://www.chessgames.com/perl/chessplayer?pid=52948` | `52948` |

If you paste a full URL by mistake, the validator stops the build and tells
you which part to keep. Nothing is published until you fix it.

Chess.com has two separate columns on purpose. `chesscom` is the player's own
member account, which they control. `chesscomPlayer` is Chess.com's editorial
page about them, which exists for many historical players who never held an
account.

The links were seeded automatically from Wikidata for 1,952 of the 2,164
players. Adding one by hand is only needed for the rest, or when Wikidata is
wrong. Your value always wins: the importer never overwrites a filled cell.

---

## What the build checks before publishing

- No duplicate FIDE IDs
- Federation and birth-country codes exist in `fed_names.json`
- `sex` is `M` or `F`
- Years are inside plausible ranges and in a sensible order
  (born → GM title → death)
- `deathYear`/`deceased` and `revokedYear`/`revoked` agree with each other
- Photo and source values look like URLs
- Style axes are all-or-nothing and within 0–100
- The roster has not shrunk by more than 25 players
- After deploying, the live site reports the same player count as the build

Any failure stops the run and leaves the current live site untouched.

---

## Ratings

There are none, by design. The site is a biographical directory. See
[`legacy/README.md`](legacy/README.md) for why the automatic rating pipeline
was removed.
