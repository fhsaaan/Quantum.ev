/* Live dispatch demo: replays /api/simulate results on a bay-by-time board. */
const NAMES = {
  hold: 'Lock bay on departure',
  nearest: 'Book by arrival time',
  cheapest: 'Book by arrival, cheapest slot',
  rolling: 'Book by arrival + re-plan',
  hindsight: 'Perfect hindsight (not achievable)',
};
const EXPLAIN = {
  hold: 'The bay is locked the moment a car sets off, so it sits empty for the whole drive. This is the problem you described.',
  nearest: 'The bay is booked only for the arrival time. While a car is driving, another car can charge there and leave before it arrives.',
  rolling: 'Bays are booked by arrival time, and each new request re-plans every car that has not left yet. Cars on the road are never moved.',
};
const $ = id => document.getElementById(id);
const state = { scenario: 'gap', policy: 'hold', cars: 50, seed: 0, data: null, t: 0, timer: null };

// Shareable links, e.g. /live?scenario=rush&policy=rolling&cars=50&t=8
const params = new URLSearchParams(location.search);
if (params.get('scenario') === 'rush') state.scenario = 'rush';
if (Object.hasOwn(EXPLAIN, params.get('policy') ?? '')) state.policy = params.get('policy');
const linkedCars = Number(params.get('cars'));
if (Number.isInteger(linkedCars) && linkedCars >= 10 && linkedCars <= 80) state.cars = linkedCars;
let startAt = Math.min(16, Math.max(0, Number(params.get('t')) || 0));

const clock = t => {
  const mins = 16 * 60 + Math.round(t * 30);
  return `${String(Math.floor(mins / 60) % 24).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}`;
};
const pct = s => `${(s / 16) * 100}%`;

function press() {
  document.querySelectorAll('[data-scenario]').forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.scenario === state.scenario));
  document.querySelectorAll('[data-policy]').forEach(b =>
    b.setAttribute('aria-pressed', b.dataset.policy === state.policy));
  $('rush-controls').style.display = state.scenario === 'rush' ? 'flex' : 'none';
  $('explain').textContent = EXPLAIN[state.policy];
}

function stats() {
  const m = state.data.policies[state.policy].metrics;
  const base = state.data.policies.hold.metrics;
  const saved = base.total_rs - m.total_rs;
  const moved = state.policy === 'rolling'
    ? state.data.events.reduce((n, e) => n + e.moved.length, 0) : 0;
  const cards = [
    [`₹${Math.round(m.total_rs).toLocaleString('en-IN')}`, saved > 0 ? `evening cost, ₹${Math.round(saved).toLocaleString('en-IN')} less than locking` : 'evening cost'],
    [`${Math.round(m.avg_wait_min)} min`, 'average wait'],
    [m.unserved, 'cars not served'],
    [moved, 'drivers re-routed before leaving'],
  ];
  $('stats').replaceChildren(...cards.map(([big, small]) => {
    const d = document.createElement('div');
    d.className = 'stat';
    const b = document.createElement('b'); b.textContent = big;
    const s = document.createElement('span'); s.textContent = small;
    d.append(b, s);
    return d;
  }));
}

function bar(cls, from, to, text) {
  const d = document.createElement('div');
  d.className = `bar ${cls}`;
  d.style.left = pct(from);
  d.style.width = pct(to - from);
  d.textContent = text;
  return d;
}

function board() {
  const { data, policy, t } = state;
  const gantt = $('gantt');
  const hours = document.createElement('div');
  hours.className = 'hours';
  data.slots.slice(0, 16).forEach((label, i) => {
    const c = document.createElement('div');
    c.textContent = i % 2 === 0 ? label : '';
    hours.append(c);
  });
  const askedAt = Object.fromEntries(data.cars.map(c => [c.id, c.asks]));
  const lanes = data.chargers.map(c => {
    const lane = document.createElement('div');
    lane.className = 'lane';
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = `${c.station} · ${c.kw} kW`;
    who.title = who.textContent;
    const grid = document.createElement('div');
    grid.className = 'grid';
    lane.append(who, grid);
    data.policies[policy].bookings.filter(b => b.charger === c.id && askedAt[b.car] <= t).forEach(b => {
      if (b.drive > 0) lane.append(bar(policy === 'hold' ? 'lock' : 'road', b.depart, b.start, ''));
      lane.append(bar('charge', b.start, b.end, `Car ${b.car + 1}`));
    });
    return lane;
  });
  const now = document.createElement('div');
  now.className = 'now';
  now.style.left = `calc(var(--name) + (100% - var(--name)) * ${t / 16})`;
  gantt.replaceChildren(hours, ...lanes, now);
  $('clock').value = t;
  $('clock-out').textContent = clock(t);

  const asking = data.cars.filter(c => c.asks <= t);
  const last = data.events.filter(e => e.slot <= t).at(-1);
  let msg = 'Waiting for the first car to ask for a charge.';
  if (last) {
    const names = last.arrivals.map(i => `Car ${i + 1}`).join(', ');
    msg = `${clock(last.slot)}: ${names} asked. ${asking.length} of ${data.cars.length} cars known so far.`;
    if (policy === 'rolling' && last.moved.length) msg += ` ${last.moved.length} waiting driver(s) got a better slot.`;
  }
  $('log').textContent = msg;
}

function compare() {
  const rows = Object.keys(NAMES).map(k => [k, state.data.policies[k]]);
  const head = ['Rule', 'Cost', 'Avg wait', 'Not served', 'Peak kW'];
  const table = $('compare');
  const tr = (cells, tag, cls) => {
    const r = document.createElement('tr');
    if (cls) r.className = cls;
    cells.forEach(c => { const x = document.createElement(tag); x.textContent = c; r.append(x); });
    return r;
  };
  table.replaceChildren(tr(head, 'th'), ...rows.map(([k, { metrics: m }]) => tr([
    NAMES[k], `₹${Math.round(m.total_rs).toLocaleString('en-IN')}`,
    `${Math.round(m.avg_wait_min)} min`, m.unserved, m.peak_kw,
  ], 'td', k === state.policy ? 'on' : '')));
}

function render() { press(); stats(); board(); compare(); }

function stop() {
  clearInterval(state.timer);
  state.timer = null;
  $('play').textContent = 'Play';
}

function play() {
  if (state.timer) return stop();
  if (state.t >= 16) state.t = 0;
  $('play').textContent = 'Pause';
  state.timer = setInterval(() => {
    state.t = Math.min(16, state.t + 0.1);
    board();
    if (state.t >= 16) stop();
  }, 90);
}

async function load() {
  stop();
  try {
    const r = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: state.scenario, cars: state.cars, seed: state.seed }),
    });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || 'Simulation failed');
    state.data = body;
    state.t = startAt;
    startAt = 0;
    render();
  } catch (e) {
    $('stats').innerHTML = '';
    $('explain').textContent = `Could not load the simulation: ${e.message}`;
    $('explain').classList.add('error');
  }
}

document.querySelectorAll('[data-scenario]').forEach(b => b.addEventListener('click', () => {
  state.scenario = b.dataset.scenario;
  load();
}));
document.querySelectorAll('[data-policy]').forEach(b => b.addEventListener('click', () => {
  state.policy = b.dataset.policy;
  if (state.data) render();
}));
$('play').addEventListener('click', play);
$('clock').addEventListener('input', e => { stop(); state.t = Number(e.target.value); board(); });
$('cars').addEventListener('input', e => { state.cars = Number(e.target.value); $('cars-out').textContent = state.cars; });
$('cars').addEventListener('change', load);
$('reseed').addEventListener('click', () => { state.seed = (state.seed + 1) % 10000; load(); });

press();
load();
