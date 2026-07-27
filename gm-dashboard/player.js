/* Grandmaster Almanac — per-player page hydration
 *
 * Reads the FIDE ID from the containing <article data-fide-id="..."> that
 * build_pages.py stamps into every player/<id>.html, fetches the live data.json
 * from the CDN (with local fallback), and hydrates the trend chart, radar
 * chart, share-card, and the World-Rank stat that couldn't be prerendered.
 *
 * Server-rendered HTML in player/<id>.html already provides the profile head,
 * stat tiles, and estimated-badge tooltips — those don't need re-rendering.
 * We ONLY paint the two charts and wire up the share button. If Chart.js
 * fails to load or the fetch fails, the static content still renders fine.
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
  let eloChart = null;
  let radarChart = null;
  function applyTheme() {
    root.setAttribute('data-theme', theme);
    if (themeToggle) {
      themeToggle.innerHTML = theme === 'dark' ? SUN : MOON;
      themeToggle.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
    }
    // Re-paint charts when theme changes so grid/tick colors match the theme
    if (window.__loadedPlayer) hydrate(window.__loadedPlayer, window.__loadedData);
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

  function chartColors() {
    const styles = getComputedStyle(document.documentElement);
    return {
      line: styles.getPropertyValue('--data-line').trim() || '#114d3a',
      area: styles.getPropertyValue('--data-area').trim() || 'rgba(17,77,58,0.15)',
      grid: styles.getPropertyValue('--data-grid').trim() || '#d8d1bb',
      text: styles.getPropertyValue('--text').trim() || '#1d2520',
      muted: styles.getPropertyValue('--text-muted').trim() || '#6b6f63',
      primary: styles.getPropertyValue('--primary').trim() || '#114d3a',
    };
  }

  function topStyleAxis(style) {
    const axes = [
      { k: 'aggressive', label: 'Aggressive Attacker' },
      { k: 'positional', label: 'Positional Player' },
      { k: 'tactical', label: 'Tactical Threat' },
      { k: 'endgame', label: 'Endgame Specialist' },
      { k: 'opening', label: 'Opening Theorist' },
      { k: 'defense', label: 'Resilient Defender' },
    ];
    let top = axes[0]; let topV = -1;
    for (const a of axes) {
      if (style[a.k] > topV) { topV = style[a.k]; top = a; }
    }
    return top;
  }

  function generateTagline(p, styleTop) {
    const parts = [];
    if (p.peak >= 2800) parts.push('Super-elite 2800+ peak');
    else if (p.peak >= 2700) parts.push('Super-GM');
    else if (p.peak >= 2600) parts.push('Strong GM');
    else parts.push('Grandmaster');
    parts.push(styleTop.label);
    if (p.age != null && p.age < 20) parts.push('Prodigy');
    else if (p.age != null && p.age >= 60) parts.push('Veteran');
    return parts.slice(0, 3).join(' · ');
  }

  function shareCardHTML(p) {
    const styleTop = topStyleAxis(p.style);
    const tagline = generateTagline(p, styleTop);
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
              <div class="sc-stat-label">Current ELO</div>
              <div class="sc-stat-value">${p.rating ?? '—'}</div>
            </div>
            <div class="sc-stat">
              <div class="sc-stat-label">Peak ELO</div>
              <div class="sc-stat-value">${p.peak}</div>
            </div>
            <div class="sc-stat">
              <div class="sc-stat-label">Style</div>
              <div class="sc-stat-value" style="font-size:16px;line-height:1.1">${styleTop.label}</div>
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

  function paintRankStat(p, all) {
    // Real World Rank: 1 = highest current rating among rated active players.
    // Matches the "World Rank" the modal shows when no filters are applied.
    const rated = all.filter((x) => typeof x.rating === 'number');
    rated.sort((a, b) => b.rating - a.rating);
    const idx = rated.findIndex((x) => x.id === p.id);
    const rank = idx >= 0 ? idx + 1 : null;
    const nodes = document.querySelectorAll('.stat');
    // The last .stat tile holds World Rank (see render_page in build_pages.py)
    const last = nodes[nodes.length - 1];
    if (!last) return;
    const val = last.querySelector('.stat-value');
    if (val) val.textContent = rank ? '#' + rank.toLocaleString() : '—';
  }

  function hydrate(p, data) {
    const c = chartColors();
    if (eloChart) { eloChart.destroy(); eloChart = null; }
    if (radarChart) { radarChart.destroy(); radarChart = null; }

    // ===== Rating trend =====
    const eloCanvas = document.getElementById('eloChart');
    const hasHistory = p.history && p.history.some((v) => v != null);
    if (eloCanvas && hasHistory && window.Chart) {
      const axis = data.historyAxis;
      const labels = axis.map((d) => {
        const [y, m] = d.split('-');
        return `${y}-${m}`;
      });
      eloChart = new Chart(eloCanvas, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Standard rating',
            data: p.history,
            borderColor: c.line,
            backgroundColor: c.area,
            borderWidth: 2,
            tension: 0.35,
            fill: true,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: c.line,
            spanGaps: true,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 500 },
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: c.text,
              titleColor: '#fff',
              bodyColor: '#fff',
              callbacks: {
                title: (items) => {
                  const d = axis[items[0].dataIndex];
                  const [y, m] = d.split('-');
                  const monthName = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][parseInt(m, 10) - 1];
                  return `${monthName} ${y}`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: {
                color: c.muted,
                maxTicksLimit: 8,
                callback: function(val) {
                  const lbl = this.getLabelForValue(val);
                  return lbl.endsWith('-01') ? lbl.slice(0, 4) : '';
                },
                font: { size: 11 },
              },
            },
            y: {
              grid: { color: c.grid, lineWidth: 0.5 },
              border: { display: false },
              ticks: { color: c.muted, font: { size: 11 } },
            },
          },
        },
      });
    } else if (eloCanvas && !hasHistory) {
      const placeholder = document.createElement('div');
      placeholder.className = 'chart-placeholder';
      const era = (p.bday && p.deathYear) ? `${p.bday}\u2013${p.deathYear}` : (p.deathYear ? `\u2020 ${p.deathYear}` : 'historical');
      placeholder.innerHTML = `<div class="cp-icon">\u265E</div><div class="cp-text"><strong>No rating data 2016\u20132026</strong><div class="cp-sub">${escapeHtml(p.name.split(',')[0])} played before the modern rating window (${era}). Estimated peak rating: <b>${p.peak}</b>.</div></div>`;
      eloCanvas.replaceWith(placeholder);
    }

    // ===== Playstyle radar =====
    const radarCanvas = document.getElementById('radarChart');
    if (radarCanvas && p.style && window.Chart) {
      const s = p.style;
      radarChart = new Chart(radarCanvas, {
        type: 'radar',
        data: {
          labels: ['Aggressive', 'Positional', 'Tactical', 'Endgame', 'Opening Prep', 'Defense'],
          datasets: [{
            label: 'Playstyle',
            data: [s.aggressive, s.positional, s.tactical, s.endgame, s.opening, s.defense],
            borderColor: c.line,
            backgroundColor: c.area,
            borderWidth: 2,
            pointBackgroundColor: c.line,
            pointRadius: 3,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: { duration: 500 },
          plugins: { legend: { display: false } },
          scales: {
            r: {
              min: 0, max: 100,
              angleLines: { color: c.grid },
              grid: { color: c.grid },
              pointLabels: { color: c.muted, font: { size: 11, weight: '500' } },
              ticks: { display: false, stepSize: 25 },
            },
          },
        },
      });
    }

    // ===== Share card + world rank =====
    const shareHost = document.getElementById('shareCard');
    if (shareHost) shareHost.innerHTML = shareCardHTML(p);
    paintRankStat(p, data.players);
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
      window.__loadedData = data;
      hydrate(p, data);
    })
    .catch((err) => {
      console.error('Failed to hydrate player page:', err);
    });
})();
