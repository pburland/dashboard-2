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

async function post(path, body, timeoutMs = 90000) {
  const legacy = load(TOKEN_KEY);
  const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(path, {method: 'POST', credentials: 'same-origin', signal: ctl.signal,
      headers: {'Content-Type': 'application/json', ...(legacy ? {'X-Admin-Token': legacy} : {})},
      body: JSON.stringify(body)});
    if (r.status === 401) throw Object.assign(new Error('unauthorized'), {auth: true});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `Server error ${r.status}`);
    return data;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error('No answer after ' + timeoutMs / 1000 + 's');
    throw e;
  } finally { clearTimeout(timer); }
}

// Tiny, safe Markdown: escape first, then **bold**, bullets and paragraphs.
function md(text) {
  const out = [];
  let list = false;
  for (const raw of String(text || '').split('\n')) {
    const line = esc(raw.trim()).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|\s)_(.+?)_(?=\s|$)/g, '$1<i>$2</i>');
    const item = line.match(/^[-*•]\s+(.*)/);
    if (item) { if (!list) { out.push('<ul>'); list = true; } out.push(`<li>${item[1]}</li>`); continue; }
    if (list) { out.push('</ul>'); list = false; }
    if (!line) continue;
    const h = line.match(/^#+\s+(.*)/);
    out.push(h ? `<p><b>${h[1]}</b></p>` : `<p>${line}</p>`);
  }
  if (list) out.push('</ul>');
  return out.join('');
}

function whenLine(s) {
  const b = s.best_time;
  if (!b) return '';
  if (!b.label) return `<div class="when">${esc(b.why)}</div>`;
  const day = fmt(s.date, {weekday: 'short'});
  return `<div class="when">Best time: <b>${esc(day)} ${esc(b.label)}</b>${b.place ? ' in ' + esc(b.place) : ''} · ${esc(b.why)}</div>`;
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
  if (b.dataset.tab === 'reports') renderReports();
  if (b.dataset.tab === 'ask') openChat();
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
  if (st.brief) body += `<div class="brief">${esc(st.brief)}</div>`;
  if (s.notes) body += `<div class="note">${esc(s.notes)}</div>`;
  if (s.flags?.length) body += s.flags.map(f => `<div class="flagline"><span class="pill ${f.severity === 'stop' ? 'stop' : 'warn'}">${f.severity === 'stop' ? '✕' : '▲'} ${esc(f.kind.replace(/_/g, ' '))}</span><span>${esc(f.message)}</span></div>`).join('');
  if (s.status !== 'done') body += whenLine(s);
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
      const bt = s.best_time?.label ? ` · <span class="bt">${esc(s.best_time.label)}</span>` : '';
      const prov = s.structure?.provisional ? '<span class="pill prev">if cleared</span>' : '';
      return `<div class="n4row"><span class="kbar" style="background:${color}"></span>
        <div><div class="n4t">${esc(s.title)}${prov}</div><div class="n4m">${kname}${meta ? ' · ' + meta : ''}${bt}</div></div></div>`;
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
    <div><b>${t}</b><span>temperature</span></div></div>
    ${r.readiness == null ? '<div class="n4m" style="margin-top:8px">Oura hasn\'t scored readiness yet. Open the Oura app to sync your ring; this fills in within 30 minutes.</div>' : ''}</section>`;
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

// ── plan change proposals (chat and auto-rebase) ────────────────────────
function proposalCard(p) {
  const flags = p.flags || [];
  const stops = flags.filter(f => f.severity === 'stop'), warns = flags.filter(f => f.severity === 'warn');
  const changes = Array.isArray(p.changes) ? p.changes : String(p.changes || '').split('; ');
  const id = esc(p.proposal_id || p.id);
  if (p.status === 'refused' || stops.length)
    return `<div class="prop refused"><div class="label">Not allowed</div>${changes.map(c => `<div>${esc(c)}</div>`).join('')}
      ${stops.map(f => `<div class="flagline"><span class="pill stop">✕</span><span>${esc(f.message)}</span></div>`).join('')}</div>`;
  return `<div class="prop" data-id="${id}"><div class="label">Proposed change${p.reason ? ' · ' + esc(p.reason) : ''}</div>
    ${changes.map(c => `<div class="chg">${esc(c)}</div>`).join('')}
    ${warns.map(f => `<label class="ack"><input type="checkbox" value="${esc(f.key)}"> I accept: ${esc(f.message)}</label>`).join('')}
    <div class="prop-btns"><button class="primary-btn" data-act="apply"${warns.length ? ' disabled' : ''}>Confirm</button>
    <button class="ghost-btn" data-act="cancel">Cancel</button></div><div class="n4m prop-msg"></div></div>`;
}

function wireProposals(root) {
  root.querySelectorAll('.prop[data-id]').forEach(el => {
    if (el.dataset.wired) return; el.dataset.wired = '1';
    const id = el.dataset.id, btn = el.querySelector('[data-act=apply]'), boxes = [...el.querySelectorAll('.ack input')];
    boxes.forEach(b => b.onchange = () => { btn.disabled = !boxes.every(x => x.checked); });
    btn.onclick = async () => {
      btn.disabled = true;
      try {
        const r = await post(`/api/plan/proposals/${id}/apply`, {accepted_warns: boxes.map(b => b.value)}, 30000);
        if (r.applied) el.innerHTML = `<div class="label">Done</div>${(r.changes || []).map(c => `<div>${esc(c)}</div>`).join('')}`;
        else if (r.stale) el.outerHTML = proposalCard(r.new_proposal), wireProposals(root);
        else el.querySelector('.prop-msg').textContent = (r.flags || []).map(f => f.message).join(' ') || 'Not applied.';
      } catch (e) { el.querySelector('.prop-msg').textContent = e.message; btn.disabled = false; }
    };
    el.querySelector('[data-act=cancel]').onclick = async () => {
      try { await post(`/api/plan/proposals/${id}/cancel`, {}, 15000); } catch {}
      el.innerHTML = '<div class="n4m">Cancelled. Nothing changed.</div>';
    };
  });
}

// ── post-workout check-in ───────────────────────────────────────────────
function checkinCard(p) {
  if (!p) return '';
  const nums = Array.from({length: 10}, (_, i) => `<button type="button" data-rpe="${i + 1}">${i + 1}</button>`).join('');
  return `<section class="card checkin" id="checkin" data-pid="${p.planned_workout_id ?? ''}" data-aid="${p.activity_id ?? ''}">
    <div class="label">${esc(p.title)} · ${fmt(p.date, {weekday: 'short', month: 'short', day: 'numeric'})}</div>
    <div class="wk-title">How was it?</div>
    <div class="ci-row ci-rpe">${nums}</div>
    <div class="ci-q">Felt:</div><div class="ci-row ci-felt"><button type="button" data-felt="good">Good</button><button type="button" data-felt="fine">Fine</button><button type="button" data-felt="bad">Bad</button></div>
    <div class="ci-q">Any pain?</div><div class="ci-row ci-pain"><button type="button" data-pain="0">No</button><button type="button" data-pain="1">Yes</button></div>
    <input id="ci-where" type="text" placeholder="Where?" maxlength="200" hidden>
    <input id="ci-note" type="text" placeholder="Anything else? (optional)" maxlength="1000">
    <button class="primary-btn" id="ci-done" disabled>Done.</button>
    ${p.planned_workout_id && !p.activity_id ? `<div class="ci-skip"><button class="btn-link" id="ci-skip">Didn't do it</button>
      <div class="ci-row" id="ci-why" hidden>${['busy', 'tired', 'sick', 'weather'].map(r => `<button type="button" data-why="${r}">${r[0].toUpperCase() + r.slice(1)}</button>`).join('')}<button type="button" data-why="">Skip reason</button></div></div>` : ''}
    <div class="n4m" id="ci-msg"></div></section>`;
}

function wireCheckin() {
  const card = $('checkin');
  if (!card) return;
  const st = {rpe: null, felt: null, pain: null};
  const pick = (sel, key, val, btn) => { card.querySelectorAll(sel + ' button').forEach(b => b.classList.toggle('on', b === btn)); st[key] = val; ready(); };
  const ready = () => { $('ci-done').disabled = !(st.rpe && st.felt && st.pain !== null); };
  card.querySelectorAll('.ci-rpe button').forEach(b => b.onclick = () => pick('.ci-rpe', 'rpe', Number(b.dataset.rpe), b));
  card.querySelectorAll('.ci-felt button').forEach(b => b.onclick = () => pick('.ci-felt', 'felt', b.dataset.felt, b));
  card.querySelectorAll('.ci-pain button').forEach(b => b.onclick = () => {
    pick('.ci-pain', 'pain', b.dataset.pain === '1', b);
    $('ci-where').hidden = !st.pain; if (st.pain) $('ci-where').focus();
  });
  if ($('ci-skip')) {
    $('ci-skip').onclick = () => { $('ci-why').hidden = false; };
    card.querySelectorAll('[data-why]').forEach(b => b.onclick = async () => {
      try {
        const r = await post('/api/checkin/skip', {planned_workout_id: Number(card.dataset.pid), reason: b.dataset.why || null}, 15000);
        card.innerHTML = `<div class="label">Skipped</div><div>${esc(r.message)}</div>`;
      } catch (e) { $('ci-msg').textContent = e.message; }
    });
  }
  $('ci-done').onclick = async () => {
    $('ci-done').disabled = true;
    try {
      const r = await post('/api/checkin', {planned_workout_id: card.dataset.pid ? Number(card.dataset.pid) : null,
        activity_id: card.dataset.aid ? Number(card.dataset.aid) : null, rpe: st.rpe, felt: st.felt, pain: st.pain,
        pain_detail: st.pain ? $('ci-where').value.trim() || null : null,
        note: $('ci-note').value.trim() || null}, 15000);
      card.innerHTML = `<div class="label">Checked in</div><div>${esc(r.effects.length ? r.effects.join(' ') : 'Saved.')}</div>`;
      if (r.effects.length) setTimeout(start, 600);       // the gate changed: refresh Today
    } catch (e) {
      if (e.auth) return showSignin('Signed out on this device. Paste your token again.');
      $('ci-msg').textContent = e.message; $('ci-done').disabled = false;
    }
  };
}

function fuelCard(f, b) {
  if (!f) return '';
  const n = x => Number(x).toLocaleString('en-US');
  const scan = b && b.composition_day ? ` (DEXA ${fmt(b.composition_day, {month: 'short', day: 'numeric'})})` : '';
  const body = b ? `<div class="n4m" style="margin-top:8px">${b.source === 'dexa' ? 'DEXA' : 'Weight'} ${fmt(b.day, {month: 'short', day: 'numeric'})}: ${esc(Number(b.weight_lb).toFixed(1))} lb${b.bf_pct != null ? ` · ${esc(Number(b.bf_pct).toFixed(1))}% fat` : ''}${b.lean_lb != null ? ` · ${Math.round(b.lean_lb)} lb lean` : ''}${scan}</div>` : '';
  const day = {rest: 'Rest day', lift: 'Lifting day', easy: 'Easy day', lift_easy: 'Lift + easy day', key: 'Key session day',
               long_run: 'Long run day', long_ride: 'Long ride day'}[f.day_type];
  return `<section class="card"><div class="label">Fuel today</div>
    <div class="readiness"><div><b>${n(f.kcal)}</b><span>calories</span></div>
    <div><b>${f.protein_g}g</b><span>protein</span></div><div><b>${f.carbs_g}g</b><span>carbs</span></div></div>
    ${day ? `<div class="n4m" style="margin-top:8px">${esc(day)}${f.fat_min_g ? ` · fat at least ${f.fat_min_g} g` : ''}</div>` : ''}
    ${f.why.length ? `<div class="n4m" style="margin-top:8px">${esc(f.why.join('; '))}</div>` : ''}${body}</section>`;
}

function zonesCard(z) {
  if (!z || !(z.pending.length || z.invalid.length || z.due.length)) return '';
  const name = {run_lthr: 'Run test', bike_ftp: 'Bike test', swim_css: 'Swim test'};
  const pend = z.pending.map(p => `<p><b>${name[p.kind]} (${esc(fmt(p.test_date, {month: 'short', day: 'numeric'}))})</b>:
      ${esc(p.text)}. That's a big change from the provisional numbers. Use the new zones?</p>
      <button class="primary-btn" data-test="${p.id}" data-choice="apply">Use new zones</button>
      <button class="ghost-btn" data-test="${p.id}" data-choice="reject" style="margin-top:8px;width:100%">Keep the old ones</button>`).join('');
  const bad = z.invalid.map(i => `<p class="muted">${name[i.kind]} didn't count: ${esc(i.reason)}. Old zones kept; a re-test is planned in 7 days.</p>`).join('');
  const due = z.due.map(d => `<p class="muted">${esc(d)}</p>`).join('');
  return `<section class="card"><div class="label">Training zones</div>${pend}${bad}${due}<div class="n4m" id="zonemsg"></div></section>`;
}

document.addEventListener('click', async e => {
  const b = e.target.closest('[data-test]');
  if (!b) return;
  try { await post(`/api/tests/${b.dataset.test}/${b.dataset.choice}`, {}); $('zonemsg').textContent = 'Saved. Updating your plan…'; setTimeout(start, 800); }
  catch (err) { $('zonemsg').textContent = err.why || err.message; }
});

// One status light with one plain reason (outside review): the detail lives in the report.
function statusLine(h, phase) {
  const color = {clear: 'var(--green)', caution: 'var(--orange)', hold: 'var(--red)', return: 'var(--blue)'}[h.status];
  const extra = h.reasons.filter(r => !r.startsWith('return to training') && !r.startsWith('long run capped'));
  let label, why;
  if (h.status === 'return' && h.comeback) {
    const c = h.comeback;
    label = `Comeback · day ${c.day} of ${c.days}`;
    why = extra[0] || `Easy effort only · ${c.volume_pct}% volume · ends ${fmt(c.ends, {month: 'short', day: 'numeric'})}`;
  } else {
    label = {clear: 'Clear to train', caution: 'Take it easy today', hold: 'Health hold', return: 'Comeback'}[h.status];
    why = h.status === 'clear' ? (phase.name ? `${phase.name}: train as planned` : 'Train as planned') : (extra[0] || h.reasons[0] || '');
  }
  const watch = h.reasons.some(r => r.startsWith('Easing off')) ? [] : (h.watch || []);
  return `<section class="card light" id="statuslight"><span class="lamp" style="background:${color}" aria-hidden="true"></span>
    <div><div class="light-label">${esc(label)}</div><div class="light-why">${esc(why[0] ? why[0].toUpperCase() + why.slice(1) : '')}</div>
    ${watch.length ? `<div class="light-watch">${esc(watch[0])}</div>` : ''}</div></section>`;
}

function renderToday(t, cached) {
  if (t.athlete?.name) document.querySelector('header h1').textContent = t.athlete.name;
  if (t.athlete?.assistant) { document.querySelector('[data-tab=ask]').textContent = t.athlete.assistant; store('training.assistant', t.athlete.assistant); }
  $('hdrdate').textContent = fmt(t.today, {weekday: 'short', month: 'short', day: 'numeric'}).toUpperCase();
  $('hdrplace').textContent = t.where && t.where.away ? `${t.where.place} time` : 'server clock';
  $('phase').textContent = (t.phase.name ? `${t.phase.name} · ends ${fmt(t.phase.end, {month: 'short', day: 'numeric'})}` : '')
    + (t.where && t.where.away ? ` · ${t.where.place}` : '');
  $('goals').innerHTML = t.races.map((r, i) => `<div class="goal${i === 0 ? ' primary' : ''}">
      <span class="bar" style="background:${['var(--blue)', 'var(--green)', 'var(--orange)'][i] || 'var(--muted)'}"></span>
      <div class="badge">Goal #${r.priority} · ${esc(r.distance)}${r.status === 'uncertain' ? ' · uncertain' : ''}</div>
      <div class="days">${r.days_until}<small>days</small></div>
      <div class="name">${esc(r.name.replace('IRONMAN ', 'IM '))}</div>
      <div class="meta">${r.goal_time ? 'Goal ' + esc(hm(r.goal_time)) : 'Goal: finish strong'}${r.stretch_time ? ' · stretch ' + esc(hm(r.stretch_time)) : ''}</div></div>`).join('');
  const sessions = t.sessions.filter(s => !s.suppressed);
  let todayHtml = statusLine(t.health, t.phase) + checkinCard(t.pending_checkin)
    + (t.proposals || []).map(p => `<section class="card">${proposalCard(p)}</section>`).join('');
  if (!t.health.prescriptions_allowed) {
    todayHtml += `<section class="card hold"><div class="state"><span class="dot"></span>Health hold</div><h2>No workout today.</h2>
      <ul class="crit">${t.health.reasons.slice(1).map(r => `<li><span class="box"></span><div class="t">${esc(r.replace('to exit: ', ''))}</div></li>`).join('')}</ul>
      ${t.health.status === 'hold' ? (new URLSearchParams(location.search).get('clear') ? clearanceForm() : '<button class="primary-btn" id="clearopen">I\'ve been cleared</button>') : ''}</section>`;
  } else if (sessions.length) {
    todayHtml += sessions.map(sessionCard).join('');
    if (!sessions.some(s => s.sport === 'strength')) todayHtml += '<div class="none-line"><b>No lifting today.</b></div>';
  } else {
    todayHtml += '<section class="card workout" style="--accent:var(--muted)"><div class="label">Today</div><div class="wk-title">Rest day</div></section>';
  }
  const n4 = t.next_days.length ? next4(t.next_days)
    : `<div class="n4m">${t.health.prescriptions_allowed ? 'Nothing planned yet.' : 'Nothing during the hold. The Plan tab shows what follows once you\'re cleared.'}</div>`;
  todayHtml += `<section class="card"><div class="label">Next 4 days</div>${n4}${t.timing_note ? `<div class="n4m" style="margin-top:8px">Best times without: ${esc(t.timing_note)}</div>` : ''}</section>`;
  todayHtml += fuelCard(t.fuel, t.body);
  todayHtml += zonesCard(t.zones);
  todayHtml += gateCard(t.long_run_gate) + recentCard(t.recent_activities);
  if (t.readiness) todayHtml += `<details class="details-card"><summary>Recovery numbers</summary>${readinessCard(t.readiness)}</details>`;
  $('today').innerHTML = todayHtml;
  wireCheckin(); wireProposals($('today')); wireClearance();
  if ($('clearopen')) $('clearopen').onclick = () => { $('clearopen').outerHTML = clearanceForm(); wireClearance(); };
  const last = t.last_sync ? new Date(t.last_sync.finished_at).toLocaleString('en-US', {weekday: 'short', hour: 'numeric', minute: '2-digit'}) : 'never';
  $('sync').textContent = (cached ? `Offline · showing data from ${new Date(cached).toLocaleString()}. ` : '') + `Last sync ${last}`;
}

// ── plan ────────────────────────────────────────────────────────────────
let planView = 'weeks';
async function renderPlan() {
  if (planView === 'season') return renderSeason();
  try {
    const {data} = await api('/api/plan?days=28');
    const todayIso = $('hdrdate').dataset.iso;
    let html = '', week = -1;
    data.days.forEach((d, i) => {
      if (Math.floor(i / 7) !== week) {
        week = Math.floor(i / 7);
        const anyPrev = data.days.slice(week * 7, week * 7 + 7).some(x => x.sessions.some(s => s.structure?.preview));
        html += `<div class="weekhdr">Week of ${fmt(d.date, {month: 'short', day: 'numeric'})}${anyPrev ? ' · preview, re-planned Sunday' : ''}</div>`;
      }
      html += `<div class="plan-day${d.date === todayIso ? ' today' : ''}"><div class="n4d"><span>${fmt(d.date, {weekday: 'short'})}</span><b>${fmt(d.date, {day: 'numeric'})}</b></div>
      <div class="n4s">${d.sessions.map(s => {
        const [kname, color] = KIND[kindOf(s)] || KIND.rest, st = s.structure || {};
        const meta = [s.distance_mi != null ? `${s.distance_mi} mi` : '', s.duration_min ? `${Math.round(s.duration_min)} min` : ''].filter(Boolean).join(' · ');
        const act = s.actual ? ` <span class="done-chip">✓ ${s.actual.mi} mi · ${Math.round(s.actual.avg_hr || 0)} bpm</span>` : '';
        const cb = st.changed_by;
        const tag = (s.status === 'skipped' ? '<span class="pill prev">skipped</span>' : '')
          + (st.provisional ? '<span class="pill prev">if cleared</span>' : '')
          + (cb ? `<span class="pill prev">${esc(cb.by === 'you' ? 'moved by you' : cb.by)} · ${fmt(cb.on, {month: 'short', day: 'numeric'})}</span>` : '');
        const why = cb ? `<div class="brief">Why: ${esc(cb.reason)}${cb.batch && s.status === 'planned' && Date.now() - D(cb.on) < 7 * 864e5
          ? ` <button class="btn-link" data-undo="${esc(cb.batch)}">Undo</button>` : ''}</div>` : '';
        const bt = s.best_time?.label ? ` · <span class="bt">${esc(s.best_time.label)}</span>` : '';
        const more = (st.brief || s.best_time ? `<div class="brief">${esc(st.brief || '')}</div>${whenLine(s)}` : '') + why;
        return `<div class="n4row"><span class="kbar" style="background:${color}"></span><div style="flex:1"><details class="pb"><summary>
          <div class="n4t">${esc(s.title)}${tag}${act}</div><div class="n4m">${kname}${meta ? ' · ' + meta : ''}${bt}</div></summary>${more}</details></div></div>`;
      }).join('') || '<div class="n4m">Rest</div>'}</div></div>`;
    });
    $('plan').innerHTML = planToggle() + `<section class="card"><div class="label">Next 4 weeks · tap a workout for its brief</div>${html}
      ${data.timing_note ? `<div class="n4m" style="margin-top:10px">Best times without: ${esc(data.timing_note)}</div>` : ''}</section>`;
    wirePlanToggle();
    $('plan').querySelectorAll('[data-undo]').forEach(b => b.onclick = async ev => {
      ev.preventDefault(); b.disabled = true;
      try { await post(`/api/plan/undo/${b.dataset.undo}`, {}, 15000); renderPlan(); }
      catch (e) { b.textContent = e.message; }
    });
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('plan').innerHTML = errorCard('Plan', e.why || e.message); }
}

function planToggle() {
  return `<div class="seg" role="tablist"><button data-view="weeks" aria-selected="${planView === 'weeks'}">Next 4 weeks</button>
    <button data-view="season" aria-selected="${planView === 'season'}">Season</button></div>`;
}
function wirePlanToggle() {
  $('plan').querySelectorAll('[data-view]').forEach(b => b.onclick = () => { planView = b.dataset.view; renderPlan(); });
}

// The season on one page: phases as a strip, then everything dated in order.
async function renderSeason() {
  try {
    const {data} = await api('/api/season');
    const day = d => fmt(d, {month: 'short', day: 'numeric'});
    const ph = data.phases, t0 = Date.parse(ph[0]?.start_date || data.today), t1 = Date.parse(ph.at(-1)?.end_date || data.today);
    const span = Math.max(1, t1 - t0);
    const kindColor = {prep: 'var(--muted)', return: 'var(--muted)', base: 'var(--blue)', build: 'var(--orange)',
                       peak: 'var(--red)', race: 'var(--red)', transition: 'var(--card2)'};
    const strip = ph.map(p => {
      const w = 100 * (Date.parse(p.end_date) - Date.parse(p.start_date) + 864e5) / (span + 864e5);
      return `<div class="seg-ph" style="width:${w.toFixed(2)}%;background:${kindColor[p.kind] || 'var(--card2)'}"
        title="${esc(p.name)}: ${day(p.start_date)}–${day(p.end_date)}"></div>`;
    }).join('');
    const nowPct = 100 * (Date.parse(data.today) - t0) / span;
    const items = [];
    ph.forEach(p => items.push([p.start_date, '▸', `${p.name} starts`, `until ${day(p.end_date)}`]));
    data.races.forEach(r => items.push([r.race_date, '🏁', r.name, `${r.distance} · goal #${r.priority}${r.status === 'uncertain' ? ' · undecided' : ''}`]));
    data.events.forEach(e => items.push([e.event_date, e.kind === 'test' ? '⏱' : '★', e.title, '']));
    if (data.return) items.push([data.return.end, '✓', 'Comeback ends', 'normal training from the next day']);
    data.checkpoints.forEach(c => items.push([c.date, '◆', c.name, '']));
    data.deficit_blocks.forEach(b => items.push([b.from, '🍽', `Calorie deficit: ${b.name}`, `to ${day(b.to)} · ${b.kcal} kcal under on easy days`]));
    data.lift_checkpoints.forEach(l => items.push([l.date, '🏋️', `${l.lift} checkpoint: ${l.lb} lb`, '']));
    items.sort((a, b) => String(a[0]).localeCompare(String(b[0])));
    let month = '';
    const list = items.map(([d, icon, title, sub]) => {
      const m = fmt(d, {month: 'long', year: 'numeric'});
      const head = m !== month ? `<div class="weekhdr">${esc(m)}</div>` : '';
      month = m;
      return `${head}<div class="season-row${d < data.today ? ' past' : ''}"><span class="season-d">${esc(day(d))}</span>
        <span class="season-i" aria-hidden="true">${icon}</span><div><div>${esc(title)}</div>${sub ? `<div class="muted">${esc(sub)}</div>` : ''}</div></div>`;
    }).join('');
    $('plan').innerHTML = planToggle() + `<section class="card"><div class="label">Season</div>
      <div class="strip">${strip}<div class="strip-now" style="left:${Math.min(100, Math.max(0, nowPct)).toFixed(1)}%" title="Today"></div></div>
      <div class="legend" style="margin:8px 0 4px"><span><i style="background:var(--muted)"></i>Comeback / prep</span><span><i style="background:var(--blue)"></i>Base</span>
        <span><i style="background:var(--orange)"></i>Build</span><span><i style="background:var(--red)"></i>Peak / race</span></div>
      <div class="n4m">${esc(data.undecided)}</div></section>
      <section class="card">${list || '<div class="n4m">Nothing scheduled yet.</div>'}</section>`;
    wirePlanToggle();
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('plan').innerHTML = errorCard('Season', e.why || e.message); }
}

// ── line charts for Trends (one y-axis; thin 2px lines; hover titles on points) ──
function lineChart({series, yfmt = v => v, invert = false, H = 160, xs}) {
  const W = 380, L = 40, R = 46, T = 10, B = 22;
  const all = series.flatMap(s => s.pts.map(p => p.y));
  if (!all.length) return '';
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.12; lo -= pad; hi += pad;
  const x0 = Date.parse(xs[0]), x1 = Math.max(x0 + 864e5, Date.parse(xs.at(-1)));
  const px = d => L + (W - L - R) * (Date.parse(d) - x0) / (x1 - x0);
  const py = v => { const f = (v - lo) / (hi - lo); return T + (H - T - B) * (invert ? f : 1 - f); };
  let g = '';
  for (let i = 0; i <= 3; i++) {
    const v = lo + (hi - lo) * i / 3;
    g += `<line x1="${L}" x2="${W - R}" y1="${py(v)}" y2="${py(v)}" stroke="#2c2c2e"/><text x="${L - 6}" y="${py(v) + 4}" fill="#86868b" font-size="10" text-anchor="end">${esc(yfmt(v))}</text>`;
  }
  [xs[0], xs[Math.floor(xs.length / 2)], xs.at(-1)].forEach((d, i) =>
    g += `<text x="${px(d)}" y="${H - 6}" fill="#86868b" font-size="10" text-anchor="${['start', 'middle', 'end'][i]}">${esc(fmt(d, {month: 'short', day: 'numeric'}))}</text>`);
  series.forEach(s => {
    if (s.dots) s.pts.forEach(p => g += `<circle cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="3" fill="${s.color}" opacity=".45"><title>${esc(p.label)}</title></circle>`);
    if (s.line && s.pts.length > 1) {
      g += `<polyline points="${s.pts.map(p => `${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(' ')}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>`;
      s.pts.forEach(p => g += `<circle cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="9" fill="transparent"><title>${esc(p.label)}</title></circle>`);
      const last = s.pts.at(-1);
      if (s.name) g += `<text x="${px(last.x) + 6}" y="${py(last.y) + 4}" fill="#aeaeb2" font-size="10">${esc(s.name)}</text>`;
    }
  });
  return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map(s => s.name || '').join(', '))}">${g}</svg></div>`;
}

const pace = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

function loadCard(ld) {
  const d = ld.days;
  if (!d.length || !d.some(x => x.fitness > 0)) return '<section class="card"><div class="label">Fitness and fatigue</div><p class="muted">Not enough workouts with heart rate yet.</p></section>';
  const xs = d.map(x => x.day), now = d.at(-1), then = d[Math.max(0, d.length - 29)];
  const chart = lineChart({xs, series: [
    {name: 'Fitness', color: '#0a84ff', line: true, pts: d.map(x => ({x: x.day, y: x.fitness, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: fitness ${x.fitness}`}))},
    {name: 'Fatigue', color: '#c86e08', line: true, pts: d.map(x => ({x: x.day, y: x.fatigue, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: fatigue ${x.fatigue}`}))}],
    yfmt: v => Math.round(v)});
  const df = now.fitness - then.fitness;
  const form = now.form > 5 ? 'fresh' : now.form < -10 ? 'carrying fatigue' : 'normal training load';
  return `<section class="card"><div class="label">Fitness and fatigue</div>
    <div class="row"><div class="stat"><div class="v">${now.form > 0 ? '+' : ''}${Math.round(now.form)}</div><div class="n">form today (fitness − fatigue): ${form}</div></div></div>
    ${chart}<div class="legend" style="margin-top:6px"><span><i style="background:#0a84ff"></i>Fitness (6-week average)</span><span><i style="background:#c86e08"></i>Fatigue (1-week average)</span></div>
    <div class="n4m">Fitness is ${df >= 0 ? 'up' : 'down'} ${Math.abs(df).toFixed(1)} over 4 weeks. Interpret with caution: built from heart-rate load (swims without HR count as zero) until per-sport scores are added.</div></section>`;
}

function weightCard(w) {
  const d = w.days;
  if (d.length < 2) return '<section class="card"><div class="label">Body weight · 7-day average</div><p class="muted">Log morning weigh-ins in Hevy (Body measurements) to see the trend.</p></section>';
  const xs = d.map(x => x.day), now = d.at(-1), then = d[Math.max(0, d.length - 15)];
  const perWk = (now.avg7 - then.avg7) / Math.max(1, (Date.parse(now.day) - Date.parse(then.day)) / 6048e5);
  const chart = lineChart({xs, series: [
    {color: '#0a84ff', dots: true, pts: d.filter(x => x.weighed != null).map(x => ({x: x.day, y: x.weighed, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: ${x.weighed} lb`}))},
    {color: '#0a84ff', line: true, pts: d.map(x => ({x: x.day, y: x.avg7, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: 7-day average ${x.avg7} lb`}))}],
    yfmt: v => v.toFixed(1)});
  return `<section class="card"><div class="label">Body weight · 7-day average</div>
    <div class="row"><div class="stat"><div class="v">${now.avg7}<small> lb</small></div><div class="n">${perWk <= 0 ? 'down' : 'up'} ${Math.abs(perWk).toFixed(1)} lb a week over 2 weeks</div></div></div>
    ${chart}<div class="n4m">Dots are weigh-ins, the line is the 7-day average. In a deficit block the target is losing about 0.4–0.8 lb a week; faster than that, the app eases the deficit.</div></section>`;
}

function efficiencyCard(e) {
  const r = e.runs;
  if (r.length < 2) return `<section class="card"><div class="label">Running pace at ${e.hr} bpm</div><p class="muted">Needs a few flat, easy runs of 20+ minutes with heart rate.</p></section>`;
  const xs = r.map(x => x.day), now = r.at(-1), then = r.find(x => Date.parse(x.day) >= Date.parse(now.day) - 28 * 864e5) || r[0];
  const chart = lineChart({xs, invert: true, series: [
    {color: '#0a84ff', dots: true, pts: r.map(x => ({x: x.day, y: x.pace_s, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: ${pace(x.pace_s)}/mi at ${e.hr} bpm`}))},
    {color: '#0a84ff', line: true, pts: r.map(x => ({x: x.day, y: x.rolling_pace_s, label: `${fmt(x.day, {month: 'short', day: 'numeric'})}: 4-week average ${pace(x.rolling_pace_s)}/mi`}))}],
    yfmt: v => pace(v)});
  const diff = then.rolling_pace_s - now.rolling_pace_s;
  const verdict = Math.abs(diff) < 5 ? 'holding steady' : diff > 0 ? `${diff} s/mi faster than 4 weeks ago: aerobic fitness improving` : `${-diff} s/mi slower than 4 weeks ago: fatigue, heat or lost fitness`;
  return `<section class="card"><div class="label">Running pace at ${e.hr} bpm · higher is faster</div>
    <div class="row"><div class="stat"><div class="v">${pace(now.rolling_pace_s)}<small> /mi</small></div><div class="n">${esc(verdict)}</div></div></div>
    ${chart}<div class="n4m">Flat, easy runs only (under 15 m of climbing per mile). Dots are single runs; the line is the 4-week average. Interpret with caution.</div></section>`;
}

// ── reports ─────────────────────────────────────────────────────────────
async function renderReports() {
  try {
    const {data} = await api('/api/reports');
    if (!data.length) {
      $('reports').innerHTML = '<section class="card"><div class="label">Weekly reports</div><p class="muted">The first report is written Sunday evening. Each one sets up the next week\'s plan.</p></section>';
      return;
    }
    $('reports').innerHTML = data.map(r => {
      const s = r.summary || {}, dec = s.decision || {};
      const f = dec.factor, pill = f == null ? '' : f > 1 ? `<span class="pill ok">Next week +${Math.round((f - 1) * 100)}%</span>`
        : f < 1 ? `<span class="pill warn">Next week −${Math.round((1 - f) * 100)}%</span>` : '<span class="pill off">Next week: hold steady</span>';
      return `<section class="card report"><div class="label">Week of ${fmt(r.week_start, {month: 'short', day: 'numeric'})}</div>
        <div class="meta"><span class="pill blue">${esc(s.completed_sessions ?? 0)}/${esc(s.planned_sessions ?? 0)} sessions</span>
        <span class="pill blue">${esc(s.actual_run_mi ?? 0)} run mi</span>${pill}</div>${md(r.narrative)}</section>`;
    }).join('');
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('reports').innerHTML = errorCard('Reports', e.why || e.message); }
}

// ── Pat-GPT ─────────────────────────────────────────────────────────────
const CONV_KEY = 'training.chat.conversation';
const CHIPS = ['When should I do my next workout?', 'How did last week go?', 'What does my doctor need to clear me?', 'Summarize my next 2 weeks'];
let chatLoaded = false, chatBusy = false;

function chatMsg(role, html, extra = '') {
  $('chatlog').insertAdjacentHTML('beforeend', `<div class="msg ${role === 'user' ? 'me' : 'ai'} ${extra}">${html}</div>`);
  $('chatlog').lastElementChild.scrollIntoView({block: 'end', behavior: 'smooth'});
  return $('chatlog').lastElementChild;
}
function actsHtml(acts) {
  return (acts || []).filter(a => ['propose_change', 'replan_week'].includes(a.tool) && a.result && a.result.proposal_id)
    .map(a => proposalCard(a.result)).join('') + actsLine(acts);
}
function actsLine(acts) {
  const words = (acts || []).map(a => a.tool === 'log_note' ? `Noted (${a.input.type})`
    : a.tool === 'start_health_hold' && a.result.opened ? 'Health hold started'
    : a.tool === 'apply_change' && a.result.applied ? 'Plan updated'
    : a.tool === 'add_travel' && a.result.saved ? 'Trip saved'
    : a.tool === 'save_preference' && a.result.saved ? 'Preference saved' : '').filter(Boolean);
  return words.length ? `<div class="acts">✓ ${esc(words.join(' · '))}</div>` : '';
}
async function openChat() {
  $('chips').innerHTML = CHIPS.map(c => `<button type="button">${esc(c)}</button>`).join('');
  $('chips').querySelectorAll('button').forEach(b => b.onclick = () => { $('chatin').value = b.textContent; $('compose').requestSubmit(); });
  if (chatLoaded) return;
  chatLoaded = true;
  const id = load(CONV_KEY);
  if (!id) { chatMsg('ai', md("Ask me anything about your training: today's workout, the best time to fit it in, how last week went, or what's coming next.")); return; }
  try {
    const {data} = await api('/api/chat/' + id);
    $('chatlog').innerHTML = '';
    data.forEach(m => chatMsg(m.role, (m.role === 'user' ? esc(m.content) : md(m.content)) + (m.role === 'assistant' ? actsHtml(m.actions) : '')));
    wireProposals($('chatlog'));
  } catch { try { localStorage.removeItem(CONV_KEY); } catch {} }
}
$('newchat').onclick = () => { try { localStorage.removeItem(CONV_KEY); } catch {} $('chatlog').innerHTML = ''; chatLoaded = false; openChat(); };
$('chatin').addEventListener('input', e => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px'; });
$('chatin').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !('ontouchstart' in window)) { e.preventDefault(); $('compose').requestSubmit(); } });
$('compose').onsubmit = async e => {
  e.preventDefault();
  const text = $('chatin').value.trim();
  if (!text || chatBusy) return;
  chatBusy = true; $('chatsend').disabled = true;
  $('chatin').value = ''; $('chatin').style.height = 'auto';
  chatMsg('user', esc(text));
  const thinking = chatMsg('ai', 'Thinking…', 'thinking');
  try {
    const id = load(CONV_KEY);
    const r = await post('/api/chat', {message: text, conversation_id: id ? Number(id) : null});
    store(CONV_KEY, String(r.conversation_id));
    thinking.classList.remove('thinking');
    thinking.innerHTML = md(r.reply) + actsHtml(r.actions);
    wireProposals($('chatlog'));
  } catch (err) {
    if (err.auth) return showSignin('Signed out on this device. Paste your token again.');
    thinking.classList.remove('thinking');
    thinking.innerHTML = `<span style="color:var(--red)">${esc(err.message)}</span>`;
  } finally { chatBusy = false; $('chatsend').disabled = false; }
};

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
    const rp = data.rpe7 || [];
    let rpeSvg = '<p class="muted">No check-ins yet. Tap "How was it?" after a workout.</p>';
    if (rp.length) {
      const RW = 380, RH = 120, x0 = Date.parse(rp[0].day), x1 = Math.max(x0 + 864e5, Date.parse(rp.at(-1).day));
      const px = d => 24 + (RW - 30) * (Date.parse(d) - x0) / (x1 - x0), py = v => 8 + (RH - 28) * (1 - (v - 1) / 9);
      const pts = rp.map(r => `${px(r.day).toFixed(1)},${py(r.rpe7).toFixed(1)}`).join(' ');
      rpeSvg = `<div class="chart"><svg viewBox="0 0 ${RW} ${RH}" role="img" aria-label="7-day average RPE">
        ${[2, 5, 8].map(v => `<line x1="24" x2="${RW}" y1="${py(v)}" y2="${py(v)}" stroke="#2c2c2e"/><text x="18" y="${py(v) + 4}" fill="#86868b" font-size="11" text-anchor="end">${v}</text>`).join('')}
        <polyline points="${pts}" fill="none" stroke="#ff9f0a" stroke-width="2"/></svg></div>
        <div class="n4m">Latest: ${rp.at(-1).rpe7} (7-day average). Easy weeks should sit around 3-5.</div>`;
    }
    $('trends').innerHTML = loadCard(data.load) + weightCard(data.weight) + efficiencyCard(data.efficiency) + `<section class="card"><div class="label">Weekly run miles</div>
      <div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly run miles">${g}</svg></div>
      <div class="legend" style="margin-top:8px"><span><i style="background:var(--blue)"></i>Actual</span><span><i style="background:var(--teal);height:2px;vertical-align:3px"></i>Planned</span></div></section>
      <section class="card"><div class="label">How hard it felt · 7-day average RPE</div>${rpeSvg}</section>
      <section class="card"><div class="label">Bench press · estimated 1RM</div>${last ? `
      <div class="row"><div class="stat"><div class="v">${Math.round(last.e1rm)}<small> lb</small></div><div class="n">${fmt(last.day, {month: 'short', day: 'numeric'})} · top set ${last.top} lb</div></div>
      <div style="text-align:right">${data.bench_goal ? `<span class="pill ${last.e1rm >= data.bench_goal ? 'ok' : 'off'}">${last.e1rm >= data.bench_goal ? `✓ ${data.bench_goal} reached` : `Goal ${data.bench_goal} by Lake Placid`}</span>` : ''}</div></div>
      <table style="margin-top:10px">${b.slice(-8).reverse().map(x => `<tr><td>${fmt(x.day, {month: 'short', day: 'numeric'})}</td><td>${x.e1rm} lb est.</td><td class="muted">top ${x.top}</td></tr>`).join('')}</table>` : '<p class="muted">No bench sessions in Hevy yet.</p>'}</section>`;
  } catch (e) { if (e.auth) return showSignin('Signed out on this device. Paste your token again.'); $('trends').innerHTML = errorCard('Trends', e.why || e.message); }
}

// ── connections check ───────────────────────────────────────────────────
const CONN_NAMES = {database: 'Database', garmin: 'Garmin', hevy: 'Hevy', oura: 'Oura', weather: 'Weather',
                    calendar: 'Work calendar', anthropic: 'Coach (Anthropic)'};
$('checkconn').onclick = async () => {
  $('connresult').innerHTML = '<section class="card"><div class="muted">Checking… (up to 30 s)</div></section>';
  try {
    const {data} = await api('/admin/diagnostics');
    const rows = Object.entries(CONN_NAMES).filter(([k]) => data[k]).map(([k, name]) => {
      const r = data[k];
      const why = r.ok ? '' : r.not_configured ? `not set up: ${r.not_configured.join(', ')}` : (r.error || 'failed');
      return `<div class="cond"><span class="pill ${r.ok ? 'ok' : 'stop'}">${r.ok ? '✓' : '✕'}</span><span><b>${esc(name)}</b>${why ? `<br><span class="muted">${esc(why)}</span>` : ''}</span></div>`;
    }).join('');
    $('connresult').innerHTML = `<section class="card"><div class="label">Connections</div>${rows}</section>`;
  } catch (e) {
    if (e.auth) return showSignin('Signed out on this device. Paste your token again.');
    $('connresult').innerHTML = errorCard('Connections', e.why || e.message);
  }
};

// ── planned workouts on the Garmin calendar ─────────────────────────────
$('garminbtn').onclick = async () => {
  const show = html => { $('connresult').innerHTML = `<section class="card"><div class="label">Garmin workouts</div>${html}</section>`; };
  show('<div class="muted">Loading…</div>');
  try {
    const {data} = await api('/api/garmin/push');
    const on = !!data.enabled;
    const n = (data.upcoming || []).length;
    show(`<p>${on ? 'On' : 'Off'}: planned runs, rides and swims ${on ? 'go' : 'would go'} to your Garmin calendar
      after each morning sync and Sunday's plan${data.from ? `, from ${esc(fmt(data.from, {month: 'short', day: 'numeric'}))}` : ''}.
      Easy sessions carry a heart-rate range. Workouts you made yourself are never touched.</p>
      <p class="muted">${n} upcoming workout${n === 1 ? '' : 's'} on Garmin from the app.</p>
      <button class="primary-btn" id="garmintoggle">${on ? 'Turn off' : 'Turn on'}</button>
      <button class="ghost-btn" id="garminnow" style="margin-top:8px;width:100%">Send now</button>
      <div class="n4m" id="garminmsg"></div>`);
    const run = async body => {
      $('garminmsg').textContent = 'Talking to Garmin…';
      try {
        const r = (await post('/api/garmin/push', body, 120000)).result;
        $('garminmsg').textContent = r.skipped ? `Not sent: ${r.skipped}.` :
          `Done: ${r.created} added, ${r.updated} updated, ${r.removed} removed, ${r.unchanged} unchanged` +
          (r.errors.length ? `. Problems: ${r.errors.join('; ')}` : '.');
      } catch (e) { $('garminmsg').textContent = e.why || e.message; }
    };
    $('garmintoggle').onclick = async () => { await run({enabled: !on}); setTimeout(() => $('garminbtn').onclick(), 1200); };
    $('garminnow').onclick = () => run({});
  } catch (e) {
    if (e.auth) return showSignin('Signed out on this device. Paste your token again.');
    show(`<div class="muted">${esc(e.why || e.message)}</div>`);
  }
};

// ── the coming week's workouts on their own calendar (.ics feed) ────────
$('calbtn').onclick = async () => {
  const show = html => { $('connresult').innerHTML = `<section class="card"><div class="label">Workout calendar</div>${html}</section>`; };
  show('<div class="muted">Loading…</div>');
  try {
    const {data} = await api('/api/calendar/feed');
    show(`<p>The weeks you approve, on a separate "Training" calendar: each workout as a time block at its
      suggested time. It updates itself when the plan changes inside an approved week, and it never sends alerts.
      Subscribe once:</p>
      <p><b>iPhone:</b> Settings → Calendar → Accounts → Add Account → Other → Add Subscribed Calendar → paste the
      address → Next → Save. Then in Settings → Calendar → Accounts → Subscribed Calendars → Training, set Fetch to Hourly.</p>
      <p><b>Google Calendar</b> (on a computer): Other calendars → + → From URL → paste → Add calendar. Google refreshes
      it a few times a day. Use one of the two, not both, or you'll see every workout twice.</p>
      <input id="calurl" readonly value="${esc(data.url)}" style="width:100%;font-size:13px;padding:8px">
      <button class="primary-btn" id="calcopy" style="margin-top:8px">Copy address</button>
      <p class="muted">Keep this address to yourself: anyone with it can see your workouts.</p>`);
    $('calcopy').onclick = async () => {
      try { await navigator.clipboard.writeText(data.url); $('calcopy').textContent = 'Copied'; }
      catch { $('calurl').select(); document.execCommand('copy'); $('calcopy').textContent = 'Copied'; }
    };
  } catch (e) {
    if (e.auth) return showSignin('Signed out on this device. Paste your token again.');
    show(`<div class="muted">${esc(e.why || e.message)}</div>`);
  }
};

// ── weekly approval: Garmin + Training calendar ──────────────────────────
async function loadApproval() {
  try {
    const {data} = await api('/api/approval');
    $('approvalcard')?.remove();
    if (data.approved_at || !data.sessions.length) return;
    const day = d => fmt(d, {weekday: 'short', month: 'short', day: 'numeric'});
    const rows = data.sessions.map(s => `<li><b>${esc(day(s.date))}</b> · ${esc(s.label || 'any time')} · ${esc(s.title)}${s.duration_min ? ` (${Math.round(s.duration_min)} min)` : ''}</li>`).join('');
    const anchor = $('statuslight');
    (anchor ? anchor : $('today')).insertAdjacentHTML(anchor ? 'afterend' : 'afterbegin', `<section class="card" id="approvalcard"><div class="label">Approve the week of ${esc(fmt(data.week_start, {month: 'short', day: 'numeric'}))}</div>
      <ul class="crit" style="margin:6px 0 10px">${rows}</ul>
      ${data.timing_note ? `<div class="n4m">Times: ${esc(data.timing_note)}</div>` : ''}
      <button class="primary-btn" id="approvebtn">Approve: send to Garmin + calendar</button>
      <div class="n4m" id="approvemsg">Want changes first? Tell Coach (e.g. "move Thursday's run to Friday"), then approve.</div></section>`);
    $('approvebtn').onclick = async () => {
      $('approvemsg').textContent = 'Sending…';
      try {
        const r = await post('/api/approval', {week_start: String(data.week_start)}, 120000);
        const g = r.garmin || {};
        $('approvemsg').textContent = `Approved: ${r.sessions} sessions on your Training calendar` +
          (g.skipped ? ` (Garmin: ${g.skipped}).` : g.errors && g.errors.length ? `. Garmin had a problem: ${g.errors[0]}` : ', and runs, rides and swims on your Garmin.');
        $('approvebtn').remove();
      } catch (e) { $('approvemsg').textContent = e.why || e.message; }
    };
  } catch (e) { /* the approval card is optional; Today still works */ }
}

// ── phone notifications ─────────────────────────────────────────────────
const NOTIF_TYPES = [['workout', 'Tomorrow\'s workout (8:30 PM)'], ['checkin', '"How was it?" after a session'],
  ['safety', 'Safety (readiness, heart rate, heat)'], ['plan', 'Plan changes and changes to confirm'],
  ['report', 'Weekly report ready'], ['approval', 'Sunday: approve next week (Garmin + calendar)'],
  ['clearance', 'Clearance reminder (during a hold)']];
const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
const isStandalone = () => window.navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;
function keyBytes(b64) {
  const s = atob(b64.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - b64.length % 4) % 4));
  return Uint8Array.from(s, c => c.charCodeAt(0));
}
async function turnOnNotifications() {
  const perm = await Notification.requestPermission();
  if (perm !== 'granted') throw new Error('Notifications were not allowed. Turn them on in iPhone Settings > Notifications > Training.');
  const reg = await navigator.serviceWorker.ready;
  const {data} = await api('/api/push/key');
  const sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: keyBytes(data.public_key)});
  await post('/api/push/subscribe', {subscription: sub.toJSON()}, 15000);
}
async function renderNotifPanel() {
  const el = $('notifpanel');
  if (isIOS && !isStandalone()) {
    el.innerHTML = `<section class="card"><div class="label">Notifications</div><p style="margin:0">On iPhone, notifications only work from the Home Screen app: tap Share, then <b>Add to Home Screen</b>, then open Training from your Home Screen and come back here.</p></section>`;
    return;
  }
  if (!('Notification' in window) || !('PushManager' in window)) {
    el.innerHTML = '<section class="card"><div class="label">Notifications</div><p style="margin:0">This browser can\'t receive notifications.</p></section>';
    return;
  }
  let info = {prefs: {}, phones: 0};
  try { info = (await api('/api/notify/prefs')).data; } catch {}
  const on = Notification.permission === 'granted' && info.phones > 0;
  el.innerHTML = `<section class="card"><div class="label">Notifications</div>
    ${on ? '<p class="n4m" style="margin:0 0 8px">On for this phone.</p>' : '<button class="primary-btn" id="notifon">Turn on notifications</button>'}
    ${NOTIF_TYPES.map(([k, label]) => `<label class="ack"><input type="checkbox" data-pref="${k}" ${info.prefs[k] !== false ? 'checked' : ''}> ${esc(label)}</label>`).join('')}
    <div class="n4m">Quiet 9:30 PM-5:30 AM. At most 4 a day.</div>
    <button class="ghost-btn" id="notiftest" style="margin-top:10px;width:100%">Send test notification</button>
    <div class="n4m" id="notifmsg"></div></section>`;
  const msg = t => { $('notifmsg').textContent = t; };
  if ($('notifon')) $('notifon').onclick = async () => {
    try { await turnOnNotifications(); msg('Done. Sending a test...'); await post('/api/push/test', {}, 20000); renderNotifPanel(); }
    catch (e) { msg(e.message); }
  };
  el.querySelectorAll('[data-pref]').forEach(cb => cb.onchange = async () => {
    try { await post('/api/notify/prefs', {prefs: {[cb.dataset.pref]: cb.checked}}, 15000); } catch (e) { msg(e.message); }
  });
  $('notiftest').onclick = async () => {
    try { const r = await post('/api/push/test', {}, 20000); msg(r.sent ? 'Sent. It should arrive in a few seconds.' : `Not sent: ${r.error || 'unknown error'}`); }
    catch (e) { msg(e.message); }
  };
}
$('notifbtn').onclick = () => { if ($('notifpanel').innerHTML) $('notifpanel').innerHTML = ''; else renderNotifPanel(); };

// ── clearance ───────────────────────────────────────────────────────────
function clearanceForm() {
  return `<div class="prop" id="clearform"><div class="label">I've been cleared</div>
    <label class="ack"><input type="checkbox" data-c="physician_clearance"> My doctor cleared me to exercise (spleen OK for running and lifting)</label>
    <label class="ack"><input type="checkbox" data-c="fever_free_48h"> No fever for 48 hours, without fever medicine</label>
    <label class="ack"><input type="checkbox" data-c="rhr_near_baseline_3d"> Resting heart rate within 5 bpm of normal for 3 mornings</label>
    <button class="primary-btn" id="clearbtn" disabled>Start my comeback</button><div class="n4m" id="clearmsg"></div></div>`;
}
function wireClearance() {
  const f = $('clearform');
  if (!f) return;
  const boxes = [...f.querySelectorAll('[data-c]')];
  boxes.forEach(b => b.onchange = () => { $('clearbtn').disabled = !boxes.every(x => x.checked); });
  $('clearbtn').onclick = async () => {
    $('clearbtn').disabled = true;
    try {
      const r = await post('/api/health/clear', Object.fromEntries(boxes.map(b => [b.dataset.c, b.checked])), 20000);
      f.innerHTML = `<div class="label">Cleared</div><div>${esc(r.message)}</div>`;
      setTimeout(start, 2500);
    } catch (e) { $('clearmsg').textContent = e.message; $('clearbtn').disabled = false; }
  };
}

// ── refresh: pull new data from Garmin, Oura and Hevy, then redraw ─────
async function refreshAll() {
  const btn = $('refresh');
  if (btn.classList.contains('spin')) return;
  btn.classList.add('spin');
  const note = t => { $('sync').textContent = t; };
  try {
    const r = await post('/api/refresh', {}, 15000);
    note('Syncing Garmin, Oura and Hevy…');
    let st = {done: false};
    for (let i = 0; i < 40 && !st.done; i++) {          // up to ~2 minutes
      await new Promise(res => setTimeout(res, 3000));
      st = (await api('/api/refresh/status?after=' + encodeURIComponent(r.after))).data;
    }
    await start();
    const tab = document.querySelector('.tabs button[aria-selected=true]')?.dataset.tab;
    if (tab === 'plan') renderPlan(); else if (tab === 'trends') renderTrends(); else if (tab === 'reports') renderReports();
    if (!st.done) note('Still syncing in the background; refresh again in a minute.');
    else if (st.failed?.length) note(`Updated, but couldn't reach: ${st.failed.join(', ')}.`);
  } catch (e) {
    if (e.auth) return showSignin('Signed out on this device. Paste your token again.');
    note(e.message);
  } finally { btn.classList.remove('spin'); }
}
$('refresh').onclick = refreshAll;

// ── start ───────────────────────────────────────────────────────────────
let starting = false;
async function start() {
  if (starting) return;
  starting = true;
  try {
    const qs = new URLSearchParams(location.search);
    const {data, cached, why} = await api('/api/today' + (qs.get('checkin') ? `?checkin=${encodeURIComponent(qs.get('checkin'))}` : ''));
    $('signin').hidden = true; $('app').hidden = false;
    $('hdrdate').dataset.iso = String(data.today);
    renderToday(data, cached);
    if (!cached) loadApproval();
    if (qs.get('tab')) document.querySelector(`.tabs button[data-tab="${qs.get('tab')}"]`)?.click();
    if (why) $('sync').textContent = `${why}. ` + $('sync').textContent;
    if (cached) {
      // Make an old copy impossible to miss: the date at the top would otherwise look current.
      const when = new Date(cached).toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'});
      $('today').insertAdjacentHTML('afterbegin', `<div class="banner" id="stale">Showing a saved copy from ${esc(when)}: `
        + `couldn't reach the server (${esc(why || 'no connection')}). Tap ↻ at the top to try again.</div>`);
    }
    else if (lastLoadMs != null) $('sync').textContent += ` · loaded in ${(lastLoadMs / 1000).toFixed(1)}s`;
  } catch (e) {
    if (e.auth) return showSignin('');
    $('signin').hidden = true; $('app').hidden = false;
    $('today').innerHTML = errorCard('Today', e.why || e.message);
  } finally {
    starting = false;
  }
}

try { const a = localStorage.getItem('training.assistant'); if (a) document.querySelector('[data-tab=ask]').textContent = a; } catch {}
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
document.addEventListener('visibilitychange', () => { if (!document.hidden) start(); });
start();
