/* main.js — Cairo Smart Transportation System frontend logic */

const API = '';   // same origin; prefix with http://localhost:5000 for dev

// ─── State ────────────────────────────────────────────────────────────────
let graphData   = null;   // { nodes, edges }
let mstData     = null;
let emergencyNode = null;
let schedChart  = null;
let maintChart  = null;
let losChart    = null;
let forecastChart = null;
let featureChart  = null;

// ─── Boot ─────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  updateClock();
  setInterval(updateClock, 30000);
  setupTabs();
  await fetchSummary();
  await loadGraph();
  populateSelects();
  runSchedule();
  runMaintenance();
  runSignals();
});

function updateClock() {
  const el = document.getElementById('live-time');
  if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── Tabs ─────────────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.tab;
      document.getElementById('tab-' + tab).classList.add('active');
      if (tab === 'mst')    { setTimeout(() => { if (graphData) loadMST(); }, 50); }
      if (tab === 'routing') { loadTrafficTable(); }
      if (tab === 'race')   { populateRaceSelects(); }
      if (tab === 'ml')     { runForecast(); }
    });
  });
}

// ─── Summary ──────────────────────────────────────────────────────────────
async function fetchSummary() {
  try {
    const r = await fetch(API + '/api/summary');
    const d = await r.json();
    setText('m-nodes', d.nodes - d.facilities_count);
    setText('m-edges', d.existing_edges);
  } catch (e) { console.warn('summary', e); }
}

// ─── Graph ────────────────────────────────────────────────────────────────
async function loadGraph() {
  const time = val('net-time');
  try {
    const r = await fetch(API + `/api/graph?time=${time}`);
    graphData = await r.json();
    const canvas = document.getElementById('netCanvas');
    canvas.height = 420;
    drawNetwork(canvas, graphData.nodes, graphData.edges);
  } catch (e) { console.warn('graph', e); }
}

// ─── Populate selects ─────────────────────────────────────────────────────
function populateSelects() {
  if (!graphData) return;
  const ids = graphData.nodes.map(n => ({ id: n.id, name: n.name }));
  ['dijk-src', 'dijk-dst', 'astar-src'].forEach(selId => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    sel.innerHTML = '';
    ids.forEach(n => {
      const o = document.createElement('option');
      o.value = n.id; o.textContent = n.name;
      sel.appendChild(o);
    });
  });
  const ds = document.getElementById('dijk-src');
  const dd = document.getElementById('dijk-dst');
  if (ds) ds.value = '1';
  if (dd) dd.value = '3';
  const as = document.getElementById('astar-src');
  if (as) as.value = '4';
  populateRaceSelects();
}

function populateRaceSelects() {
  if (!graphData) return;
  const ids = graphData.nodes.map(n => ({ id: n.id, name: n.name }));
  ['race-src', 'race-dst'].forEach(selId => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    if (sel.options.length === 0) {
      ids.forEach(n => {
        const o = document.createElement('option');
        o.value = n.id; o.textContent = n.name;
        sel.appendChild(o);
      });
    }
  });
  const rs = document.getElementById('race-src');
  const rd = document.getElementById('race-dst');
  if (rs && !rs.value) rs.value = '7';
  if (rd && !rd.value) rd.value = 'F9';
}

// ─── MST ──────────────────────────────────────────────────────────────────
async function loadMST() {
  const algo      = val('mst-algo');
  const potential = document.getElementById('mst-potential').checked;
  try {
    const r = await fetch(API + `/api/mst?algo=${algo}&potential=${potential}`);
    mstData = await r.json();

    const canvas = document.getElementById('mstCanvas');
    canvas.height = 400;
    if (graphData) {
      drawNetwork(canvas, graphData.nodes, graphData.edges, {
        mstEdges: mstData.edges,
        highlightColor: '#22c55e',
      });
    }

    // Steps table
    const tbody = document.getElementById('mst-steps-body');
    tbody.innerHTML = '';
    (mstData.steps || []).slice(0, 20).forEach((s, i) => {
      const tr = document.createElement('tr');
      const added = s.action === 'added';
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${s.src_name || s.src} → ${s.dst_name || s.dst}</td>
        <td>${s.weight} ${s.is_potential ? '💰' : 'km'}</td>
        <td><span class="badge ${added ? 'badge-success' : 'badge-danger'}">${added ? 'Added' : 'Skipped'}</span></td>`;
      tbody.appendChild(tr);
    });

    // Cost analysis
    const ca = mstData.cost_analysis || {};
    const grid = document.getElementById('mst-analysis');
    grid.innerHTML = `
      <div class="info-item"><div class="label">MST edges</div><div class="value">${mstData.edge_count}</div></div>
      <div class="info-item"><div class="label">Total distance</div><div class="value">${ca.mst_distance_km} km</div></div>
      <div class="info-item"><div class="label">Full network</div><div class="value">${ca.full_network_distance_km} km</div></div>
      <div class="info-item"><div class="label">Distance saved</div><div class="value">${ca.distance_saving_pct}%</div></div>
      <div class="info-item"><div class="label">New roads in MST</div><div class="value">${ca.mst_new_roads}</div></div>
      <div class="info-item"><div class="label">New road cost</div><div class="value">${ca.new_road_cost_mEGP}M EGP</div></div>`;
  } catch (e) { console.warn('mst', e); }
}

// ─── Dijkstra ─────────────────────────────────────────────────────────────
async function runDijkstra() {
  const body = { src: val('dijk-src'), dst: val('dijk-dst'), time: val('dijk-time') };
  try {
    const r = await fetch(API + '/api/route', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json();
    renderRouteResult('dijk-result', d, 'normal');
  } catch (e) { console.warn('dijkstra', e); }
}

// ─── A* ───────────────────────────────────────────────────────────────────
async function runAstar() {
  const body = { src: val('astar-src'), dst: val('astar-dst'), time: val('astar-time') };
  try {
    const r = await fetch(API + '/api/astar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json();
    renderRouteResult('astar-result', d, 'emerg');
  } catch (e) { console.warn('astar', e); }
}

function renderRouteResult(elId, data, style) {
  const el = document.getElementById(elId);
  el.classList.remove('hidden');
  if (!data.found) { el.innerHTML = '<span style="color:#f87171">No path found.</span>'; return; }
  const dotClass = style === 'emerg' ? 'emerg' : 'normal';
  const icon = style === 'emerg' ? '🚨 ' : '';
  let html = `<div class="route-meta">
    <span class="badge badge-info">📍 ${data.total_distance} km</span>
    <span class="badge badge-warn">⏱ ~${data.travel_time_min} min</span>
    <span class="badge badge-success">${data.algorithm}</span>
    <span class="badge" style="background:rgba(255,255,255,.08)">${data.nodes_explored} nodes explored</span>
  </div>`;
  (data.path_names || data.path).forEach((name, i) => {
    const isLast = i === (data.path_names || data.path).length - 1;
    html += `<div class="route-step">
      <div class="step-node ${isLast ? 'end' : dotClass}"></div>
      <span>${icon}${name}</span>
    </div>`;
    icon = '';  // only first
  });
  el.innerHTML = html;
}

// ─── Traffic table ────────────────────────────────────────────────────────
async function loadTrafficTable() {
  const time = val('dijk-time') || 'morning';
  try {
    const r = await fetch(API + `/api/traffic?time=${time}`);
    const d = await r.json();
    const tbody = document.getElementById('traffic-body');
    tbody.innerHTML = '';
    d.roads.slice(0, 15).forEach(road => {
      const ratio = road.congestion_ratio;
      const los = losLabel(ratio);
      const badge = ratio >= 0.9 ? 'badge-danger' : ratio >= 0.7 ? 'badge-warn' : 'badge-success';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${road.src_name} → ${road.dst_name}</td>
        <td>${road.capacity.toLocaleString()}</td>
        <td>${road.current_flow.toLocaleString()}</td>
        <td>
          <span class="badge ${badge}">${(ratio * 100).toFixed(0)}%</span>
          <div class="progress-bar" style="margin-top:4px;width:80px">
            <div class="progress-fill" style="width:${Math.min(100, ratio * 100)}%;background:${ratio >= 0.9 ? '#ef4444' : ratio >= 0.7 ? '#f59e0b' : '#22c55e'}"></div>
          </div>
        </td>
        <td>${road.condition}/10</td>
        <td><strong>${los}</strong></td>`;
      tbody.appendChild(tr);
    });
  } catch (e) { console.warn('traffic', e); }
}

function losLabel(r) {
  if (r < 0.6) return 'A'; if (r < 0.7) return 'B';
  if (r < 0.8) return 'C'; if (r < 0.9) return 'D';
  if (r < 1.0) return 'E'; return 'F';
}

// ─── Race ─────────────────────────────────────────────────────────────────
async function runRace() {
  const body = { src: val('race-src'), dst: val('race-dst'), time: val('race-time') };
  try {
    const r = await fetch(API + '/api/race', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json();
    const { dijkstra: dj, astar: as, comparison: cmp } = d;
    const nodes = graphData?.nodes || [];
    const edges = graphData?.edges || [];

    // Side-by-side animate
    await Promise.all([
      animateRace(
        document.getElementById('raceDijkstraCanvas'),
        nodes, edges, dj.path, dj.nodes_explored, '#60a5fa', 'Dijkstra'
      ),
      animateRace(
        document.getElementById('raceAstarCanvas'),
        nodes, edges, as.path, as.nodes_explored, '#34d399', 'A*'
      ),
    ]);

    document.getElementById('race-d-stats').innerHTML = statsHTML(dj);
    document.getElementById('race-a-stats').innerHTML = statsHTML(as);
    document.getElementById('race-verdict').innerHTML =
      `A* explored <strong style="color:#34d399">${cmp.nodes_explored_astar}</strong> nodes<br>
       vs Dijkstra <strong style="color:#60a5fa">${cmp.nodes_explored_dijkstra}</strong><br>
       <strong>${cmp.efficiency_gain_pct}%</strong> more efficient<br>
       ${cmp.same_path ? '✅ Same optimal path' : '⚠ Different paths'}`;
  } catch (e) { console.warn('race', e); }
}

function statsHTML(r) {
  return `<strong>Distance:</strong> ${r.total_distance} km<br>
          <strong>Travel time:</strong> ${r.travel_time_min} min<br>
          <strong>Nodes explored:</strong> ${r.nodes_explored}<br>
          <strong>Path:</strong> ${(r.path_names || r.path).join(' → ')}`;
}

// ─── Schedule DP ──────────────────────────────────────────────────────────
async function runSchedule() {
  const buses = parseInt(document.getElementById('sched-fleet')?.value || 200);
  try {
    const r = await fetch(API + '/api/schedule', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ buses }),
    });
    const d = await r.json();

    const resultEl = document.getElementById('sched-result');
    resultEl.innerHTML = `
      <div class="info-grid" style="margin-bottom:10px">
        <div class="info-item"><div class="label">Fleet allocated</div><div class="value">${d.budget_buses}</div></div>
        <div class="info-item"><div class="label">Max passengers/day</div><div class="value">${(d.total_passengers / 1000).toFixed(0)}K</div></div>
      </div>`;

    const labels = d.allocation.map(a => a.route_id);
    const busData = d.allocation.map(a => a.buses_assigned);
    const paxData = d.allocation.map(a => Math.round(a.estimated_passengers / 1000));

    if (schedChart) schedChart.destroy();
    schedChart = new Chart(document.getElementById('schedChart'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Buses', data: busData, backgroundColor: 'rgba(37,99,235,.7)', yAxisID: 'y' },
          { label: 'Pax (K)', data: paxData, backgroundColor: 'rgba(5,150,105,.7)', yAxisID: 'y2' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#8b92a8', font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' } },
          y:  { ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' }, title: { display: true, text: 'Buses', color: '#8b92a8' } },
          y2: { position: 'right', ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { display: false }, title: { display: true, text: 'Passengers (K)', color: '#8b92a8' } },
        },
      },
    });

    // DP table
    renderDPTable(d.dp_table_sample);
  } catch (e) { console.warn('schedule', e); }
}

function renderDPTable(table) {
  const el = document.getElementById('dp-table');
  if (!el || !table) return;
  let html = '<thead><tr><th>Route \\ Budget</th>';
  for (let j = 0; j <= 20; j++) html += `<th>${j * 10}</th>`;
  html += '</tr></thead><tbody>';
  table.forEach((row, i) => {
    html += `<tr><th>R${i}</th>`;
    row.forEach((v, j) => {
      const isOpt = j === row.length - 1 && v > 0;
      html += `<td class="${isOpt ? 'dp-cell-opt' : ''}">${v > 0 ? (v / 1000).toFixed(0) + 'K' : '0'}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody>';
  el.innerHTML = html;
}

// ─── Maintenance DP ───────────────────────────────────────────────────────
async function runMaintenance() {
  const budget = parseInt(document.getElementById('maint-budget')?.value || 200);
  try {
    const r = await fetch(API + '/api/maintenance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ budget_mEGP: budget }),
    });
    const d = await r.json();

    document.getElementById('maint-result').innerHTML = `
      <div class="info-grid" style="margin-bottom:10px">
        <div class="info-item"><div class="label">Budget used</div><div class="value">${d.total_cost}M EGP</div></div>
        <div class="info-item"><div class="label">Total gain</div><div class="value">+${d.total_gain} pts</div></div>
      </div>`;

    const roads = d.selected_roads || [];
    if (maintChart) maintChart.destroy();
    maintChart = new Chart(document.getElementById('maintChart'), {
      type: 'bar',
      data: {
        labels: roads.map(r => r.road_id),
        datasets: [
          { label: 'Before', data: roads.map(r => r.current_condition), backgroundColor: 'rgba(220,38,38,.7)' },
          { label: 'After',  data: roads.map(r => r.new_condition),     backgroundColor: 'rgba(5,150,105,.7)' },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#8b92a8', font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' } },
          y: { min: 0, max: 10, ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' }, title: { display: true, text: 'Condition (1-10)', color: '#8b92a8' } },
        },
      },
    });
  } catch (e) { console.warn('maintenance', e); }
}

// ─── Signals ──────────────────────────────────────────────────────────────
async function runSignals() {
  const time = val('sig-time');
  const body = { time, emergency_node: emergencyNode };
  try {
    const r = await fetch(API + '/api/signals', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const d = await r.json();

    const grid = document.getElementById('signal-grid');
    grid.innerHTML = '';
    (d.plans || []).slice(0, 9).forEach(p => {
      const ratio = p.congestion_ratio || 0;
      const light = p.is_emergency ? 'green' : ratio >= 0.9 ? 'red' : ratio >= 0.7 ? 'amber' : 'green';
      const box = document.createElement('div');
      box.className = 'signal-box';
      box.innerHTML = `
        <div class="signal-light ${light}"></div>
        <div class="signal-name">${p.name.split(' ').slice(0, 2).join(' ')}</div>
        <div class="signal-info">${p.is_emergency ? '🚨 PREEMPTED' : `LOS ${p.level_of_service} · ${p.green_time}s`}</div>
        <div class="signal-info" style="margin-top:2px">${(ratio * 100).toFixed(0)}% load</div>`;
      grid.appendChild(box);
    });

    renderOptimality(d.optimality_analysis);
    renderLOSChart(d.plans || []);
  } catch (e) { console.warn('signals', e); }
}

function toggleEmergency() {
  emergencyNode = emergencyNode ? null : '3';  // Toggle Downtown emergency
  runSignals();
}

function renderLOSChart(plans) {
  const labels = plans.slice(0, 9).map(p => p.name.split(' ')[0]);
  const ratios = plans.slice(0, 9).map(p => +(p.congestion_ratio * 100).toFixed(1));
  const colors = ratios.map(r => r >= 90 ? 'rgba(220,38,38,.75)' : r >= 70 ? 'rgba(217,119,6,.75)' : 'rgba(5,150,105,.75)');

  if (losChart) losChart.destroy();
  losChart = new Chart(document.getElementById('losChart'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Congestion %', data: ratios, backgroundColor: colors }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' } },
        y: { min: 0, max: 120, ticks: { color: '#8b92a8', font: { size: 10 }, callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,.05)' } },
      },
    },
  });
}

function renderOptimality(analysis) {
  if (!analysis) return;
  const grid = document.getElementById('optimality-grid');
  let html = '<div>';
  html += '<div style="font-size:12px;font-weight:500;color:#34d399;margin-bottom:8px">✅ Optimal cases</div>';
  analysis.optimal_cases.forEach(c => {
    html += `<div class="opt-card optimal"><div class="opt-title">${c.scenario}</div><div class="opt-reason">${c.reason}</div></div>`;
  });
  html += '</div><div>';
  html += '<div style="font-size:12px;font-weight:500;color:#f87171;margin-bottom:8px">⚠ Suboptimal cases (Cairo context)</div>';
  analysis.suboptimal_cases.forEach(c => {
    html += `<div class="opt-card suboptimal"><div class="opt-title">${c.scenario}</div><div class="opt-reason">${c.reason}</div></div>`;
  });
  html += '</div>';
  grid.innerHTML = html;
}

// ─── ML Prediction ────────────────────────────────────────────────────────
async function trainModels() {
  const badge = document.getElementById('m-ml');
  if (badge) badge.textContent = '⏳';
  try {
    const r = await fetch(API + '/api/train');
    const d = await r.json();
    if (badge) badge.textContent = d.error ? 'ERR' : 'RF✓';

    const el = document.getElementById('ml-train-result');
    if (d.status === 'trained' || d.status === 'loaded_from_cache') {
      const rf = d.random_forest || {};
      const gb = d.gradient_boosting || {};
      el.innerHTML = `
        <div class="info-item"><div class="label">RF MAE</div><div class="value">${rf.mae ?? '—'}</div></div>
        <div class="info-item"><div class="label">RF R²</div><div class="value">${rf.r2 ?? '—'}</div></div>
        <div class="info-item"><div class="label">GB MAE</div><div class="value">${gb.mae ?? '—'}</div></div>
        <div class="info-item"><div class="label">GB R²</div><div class="value">${gb.r2 ?? '—'}</div></div>`;

      if (d.feature_importances) renderFeatureChart(d.feature_importances);
    } else {
      el.innerHTML = `<div class="info-item" style="grid-column:span 2"><div class="label">Status</div><div class="value" style="font-size:13px">${d.status}</div></div>`;
    }
  } catch (e) { console.warn('train', e); }
}

async function runForecast() {
  const roadId  = val('ml-road');
  const dayType = val('ml-daytype');
  try {
    const r = await fetch(API + `/api/forecast/${roadId}?day_type=${dayType}`);
    const d = await r.json();

    const forecast = d.forecast || [];
    const labels = forecast.map(f => f.label);
    const ratios = forecast.map(f => f.congestion_ratio);
    const colors = ratios.map(r => r >= 0.9 ? 'rgba(220,38,38,.75)' : r >= 0.7 ? 'rgba(217,119,6,.75)' : 'rgba(5,150,105,.75)');

    if (forecastChart) forecastChart.destroy();
    forecastChart = new Chart(document.getElementById('forecastChart'), {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'Congestion ratio', data: ratios, backgroundColor: colors, borderRadius: 3 },
          { type: 'line', label: 'Trend', data: ratios, borderColor: '#60a5fa', borderWidth: 2, pointRadius: 2, fill: false, tension: 0.4 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#8b92a8', font: { size: 11 } } } },
        scales: {
          x: { ticks: { color: '#8b92a8', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,.05)' } },
          y: { min: 0, max: 1.5, ticks: { color: '#8b92a8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,.05)' },
               title: { display: true, text: 'Congestion ratio', color: '#8b92a8' } },
        },
      },
    });
  } catch (e) { console.warn('forecast', e); }
}

function renderFeatureChart(importances) {
  const sorted = Object.entries(importances).sort((a, b) => b[1] - a[1]);
  const labels = sorted.map(([k]) => k);
  const data   = sorted.map(([, v]) => +(v * 100).toFixed(1));

  if (featureChart) featureChart.destroy();
  featureChart = new Chart(document.getElementById('featureChart'), {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Importance (%)', data, backgroundColor: 'rgba(37,99,235,.7)', borderRadius: 3 }] },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: '#8b92a8', font: { size: 10 }, callback: v => v + '%' }, grid: { color: 'rgba(255,255,255,.05)' } },
        y: { ticks: { color: '#8b92a8', font: { size: 11 } }, grid: { color: 'rgba(255,255,255,.05)' } },
      },
    },
  });
}

// ─── Utilities ────────────────────────────────────────────────────────────
function val(id) {
  const el = document.getElementById(id);
  return el ? el.value : '';
}
function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
}
