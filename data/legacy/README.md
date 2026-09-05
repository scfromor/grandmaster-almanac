# Retired: the automatic FIDE rating pipeline

Nothing in this folder runs. It is kept for reference only.

## Why it was retired

The site used to download FIDE's monthly standard rating list and rebuild
itself automatically. That stopped being reliable:

- **FIDE blocks datacenter IP addresses.** `ratings.fide.com` times out from
  GitHub Actions runners. Every workaround routed through third parties.
- **The Internet Archive fallback published stale data twice.** In August and
  again in September 2026 the site showed the previous month's ratings while
  claiming to be current, because the resolver accepted an older snapshot when
  the current month had not been archived yet.
- **Failures were silent.** The scheduled job only ran on days 3–9 of the
  month and there was no alert when it failed, so stale data sat live until
  someone noticed by eye.

Ratings changed every month, could not be verified without hitting a source
that blocks us, and were the only reason the site needed automation at all.
The redesign removes ratings entirely and rebuilds the site from a
hand-maintained `data/roster.csv` instead. Biographical facts — birth year,
federation, GM year, death — change rarely and can be checked by a human.

## What the files were

| File | Role |
|---|---|
| `monthly-refresh.yml.retired` | Scheduled workflow, ran daily on days 3–9 |
| `fide_source.py` | Resolved and downloaded the FIDE rating list ZIP |
| `refresh_dashboard.py` | Merged the FIDE list into `data.json` |
| `check_freshness.py` | Gate that failed the build on stale data |
| `style_model.py` | Derived playstyle radar axes from rating and age |
| `enrich_dataset.py` | Backfilled photos and bios from Wikipedia |
| `wiki_enrichment.py` | Wikipedia lookup helpers |
| `refresh_log.json` | Run history of the retired pipeline |

## Note on the playstyle radar

`style_model.py` computed each radar axis from a player's rating and age.
With ratings gone the axes **cannot be recomputed**. The values that existed
when the site was converted are now frozen as plain columns in `roster.csv`.

A player added by hand with the six `style_*` columns left blank simply shows
no radar and a "—" playstyle. That is intended: a missing radar is better than
a fabricated one.
