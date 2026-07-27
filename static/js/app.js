'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  allRecords:    [],
  activeGroup:   'all',
  activeSource:  'all',
  hideDups:      false,
  lastQuery:     null,
  marker:        null,
  radiusCircle:  null,
  pointMarkers:  [],
};

// Source colours (mirror CSS)
const SOURCE_COLOR  = { Flora_Funga: '#2d7a3a', SpeciesLink: '#6ba35a', GBIF: '#a8c84a' };
const SOURCE_LABEL  = { Flora_Funga: 'Flora e Funga', SpeciesLink: 'SpeciesLink', GBIF: 'GBIF' };
const GROUP_EMOJI   = { Angiospermae:'🌸', Gymnospermae:'🌲', Pteridophyta:'🌿', Bryophyta:'🪴' };

// ── Map ───────────────────────────────────────────────────────────────────
const map = L.map('map', { zoomControl: true }).setView([-15.0, -52.0], 5);

L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '© OpenStreetMap © CARTO',
  maxZoom: 18,
}).addTo(map);

map.on('click', e => {
  document.getElementById('lat').value = e.latlng.lat.toFixed(5);
  document.getElementById('lon').value = e.latlng.lng.toFixed(5);
  updateMarker(e.latlng.lat, e.latlng.lng);
  document.getElementById('map-coords').textContent =
    `${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`;
});

map.on('mousemove', e => {
  document.getElementById('map-coords').textContent =
    `${e.latlng.lat.toFixed(4)}, ${e.latlng.lng.toFixed(4)}`;
});

function updateMarker(lat, lon) {
  if (state.marker)      map.removeLayer(state.marker);
  if (state.radiusCircle) map.removeLayer(state.radiusCircle);

  const radius = parseInt(document.getElementById('radius').value) * 1000;

  state.marker = L.circleMarker([lat, lon], {
    radius: 7, color: '#1e3a22', fillColor: '#4a8c55',
    fillOpacity: 1, weight: 2,
  }).addTo(map);

  state.radiusCircle = L.circle([lat, lon], {
    radius, color: '#4a8c55', fillColor: '#4a8c55',
    fillOpacity: 0.05, weight: 1.5, dashArray: '6 5',
  }).addTo(map);
}

function clearPointMarkers() {
  state.pointMarkers.forEach(m => map.removeLayer(m));
  state.pointMarkers = [];
}

function plotOccurrencePoints(records) {
  clearPointMarkers();
  const visible = records.filter(r => !r.is_duplicate || !state.hideDups);
  visible.forEach(r => {
    if (!r.latitude || !r.longitude) return;
    const color = SOURCE_COLOR[r.source_bank] || '#4a8c55';
    const m = L.circleMarker([r.latitude, r.longitude], {
      radius: 4, color, fillColor: color,
      fillOpacity: r.is_duplicate ? 0.3 : 0.75,
      weight: 1,
    }).addTo(map).bindPopup(
      `<b><i>${r.accepted_name || r.species_name}</i></b><br>` +
      `${SOURCE_LABEL[r.source_bank] || r.source_bank}<br>` +
      `${r.municipality || ''} ${r.state || ''} ${r.year || ''}`
    );
    state.pointMarkers.push(m);
  });
}

// ── Sliders ───────────────────────────────────────────────────────────────
document.getElementById('radius').addEventListener('input', function () {
  document.getElementById('radius-val').textContent = this.value;
  const lat = parseFloat(document.getElementById('lat').value);
  const lon = parseFloat(document.getElementById('lon').value);
  if (!isNaN(lat) && !isNaN(lon)) updateMarker(lat, lon);
});

document.getElementById('top').addEventListener('input', function () {
  const v = parseInt(this.value);
  document.getElementById('top-val').textContent = v >= 500 ? 'All' : v;
  if (state.allRecords.length) renderFiltered();
});

// ── Group tabs ────────────────────────────────────────────────────────────
document.querySelectorAll('.gtab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.gtab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    state.activeGroup = btn.dataset.group;
    if (state.allRecords.length) renderFiltered();
  });
});

// ── Source radio ──────────────────────────────────────────────────────────
document.querySelectorAll('input[name="source"]').forEach(r => {
  r.addEventListener('change', () => {
    state.activeSource = r.value;
    if (state.allRecords.length) renderFiltered();
  });
});

// ── Hide duplicates ───────────────────────────────────────────────────────
document.getElementById('hide-duplicates').addEventListener('change', function () {
  state.hideDups = this.checked;
  if (state.allRecords.length) renderFiltered();
});

// ── Run ───────────────────────────────────────────────────────────────────
document.getElementById('run-btn').addEventListener('click', runSearch);

async function runSearch() {
  const lat    = parseFloat(document.getElementById('lat').value);
  const lon    = parseFloat(document.getElementById('lon').value);
  const radius = parseInt(document.getElementById('radius').value);

  if (isNaN(lat) || isNaN(lon)) {
    showStatus('error', 'Enter valid coordinates first.');
    return;
  }

  const params = new URLSearchParams({ lat, lon, radius, group: 'all', source: 'all' });
  setRunning(true);
  showStatus('loading', 'Querying occurrence records…');
  updateMarker(lat, lon);
  map.setView([lat, lon], Math.max(map.getZoom(), 6));

  try {
    const res = await fetch(`/api/occurrences?${params}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    const data = await res.json();
    state.allRecords = data.records || [];
    state.lastQuery  = data;

    renderResults(data);
    plotOccurrencePoints(state.allRecords);
    showStatus('success',
      `${data.n_unique} unique points · ${data.n_total} total records · ${data.n_species} species`);
  } catch (e) {
    showStatus('error', `Error: ${e.message}`);
  }
  setRunning(false);
}

function setRunning(on) {
  const btn = document.getElementById('run-btn');
  btn.disabled = on;
  btn.innerHTML = on ? '⏳ Searching…' : '🔍 Find Occurrences';
}

// ── Render ────────────────────────────────────────────────────────────────
function renderResults(data) {
  const q = data.query || {};
  document.getElementById('results-meta').classList.remove('hidden');
  document.getElementById('results-meta').innerHTML =
    `<strong>${q.lat?.toFixed(4)}, ${q.lon?.toFixed(4)}</strong> &nbsp;·&nbsp; ` +
    `radius ${q.radius_km} km &nbsp;·&nbsp; ` +
    `${data.n_species} species · ${data.n_unique} unique points`;

  document.getElementById('export-btn').classList.remove('hidden');
  renderGroupBar(state.allRecords);
  renderFiltered();
}

function renderGroupBar(records) {
  const bar = document.getElementById('group-bar');
  const counts = {};
  records.forEach(r => { counts[r.group] = (counts[r.group] || 0) + 1; });

  const all = `<span class="gbar-chip gbar-all" data-grp="all">All <b>${records.length}</b></span>`;
  const chips = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([g, n]) => {
      const cls = 'gbar-chip gbar-' + (
        g === 'Angiospermae' ? 'angio' :
        g === 'Gymnospermae' ? 'gymno' :
        g === 'Pteridophyta' ? 'ptero' :
        g === 'Bryophyta'    ? 'bryo'  : 'all'
      );
      return `<span class="${cls}" data-grp="${g}">${GROUP_EMOJI[g] || ''} ${g.replace('ae','').replace('phyta','')} <b>${n}</b></span>`;
    }).join('');

  bar.innerHTML = all + chips;
  bar.classList.remove('hidden');

  bar.querySelectorAll('.gbar-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      state.activeGroup = chip.dataset.grp;
      document.querySelectorAll('.gtab').forEach(b =>
        b.classList.toggle('active', b.dataset.group === state.activeGroup));
      renderFiltered();
    });
  });
}

function renderFiltered() {
  let list = state.allRecords;

  if (state.activeGroup !== 'all')
    list = list.filter(r => r.group === state.activeGroup);
  if (state.activeSource !== 'all')
    list = list.filter(r => r.source_bank === state.activeSource);
  if (state.hideDups)
    list = list.filter(r => !r.is_duplicate);

  const topVal = parseInt(document.getElementById('top').value);
  if (topVal < 500) list = list.slice(0, topVal);

  renderCards(list);
  plotOccurrencePoints(list);
}

// ── Cards ─────────────────────────────────────────────────────────────────
function renderCards(records) {
  const container = document.getElementById('results-list');
  if (!records.length) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🔎</div>
      <p>No records match the current filters.</p>
    </div>`;
    return;
  }
  container.innerHTML = records.map((r, i) => cardHTML(r, i + 1)).join('');
  container.querySelectorAll('.species-card').forEach((el, i) => {
    el.addEventListener('click', () => openModal(records[i]));
  });
}

function cardHTML(r, rank) {
  const srcColor  = SOURCE_COLOR[r.source_bank] || '#4a8c55';
  const srcCls    = r.source_bank === 'Flora_Funga' ? 'sb-flora' :
                    r.source_bank === 'SpeciesLink'  ? 'sb-splink' : 'sb-gbif';
  const iucn      = r.iucn_status || 'NE';
  const accepted  = r.accepted_name || r.species_name || '';
  const isDup     = r.is_duplicate;
  const endemic   = r.endemic_brazil === true || r.endemic_brazil === 'true';
  const nameStatus = r.name_status === 'Synonym'
    ? `<span class="dup-badge">Syn.</span>` : '';

  return `
    <div class="species-card" style="--source-color:${srcColor}">
      <div class="sp-rank">${rank}</div>
      <div class="sp-body">
        <div class="sp-name">${accepted}</div>
        <div class="sp-common">${r.family || ''} ${r.state ? '· ' + r.state : ''}</div>
        <div class="sp-tags">
          <span class="badge src-badge ${srcCls}">${SOURCE_LABEL[r.source_bank] || r.source_bank}</span>
          ${endemic ? '<span class="endemic-badge">Endemic</span>' : ''}
          ${iucn !== 'NE' ? `<span class="badge ${iucnClass(iucn)}">${iucn}</span>` : ''}
          ${nameStatus}
          ${isDup ? '<span class="dup-badge">duplicate</span>' : ''}
          ${r.year ? `<span style="font-family:var(--font-mono);font-size:10px;color:var(--slate)">${r.year}</span>` : ''}
        </div>
      </div>
      <div class="sp-count-col">
        <span class="sp-count-val">${r.total_unique_points || 0}</span>
        <span class="sp-count-lbl">pts</span>
      </div>
    </div>`;
}

function iucnClass(s) {
  const m = {LC:'iucn-lc',NT:'iucn-nt',VU:'iucn-vu',EN:'iucn-en',CR:'iucn-cr',DD:'iucn-dd'};
  return m[s] || 'iucn-ne';
}

// ── Detail modal ──────────────────────────────────────────────────────────
function openModal(r) {
  const maxCount = Math.max(r.flora_funga_n || 0, r.specieslink_n || 0, r.gbif_n || 0, 1);

  const barHTML = (label, n, cls) => {
    const pct = Math.round((n / maxCount) * 100);
    return `<div class="src-bar-row">
      <span class="src-bar-lbl">${label}</span>
      <div class="src-bar-track"><div class="src-bar-fill ${cls}" style="width:${pct}%"></div></div>
      <span class="src-bar-val">${n}</span>
    </div>`;
  };

  const tableRows = [
    ['Accepted name',  r.accepted_name || '—'],
    ['Name status',    r.name_status || '—'],
    ['Family',         r.family || '—'],
    ['Order',          r.order || '—'],
    ['Group',          r.group || '—'],
    ['Life form',      r.life_form || '—'],
    ['Endemic Brazil', r.endemic_brazil === true || r.endemic_brazil === 'true' ? 'Yes' : 'No'],
    ['Biomes',         r.biomes || r.biome || '—'],
    ['State',          r.state || '—'],
    ['Municipality',   r.municipality || '—'],
    ['Year',           r.year || '—'],
    ['Collector',      r.collector || '—'],
    ['Catalog no.',    r.catalog_number || '—'],
    ['Institution',    r.institution_code || '—'],
    ['Basis',          r.basis_of_record || '—'],
    ['Is native',      r.is_native || '—'],
    ['Is duplicate',   r.is_duplicate ? 'Yes (cross-bank)' : 'No'],
    ['Coordinates',    r.latitude && r.longitude
                       ? `${parseFloat(r.latitude).toFixed(5)}, ${parseFloat(r.longitude).toFixed(5)}` : '—'],
    ['Precision',      r.coordinate_precision_m != null ? `${r.coordinate_precision_m} m` : '—'],
    ['Source bank',    SOURCE_LABEL[r.source_bank] || r.source_bank || '—'],
    ['Record ID',      r.record_id || '—'],
  ].map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');

  document.getElementById('modal-body').innerHTML = `
    <div class="modal-sp-name">${r.accepted_name || r.species_name}</div>
    <div class="modal-accepted">
      ${r.species_name !== r.accepted_name && r.species_name
        ? `As recorded: <em>${r.species_name}</em>` : ''}
    </div>
    <div class="modal-badges">
      <span class="badge src-badge ${r.source_bank === 'Flora_Funga' ? 'sb-flora' : r.source_bank === 'SpeciesLink' ? 'sb-splink' : 'sb-gbif'}">${SOURCE_LABEL[r.source_bank] || r.source_bank}</span>
      ${r.iucn_status && r.iucn_status !== 'NE' ? `<span class="badge ${iucnClass(r.iucn_status)}">${r.iucn_status}</span>` : ''}
      ${r.endemic_brazil === true || r.endemic_brazil === 'true' ? '<span class="endemic-badge">Endemic to Brazil</span>' : ''}
      ${r.is_duplicate ? '<span class="dup-badge">Cross-bank duplicate</span>' : ''}
    </div>

    <div class="sec-label">Occurrence counts for this species</div>
    <div class="source-bars" style="margin-bottom:14px">
      ${barHTML('Flora e Funga', r.flora_funga_n || 0, 'fill-flora')}
      ${barHTML('SpeciesLink',   r.specieslink_n  || 0, 'fill-splink')}
      ${barHTML('GBIF',          r.gbif_n         || 0, 'fill-gbif')}
    </div>
    <div style="font-family:var(--font-mono);font-size:10px;color:var(--slate);margin-bottom:16px">
      Total unique points (deduped): <strong style="color:var(--forest)">${r.total_unique_points || 0}</strong>
    </div>

    <div class="sec-label">Record details</div>
    <table class="modal-tbl">${tableRows}</table>
  `;

  document.getElementById('modal').classList.remove('hidden');
}

document.getElementById('modal-close').addEventListener('click', () =>
  document.getElementById('modal').classList.add('hidden'));
document.getElementById('modal-bg').addEventListener('click', () =>
  document.getElementById('modal').classList.add('hidden'));

// ── CSV export ────────────────────────────────────────────────────────────
document.getElementById('export-btn').addEventListener('click', () => {
  if (!state.allRecords.length) return;

  let list = state.allRecords;
  if (state.activeGroup !== 'all') list = list.filter(r => r.group === state.activeGroup);
  if (state.activeSource !== 'all') list = list.filter(r => r.source_bank === state.activeSource);
  if (state.hideDups) list = list.filter(r => !r.is_duplicate);
  const topVal = parseInt(document.getElementById('top').value);
  if (topVal < 500) list = list.slice(0, topVal);

  const cols = [
    'record_id','species_name','accepted_name','name_status','family','order',
    'group','life_form','endemic_brazil','biome','state','municipality',
    'latitude','longitude','coordinate_precision_m','year','collector',
    'catalog_number','institution_code','source_bank','basis_of_record',
    'is_native','is_duplicate','duplicate_of',
    'gbif_n','flora_funga_n','specieslink_n','total_unique_points'
  ];
  const header = cols.join(',');
  const rows = list.map(r =>
    cols.map(c => {
      const v = r[c] ?? '';
      return String(v).includes(',') ? `"${v}"` : v;
    }).join(',')
  );

  const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const q = state.lastQuery?.query || {};
  a.download = `epov_${(q.lat||0).toFixed(2)}_${(q.lon||0).toFixed(2)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
});

// ── Status ────────────────────────────────────────────────────────────────
function showStatus(type, msg) {
  const el = document.getElementById('status');
  el.className = `status ${type}`;
  el.textContent = msg;
  el.classList.remove('hidden');
}

// ── File upload + validation ──────────────────────────────────────────────
document.getElementById('list-file').addEventListener('change', function () {
  const name = this.files[0]?.name || 'Choose .txt file';
  document.getElementById('upload-text').textContent = name;
  document.getElementById('validate-btn').disabled = !this.files[0];
});

document.getElementById('validate-btn').addEventListener('click', runValidation);

async function runValidation() {
  const file = document.getElementById('list-file').files[0];
  if (!file) return;
  const lat = parseFloat(document.getElementById('lat').value);
  const lon = parseFloat(document.getElementById('lon').value);
  if (isNaN(lat) || isNaN(lon)) {
    alert('Set coordinates before validating.');
    return;
  }

  openValModal('<div class="val-loading">⏳ Validating against GBIF occurrences…</div>');

  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch(`/api/validate-list?lat=${lat}&lon=${lon}`,
                            { method: 'POST', body: form });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderValResults(data, lat, lon);
  } catch (e) {
    openValModal(`<div style="color:var(--rust);padding:20px">Error: ${e.message}</div>`);
  }
}

function probClass(label) {
  if (!label) return 'prob-nd';
  const l = label.toLowerCase();
  if (l.includes('very likely'))   return 'prob-vl';
  if (l.includes('likely'))        return 'prob-l';
  if (l.includes('possible'))      return 'prob-p';
  if (l.includes('very unlikely')) return 'prob-vu';
  if (l.includes('unlikely'))      return 'prob-u';
  return 'prob-nd';
}

function renderValResults(data, lat, lon) {
  const rows = (data.results || []).map(r => {
    const dist = r.nearest_distance_km != null
      ? `<span style="font-family:var(--font-mono);font-size:10px">${r.nearest_distance_km.toFixed(0)} km</span>`
      : '<span style="opacity:.4">—</span>';
    const geo = r.geographically_compatible
      ? '<span style="color:var(--canopy)">✓</span>'
      : '<span style="color:var(--rust)">✗</span>';
    return `<tr>
      <td><em>${r.species}</em><br>
        <span style="font-size:10px;color:var(--slate)">${r.family || ''}</span>
      </td>
      <td><span class="badge src-badge ${r.group==='Angiospermae'?'sb-flora':r.group==='Bryophyta'?'sb-gbif':'sb-splink'}">${r.group||'—'}</span></td>
      <td>${dist}</td>
      <td>${geo}</td>
      <td><span class="prob-badge ${probClass(r.probability_label)}">${r.probability_label}</span></td>
      <td style="font-family:var(--font-mono);font-size:10px;color:var(--slate)">${((r.occurrence_score||0)*100).toFixed(0)}%</td>
    </tr>`;
  }).join('');

  openValModal(`
    <div class="val-title-lg">Species list validation</div>
    <div class="val-subtitle">
      ${data.n_processed} species · ${lat.toFixed(4)}, ${lon.toFixed(4)} ·
      GBIF occurrence proximity
    </div>
    <table class="val-table">
      <thead><tr>
        <th>Species</th><th>Group</th>
        <th>Nearest occ.</th><th>In range</th>
        <th>Probability</th><th>Score</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `);
}

function openValModal(html) {
  document.getElementById('val-modal-body').innerHTML = html;
  document.getElementById('val-modal').classList.remove('hidden');
}

document.getElementById('val-modal-close').addEventListener('click', () =>
  document.getElementById('val-modal').classList.add('hidden'));
document.getElementById('val-modal-bg').addEventListener('click', () =>
  document.getElementById('val-modal').classList.add('hidden'));

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('modal').classList.add('hidden');
    document.getElementById('val-modal').classList.add('hidden');
  }
});

// ── Init ──────────────────────────────────────────────────────────────────
updateMarker(-15.78, -47.93);
