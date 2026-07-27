#!/usr/bin/env python3
"""
build_pages.py — Generate per-player static HTML pages + sitemap.xml.

Rationale
---------
The main index.html renders profiles inside a modal, which is fine for UX
but produces zero indexable content for search engines (crawlers see only
the single-page listing). This script emits one lightweight static page per
grandmaster at `gm-dashboard/player/<FIDE_ID>.html`, containing:

  * <title>, meta description, canonical URL, OpenGraph tags — real per-player
    metadata Google/Bing/social platforms can index and preview.
  * Server-rendered profile facts (name, federation, rating, peak, birth,
    status) so the crawler sees content even without executing JS.
  * A boot script (`player.js`) that hydrates the page with the same
    Chart.js trend + radar and share-card export as the modal, by re-reading
    the FIDE ID from the URL.

Also emits `gm-dashboard/sitemap.xml` covering the index + all player pages.

Inputs:
    gm-dashboard/data.json          — the live enriched dataset

Outputs:
    gm-dashboard/player/<id>.html   — one per GM (~2,100+ files)
    gm-dashboard/sitemap.xml        — sitemap listing every URL

This runs after refresh_dashboard.py in the monthly GitHub Actions workflow,
and can also be executed standalone for local dev.
"""

from __future__ import annotations

import html
import json
import os
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.dirname(HERE)
DASHBOARD_DIR = os.path.join(REPO_ROOT, "gm-dashboard")
DATA_JSON = os.path.join(DASHBOARD_DIR, "data.json")
PLAYER_DIR = os.path.join(DASHBOARD_DIR, "player")
SITEMAP_PATH = os.path.join(DASHBOARD_DIR, "sitemap.xml")

# Live site base URL — used for canonical, OpenGraph, sitemap.
# Kept as a constant so it can be overridden via env var without editing code.
BASE_URL = os.environ.get(
    "GM_ALMANAC_BASE_URL",
    "https://scfromor.com/chess/grandmaster_almanac",
).rstrip("/")


def esc(v) -> str:
    """Escape a value for safe HTML text/attribute insertion."""
    if v is None:
        return ""
    return html.escape(str(v), quote=True)


def status_label(p: dict) -> str:
    if p.get("revoked"):
        yr = p.get("revokedYear")
        return f"Title Revoked {yr}" if yr else "Title Revoked"
    if p.get("deceased"):
        yr = p.get("deathYear")
        return f"Deceased ({yr})" if yr else "Deceased"
    return "Active" if p.get("active") else "Inactive"


def meta_description(p: dict) -> str:
    """Build the <meta name=description> string — short, factual, indexable."""
    parts = [f"Chess Grandmaster {p['name']}"]
    if p.get("fedName"):
        parts.append(f"({p['fedName']})")
    facts = []
    if p.get("rating"):
        facts.append(f"current FIDE {p['rating']}")
    if p.get("peak"):
        facts.append(f"peak {p['peak']}")
    if p.get("bday"):
        if p.get("deceased") and p.get("deathYear"):
            facts.append(f"{p['bday']}\u2013{p['deathYear']}")
        else:
            facts.append(f"b. {p['bday']}")
    if p.get("gmYear"):
        facts.append(f"GM {p['gmYear']}")
    if facts:
        parts.append("\u2014 " + ", ".join(facts) + ".")
    else:
        parts.append("\u2014 career profile.")
    parts.append(
        "Rating history, playstyle radar, and shareable career card on the "
        "Grandmaster Almanac."
    )
    return " ".join(parts)


def page_title(p: dict) -> str:
    return f"{p['name']} \u2014 FIDE Grandmaster Profile | Grandmaster Almanac"


# Federation code -> ISO 3166-1 alpha-2 (matches app.js FED_ISO exactly).
# None values mean "no country flag" — historical entities, FIDE, unaffiliated.
FED_ISO = {
    "ALB": "al", "ALG": "dz", "AND": "ad", "ARG": "ar", "ARM": "am", "AUS": "au",
    "AUT": "at", "AZE": "az",
    "BAN": "bd", "BEL": "be", "BIH": "ba", "BLR": "by", "BOL": "bo", "BRA": "br",
    "BUL": "bg",
    "CAN": "ca", "CHI": "cl", "CHN": "cn", "COL": "co", "CRC": "cr", "CRO": "hr",
    "CUB": "cu", "CYP": "cy", "CZE": "cz",
    "DEN": "dk", "DOM": "do",
    "ECU": "ec", "EGY": "eg", "ENG": "gb-eng", "ESP": "es", "EST": "ee",
    "FAI": "fo", "FID": None, "FIN": "fi", "FRA": "fr", "FRG": None,
    "GDR": None, "GEO": "ge", "GER": "de", "GRE": "gr",
    "HUN": "hu",
    "INA": "id", "IND": "in", "IRI": "ir", "IRL": "ie", "ISL": "is", "ISR": "il",
    "ITA": "it",
    "JOR": "jo",
    "KAZ": "kz", "KGZ": "kg", "KOR": "kr",
    "LAT": "lv", "LTU": "lt",
    "MAR": "ma", "MAS": "my", "MDA": "md", "MEX": "mx", "MGL": "mn", "MKD": "mk",
    "MNC": "mc", "MNE": "me", "MYA": "mm",
    "NED": "nl", "NON": None, "NOR": "no", "NZL": "nz",
    "PAK": "pk", "PAR": "py", "PER": "pe", "PHI": "ph", "POL": "pl", "POR": "pt",
    "QAT": "qa",
    "ROU": "ro", "RSA": "za", "RUS": "ru",
    "SCG": None, "SCO": "gb-sct", "SEN": "sn", "SGP": "sg", "SLO": "si",
    "SRB": "rs", "SUI": "ch", "SVK": "sk", "SWE": "se",
    "TCH": None, "TJK": "tj", "TKM": "tm", "TPE": "tw", "TUN": "tn", "TUR": "tr",
    "UAE": "ae", "UKR": "ua", "URS": None, "URU": "uy", "USA": "us", "UZB": "uz",
    "VEN": "ve", "VIE": "vn",
    "YUG": None, "ZAM": "zm",
}
HISTORIC_FLAG_URL = {
    "URS": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Flag_of_the_Soviet_Union.svg",
    "YUG": "https://upload.wikimedia.org/wikipedia/commons/6/61/Flag_of_Yugoslavia_%281946-1992%29.svg",
    "TCH": "https://upload.wikimedia.org/wikipedia/commons/c/cb/Flag_of_the_Czech_Republic.svg",
    "GDR": "https://upload.wikimedia.org/wikipedia/commons/a/a1/Flag_of_East_Germany.svg",
    "FRG": "https://upload.wikimedia.org/wikipedia/commons/0/01/Flag_of_West_Germany%3B_Flag_of_Germany_%281990%E2%80%931996%29.svg",
    "SCG": "https://upload.wikimedia.org/wikipedia/commons/3/3e/Flag_of_Serbia_and_Montenegro_%281992%E2%80%932006%29.svg",
}


def fed_flag_html(fed: str | None) -> str:
    """Return an <img> or globe-SVG span for the given federation code."""
    if not fed:
        return ""
    if fed in HISTORIC_FLAG_URL:
        return (
            f'<img class="fed-flag-img" src="{esc(HISTORIC_FLAG_URL[fed])}" '
            f'alt="" width="20" height="15" loading="lazy" crossorigin="anonymous">'
        )
    iso = FED_ISO.get(fed)
    if not iso:
        return (
            '<span class="fed-globe"><svg viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<circle cx="12" cy="12" r="9"/>'
            '<ellipse cx="12" cy="12" rx="4" ry="9"/>'
            '<line x1="3" y1="12" x2="21" y2="12"/>'
            '<path d="M5 7.5c1.8 1 4.4 1.5 7 1.5s5.2-.5 7-1.5"/>'
            '<path d="M5 16.5c1.8-1 4.4-1.5 7-1.5s5.2.5 7 1.5"/>'
            "</svg></span>"
        )
    return (
        f'<img class="fed-flag-img" src="https://flagcdn.com/{iso}.svg" '
        f'alt="" width="20" height="15" loading="lazy" crossorigin="anonymous">'
    )


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <link rel="canonical" href="{canonical}" />
    <meta property="og:type" content="profile" />
    <meta property="og:title" content="{og_title}" />
    <meta property="og:description" content="{description}" />
    <meta property="og:url" content="{canonical}" />
    {og_image_tag}
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="robots" content="index,follow" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
    <link rel="stylesheet" href="../style.css" />
    <link
      rel="icon"
      href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%23114d3a'/><text x='16' y='23' text-anchor='middle' font-size='22' fill='%23ecead8'>%E2%99%9E</text></svg>"
    />
    <script type="application/ld+json">
{json_ld}
    </script>
  </head>
  <body class="player-page">
    <header class="topbar">
      <div class="brand">
        <a href="../" class="brand-link" aria-label="Back to Grandmaster Almanac">
          <svg
            class="logo"
            viewBox="0 0 32 32"
            width="32"
            height="32"
            aria-hidden="true"
          >
            <rect x="0.5" y="0.5" width="31" height="31" rx="6" fill="none" stroke="currentColor" stroke-width="1.25" />
            <path
              d="M10 22h12v2H10zM12 20h8l-1-3h-6zM13 17h6c0-2-1-3-3-3s-3 1-3 3zM15 14h2v-2h-2zM14 12h4l-.5-1.5h-3z"
              fill="currentColor"
            />
          </svg>
          <div>
            <h1>Grandmaster Almanac</h1>
            <p class="brand-sub">Player profile</p>
          </div>
        </a>
      </div>
      <div class="topbar-actions">
        <a href="../" class="ghost-btn back-link" aria-label="Back to full directory">\u2039 Back to directory</a>
        <button
          class="icon-btn"
          data-theme-toggle
          aria-label="Toggle theme"
          type="button"
        ></button>
      </div>
    </header>

    <main class="player-main">
      <article class="player-article" data-fide-id="{fide_id}">
        <!-- Server-rendered header: crawlers and no-JS clients see real content. -->
        <div id="modalContent" class="player-static">
          <div class="profile-head">
            {avatar_html}
            <div>
              <div id="modalName" class="profile-name">{name}</div>
              <div class="profile-meta">
                {meta_line}
              </div>
            </div>
          </div>

          <div class="stat-row">
            <div class="stat"><div class="stat-label">Current ELO</div><div class="stat-value">{rating}</div></div>
            <div class="stat"><div class="stat-label">Peak ELO<span class="est-badge" title="Peak ELO is a model-derived estimate for most players. Historical peaks for well-known legends are hard-coded from FIDE records.">Est.</span></div><div class="stat-value">{peak}</div></div>
            <div class="stat"><div class="stat-label">{born_label}</div><div class="stat-value">{born_value}</div></div>
            <div class="stat"><div class="stat-label">GM Title</div><div class="stat-value">{gm_year}</div></div>
            <div class="stat"><div class="stat-label">Games</div><div class="stat-value">{games}</div></div>
            <div class="stat"><div class="stat-label">World Rank</div><div class="stat-value">{rank_display}</div></div>
          </div>

          <!-- Charts are hydrated by player.js on load. Static markup below is a
               fallback for crawlers/no-JS clients. -->
          <div class="profile-body" id="profileBody">
            <div class="chart-card">
              <div class="chart-title">10-Year Rating Trend<span class="est-badge" title="Historical rating series is reconstructed from a deterministic per-player model anchored on current and peak ELO \u2014 not sourced from monthly FIDE lists.">Estimated</span></div>
              <div class="chart-box"><canvas id="eloChart"></canvas></div>
            </div>
            <div class="chart-card">
              <div class="chart-title">Playstyle Radar<span class="est-badge" title="Playstyle axes (Aggressive, Positional, Tactical, Endgame, Opening Prep, Defense) are derived from a heuristic model, not measured from game data.">Estimated</span></div>
              <div class="chart-box"><canvas id="radarChart"></canvas></div>
            </div>
          </div>

          <details class="share-section" id="shareDetails">
            <summary class="share-summary">
              <span class="share-summary-label">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
                Generate shareable career card
              </span>
              <span class="share-summary-chevron" aria-hidden="true">\u203a</span>
            </summary>
            <div class="share-body">
              <div id="shareCard"></div>
              <div class="share-actions">
                <button class="primary-btn" id="downloadShare" type="button">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>
                  Download PNG
                </button>
              </div>
            </div>
          </details>

          <p class="note">
            <strong>About the data.</strong> Current ratings and federation are from the official
            <a href="https://ratings.fide.com/download_lists.phtml" target="_blank" rel="noopener">FIDE standard rating list</a>.
            Peak rating, 10-year history, and playstyle radar are statistical estimates derived from
            rating, age, and a deterministic per-player model. See the
            <a href="../">Grandmaster Almanac directory</a> for the full dataset and filters.
          </p>
        </div>
      </article>
    </main>

    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.min.js"></script>
    <script src="../player.js"></script>
  </body>
</html>
"""


def build_meta_line(p: dict) -> str:
    """Reproduce the modal's profile-meta line: fed \xb7 birthplace \xb7 age \xb7 gender \xb7 status."""
    parts = [esc(p.get("fedName", ""))]

    # Birthplace, avoiding "Tønsberg, Norway" when fed already says Norway.
    birth_parts = []
    if p.get("birthCity"):
        birth_parts.append(esc(p["birthCity"]))
    same_country = p.get("birthCountry") and p["birthCountry"] == p.get("fed")
    if p.get("birthCountryName") and not (same_country and p.get("birthCity")):
        birth_parts.append(esc(p["birthCountryName"]))
    if birth_parts:
        parts.append(f'<span class="sep">\xb7</span>Born in {", ".join(birth_parts)}')

    # Federation history — matches app.js logic
    fh = p.get("fedHistoryNames") or []
    if len(fh) > 2:
        priors = " \u2192 ".join(esc(n) for n in fh[:-1])
        parts.append(f'<span class="sep">\xb7</span>Previously {priors}')
    elif p.get("fed") != p.get("prevFed") and p.get("prevFedName"):
        parts.append(f'<span class="sep">\xb7</span>Previously {esc(p["prevFedName"])}')

    # Age / lifespan
    age = p.get("age")
    if age is not None:
        parts.append(
            f'<span class="sep">\xb7</span>{age} yrs' if not p.get("deceased")
            else f'<span class="sep">\xb7</span>lived {age} yrs'
        )

    # Gender
    sex = p.get("sex")
    gender_str = "Female" if sex == "F" else "Male" if sex == "M" else None
    if gender_str:
        parts.append(f'<span class="sep">\xb7</span>{gender_str}')

    # Status
    parts.append(f'<span class="sep">\xb7</span>{esc(status_label(p))}')

    return "".join(parts)


def get_initials(name: str) -> str:
    parts = [s.strip() for s in name.split(",") if s.strip()]
    if len(parts) == 2 and parts[0] and parts[1]:
        return (parts[1][0] + parts[0][0]).upper()
    tokens = name.split()
    if len(tokens) >= 2:
        return (tokens[0][0] + tokens[1][0]).upper()
    return (tokens[0][0] if tokens else "?").upper()


def avatar_html_for(p: dict) -> str:
    photo = p.get("photo")
    if photo:
        return (
            f'<div class="profile-avatar has-photo" '
            f'style="background-image:url(\'{esc(photo)}\')" '
            f'aria-label="{esc(p["name"])}"></div>'
        )
    return f'<div class="profile-avatar">{esc(get_initials(p["name"]))}</div>'


def build_json_ld(p: dict, canonical: str) -> str:
    """Schema.org Person markup for richer search snippets."""
    obj = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": p["name"],
        "url": canonical,
        "jobTitle": "Chess Grandmaster",
        "nationality": p.get("fedName"),
    }
    if p.get("photo"):
        obj["image"] = p["photo"]
    if p.get("bday"):
        obj["birthDate"] = str(p["bday"])
    if p.get("deathYear"):
        obj["deathDate"] = str(p["deathYear"])
    if p.get("birthCountryName"):
        obj["birthPlace"] = {
            "@type": "Place",
            "name": p.get("birthCity") or p["birthCountryName"],
            "address": {
                "@type": "PostalAddress",
                "addressCountry": p["birthCountryName"],
            },
        }
    # Award = FIDE GM title
    award_parts = ["FIDE Grandmaster"]
    if p.get("gmYear"):
        award_parts.append(f"({p['gmYear']})")
    obj["award"] = " ".join(award_parts)
    return json.dumps(obj, indent=2, ensure_ascii=False)


def render_page(p: dict) -> str:
    canonical = f"{BASE_URL}/player/{p['id']}.html"
    og_image_tag = ""
    if p.get("photo"):
        og_image_tag = f'<meta property="og:image" content="{esc(p["photo"])}" />'
    born_label = "Lifespan" if p.get("deceased") else "Born"
    if p.get("deceased") and p.get("deathYear") and p.get("bday"):
        born_value = f"{p['bday']} \u2013 {p['deathYear']}"
    elif p.get("bday"):
        born_value = str(p["bday"])
    else:
        born_value = "\u2014"
    return PAGE_TEMPLATE.format(
        title=esc(page_title(p)),
        description=esc(meta_description(p)),
        canonical=esc(canonical),
        og_title=esc(f"{p['name']} \u2014 FIDE Grandmaster"),
        og_image_tag=og_image_tag,
        json_ld=build_json_ld(p, canonical),
        fide_id=esc(p["id"]),
        avatar_html=avatar_html_for(p),
        name=esc(p["name"]),
        meta_line=build_meta_line(p),
        rating=esc(p.get("rating") if p.get("rating") is not None else "\u2014"),
        peak=esc(p.get("peak") if p.get("peak") is not None else "\u2014"),
        born_label=born_label,
        born_value=esc(born_value),
        gm_year=esc(p.get("gmYear") if p.get("gmYear") else "\u2014"),
        games=esc(p.get("games") or 0),
        rank_display="\u2014",  # Hydrated on client-side once data.json loads
    )


def build_sitemap(players: list[dict]) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [
        f"  <url><loc>{esc(BASE_URL)}/</loc><lastmod>{today}</lastmod>"
        f"<changefreq>monthly</changefreq><priority>1.0</priority></url>"
    ]
    for p in players:
        urls.append(
            f"  <url><loc>{esc(BASE_URL)}/player/{esc(p['id'])}.html</loc>"
            f"<lastmod>{today}</lastmod><changefreq>monthly</changefreq>"
            "<priority>0.6</priority></url>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>\n"
    )


def main() -> None:
    if not os.path.exists(DATA_JSON):
        print(f"ERROR: {DATA_JSON} not found. Run refresh_dashboard.py first.",
              file=sys.stderr)
        sys.exit(1)

    with open(DATA_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    players = data.get("players", [])
    if not players:
        print("ERROR: No players in data.json", file=sys.stderr)
        sys.exit(1)

    # Wipe & recreate — every refresh regenerates the full set, so stray files
    # from removed players (name changes, revoked-then-restored, dedup) are
    # cleared out. Safer than in-place update.
    if os.path.isdir(PLAYER_DIR):
        shutil.rmtree(PLAYER_DIR)
    os.makedirs(PLAYER_DIR, exist_ok=True)

    for p in players:
        page_html = render_page(p)
        out_path = os.path.join(PLAYER_DIR, f"{p['id']}.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(page_html)

    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(build_sitemap(players))

    summary = {
        "status": "ok",
        "player_pages_written": len(players),
        "sitemap_urls": len(players) + 1,
        "base_url": BASE_URL,
        "output_dir": os.path.relpath(PLAYER_DIR, REPO_ROOT),
        "sitemap_path": os.path.relpath(SITEMAP_PATH, REPO_ROOT),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
