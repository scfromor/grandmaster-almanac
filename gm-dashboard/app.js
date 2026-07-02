/* Grandmaster Almanac — dashboard logic */
(() => {
  // ===== State =====
  const state = {
    raw: null,
    filtered: [],
    sort: { key: 'rating', dir: 'desc' },
    page: 1,
    pageSize: 50,
    activeId: null,
    eloChart: null,
    radarChart: null,
  };

  // ===== FIDE federation code -> ISO 3166-1 alpha-2 (for flag emojis) =====
  // Most FIDE codes follow IOC; this maps to the ISO codes flag emojis are built from.
  // null means "no straightforward flag" (historical entities, FIDE flag, refugee, etc.).
  const FED_ISO = {
    ALB:'AL', ALG:'DZ', AND:'AD', ARG:'AR', ARM:'AM', AUS:'AU', AUT:'AT', AZE:'AZ',
    BAN:'BD', BEL:'BE', BIH:'BA', BLR:'BY', BOL:'BO', BRA:'BR', BUL:'BG',
    CAN:'CA', CHI:'CL', CHN:'CN', COL:'CO', CRC:'CR', CRO:'HR', CUB:'CU', CYP:'CY', CZE:'CZ',
    DEN:'DK', DOM:'DO',
    ECU:'EC', EGY:'EG', ENG:'GB-ENG', ESP:'ES', EST:'EE',
    FAI:'FO', FID:null, FIN:'FI', FRA:'FR', FRG:null,
    GDR:null, GEO:'GE', GER:'DE', GRE:'GR',
    HUN:'HU',
    INA:'ID', IND:'IN', IRI:'IR', IRL:'IE', ISL:'IS', ISR:'IL', ITA:'IT',
    JOR:'JO',
    KAZ:'KZ', KGZ:'KG', KOR:'KR',
    LAT:'LV', LTU:'LT',
    MAR:'MA', MAS:'MY', MDA:'MD', MEX:'MX', MGL:'MN', MKD:'MK', MNC:'MC', MNE:'ME', MYA:'MM',
    NED:'NL', NON:null, NOR:'NO', NZL:'NZ',
    PAK:'PK', PAR:'PY', PER:'PE', PHI:'PH', POL:'PL', POR:'PT',
    QAT:'QA',
    ROU:'RO', RSA:'ZA', RUS:'RU',
    SCG:null, SCO:'GB-SCT', SEN:'SN', SGP:'SG', SLO:'SI', SRB:'RS', SUI:'CH', SVK:'SK', SWE:'SE',
    TCH:null, TJK:'TJ', TKM:'TM', TPE:'TW', TUN:'TN', TUR:'TR',
    UAE:'AE', UKR:'UA', URS:null, URU:'UY', USA:'US', UZB:'UZ',
    VEN:'VE', VIE:'VN',
    YUG:null, ZAM:'ZM',
  };
  // Emoji-renderable subdivisions (England, Scotland, Wales)
  const SUBDIV_FLAG = {
    'GB-ENG': '\uD83C\uDFF4\uDB40\uDC67\uDB40\uDC62\uDB40\uDC65\uDB40\uDC6E\uDB40\uDC67\uDB40\uDC7F',
    'GB-SCT': '\uD83C\uDFF4\uDB40\uDC67\uDB40\uDC62\uDB40\uDC73\uDB40\uDC63\uDB40\uDC74\uDB40\uDC7F',
  };
  function fedFlag(fed) {
    const iso = FED_ISO[fed];
    if (!iso) return '';
    if (SUBDIV_FLAG[iso]) return SUBDIV_FLAG[iso];
    // Two-letter ISO -> regional-indicator emoji
    const A = 0x1F1E6;
    return String.fromCodePoint(A + iso.charCodeAt(0) - 65, A + iso.charCodeAt(1) - 65);
  }

  // ===== Theme toggle =====
  const themeToggle = document.querySelector('[data-theme-toggle]');
  const root = document.documentElement;
  let theme = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  const SUN = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>`;
  const MOON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
  const applyTheme = () => {
    root.setAttribute('data-theme', theme);
    themeToggle.innerHTML = theme === 'dark' ? SUN : MOON;
    themeToggle.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
    // Re-render charts to update palette
    if (state.activeId) renderProfile(state.activeId, false);
  };
  themeToggle.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme();
  });
  applyTheme();

  // ===== Load data =====
  fetch('data.json')
    .then((r) => r.json())
    .then((d) => {
      state.raw = d;
      init();
    })
    .catch((err) => {
      document.querySelector('#tbody').innerHTML = `<tr><td colspan="8" class="empty">Failed to load data: ${err.message}</td></tr>`;
    });

  // ===== Initialize =====
  function init() {
    document.getElementById('ratingPeriod').textContent = formatRatingPeriod(state.raw.ratingPeriod);
    document.getElementById('totalCount').textContent = state.raw.players.length.toLocaleString();
    buildFedSelects();
    bindFilters();
    bindSort();
    bindPager();
    bindModal();
    applyFilters();
    // Honor a deep-link hash like #p-1503014 on first load
    syncFromHash();
  }

  function formatRatingPeriod(p) {
    // e.g. "JUN26" -> "June 2026"
    if (!p) return '';
    const months = { JAN:'January',FEB:'February',MAR:'March',APR:'April',MAY:'May',JUN:'June',JUL:'July',AUG:'August',SEP:'September',OCT:'October',NOV:'November',DEC:'December' };
    const m = months[p.slice(0,3)];
    const y = '20' + p.slice(3);
    return m ? `${m} ${y}` : p;
  }

  // ===== Populate selects =====
  function buildFedSelects() {
    const feds = state.raw.feds.slice().sort((a, b) => {
      const an = state.raw.fedNames[a] || a;
      const bn = state.raw.fedNames[b] || b;
      return an.localeCompare(bn);
    });
    const html = feds
      .map((f) => `<option value="${f}">${state.raw.fedNames[f] || f} (${f})</option>`)
      .join('');
    ['birthCountry', 'currentFed', 'prevFed'].forEach((id) => {
      const sel = document.getElementById(id);
      sel.insertAdjacentHTML('beforeend', html);
    });
  }

  // ===== Filtering =====
  const filterEls = ['search','curMin','curMax','peakMin','peakMax','byMin','byMax','birthCountry','currentFed','prevFed','gender','status'];
  function bindFilters() {
    filterEls.forEach((id) => {
      const el = document.getElementById(id);
      el.addEventListener('input', () => { state.page = 1; applyFilters(); });
      el.addEventListener('change', () => { state.page = 1; applyFilters(); });
    });
    document.getElementById('reset').addEventListener('click', () => {
      filterEls.forEach((id) => { document.getElementById(id).value = ''; });
      state.page = 1;
      applyFilters();
    });
    document.getElementById('downloadCsv').addEventListener('click', downloadCsv);
    // Slash shortcut to focus search
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'SELECT') {
        e.preventDefault();
        document.getElementById('search').focus();
      }
      if (e.key === 'Escape' && state.activeId) closeModal();
    });
  }

  function applyFilters() {
    const q = document.getElementById('search').value.trim().toLowerCase();
    const curMin = num('curMin'); const curMax = num('curMax');
    const peakMin = num('peakMin'); const peakMax = num('peakMax');
    const byMin = num('byMin'); const byMax = num('byMax');
    const birth = document.getElementById('birthCountry').value;
    const curFed = document.getElementById('currentFed').value;
    const prevFed = document.getElementById('prevFed').value;
    const gender = document.getElementById('gender').value;
    const status = document.getElementById('status').value;

    state.filtered = state.raw.players.filter((p) => {
      if (q) {
        const hay = `${p.name} ${p.fed} ${p.fedName} ${p.birthCountry} ${p.birthCountryName} ${p.prevFed}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (curMin != null && (p.rating == null || p.rating < curMin)) return false;
      if (curMax != null && (p.rating == null || p.rating > curMax)) return false;
      if (peakMin != null && p.peak < peakMin) return false;
      if (peakMax != null && p.peak > peakMax) return false;
      if (byMin != null && (p.bday == null || p.bday < byMin)) return false;
      if (byMax != null && (p.bday == null || p.bday > byMax)) return false;
      if (birth && p.birthCountry !== birth) return false;
      if (curFed && p.fed !== curFed) return false;
      if (prevFed && p.prevFed !== prevFed) return false;
      if (gender && p.sex !== gender) return false;
      // Status filter: 'active' = currently rated & active; 'inactive' = living but inactive on FIDE list;
      // 'deceased' = deceased; 'living' = anyone not deceased; 'revoked' = FIDE stripped the GM title.
      // Revoked players are excluded from 'active' / 'living' / 'inactive' by default so they don't
      // pollute normal browsing — the dedicated 'revoked' filter surfaces them.
      if (status === 'active' && (!p.active || p.deceased || p.revoked)) return false;
      if (status === 'inactive' && (p.active || p.deceased || p.revoked)) return false;
      if (status === 'deceased' && !p.deceased) return false;
      if (status === 'living' && (p.deceased || p.revoked)) return false;
      if (status === 'revoked' && !p.revoked) return false;
      return true;
    });

    sortFiltered();
    render();
  }

  function num(id) {
    const v = document.getElementById(id).value.trim();
    if (v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  // ===== Sorting =====
  function bindSort() {
    document.querySelectorAll('#gmTable thead th').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (!k || k === 'rank') return;
        if (state.sort.key === k) {
          state.sort.dir = state.sort.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.sort.key = k;
          state.sort.dir = ['rating', 'peak'].includes(k) ? 'desc' : 'asc';
        }
        sortFiltered();
        render();
      });
    });
  }
  function sortFiltered() {
    const { key, dir } = state.sort;
    const mul = dir === 'asc' ? 1 : -1;
    state.filtered.sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mul;
      if (typeof av === 'boolean') return ((av === bv) ? 0 : av ? -1 : 1) * mul;
      return String(av).localeCompare(String(bv)) * mul;
    });
  }

  // ===== Rendering table =====
  function bindPager() {
    document.getElementById('firstPage').addEventListener('click', () => {
      if (state.page !== 1) { state.page = 1; render(); window.scrollTo({ top: 200, behavior: 'smooth' }); }
    });
    document.getElementById('prevPage').addEventListener('click', () => {
      if (state.page > 1) { state.page--; render(); window.scrollTo({ top: 200, behavior: 'smooth' }); }
    });
    document.getElementById('nextPage').addEventListener('click', () => {
      const total = state.filtered.length;
      if (state.page * state.pageSize < total) { state.page++; render(); window.scrollTo({ top: 200, behavior: 'smooth' }); }
    });
    document.getElementById('lastPage').addEventListener('click', () => {
      const total = state.filtered.length;
      const last = Math.max(1, Math.ceil(total / state.pageSize));
      if (state.page !== last) { state.page = last; render(); window.scrollTo({ top: 200, behavior: 'smooth' }); }
    });
    const pageInput = document.getElementById('pageInput');
    const jumpToPage = () => {
      const total = state.filtered.length;
      const last = Math.max(1, Math.ceil(total / state.pageSize));
      let v = parseInt(pageInput.value, 10);
      if (!Number.isFinite(v)) { pageInput.value = state.page; return; }
      v = Math.max(1, Math.min(last, v));
      if (v !== state.page) { state.page = v; render(); window.scrollTo({ top: 200, behavior: 'smooth' }); }
      else { pageInput.value = state.page; }
    };
    pageInput.addEventListener('change', jumpToPage);
    pageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); jumpToPage(); pageInput.blur(); }
    });
  }

  function render() {
    const tbody = document.getElementById('tbody');
    const total = state.filtered.length;
    document.getElementById('resultCount').textContent = total.toLocaleString();
    // Update header sort indicators
    document.querySelectorAll('#gmTable thead th').forEach((th) => {
      th.classList.toggle('sorted', th.dataset.sort === state.sort.key);
      th.classList.toggle('asc', state.sort.dir === 'asc');
    });

    if (total === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">No grandmasters match these filters.<br><small>Try clearing or widening a filter.</small></td></tr>`;
      document.getElementById('pagInfo').textContent = '';
      document.getElementById('firstPage').disabled = true;
      document.getElementById('prevPage').disabled = true;
      document.getElementById('nextPage').disabled = true;
      document.getElementById('lastPage').disabled = true;
      const pi = document.getElementById('pageInput'); pi.value = ''; pi.disabled = true;
      document.getElementById('pageTotal').textContent = 'of 0';
      return;
    }

    const start = (state.page - 1) * state.pageSize;
    const end = Math.min(start + state.pageSize, total);
    const slice = state.filtered.slice(start, end);

    tbody.innerHTML = slice
      .map((p, i) => {
        const rank = start + i + 1;
        const initials = getInitials(p.name);
        const isTop = p.rating >= 2700;
        let statusCls, statusLabel;
        if (p.revoked) {
          statusCls = 'revoked';
          statusLabel = p.revokedYear ? `Revoked ${p.revokedYear}` : 'Title Revoked';
        } else if (p.deceased) {
          statusCls = 'deceased';
          statusLabel = p.deathYear ? `† ${p.deathYear}` : 'Deceased';
        } else if (p.active) {
          statusCls = 'active';
          statusLabel = 'Active';
        } else {
          statusCls = '';
          statusLabel = 'Inactive';
        }
        const bornCell = p.bday ?? '—';
        const avatarHtml = p.photo
          ? `<span class="player-avatar has-photo" aria-hidden="true" style="background-image:url('${escapeHtml(p.photo)}')"></span>`
          : `<span class="player-avatar" aria-hidden="true">${initials}</span>`;
        return `<tr data-id="${p.id}">
          <td class="num" style="color:var(--text-muted)">${rank}</td>
          <td>
            <div class="player-name">
              ${avatarHtml}
              <strong>${escapeHtml(p.name)}</strong>
            </div>
          </td>
          <td><span class="fed-cell">${fedFlag(p.fed) ? `<span class="fed-flag" aria-hidden="true">${fedFlag(p.fed)}</span>` : ''}<span>${escapeHtml(p.fedName)}</span></span></td>
          <td class="num rating-cell ${isTop ? 'top' : ''}">${p.rating ?? '—'}</td>
          <td class="num">${p.peak}</td>
          <td class="num">${bornCell}</td>
          <td>${p.sex === 'F' ? 'Female' : p.sex === 'M' ? 'Male' : '—'}</td>
          <td><span class="status-dot ${statusCls}">${statusLabel}</span></td>
        </tr>`;
      })
      .join('');

    // Bind row clicks
    tbody.querySelectorAll('tr[data-id]').forEach((tr) => {
      tr.addEventListener('click', () => openProfile(tr.dataset.id));
    });

    document.getElementById('pagInfo').textContent =
      `Showing ${(start + 1).toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()}`;
    const lastPg = Math.max(1, Math.ceil(total / state.pageSize));
    document.getElementById('firstPage').disabled = state.page === 1;
    document.getElementById('prevPage').disabled = state.page === 1;
    document.getElementById('nextPage').disabled = end >= total;
    document.getElementById('lastPage').disabled = state.page === lastPg;
    const pi = document.getElementById('pageInput');
    pi.disabled = false;
    pi.max = lastPg;
    pi.value = state.page;
    document.getElementById('pageTotal').textContent = `of ${lastPg.toLocaleString()}`;
  }

  function getInitials(name) {
    // FIDE format is "Last, First" — show First-letter + Last-letter for chess vibe
    const parts = name.split(',').map((s) => s.trim()).filter(Boolean);
    if (parts.length === 2) {
      return (parts[1][0] + parts[0][0]).toUpperCase();
    }
    const tokens = name.split(/\s+/);
    return ((tokens[0] || '?')[0] + (tokens[1] || '')[0] || '').toUpperCase();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // ===== CSV export =====
  function csvCell(v) {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }
  function downloadCsv() {
    const cols = [
      { label: 'Rank',                     val: (_, i) => i + 1 },
      { label: 'Name',                     val: (p) => p.name },
      { label: 'Federation Code',          val: (p) => p.fed },
      { label: 'Federation',               val: (p) => p.fedName },
      { label: 'Previous Federation Code', val: (p) => p.prevFed },
      { label: 'Previous Federation',      val: (p) => p.prevFedName },
      { label: 'Federation History',       val: (p) => Array.isArray(p.fedHistoryNames) ? p.fedHistoryNames.join(' -> ') : '' },
      { label: 'Federation History Codes', val: (p) => Array.isArray(p.fedHistory) ? p.fedHistory.join(' -> ') : '' },
      { label: 'Current Rating',           val: (p) => p.rating },
      { label: 'Peak Rating',              val: (p) => p.peak },
      { label: 'Birth Year',               val: (p) => p.bday },
      { label: 'GM Title Year',            val: (p) => p.gmYear ?? '' },
      { label: 'Birth City',               val: (p) => p.birthCity },
      { label: 'Birth Country',            val: (p) => p.birthCountryName },
      { label: 'Gender',                   val: (p) => p.sex === 'F' ? 'Female' : 'Male' },
      { label: 'Status',                   val: (p) => p.revoked ? (p.revokedYear ? `Title Revoked (${p.revokedYear})` : 'Title Revoked') : p.deceased ? (p.deathYear ? `Deceased (${p.deathYear})` : 'Deceased') : (p.active ? 'Active' : 'Inactive') },
      { label: 'Title Revoked Year',       val: (p) => p.revokedYear ?? '' },
      { label: 'Title Revoked Reason',     val: (p) => p.revokedReason ?? '' },
      { label: 'Games',                    val: (p) => p.games },
      { label: 'Playstyle',                val: (p) => p.style ? topStyleAxis(p.style).label : '' },
      { label: 'FIDE ID',                  val: (p) => p.id },
    ];
    const rows = state.filtered;
    const header = cols.map((c) => csvCell(c.label)).join(',');
    const body = rows.map((p, i) => cols.map((c) => csvCell(c.val(p, i))).join(',')).join('\n');
    const csv = '\uFEFF' + header + '\n' + body + '\n';
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const stamp = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `grandmaster-almanac_${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ===== Modal / profile =====
  const modalRoot = document.getElementById('modalRoot');
  function bindModal() {
    modalRoot.querySelectorAll('[data-close]').forEach((el) => el.addEventListener('click', closeModal));
    // Hash-driven deep links — react to back/forward as well
    window.addEventListener('hashchange', syncFromHash);
  }
  function openProfile(id) {
    state.activeId = id;
    renderProfile(id, true);
    modalRoot.hidden = false;
    document.body.style.overflow = 'hidden';
    if (location.hash !== '#p-' + id) {
      history.pushState(null, '', '#p-' + id);
    }
  }
  function closeModal() {
    modalRoot.hidden = true;
    state.activeId = null;
    document.body.style.overflow = '';
    if (state.eloChart) { state.eloChart.destroy(); state.eloChart = null; }
    if (state.radarChart) { state.radarChart.destroy(); state.radarChart = null; }
    if (location.hash.startsWith('#p-')) {
      history.pushState(null, '', location.pathname + location.search);
    }
  }
  function syncFromHash() {
    const m = location.hash.match(/^#p-(.+)$/);
    if (m) {
      const id = decodeURIComponent(m[1]);
      const exists = state.raw && state.raw.players.some((x) => x.id === id);
      if (exists && state.activeId !== id) {
        state.activeId = id;
        renderProfile(id, true);
        modalRoot.hidden = false;
        document.body.style.overflow = 'hidden';
      }
    } else if (state.activeId) {
      // Hash cleared while modal open — close without re-pushing history
      modalRoot.hidden = true;
      state.activeId = null;
      document.body.style.overflow = '';
      if (state.eloChart) { state.eloChart.destroy(); state.eloChart = null; }
      if (state.radarChart) { state.radarChart.destroy(); state.radarChart = null; }
    }
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

  function renderProfile(id, animate) {
    const p = state.raw.players.find((x) => x.id === id);
    if (!p) return;
    const c = chartColors();
    document.getElementById('modalContent').innerHTML = profileTemplate(p);

    // Stats — rank reflects current view: filtered position if filters narrow the set,
    // otherwise the global FIDE rank in the full player pool.
    const filtersActive = state.filtered.length !== state.raw.players.length;
    const rankList = filtersActive ? state.filtered : state.raw.players;
    const rank = rankList.findIndex((x) => x.id === id) + 1;
    document.getElementById('p-rank-label').textContent = filtersActive ? 'Rank in view' : 'World Rank';
    document.getElementById('p-rank').textContent = rank > 0 ? `#${rank.toLocaleString()}` : '—';

    // Build ELO chart
    if (state.eloChart) state.eloChart.destroy();
    if (state.radarChart) state.radarChart.destroy();
    const axis = state.raw.historyAxis;
    const labels = axis.map((d) => {
      const [y, m] = d.split('-');
      return `${y}-${m}`;
    });
    const hasHistory = p.history.some((v) => v != null);
    const eloCanvas = document.getElementById('eloChart');
    if (!hasHistory) {
      // Replace canvas with a friendly placeholder for pre-2016 deceased players
      const placeholder = document.createElement('div');
      placeholder.className = 'chart-placeholder';
      const era = (p.bday && p.deathYear) ? `${p.bday}\u2013${p.deathYear}` : (p.deathYear ? `\u2020 ${p.deathYear}` : 'historical');
      placeholder.innerHTML = `<div class="cp-icon">\u265E</div><div class="cp-text"><strong>No rating data 2016\u20132026</strong><div class="cp-sub">${escapeHtml(p.name.split(',')[0])} played before the modern rating window (${era}). Estimated peak rating: <b>${p.peak}</b>.</div></div>`;
      eloCanvas.replaceWith(placeholder);
      state.eloChart = null;
    } else {
    state.eloChart = new Chart(eloCanvas, {
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
        animation: animate ? { duration: 500 } : false,
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

    }
    // Radar chart
    const s = p.style;
    state.radarChart = new Chart(document.getElementById('radarChart'), {
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
        animation: animate ? { duration: 500 } : false,
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

    // Wire share button
    document.getElementById('downloadShare').addEventListener('click', () => downloadCard(p));
  }

  function profileTemplate(p) {
    const initials = getInitials(p.name);
    const ageStr = p.age != null ? (p.deceased ? `lived ${p.age} yrs` : `${p.age} yrs`) : '—';
    const gameMode = p.sex === 'F' ? 'Female' : 'Male';
    let statusLabel;
    if (p.revoked) statusLabel = p.revokedYear ? `<span class="revoked-pill" title="${escapeHtml(p.revokedReason || '')}">Title Revoked ${p.revokedYear}</span>` : `<span class="revoked-pill">Title Revoked</span>`;
    else if (p.deceased) statusLabel = p.deathYear ? `Deceased (${p.deathYear})` : 'Deceased';
    else if (p.active) statusLabel = 'Active';
    else statusLabel = 'Inactive';
    // Federation history: show full chain when player has more than one prior federation.
    // For a single transfer (chain length 2), preserve the existing "Previously X" wording.
    let transfer = '';
    const fh = Array.isArray(p.fedHistoryNames) ? p.fedHistoryNames : null;
    if (fh && fh.length > 2) {
      // Drop the trailing entry (current federation) — it's already shown immediately before.
      const priors = fh.slice(0, -1).map(escapeHtml).join(' → ');
      transfer = `<span class="sep">·</span>Previously ${priors}`;
    } else if (p.fed !== p.prevFed) {
      transfer = `<span class="sep">·</span>Previously ${escapeHtml(p.prevFedName)}`;
    }
    // Build birthplace: suppress country when it matches the player's current federation
    // and we already have a city (avoids "Norway · Born in Tønsberg, Norway" stutter).
    const birthParts = [];
    if (p.birthCity) birthParts.push(escapeHtml(p.birthCity));
    const sameCountry = p.birthCountry && p.birthCountry === p.fed;
    if (p.birthCountryName && !(sameCountry && p.birthCity)) {
      birthParts.push(escapeHtml(p.birthCountryName));
    }
    const birthPlace = birthParts.length
      ? `<span class="sep">·</span>Born in ${birthParts.join(', ')}`
      : '';
    const avatarHtml = p.photo
      ? `<div class="profile-avatar has-photo" style="background-image:url('${escapeHtml(p.photo)}')" aria-label="${escapeHtml(p.name)}"></div>`
      : `<div class="profile-avatar">${initials}</div>`;
    const revokedNote = p.revoked && p.revokedReason
      ? `<div class="revoked-note"><strong>Title revoked${p.revokedYear ? ` (${p.revokedYear})` : ''}.</strong> ${escapeHtml(p.revokedReason)}</div>`
      : '';
    return `
      <div class="profile-head">
        ${avatarHtml}
        <div>
          <div id="modalName" class="profile-name">${escapeHtml(p.name)}</div>
          <div class="profile-meta">
            ${escapeHtml(p.fedName)}${birthPlace}${transfer}
            <span class="sep">·</span>${ageStr}<span class="sep">·</span>${gameMode}<span class="sep">·</span>${statusLabel}
          </div>
        </div>
      </div>
      ${revokedNote}

      <div class="stat-row">
        <div class="stat"><div class="stat-label">Current ELO</div><div class="stat-value">${p.rating ?? '—'}</div></div>
        <div class="stat"><div class="stat-label">Peak ELO</div><div class="stat-value">${p.peak}</div></div>
        <div class="stat"><div class="stat-label">${p.deceased ? 'Lifespan' : 'Born'}</div><div class="stat-value">${p.bday ?? '—'}${p.deceased && p.deathYear ? ` – ${p.deathYear}` : ''}</div></div>
        <div class="stat"><div class="stat-label">GM Title</div><div class="stat-value">${p.revoked && p.gmYear && p.revokedYear ? `<span class="gm-revoked">${p.gmYear} <span class="gm-arrow">→</span> ${p.revokedYear}</span>` : (p.gmYear ?? '—')}</div></div>
        <div class="stat"><div class="stat-label">Games</div><div class="stat-value">${p.games || 0}</div></div>
        <div class="stat"><div class="stat-label" id="p-rank-label">World Rank</div><div class="stat-value" id="p-rank">—</div></div>
      </div>

      <div class="profile-body">
        <div class="chart-card">
          <div class="chart-title">10-Year Rating Trend</div>
          <div class="chart-box"><canvas id="eloChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-title">Playstyle Radar</div>
          <div class="chart-box"><canvas id="radarChart"></canvas></div>
        </div>
      </div>

      <details class="share-section" id="shareDetails">
        <summary class="share-summary">
          <span class="share-summary-label">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
            Generate shareable career card
          </span>
          <span class="share-summary-chevron" aria-hidden="true">›</span>
        </summary>
        <div class="share-body">
          <div id="shareCard">${shareCardHTML(p)}</div>
          <div class="share-actions">
            <button class="primary-btn" id="downloadShare" type="button">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14"/></svg>
              Download PNG
            </button>
          </div>
        </div>
      </details>
    `;
  }

  function shareCardHTML(p) {
    const styleTop = topStyleAxis(p.style);
    const tagline = generateTagline(p, styleTop);
    return `
      <div class="share-card" id="shareCardEl">
        <div class="sc-knight">♞</div>
        <div class="sc-head">
          <div class="sc-brand">Grandmaster Almanac</div>
          <div class="sc-flag">${fedFlag(p.fed) || p.fed}</div>
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
          <span>${p.bday ? 'Est. ' + p.bday : ''}</span>
        </div>
      </div>
    `;
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
        // Skip remote stylesheets we cannot read due to CORS (Google Fonts)
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
})();
