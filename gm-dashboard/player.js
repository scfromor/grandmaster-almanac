/* Grandmaster Almanac — per-player page hydration
 *
 * Reads the FIDE ID from the containing <article data-fide-id="..."> that
 * build_pages.py stamps into every player/<id>.html, fetches the live data.json
 * from the CDN (with local fallback), and builds the share card that cannot be
 * prerendered.
 *
 * Server-rendered HTML in player/<id>.html already provides the profile head,
 * the stat tiles and the profile links — none of that needs re-rendering, and
 * the links in particular must work with JavaScript switched off. We ONLY build
 * the share card here. If the fetch fails, the static content still renders.
 */
(() => {
  const REMOTE_DATA_URL = 'https://cdn.jsdelivr.net/gh/scfromor/grandmaster-almanac@master/gm-dashboard/data.json';
  const LOCAL_DATA_URL = '../data.json';

  const article = document.querySelector('[data-fide-id]');
  if (!article) return;
  const fideId = article.dataset.fideId;

  // ===== Theme (same behavior as index) =====
  const themeToggle = document.querySelector('[data-theme-toggle]');
  const root = document.documentElement;
  let theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  const SUN = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`;
  const MOON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  function applyTheme() {
    root.setAttribute('data-theme', theme);
    if (themeToggle) {
      themeToggle.innerHTML = theme === 'dark' ? SUN : MOON;
      themeToggle.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
    }
  }
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      theme = theme === 'dark' ? 'light' : 'dark';
      applyTheme();
    });
  }
  applyTheme();

  // ===== FED_ISO / historic-flag maps (kept in sync with app.js) =====
  const FED_ISO = {
    ALB:'al', ALG:'dz', AND:'ad', ARG:'ar', ARM:'am', AUS:'au', AUT:'at', AZE:'az',
    BAN:'bd', BEL:'be', BIH:'ba', BLR:'by', BOL:'bo', BRA:'br', BUL:'bg',
    CAN:'ca', CHI:'cl', CHN:'cn', COL:'co', CRC:'cr', CRO:'hr', CUB:'cu', CYP:'cy', CZE:'cz',
    DEN:'dk', DOM:'do',
    ECU:'ec', EGY:'eg', ENG:'gb-eng', ESP:'es', EST:'ee',
    FAI:'fo', FID:null, FIN:'fi', FRA:'fr', FRG:null,
    GDR:null, GEO:'ge', GER:'de', GRE:'gr',
    HUN:'hu',
    INA:'id', IND:'in', IRI:'ir', IRL:'ie', ISL:'is', ISR:'il', ITA:'it',
    JOR:'jo',
    KAZ:'kz', KGZ:'kg', KOR:'kr',
    LAT:'lv', LTU:'lt',
    MAR:'ma', MAS:'my', MDA:'md', MEX:'mx', MGL:'mn', MKD:'mk', MNC:'mc', MNE:'me', MYA:'mm',
    NED:'nl', NON:null, NOR:'no', NZL:'nz',
    PAK:'pk', PAR:'py', PER:'pe', PHI:'ph', POL:'pl', POR:'pt',
    QAT:'qa',
    ROU:'ro', RSA:'za', RUS:'ru',
    SCG:null, SCO:'gb-sct', SEN:'sn', SGP:'sg', SLO:'si', SRB:'rs', SUI:'ch', SVK:'sk', SWE:'se',
    TCH:null, TJK:'tj', TKM:'tm', TPE:'tw', TUN:'tn', TUR:'tr',
    UAE:'ae', UKR:'ua', URS:null, URU:'uy', USA:'us', UZB:'uz',
    VEN:'ve', VIE:'vn',
    YUG:null, ZAM:'zm',
  };
  const GLOBE_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><line x1="3" y1="12" x2="21" y2="12"/><path d="M5 7.5c1.8 1 4.4 1.5 7 1.5s5.2-.5 7-1.5"/><path d="M5 16.5c1.8-1 4.4-1.5 7-1.5s5.2.5 7 1.5"/></svg>';
  const HISTORIC_FLAG_URL = {
    URS: 'https://upload.wikimedia.org/wikipedia/commons/a/a9/Flag_of_the_Soviet_Union.svg',
    YUG: 'https://upload.wikimedia.org/wikipedia/commons/6/61/Flag_of_Yugoslavia_%281946-1992%29.svg',
    TCH: 'https://upload.wikimedia.org/wikipedia/commons/c/cb/Flag_of_the_Czech_Republic.svg',
    GDR: 'https://upload.wikimedia.org/wikipedia/commons/a/a1/Flag_of_East_Germany.svg',
    FRG: 'https://upload.wikimedia.org/wikipedia/commons/0/01/Flag_of_West_Germany%3B_Flag_of_Germany_%281990%E2%80%931996%29.svg',
    SCG: 'https://upload.wikimedia.org/wikipedia/commons/3/3e/Flag_of_Serbia_and_Montenegro_%281992%E2%80%932006%29.svg',
  };
  function fedFlag(fed) {
    const historic = HISTORIC_FLAG_URL[fed];
    if (historic) return `<img class="fed-flag-img" src="${historic}" alt="" loading="lazy" width="20" height="15" crossorigin="anonymous">`;
    const iso = FED_ISO[fed];
    if (!iso) return `<span class="fed-globe">${GLOBE_SVG}</span>`;
    return `<img class="fed-flag-img" src="https://flagcdn.com/${iso}.svg" alt="" loading="lazy" width="20" height="15" crossorigin="anonymous">`;
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function generateTagline(p) {
    const parts = ['Grandmaster'];
    if (p.fedName) parts.push(p.fedName);
    if (p.gmYear) parts.push(`GM ${p.gmYear}`);
    if (p.age != null && p.age < 20) parts.push('Prodigy');
    else if (p.age != null && p.age >= 60) parts.push('Veteran');
    return parts.slice(0, 3).join(' · ');
  }

  function shareCardHTML(p) {
    const tagline = generateTagline(p);
    const bornValue = p.bday ? (p.deceased && p.deathYear ? `${p.bday}–${p.deathYear}` : String(p.bday)) : '—';
    return `
      <div class="share-card" id="shareCardEl">
        <div class="sc-knight">♞</div>
        <div class="sc-head">
          <div class="sc-brand">Grandmaster Almanac</div>
          <div class="sc-flag">${fedFlag(p.fed)}</div>
        </div>
        <div class="sc-body">
          <div class="sc-title">${escapeHtml(p.name)}</div>
          <div class="sc-subtitle">${escapeHtml(tagline)}</div>
          <div class="sc-stats">
            <div class="sc-stat">
              <div class="sc-stat-label">${p.deceased ? 'Lifespan' : 'Born'}</div>
              <div class="sc-stat-value">${escapeHtml(bornValue)}</div>
            </div>
            <div class="sc-stat">
              <div class="sc-stat-label">GM Title</div>
              <div class="sc-stat-value">${p.gmYear ?? '—'}</div>
            </div>
            <div class="sc-stat">
              <div class="sc-stat-label">Federation</div>
              <div class="sc-stat-value">${escapeHtml(p.fed || '—')}</div>
            </div>
          </div>
        </div>
        <div class="sc-foot">
          <span>FIDE GM · ${escapeHtml(p.fedName)}</span>
        </div>
      </div>
    `;
  }

  async function downloadCard(p) {
    const el = document.getElementById('shareCardEl');
    if (!el || !window.htmlToImage) {
      alert('Card export library not loaded.');
      return;
    }
    const btn = document.getElementById('downloadShare');
    btn.disabled = true;
    btn.textContent = 'Rendering…';
    try {
      const dataUrl = await window.htmlToImage.toPng(el, {
        pixelRatio: 2,
        backgroundColor: null,
        cacheBust: true,
        skipFonts: true,
        filter: (node) => {
          if (node.tagName === 'LINK') {
            const href = node.getAttribute('href') || '';
            if (/fonts\.googleapis\.com|fonts\.gstatic\.com/.test(href)) return false;
          }
          return true;
        },
      });
      const a = document.createElement('a');
      const safeName = p.name.replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '');
      a.download = `${safeName}_career_card.png`;
      a.href = dataUrl;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (err) {
      console.error(err);
      alert('Could not generate image: ' + err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg> Download PNG';
    }
  }

  function hydrate(p) {
    // ===== Share card =====
    // The profile links are already in the served HTML, so nothing here needs
    // to touch them.
    const shareHost = document.getElementById('shareCard');
    if (shareHost) shareHost.innerHTML = shareCardHTML(p);
    const btn = document.getElementById('downloadShare');
    if (btn) btn.addEventListener('click', () => downloadCard(p), { once: true });
  }

  // ===== Load data.json (CDN then local fallback) and hydrate =====
  fetch(REMOTE_DATA_URL)
    .then((r) => {
      if (!r.ok) throw new Error(`CDN responded ${r.status}`);
      return r.json();
    })
    .catch((err) => {
      console.warn('Falling back to local data.json:', err.message);
      return fetch(LOCAL_DATA_URL).then((r) => r.json());
    })
    .then((data) => {
      const p = data.players.find((x) => x.id === fideId);
      if (!p) {
        console.warn('Player id not found in dataset:', fideId);
        return;
      }
      // Cache for theme re-paint
      window.__loadedPlayer = p;
      hydrate(p);
    })
    .catch((err) => {
      console.error('Failed to hydrate player page:', err);
    });
})();
