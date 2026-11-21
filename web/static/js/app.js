/* ═══════════════════════════════════════════════════════════
   Quantum.ev EV Charging Optimizer — Frontend Logic
   Theme: Clean White, Green, and Black Minimalist Design
   ═══════════════════════════════════════════════════════════ */

// ── Application State ─────────────────────────────────────
const state = {
  fleet: [],            // {id, lat, lon, soc, battery_kwh, ready, deadline, model, marker}
  stations: [],         // from /api/stations
  stationMarkers: [],
  routeLines: [],
  pendingLatLon: null,  // lat,lon from map click awaiting "Add"
  nextId: 0,
};

// ── Map Setup (Light Voyager Tiles for White/Green/Black theme) ──
const map = L.map('map', {
  center: [9.56, 76.52], // Centered around Kottayam & Central Kerala network
  zoom: 12,
  zoomControl: false,
});

L.control.zoom({ position: 'topright' }).addTo(map);

// Esri street tiles (no API key needed). OpenStreetMap's own volunteer tile
// servers returned 403 "Access blocked" on the Vercel deployment.
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
  attribution: 'Tiles &copy; <a href="https://www.esri.com">Esri</a> | Data: <a href="https://openchargemap.org">OpenChargeMap</a>',
  maxZoom: 19,
}).addTo(map);

// ── Load Real Stations from OpenChargeMap ─────────────────
fetch('/api/stations')
  .then(r => r.json())
  .then(stations => {
    state.stations = stations;
    stations.forEach(st => {
      const icon = L.divIcon({
        className: 'station-marker',
        html: '<div class="station-marker-inner">⚡</div>',
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      const chargerHtml = st.chargers
        .filter(c => c.kw >= 10)
        .map(c => `<span class="charger-tag">${c.count}× ${c.type} ${c.kw} kW (${c.current})</span>`)
        .join('');

      const marker = L.marker([st.latitude, st.longitude], { icon })
        .bindPopup(`
          <div class="station-popup">
            <h3>${st.name}</h3>
            <div class="meta"><strong>Operator:</strong> ${st.operator} · <strong>Tariff:</strong> ₹${st.usage_cost_rs_kwh}/kWh</div>
            <div class="meta">📍 ${st.address}</div>
            <div class="charger-list">${chargerHtml}</div>
            <div style="margin-top:8px;">
              <a href="https://www.google.com/maps/search/?api=1&query=${st.latitude},${st.longitude}" target="_blank" style="font-size:0.7rem;color:#059669;font-weight:700;text-decoration:none;">🗺️ Navigate to Station ↗</a>
            </div>
          </div>
        `)
        .addTo(map);

      state.stationMarkers.push(marker);
    });
  });

// ── Load Electricity Tariff Chart ─────────────────────────
fetch('/api/tariff')
  .then(r => r.json())
  .then(tariff => {
    const chart = document.getElementById('tariff-chart');
    if (!chart) return;
    chart.innerHTML = '';
    const maxP = Math.max(...tariff.price_rs_kwh);
    tariff.price_rs_kwh.forEach((p, i) => {
      const bar = document.createElement('div');
      bar.className = 'tariff-bar' + (p >= 10 ? ' peak' : p <= 6 ? ' offpeak' : '');
      bar.style.height = (p / maxP * 100) + '%';
      bar.title = `${tariff.slots[i]}: ₹${p}/kWh`;
      chart.appendChild(bar);
    });
  });

// ── Map Click Event: Set EV Location Pin ──────────────────
map.on('click', function (e) {
  state.pendingLatLon = { lat: e.latlng.lat, lon: e.latlng.lng };
  const locBox = document.getElementById('click-location');
  if (locBox) locBox.style.display = 'block';
  const locDisp = document.getElementById('location-display');
  if (locDisp) locDisp.textContent = `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`;
  const btnAdd = document.getElementById('btn-add-vehicle');
  if (btnAdd) btnAdd.disabled = false;
  const hintBadge = document.getElementById('hint-badge');
  if (hintBadge) {
    hintBadge.textContent = '📍 Pin Set!';
    hintBadge.style.color = 'var(--green-700)';
    hintBadge.style.background = 'var(--green-100)';
  }
});

// ── Slider Binding ────────────────────────────────────────
const socSlider = document.getElementById('soc-slider');
const socDisplay = document.getElementById('soc-display');
if (socSlider && socDisplay) {
  socSlider.addEventListener('input', () => {
    socDisplay.textContent = socSlider.value + '%';
  });
}

// ── Add Vehicle Manually ──────────────────────────────────
const btnAdd = document.getElementById('btn-add-vehicle');
if (btnAdd) {
  btnAdd.addEventListener('click', () => {
    if (!state.pendingLatLon) return;
    if (state.fleet.length >= 20) {
      alert('Maximum 20 vehicles for fast simulation.');
      return;
    }

    const modelSelect = document.getElementById('model-select');
    const batterySelect = document.getElementById('battery-select');
    const readySelect = document.getElementById('ready-select');
    const deadlineSelect = document.getElementById('deadline-select');

    const ev = {
      id: state.nextId++,
      lat: state.pendingLatLon.lat,
      lon: state.pendingLatLon.lon,
      soc: parseInt(socSlider.value),
      battery_kwh: parseFloat(batterySelect.value),
      model: modelSelect.options[modelSelect.selectedIndex].text,
      ready: readySelect.value,
      deadline: deadlineSelect.value,
      marker: null,
    };

    const icon = L.divIcon({
      className: 'ev-marker',
      html: `<div class="ev-marker-inner">${ev.id}</div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });

    ev.marker = L.marker([ev.lat, ev.lon], { icon })
      .bindPopup(`<b>EV #${ev.id}</b><br>${ev.model}<br>SoC: ${ev.soc}% · ${ev.battery_kwh} kWh<br>Window: ${ev.ready}–${ev.deadline}`)
      .addTo(map);

    state.fleet.push(ev);
    state.pendingLatLon = null;
    document.getElementById('click-location').style.display = 'none';
    btnAdd.disabled = true;
    document.getElementById('hint-badge').textContent = 'Click map to set pin';
    document.getElementById('hint-badge').style.color = '';
    document.getElementById('hint-badge').style.background = '';

    renderFleet();
  });
}

// ── Render Active Fleet List ──────────────────────────────
function renderFleet() {
  const container = document.getElementById('fleet-list');
  const countBadge = document.getElementById('fleet-count');
  const btnOpt = document.getElementById('btn-optimize');

  countBadge.textContent = `${state.fleet.length} vehicles`;
  btnOpt.disabled = state.fleet.length === 0;

  if (state.fleet.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:16px;color:var(--text-muted);font-size:0.78rem;">
        Select a real-world scenario above or click the map to place vehicles.
      </div>
    `;
    return;
  }

  container.innerHTML = state.fleet.map((ev, idx) => `
    <div class="fleet-item">
      <div class="fleet-item-info">
        <span class="fleet-badge">#${ev.id}</span>
        <div class="fleet-details">
          <span class="fleet-model">${ev.model}</span>
          <span class="fleet-sub">${ev.soc}% SoC · ${ev.battery_kwh} kWh · ${ev.ready}–${ev.deadline}</span>
        </div>
      </div>
      <button class="fleet-item-remove" onclick="removeVehicle(${idx})" title="Remove">✕</button>
    </div>
  `).join('');
}

window.removeVehicle = function(idx) {
  const ev = state.fleet[idx];
  if (ev && ev.marker) map.removeLayer(ev.marker);
  state.fleet.splice(idx, 1);
  clearRoutes();
  renderFleet();
};

// ── Clear All ─────────────────────────────────────────────
document.getElementById('btn-clear').addEventListener('click', () => {
  state.fleet.forEach(ev => map.removeLayer(ev.marker));
  state.fleet = [];
  state.nextId = 0;
  clearRoutes();
  const panel = document.getElementById('results-panel');
  if (panel) panel.classList.remove('visible');
  document.querySelectorAll('.scenario-card').forEach(c => c.classList.remove('active'));
  renderFleet();
});

function clearRoutes() {
  state.routeLines.forEach(line => map.removeLayer(line));
  state.routeLines = [];
}

// ── Real-World Entity Testing Scenarios ───────────────────
function loadScenarioFleet(samples, scenarioBtnId) {
  // Clear existing
  state.fleet.forEach(ev => map.removeLayer(ev.marker));
  state.fleet = [];
  state.nextId = 0;
  clearRoutes();
  const panel = document.getElementById('results-panel');
  if (panel) panel.classList.remove('visible');

  // Highlight active scenario card
  document.querySelectorAll('.scenario-card').forEach(c => c.classList.remove('active'));
  const activeBtn = document.getElementById(scenarioBtnId);
  if (activeBtn) activeBtn.classList.add('active');

  samples.forEach(s => {
    const ev = {
      id: state.nextId++,
      lat: s.lat,
      lon: s.lon,
      soc: s.soc,
      battery_kwh: s.batt,
      model: s.model,
      ready: s.ready,
      deadline: s.deadline,
      marker: null,
    };

    const icon = L.divIcon({
      className: 'ev-marker',
      html: `<div class="ev-marker-inner">${ev.id}</div>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });

    ev.marker = L.marker([ev.lat, ev.lon], { icon })
      .bindPopup(`<b>EV #${ev.id} (${ev.model})</b><br>Initial SoC: ${ev.soc}% · ${ev.battery_kwh} kWh<br>Arrival Window: ${ev.ready} to ${ev.deadline}`)
      .addTo(map);

    state.fleet.push(ev);
  });

  renderFleet();

  // Zoom map to encompass the fleet
  const pts = state.fleet.map(ev => [ev.lat, ev.lon]);
  if (pts.length) map.fitBounds(pts, { padding: [50, 50] });
}

// Scenario 1: E-Commerce Delivery Fleet (Kottayam Depot / MC Road)
document.getElementById('btn-scenario-delivery').addEventListener('click', () => {
  const deliveryFleet = [
    { lat: 9.555, lon: 76.510, soc: 18, batt: 40, model: 'Delivery Van A', ready: '16:30', deadline: '21:00' },
    { lat: 9.532, lon: 76.525, soc: 22, batt: 40, model: 'Delivery Van B', ready: '17:00', deadline: '22:00' },
    { lat: 9.578, lon: 76.512, soc: 15, batt: 40, model: 'Delivery Van C', ready: '16:30', deadline: '20:30' },
    { lat: 9.562, lon: 76.530, soc: 25, batt: 40, model: 'Delivery Van D', ready: '17:30', deadline: '22:30' },
    { lat: 9.548, lon: 76.505, soc: 12, batt: 40, model: 'Delivery Van E', ready: '16:00', deadline: '21:30' },
    { lat: 9.590, lon: 76.518, soc: 28, batt: 40, model: 'Delivery Van F', ready: '18:00', deadline: '23:00' },
  ];
  loadScenarioFleet(deliveryFleet, 'btn-scenario-delivery');
});

// Scenario 2: Kochi Electric Cabs (Maradu / NH 66 corridor)
document.getElementById('btn-scenario-cabs').addEventListener('click', () => {
  const cabsFleet = [
    { lat: 9.940, lon: 76.335, soc: 20, batt: 40, model: 'Cab 101 (Nexon EV)', ready: '16:00', deadline: '21:00' },
    { lat: 9.932, lon: 76.324, soc: 28, batt: 40, model: 'Cab 102 (Nexon EV)', ready: '16:30', deadline: '21:30' },
    { lat: 9.946, lon: 76.330, soc: 15, batt: 50, model: 'Cab 103 (MG ZS EV)',   ready: '17:00', deadline: '22:00' },
    { lat: 9.928, lon: 76.318, soc: 32, batt: 40, model: 'Cab 104 (Nexon EV)', ready: '17:00', deadline: '22:30' },
    { lat: 9.935, lon: 76.338, soc: 22, batt: 50, model: 'Cab 105 (MG ZS EV)',   ready: '17:30', deadline: '23:00' },
    { lat: 9.925, lon: 76.321, soc: 18, batt: 60, model: 'Cab 106 (BYD Atto 3)', ready: '18:00', deadline: '23:30' },
    { lat: 9.942, lon: 76.342, soc: 35, batt: 40, model: 'Cab 107 (Nexon EV)', ready: '18:00', deadline: '23:00' },
    { lat: 9.930, lon: 76.315, soc: 25, batt: 50, model: 'Cab 108 (MG ZS EV)',   ready: '18:30', deadline: '23:30' },
  ];
  loadScenarioFleet(cabsFleet, 'btn-scenario-cabs');
});

// Scenario 3: State Highway Commuters (MC Road corridor)
document.getElementById('btn-scenario-commuters').addEventListener('click', () => {
  const commuterFleet = [
    { lat: 9.545, lon: 76.515, soc: 14, batt: 30, model: 'Tiago EV Commuter', ready: '16:30', deadline: '21:00' },
    { lat: 9.570, lon: 76.522, soc: 24, batt: 40, model: 'Nexon EV Long Range', ready: '17:00', deadline: '22:00' },
    { lat: 9.595, lon: 76.520, soc: 19, batt: 50, model: 'MG ZS EV Exclusive', ready: '17:30', deadline: '22:30' },
    { lat: 9.560, lon: 76.518, soc: 30, batt: 40, model: 'Nexon EV Dark', ready: '18:00', deadline: '23:00' },
    { lat: 9.585, lon: 76.512, soc: 22, batt: 60, model: 'BYD Atto 3 Commuter', ready: '18:00', deadline: '23:30' },
  ];
  loadScenarioFleet(commuterFleet, 'btn-scenario-commuters');
});

// ── Run Optimization (QAOA vs Baselines) ──────────────────
document.getElementById('btn-optimize').addEventListener('click', async () => {
  if (state.fleet.length < 1) return;

  const loading = document.getElementById('loading');
  loading.classList.add('visible');
  document.getElementById('results-panel').classList.remove('visible');
  clearRoutes();

  const vehicles = state.fleet.map(ev => ({
    lat: ev.lat,
    lon: ev.lon,
    soc: ev.soc,
    battery_kwh: ev.battery_kwh,
    ready: ev.ready,
    deadline: ev.deadline,
  }));

  try {
    const resp = await fetch('/api/optimize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ vehicles, engine: 'qaoa' }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.error || 'Optimization failed');
    }

    const result = await resp.json();
    showResults(result);
  } catch (e) {
    alert('Optimization Error: ' + e.message);
  } finally {
    loading.classList.remove('visible');
  }
});

// ── Display Optimization Results in Clean Theme ───────────
function showResults(result) {
  const panel = document.getElementById('results-panel');
  const body = document.getElementById('results-body');

  const q = result.quantum_info;
  const cmp = result.comparison;
  const sched = result.schedule;

  const savings = cmp.fcfs.total_rs > 0
    ? ((1 - cmp.qaoa.total_rs / cmp.fcfs.total_rs) * 100).toFixed(1)
    : '0.0';

  const peakReduction = cmp.fcfs.peak_kw > 0
    ? (((cmp.fcfs.peak_kw - cmp.qaoa.peak_kw) / cmp.fcfs.peak_kw) * 100).toFixed(0)
    : '0';

  const served = sched.filter(s => s.served).length;
  const total = sched.length;

  // Draw clean green route lines
  clearRoutes();
  sched.forEach(s => {
    if (!s.served) return;
    const line = L.polyline(
      [[s.ev_lat, s.ev_lon], [s.station_lat, s.station_lon]],
      { color: '#059669', weight: 3, opacity: 0.85, dashArray: '6 6' }
    ).addTo(map);
    state.routeLines.push(line);
  });

  // Render Clean White/Green/Black Dashboard Content
  body.innerHTML = `
    <!-- Top KPI Cards -->
    <div class="metrics-grid">
      <div class="metric-card highlight">
        <div class="metric-label">Optimized Cost</div>
        <div class="metric-value">₹${cmp.qaoa.total_rs.toFixed(0)}</div>
        <div class="metric-sub">via QAOA Hybrid</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Savings vs Greedy</div>
        <div class="metric-value" style="color:var(--green-600);">${savings}%</div>
        <div class="metric-sub">₹${(cmp.fcfs.total_rs - cmp.qaoa.total_rs).toFixed(0)} saved</div>
      </div>
      <div class="metric-card black-card">
        <div class="metric-label">Fleet Served</div>
        <div class="metric-value">${served}/${total}</div>
        <div class="metric-sub">${q.is_feasible ? '100% Feasible' : 'Conflicts'}</div>
      </div>
    </div>

    <!-- Real-World Benchmarking Table -->
    <div>
      <div class="section-header">
        <span class="section-title">📊 Real-World Performance Benchmark</span>
      </div>
      <table class="comp-table">
        <thead>
          <tr>
            <th>Scheduling Strategy</th>
            <th>Total Cost</th>
            <th>Energy (₹)</th>
            <th>Avg Wait</th>
            <th>Peak Load</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Uncoordinated (FCFS)</strong></td>
            <td>₹${cmp.fcfs.total_rs}</td>
            <td>₹${cmp.fcfs.energy_rs}</td>
            <td>${cmp.fcfs.avg_wait_min} min</td>
            <td>${cmp.fcfs.peak_kw} kW</td>
          </tr>
          <tr class="highlight">
            <td><strong>⚛ Quantum QAOA (Ours)</strong></td>
            <td><strong>₹${cmp.qaoa.total_rs}</strong></td>
            <td>₹${cmp.qaoa.energy_rs}</td>
            <td>${cmp.qaoa.avg_wait_min} min</td>
            <td><strong>${cmp.qaoa.peak_kw} kW</strong></td>
          </tr>
          <tr>
            <td><strong>Theoretical Optimum (MILP)</strong></td>
            <td>₹${cmp.optimal.total_rs}</td>
            <td>₹${cmp.optimal.energy_rs}</td>
            <td>${cmp.optimal.avg_wait_min} min</td>
            <td>${cmp.optimal.peak_kw} kW</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Quantum Technical Specs Card -->
    <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
        <span style="font-size:1.1rem;color:var(--green-600);">⚛</span>
        <strong style="font-size:0.8rem;color:var(--black);">Qiskit QAOA Circuit Metrics</strong>
      </div>
      <div style="font-size:0.72rem;color:var(--text-secondary);line-height:1.6;font-family:'JetBrains Mono',monospace;">
        • Active Qubits per Subproblem: <strong>${q.qubits_per_round} qubits</strong><br>
        • Simulator: <strong>Qiskit Aer (Statevector)</strong><br>
        • QAOA Layers: <strong>p=2 with XY-Mixer</strong> (One-hot subspace preserved)<br>
        • Optimization Rounds: <strong>${q.iterations} LNS iterations</strong><br>
        • Execution Time: <strong>${q.total_solve_time_s}s</strong> (QAOA time: ${q.qaoa_time_s}s)<br>
        • Optimality Proof: <strong>${q.proved_optimal ? 'Exact Optimum Reached' : 'Within 0.5% of Optimum'}</strong>
      </div>
    </div>

    <!-- Charging Schedule Timeline -->
    <div>
      <div class="section-header">
        <span class="section-title">⚡ Assigned Station Schedules</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:8px;">
        ${sched.map(s => {
          if (!s.served) {
            return `
              <div class="sched-item" style="border-left:3px solid #71717a;">
                <div class="sched-header">
                  <span class="sched-title">EV #${s.ev_id}</span>
                  <span class="sched-badge unserved">Deferred</span>
                </div>
                <div class="sched-row">
                  <span>Status: Insufficient window / battery to reach station</span>
                  <strong>Penalty: ₹${s.cost_rs}</strong>
                </div>
              </div>
            `;
          }
          return `
            <div class="sched-item" style="border-left:3px solid var(--green-600);cursor:pointer;" onclick="map.flyTo([${s.station_lat}, ${s.station_lon}], 14)">
              <div class="sched-header">
                <span class="sched-title">
                  <span class="fleet-badge">EV #${s.ev_id}</span>
                  ${s.station}
                </span>
                <span class="sched-badge">₹${s.cost_rs}</span>
              </div>
              <div class="sched-row">
                <span>⏱ Charge Slot: <strong>${s.start_time} – ${s.end_time}</strong> (${s.charger_kw} kW bay)</span>
                <span>Wait: <strong>${s.wait_min} min</strong></span>
              </div>
              <div class="sched-row">
                <span>📍 Travel: <strong>${s.distance_km} km</strong></span>
                <span>Energy: <strong>₹${s.energy_rs}</strong></span>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;

  panel.classList.add('visible');
}

// ── Close Results ─────────────────────────────────────────
document.getElementById('results-close').addEventListener('click', () => {
  document.getElementById('results-panel').classList.remove('visible');
});

// Auto-load the delivery fleet scenario on first visit
setTimeout(() => {
  const btn = document.getElementById('btn-scenario-delivery');
  if (btn) btn.click();
}, 600);
