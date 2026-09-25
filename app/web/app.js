// Training app: reads /api/today, /api/plan, /api/trends with the admin token
// saved on this device. The last good response is cached so the app opens
// offline (e.g. at the trailhead) with the day's workout.
'use strict';

const TOKEN_KEY = 'training.token';
const CACHE_KEY = 'training.cache.';
const KIND = {run: ['Run', 'var(--blue)'], long: ['Long run', 'var(--blue)'], strength: ['Strength', 'var(--pink)'],
              swim: ['Swim', 'var(--teal)'], bike: ['Bike', 'var(--teal)'], rest: ['Rest', 'var(--muted)']};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const D = s => new Date(String(s).slice(0, 10) + 'T00:00:00Z');
const hm = t => String(t).replace(/^0/, '').replace(/:00$/, '');
const fmt = (s, o) => D(s).toLocaleDateString('en-US', {timeZone: 'UTC', ...o});

function store(k, v) { try { localStorage.setItem(k, v); } catch {} }
function load(k) { try { return localStorage.getItem(k); } catch { return null; } }

const TIMEOUT_MS = 15000;
let lastLoadMs = null;

async function api(path) {
  // Auth rides on an HttpOnly session cookie set by /api/session. A token
  // saved by an older version of the app is still sent as a header.
  const legacy = load(TOKEN_KEY);
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  const t0 = performance.now();
  try {
    const r = await fetch(path, {credentials: 'same-origin', signal: ctl.signal,
                                 headers: legacy ? {'X-Admin-Token': legacy} : {}});
    if (r.status === 401) throw Object.assign(new Error('unauthorized'), {auth: true});
    if (!r.ok) throw new Error(`Server error ${r.status}`);
    const data = await r.json();
    lastLoadMs = Math.round(performance.now() - t0);
    store(CACHE_KEY + path, JSON.stringify({at: Date.now(), data}));
    return {data, cached: false};
  } catch (e) {
    if (e.auth) throw e;
    const why = e.name === 'AbortError' ? `No answer from the server after ${TIMEOUT_MS / 1000}s` : (e.message || 'Network error');
    const c = load(CACHE_KEY + path);
    if (c) { const {at, data} = JSON.parse(c); return {data, cached: at, why}; }
    throw Object.assign(new Error(why), {why});
  } finally {
    clearTimeout(timer);
  }
}

function errorCard(where, why) {
  return `<section class="card"><div class="label">${esc(where)}</div>
    <p style="margin:0 0 12px;color:var(--ink2)">${esc(why)}</p>
    <button class="primary-btn" onclick="location.reload()">Retry</button></section>`;
}

// ── sign in ─────────────────────────────────────────────────────────────
function showSignin(msg) {
  $('app').hidden = true; $('signin').hidden = false; $('tokerr').textContent = msg || '';
}
$('tokbtn').onclick = async () => {
  const token = $('tok').value.trim();
  if (!token) return;
  $('tokbtn').disabled = true; $('tokerr').textContent = 'Checking…';
  try {
    const r = await fetch('/api/session', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})});
    if (r.status === 401) { $('tokerr').textContent = 'That token was rejected.'; return; }
    if (!r.ok) { $('tokerr').textContent = `Server error ${r.status}. Try again.`; return; }
    try { localStorage.removeItem(TOKEN_KEY); } catch {}
    $('tok').value = ''; $('tokerr').textContent = '';
    start();
  } catch { $('tokerr').textContent = "Can't reach the server."; }
  finally { $('tokbtn').disabled = false; }
};

// ── tabs ────────────────────────────────────────────────────────────────
document.querySelectorAll('.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('.tabs button').forEach(x => x.setAttribute('aria-selected', x === b));
  document.querySelectorAll('main').forEach(m => m.hidden = m.id !== b.dataset.tab);
  if (b.dataset.tab === 'plan') renderPlan();
  if (b.dataset.tab === 'trends') renderTrends();
}));

// ── today ───────────────────────────────────────────────────────────────
function kindOf(s) { return s.sport === 'run' && s.is_long ? 'long' : (KIND[s.sport] ? s.sport : 'rest'); }

function sessionCard(s) {
  const k = kindOf(s), [kname, color] = KIND[k], st = s.structure || {};
  const big = [s.distance_mi != null ? `<span>${esc(s.distance_mi)}<small> mi</small></span>` : '',
               s.duration_min ? `<span>${s.sport === 'run' ? '~' : ''}${esc(Math.round(s.duration_min))}<small> min</small></span>` : '',
               s.max_zone && s.sport !== 'strength' ? `<span>${esc(s.max_zone)}</span>` : ''].join('');
  let body = '';
  if (st.pace || st.hr_avg_max) body += `<div class="targets">
      ${st.pace ? `<div><b>${esc(st.pace)}</b><span>pace /mi</span></div>` : ''}
      ${st.hr_avg_max ? `<div><b>≤ ${esc(st.hr_avg_max)}</b><span>avg HR</span></div>` : ''}
      ${st.walk_if_hr_over ? `<div><b>${esc(st.walk_if_hr_over)}</b><span>walk if HR over</span></div>` : ''}</div>`;
  const lines = [];
  if (st.run_walk) lines.push(`<b>${esc(st.run_walk)}</b> the whole way`);
  if (st.fuel) lines.push(`Fuel: ${esc(st.fuel)}`);
  if (st.walk_breaks) lines.push('Walk breaks are fine');
  if (lines.length) body += `<ol class="steps">${lines.map(l => `<li>${l}</li>`).join('')}</ol>`;
  if (st.exercises) body += `<table class="ex">${st.exercises.map(([n, r, w]) =>
      `<tr><td class="t">${esc(n)}</td><td>${esc(r)}</td><td class="t muted">${esc(w)}</td></tr>`).join('')}</table>`;
  if (s.notes) body += `<div class="note">${esc(s.notes)}</div>`;
  if (s.flags?.length) body += s.flags.map(f => `<div class="flagline"><span class="pill ${f.severity === 'stop' ? 'stop' : 'warn'}">${f.severity === 'stop' ? '✕' : '▲'} ${esc(f.kind.replace(/_/g, ' '))}</span><span>${esc(f.message)}</span></div>`).join('');
  const done = s.status === 'done' ? ' <span class="done-chip">✓ done</span>' : '';
  return `<section class="card workout" style="--accent:${color}">
    <div class="label"><span class="kdot" style="background:${color}"></span>Today · ${kname}${done}</div>
    <div class="wk-title">${esc(s.title)}</div>${big ? `<div class="wk-big">${big}</div>` : ''}${body}</section>`;
}

function next4(days) {
  return days.map(d => `<div class="n4">
    <div class="n4d"><span>${fmt(d.date, {weekday: 'short'})}</span><b>${fmt(d.date, {day: 'numeric'})}</b></div>
    <div class="n4s">${d.sessions.map(s => {
      if (s.suppressed) return '<div class="n4row"><span class="kbar" style="background:var(--red)"></span><div><div class="n4t">Health hold</div></div></div>';
      const [kname, color] = KIND[kindOf(s)];
      const meta = [s.distance_mi != null ? `${s.distance_mi} mi` : '', s.duration_min ? `${Math.round(s.duration_min)} min` : ''].filter(Boolean).join(' · ');
      return `<div class="n4row"><span class="kbar" style="background:${color}"></span>
        <div><div class="n4t">${esc(s.title)}</div><div class="n4m">${kname}${meta ? ' · ' + meta : ''}</div></div></div>`;
    }).join('') || '<div class="n4row"><span class="kbar" style="background:var(--muted)"></span><div><div class="n4t">Rest</div></div></div>'}</div></div>`).join('');
}

function gateCard(g) {
  if (!g) return '';
  const V = {go: ['GO', 'var(--green)', `${g.planned_mi} mi as planned`],
             pending: ['PENDING', 'var(--orange)', `${g.planned_mi} mi if everything below passes; otherwise ${g.fallback_mi}`],
             fallback: ['FALLBACK', 'var(--red)', `Run ${g.fallback_mi} mi instead of ${g.planned_mi}`]}[g.verdict];
  const icon = {pass: ['✓', 'ok'], fail: ['✕', 'stop'], pending: ['…', 'off']};
  return `<section class="card"><div class="label">${fmt(g.date, {weekday: 'short', month: 'short', day: 'numeric'})} long run · go/no-go</div>
    <div class="verdict" style="color:${V[1]}">${V[0]}</div><div class="muted" style="font-size:13px;margin:-6px 0 10px">${esc(V[2])}</div>
    ${g.conditions.map(c => `<div class="cond"><span class="pill ${icon[c.status][1]}">${icon[c.status][0]}</span><span>${esc(c.label)}</span></div>`).join('')}</section>`;
}

function readinessCard(r) {
  if (!r) return '';
  const rhr = r.resting_hr != null && r.resting_hr_baseline != null ? ` <span class="muted">(base ${r.resting_hr_baseline})</span>` : '';
  const t = r.temp_deviation_c != null ? `${r.temp_deviation_c > 0 ? '+' : ''}${r.temp_deviation_c.toFixed(1)}°` : '—';
  return `<section class="card"><div class="label">This morning · Oura ${fmt(r.day, {month: 'short', day: 'numeric'})}</div>
    <div class="readiness"><div><b>${esc(r.readiness ?? '—')}</b><span>readiness</span></div>
    <div><b>${esc(r.resting_hr ?? '—')}</b><span>resting HR${rhr}</span></div>
    <div><b>${t}</b><span>temperature</span></div></div></section>`;
}

function recentCard(acts) {
  if (!acts?.length) return '';
  return `<section class="card"><div class="label">Last 7 days</div>${acts.map(a => {
    const [kname, color] = KIND[a.sport === 'run' ? 'run' : (KIND[a.sport] ? a.sport : 'rest')];
    const flags = a.flags.map(f => `<div class="n4m" style="color:var(--orange)">▲ ${esc(f.message)}</div>`).join('');
    return `<div class="act"><div class="n4d"><span>${fmt(a.date, {weekday: 'short'})}</span><b>${fmt(a.date, {day: 'numeric'})}</b></div>
      <div><div class="n4t">${esc(a.title || kname)}</div>${flags}</div>
      <div class="v">${a.mi ? a.mi + ' mi<br>' : ''}${a.min} min${a.avg_hr ? '<br>' + Math.round(a.avg_hr) + ' bpm' : ''}</div></div>`;
  }).join('')}</section>`;
}

function statusLine(h, phase) {
  const cls = {clear: 'blue', caution: 'warn', hold: 'stop', return: 'ok'}[h.status];
  const label = {clear: phase.name || 'Training', caution: 'Caution today', hold: 'Health hold', return: 'Return to training'}[h.status];
  return `<div class="statusline"><span class="pill ${cls}">● ${esc(label)}</span><span class="muted">${esc(h.reasons[0] || '')}</span></div>`;
}

function renderToday(t, cached) {
  $('hdrdate').textContent = fmt(t.today, {weekday: 'short', month: 'short', day: 'numeric'}).toUpperCase();
  $('phase').textContent = t.phase.name ? `${t.phase.name} · ends ${fmt(t.phase.end, {month: 'short', day: 'numeric'})}` : '';
  $('goals').innerHTML = t.races.map((r, i) => `<div class="goal${i === 0 ? ' primary' : ''}">
      <span class="bar" style="background:${['var(--blue)', 'var(--green)', 'var(--orange)'][i] || 'var(--muted)'}"></span>
      <div class="badge">Goal #${r.priority} · ${esc(r.distance)}${r.status === 'uncertain' ? ' · uncertain' : ''}</div>
      <div class="days">${r.days_until}<small>days</small></div>
      <div class="name">${esc(r.name.replace('IRONMAN ', 'IM '))}</div>
      <div class="meta">${r.goal_time ? 'Goal ' + esc(hm(r.goal_time)) : 'Target after PR'}${r.stretch_time ? ' · stretch ' + esc(hm(r.stretch_time)) : ''}</div></div>`).join('');
  const sessions = t.sessions.filter(s => !s.suppressed);
  let todayHtml = statusLine(t.health, t.phase);
  if (!t.health.prescriptions_allowed) {
    todayHtml += `<section class="card hold"><div class="state"><span class="dot"></span>Health hold</div><h2>No workout today.</h2>
      <ul class="crit">${t.health.reasons.slice(1).map(r => `<li><span class="box"></span><div class="t">${esc(r.replace('to exit: ', ''))}</div></li>`).join('')}</ul></section>`;
  } else if (sessions.length) {
    todayHtml += sessions.map(sessionCard).join('');
    if (!sessions.some(s => s.sport === 'strength')) todayHtml += '<div class="none-line"><b>No lifting today.</b></div>';
  } else {
    todayHtml += '<section class="card workout" style="--accent:var(--muted)"><div class="label">Today</div><div class="wk-title">Rest day</div></section>';
  }
  todayHtml += `<section class="card"><div class="label">Next 4 days</div>${next4(t.next_days)}</section>`;
  todayHtml += gateCard(t.long_run_gate) + readinessCard(t.readiness) + recentCard(t.recent_activities);
  $('today').innerHTML = todayHtml;
  const last = t.last_sync ? new Date(t.last_sync.finished_at).toLocaleString('en-US', {weekday: 'short', hour: 'numeric', minute: '2-digit'}) : 'never';
  $('sync').textContent = (cached ? `Offline · showing data from ${new Date(cached).toLocaleString()}. ` : '') + `Last sync ${last}`;
}

// ── plan ────────────────────────────────────────────────────────────────
async function renderPlan() {
  try {
    const {data} = await api('/api/plan?days=14');
    const todayIso = $('hdrdate').dataset.iso;
    $('plan').innerHTML = `<section class="card"><div class="label">This week and next</div>${data.map(d => `
      <div class="plan-day${d.date === todayIso ? ' today' : ''}"><div class="n4d"><span>${fmt(d.date, {weekday: 'short'})}</span><b>${fmt(d.date, {day: 'numeric'})}</b></div>
      <div class="n4s">${d.sessions.map(s => {
        const [kname, color] = KIND[kindOf(s)];
        const meta = [s.distance_mi != null ? `${s.distance_mi} mi` : '', s.duration_min ? `${Math.round(s.duration_min)} min` : ''].filter(Boolean).join(' · ');
        const act = s.actual ? ` <span class="done-chip">✓ ${s.actual.mi} mi · ${Math.round(s.actual.avg_hr || 0)} bpm</span>` : '';
        return `<div class="n4row"><span class="kbar" style="background:${color}"></span><div><div class="n4t">${esc(s.title)}${act}</div><div class="n4m">${kname}${meta ? ' · ' + meta : ''}</div></div></div>`;
      }).join('') || '<div class="n4m">Rest</div>'}</div></div>`).join('')}</section>`;
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('plan').innerHTML = errorCard('Plan', e.why || e.message); }
}

// ── trends ──────────────────────────────────────────────────────────────
async function renderTrends() {
  try {
    const {data} = await api('/api/trends');
    const wk = data.weekly_run_mi, max = Math.max(10, ...wk.map(w => Math.max(w.actual, w.planned || 0)));
    const W = 380, H = 190, L = 24, B = 22, T = 8, bw = (W - L) / wk.length, y = v => T + (H - T - B) * (1 - v / max);
    let g = '';
    [0, 10, 20, 30, 40].filter(v => v <= max).forEach(v => g += `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="#2c2c2e"/><text x="${L - 6}" y="${y(v) + 4}" fill="#86868b" font-size="11" text-anchor="end">${v}</text>`);
    wk.forEach((w, i) => {
      const cx = L + bw * i + bw / 2, width = bw * .56, x = cx - width / 2;
      if (w.actual > 0) g += `<rect x="${x}" y="${y(w.actual)}" width="${width}" height="${y(0) - y(w.actual)}" rx="3" fill="#0a84ff"><title>${w.week}: ${w.actual} mi</title></rect>`;
      if (w.planned != null) g += `<line x1="${x - 3}" x2="${x + width + 3}" y1="${y(w.planned)}" y2="${y(w.planned)}" stroke="#64d2ff" stroke-width="2"><title>planned ${w.planned} mi</title></line>`;
      if (i % 2 === 0) g += `<text x="${cx}" y="${H - 6}" fill="#86868b" font-size="10" text-anchor="middle">${fmt(w.week, {month: 'short', day: 'numeric'})}</text>`;
    });
    const b = data.bench, last = b.at(-1);
    $('trends').innerHTML = `<section class="card"><div class="label">Weekly run miles</div>
      <div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly run miles">${g}</svg></div>
      <div class="legend" style="margin-top:8px"><span><i style="background:var(--blue)"></i>Actual</span><span><i style="background:var(--teal);height:2px;vertical-align:3px"></i>Planned</span></div></section>
      <section class="card"><div class="label">Bench press · estimated 1RM</div>${last ? `
      <div class="row"><div class="stat"><div class="v">${Math.round(last.e1rm)}<small> lb</small></div><div class="n">${fmt(last.day, {month: 'short', day: 'numeric'})} · top set ${last.top} lb</div></div>
      <div style="text-align:right"><span class="pill ${last.e1rm >= 225 ? 'ok' : 'stop'}">${last.e1rm >= 225 ? '✓ 225 reached' : '✕ Off track for 225'}</span></div></div>
      <table style="margin-top:10px">${b.slice(-8).reverse().map(x => `<tr><td>${fmt(x.day, {month: 'short', day: 'numeric'})}</td><td>${x.e1rm} lb est.</td><td class="muted">top ${x.top}</td></tr>`).join('')}</table>` : '<p class="muted">No bench sessions in Hevy yet.</p>'}</section>`;
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('trends').innerHTML = errorCard('Trends', e.why || e.message); }
}

// ── start ───────────────────────────────────────────────────────────────
let starting = false;
async function start() {
  if (starting) return;
  starting = true;
  try {
    const {data, cached, why} = await api('/api/today');
    $('signin').hidden = true; $('app').hidden = false;
    $('hdrdate').dataset.iso = String(data.today);
    renderToday(data, cached);
    if (why) $('sync').textContent = `${why}. ` + $('sync').textContent;
    else if (lastLoadMs != null) $('sync').textContent += ` · loaded in ${(lastLoadMs / 1000).toFixed(1)}s`;
  } catch (e) {
    if (e.auth) return showSignin('');
    $('signin').hidden = true; $('app').hidden = false;
    $('today').innerHTML = errorCard('Today', e.why || e.message);
  } finally {
    starting = false;
  }
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
document.addEventListener('visibilitychange', () => { if (!document.hidden) start(); });
start();
