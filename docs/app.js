/* SleepScope phone app: UI, storage, charts, Claude. */
'use strict';
const $ = (id) => document.getElementById(id);
const C = { blue: '#2a78d6', green: '#1baf7a', violet: '#6250d6', orange: '#eb6834', red: '#e34948', amber: '#eda100', grey: '#8a8985', aqua: '#1baf7a' };
const EVC = { 'Obstructive Apnea': C.red, 'Central Apnea': C.violet, 'Hypopnea': C.orange, 'Arousal': C.amber, 'Unclassified Apnea': C.grey, 'Apnea (unflagged by machine)': C.red, 'Flow Limitation Run': C.violet, 'Large Leak': C.orange };
let nights = []; let history = []; let claudeBusy = false;
const store = { get: (k, d) => { try { const v = localStorage.getItem('ss_' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }, set: (k, v) => { try { localStorage.setItem('ss_' + k, JSON.stringify(v)); } catch (e) {} } };

// ---------------------------------------------------------------- navigation
function go(p) { document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.id === 'p-' + p)); document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.p === p)); window.scrollTo(0, 0); if (p === 'nights' && nights.length) drawOverview(); }
document.querySelectorAll('nav button').forEach(b => b.onclick = () => go(b.dataset.p));

// ---------------------------------------------------------------- IndexedDB for the last loaded files
const idb = { db: null,
  open() { return new Promise((res, rej) => { const r = indexedDB.open('sleepscope', 1); r.onupgradeneeded = () => r.result.createObjectStore('files'); r.onsuccess = () => { this.db = r.result; res(); }; r.onerror = () => rej(r.error); }); },
  async put(k, v) { if (!this.db) await this.open(); return new Promise((res, rej) => { const t = this.db.transaction('files', 'readwrite'); t.objectStore('files').put(v, k); t.oncomplete = res; t.onerror = () => rej(t.error); }); },
  async get(k) { if (!this.db) await this.open(); return new Promise((res, rej) => { const t = this.db.transaction('files', 'readonly'); const q = t.objectStore('files').get(k); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); }); } };

// ---------------------------------------------------------------- loading
async function filesFromInputs(list) {
  const files = {};
  for (const f of list) {
    if (/\.zip$/i.test(f.name)) { const z = await JSZip.loadAsync(await f.arrayBuffer()); for (const [name, entry] of Object.entries(z.files)) { if (entry.dir || !/\.edf$/i.test(name) || name.includes('__MACOSX')) continue; files[name.replace(/\\/g, '/')] = await entry.async('arraybuffer'); } }
    else if (/\.edf$/i.test(f.name)) files[(f.webkitRelativePath || f.name).replace(/\\/g, '/')] = await f.arrayBuffer();
  }
  return files;
}
function normalise(files) { // flatten to folder/name keyed by the date folder where possible
  const out = {}; for (const [k, v] of Object.entries(files)) { const parts = k.split('/'); const name = parts.pop(); const folder = parts.length ? parts.pop() : (name.match(/^(\d{8})_/) || [, 'x'])[1]; out[folder + '/' + name] = v; } return out;
}
async function loadFiles(files, label) {
  const prog = $('progress'); prog.style.display = 'block'; const bar = prog.firstElementChild; $('loadmsg').textContent = 'Reading ' + label + '…';
  const t0 = Date.now();
  nights = await SS.buildSessions(files, (i, n, name) => { bar.style.width = (100 * i / Math.max(n, 1)) + '%'; $('loadmsg').textContent = `Reading ${name} (${i + 1}/${n})`; });
  for (let i = 0; i < nights.length; i++) { const n = nights[i]; $('loadmsg').textContent = `Scoring ${SS.label(n.date)}`; bar.style.width = (100 * i / nights.length) + '%'; await new Promise(r => setTimeout(r, 0)); for (const s of n.sessions) SS.scoreSession(s); n.stats = SS.nightStats(n); }
  prog.style.display = 'none';
  if (!nights.length) { $('loadmsg').textContent = 'No sessions of 5 minutes or longer found. Pick the DATALOG zip or the .edf files inside a date folder.'; return; }
  const [tot, hit] = SS.validation(nights);
  $('loadmsg').textContent = `${nights.length} nights loaded in ${((Date.now() - t0) / 1000).toFixed(1)} s. App detector reproduced ${hit} of ${tot} machine-scored apneas.`;
  afterLoad();
}
function afterLoad() {
  const last = nights[nights.length - 1];
  $('hdrsub').textContent = `${nights.length} nights · last ${SS.label(last.date)} · AHI ${last.stats.AHI.toFixed(1)}`;
  $('st1').textContent = `✔ ${nights.length} nights`; $('st1').className = 'status ok'; $('st2').textContent = '✔ Ready'; $('st2').className = 'status ok'; $('st3').textContent = '✔ Ready'; $('st3').className = 'status ok';
  const ox = nights.some(n => n.sessions.some(s => s.hasOx)); $('st5').textContent = ox ? '✔ Oximetry present' : 'Optional'; $('st5').className = 'status' + (ox ? ' ok' : '');
  const hrs = nights.reduce((a, n) => a + n.hours, 0); const ev = nights.reduce((a, n) => a + n.stats.OA + n.stats.CA + n.stats.H + n.stats.UA, 0);
  $('startsum').textContent = `Loaded: ${nights.length} nights, ${hrs.toFixed(1)} hours, machine AHI ${(ev / hrs).toFixed(1)}.`;
  $('d0').value = nights[Math.max(0, nights.length - 30)].date; $('d1').value = last.date;
  renderSynopsis(); fillNightTable(); if ($('p-nights').classList.contains('active')) drawOverview();
}
$('filein').onchange = async (e) => { const list = [...e.target.files]; if (!list.length) return; try { const files = normalise(await filesFromInputs(list)); await loadFiles(files, list.length === 1 ? list[0].name : list.length + ' files'); try { await idb.put('last', { files, label: list.length === 1 ? list[0].name : list.length + ' files', when: Date.now() }); } catch (err) {} } catch (err) { $('loadmsg').textContent = 'Could not read that: ' + err; } e.target.value = ''; };
$('samplebtn').onclick = async () => { $('loadmsg').textContent = 'Fetching sample card…'; try { const r = await fetch('sample.zip'); const z = await JSZip.loadAsync(await r.arrayBuffer()); const files = {}; for (const [name, entry] of Object.entries(z.files)) if (!entry.dir && /\.edf$/i.test(name)) files[name] = await entry.async('arraybuffer'); await loadFiles(normalise(files), 'sample card'); } catch (e) { $('loadmsg').textContent = 'Sample not available offline yet: ' + e; } };
$('oxin').onchange = async (e) => { const f = e.target.files[0]; if (!f || !nights.length) return; const n = SS.importOximeterCsv(await f.text(), nights); for (const nt of nights) nt.stats = SS.nightStats(nt); afterLoad(); alert(`SpO2 attached to ${n} session(s) by timestamp.`); e.target.value = ''; };

// ---------------------------------------------------------------- synopsis
function quick(days) { if (!nights.length) return; const last = nights[nights.length - 1].date; $('d1').value = last; $('d0').value = days ? (nights.find(n => n.date >= addDays(last, -(days - 1))) || nights[0]).date : nights[0].date; renderSynopsis(); }
function addDays(iso, d) { const x = new Date(iso); x.setDate(x.getDate() + d); return x.toISOString().slice(0, 10); }
function renderSynopsis() {
  if (!nights.length) return; let a = $('d0').value, b = $('d1').value; if (a > b) [a, b] = [b, a];
  const diag = parseFloat($('diag').value) || null; store.set('diag', diag);
  $('syntext').innerHTML = SS.synopsis(nights, a, b, diag);
  claudeSynopsis(false);
}
['d0', 'd1', 'diag'].forEach(id => $(id).onchange = renderSynopsis);

// ---------------------------------------------------------------- charts
function drawOverview() {
  const x = nights.map(n => SS.label(n.date)); const S = nights.map(n => n.stats);
  Plotly.react('ch-usage', [{ type: 'bar', x, y: nights.map(n => +n.hours.toFixed(2)), marker: { color: C.blue }, name: 'Hours' }], { title: { text: 'Usage (hours), dashed = 4 h', font: { size: 13 } }, margin: { l: 34, r: 10, t: 30, b: 60 }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 4, y1: 4, line: { dash: 'dash', color: '#52514e', width: 1 } }], yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -30 } }, { displayModeBar: false, responsive: true });
  Plotly.react('ch-ahi', [
    { type: 'bar', x, y: S.map(s => +s.AHI.toFixed(2)), marker: { color: C.blue }, name: 'AHI machine' },
    { type: 'bar', x, y: S.map(s => +s.app_AHI.toFixed(2)), marker: { color: C.orange }, name: 'AHI app (flow only)' }],
    { title: { text: 'AHI per night, dashed = 5', font: { size: 13 } }, barmode: 'group', margin: { l: 34, r: 10, t: 30, b: 60 }, legend: { orientation: 'h', y: -0.35, font: { size: 10 } }, yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -30 }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 5, y1: 5, line: { dash: 'dash', color: C.red, width: 1 } }] }, { displayModeBar: false, responsive: true });
  Plotly.react('ch-leak', [{ type: 'bar', x, y: S.map(s => +s.leak_95.toFixed(1)), marker: { color: S.map(s => s.leak_95 > 24 ? C.red : C.aqua) }, name: 'Leak 95th' }],
    { title: { text: 'Leak, 95th percentile (L/min), dashed = 24', font: { size: 13 } }, margin: { l: 34, r: 10, t: 30, b: 60 }, yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -30 }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 24, y1: 24, line: { dash: 'dash', color: C.red, width: 1 } }] }, { displayModeBar: false, responsive: true });
}
function fillNightTable() {
  const tb = $('nighttbl').tBodies[0]; tb.innerHTML = '';
  nights.forEach((n, i) => { const s = n.stats; const tr = document.createElement('tr'); tr.innerHTML = `<td>${SS.label(n.date)}</td><td>${n.hours.toFixed(2)}</td><td>${s.mode}</td><td>${s.AHI.toFixed(2)}</td><td>${Number.isFinite(s.leak_95) ? s.leak_95.toFixed(1) : ''}</td><td>${Number.isFinite(s.press_95) ? s.press_95.toFixed(1) : ''}</td>`; tr.onclick = () => showNight(i); tb.appendChild(tr); });
}
function showNight(i) {
  const n = nights[i]; const s = n.stats; document.querySelectorAll('#nighttbl tbody tr').forEach((tr, k) => tr.classList.toggle('sel', k === i));
  const box = $('nightdetail'); box.innerHTML = `<div class="card"><h3 style="margin:0 0 6px">${new Date(n.date + 'T12:00').toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</h3>
    <div class="row" style="gap:6px"><span class="pill" style="background:${C.blue}">${n.hours.toFixed(1)} h</span><span class="pill" style="background:${s.AHI < 5 ? C.green : C.red}">AHI ${s.AHI.toFixed(1)}</span><span class="pill" style="background:${C.violet}">${s.mode} ${Number.isFinite(s.press_min) ? Math.round(s.press_min) + ' to ' + Math.round(s.press_max) : ''}</span><span class="pill" style="background:${s.leak_95 > 24 ? C.red : C.grey}">leak 95th ${Number.isFinite(s.leak_95) ? s.leak_95.toFixed(0) : '?'}</span><span class="pill" style="background:${C.amber}">FL 95th ${Number.isFinite(s.flowlim_95) ? s.flowlim_95.toFixed(2) : '?'}</span>${Number.isFinite(s.spo2_mean) ? `<span class="pill" style="background:${C.red}">SpO2 min ${s.spo2_min.toFixed(0)} · ODI ${s.ODI.toFixed(1)}</span>` : ''}</div>
    <p class="muted" style="margin:8px 0 0">Sessions ${s.starts} to ${s.ends}. OA ${s.OA}, CA ${s.CA}, H ${s.H}, arousals ${s.arousals}. RR ${s.rr_med.toFixed(0)}, Vt ${s.tv_med.toFixed(0)} mL, MV ${s.mv_med.toFixed(1)}.</p></div>
    <div class="card"><div id="ch-night" style="width:100%;height:${s.spo2_mean ? 620 : 520}px"></div><div class="key"><span><i style="background:${C.red}"></i>obstructive</span><span><i style="background:${C.violet}"></i>central</span><span><i style="background:${C.orange}"></i>hypopnea</span><span><i style="background:${C.amber}"></i>arousal</span><span>lighter bands = app events</span></div></div>
    <div class="card"><b>Events</b> <span class="muted">(tap one to see the airflow around it)</span><div id="evlist"></div></div><div class="card" id="zoomcard" style="display:none"><div id="ch-zoom" style="width:100%;height:240px"></div><div class="muted" id="zoomnote"></div></div>`;
  box.scrollIntoView({ behavior: 'smooth' });
  const t0 = n.sessions[0].start; const tr = []; const shapes = [];
  const series = (k, sc, name, color, yaxis) => { const xs = [], ys = []; for (const ses of n.sessions) { const a = ses.ch[k]; if (!a) continue; for (let i = 0; i < a.length; i++) { xs.push(new Date(ses.start.getTime() + 2000 * i)); ys.push(a[i] * sc); } xs.push(null); ys.push(null); } if (xs.length) tr.push({ x: xs, y: ys, mode: 'lines', line: { color, width: 1 }, name, yaxis, hoverinfo: 'x+y+name' }); };
  series('Press', 1, 'Set pressure', C.blue, 'y'); series('MaskPress', 1, 'Mask pressure', C.aqua, 'y'); series('Leak', 60, 'Leak L/min', C.orange, 'y2'); series('FlowLim', 1, 'Flow limitation', C.violet, 'y3'); series('Snore', 1, 'Snore', '#e87ba4', 'y3'); series('TidVol', 1000, 'Tidal volume mL', C.green, 'y4');
  for (const ses of n.sessions) if (ses.vent) { const xs = [], ys = []; for (let i = 0; i < ses.vent.length; i += 2) { xs.push(new Date(ses.start.getTime() + 1000 * i)); ys.push(ses.vent[i]); } tr.push({ x: xs, y: ys, mode: 'lines', line: { color: C.aqua, width: 1 }, name: 'Ventilation vs baseline', yaxis: 'y5' }); }
  const hasOx = n.sessions.some(x => x.hasOx);
  if (hasOx) for (const ses of n.sessions) if (ses.spo2) { const xs = [], ys = [], yp = []; for (let i = 0; i < ses.spo2.length; i += 5) { xs.push(new Date(ses.start.getTime() + 1000 * i)); ys.push(ses.spo2[i] > 0 ? ses.spo2[i] : null); yp.push(ses.pulse && ses.pulse[i] > 0 ? ses.pulse[i] : null); } tr.push({ x: xs, y: ys, mode: 'lines', line: { color: C.red, width: 1 }, name: 'SpO2 %', yaxis: 'y6' }); tr.push({ x: xs, y: yp, mode: 'lines', line: { color: C.orange, width: 1 }, name: 'Pulse', yaxis: 'y6' }); }
  for (const ses of n.sessions) for (const e of [...ses.machine, ...ses.app]) { const col = EVC[e.label]; if (!col) continue; shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: e.start, x1: new Date(e.start.getTime() + Math.max(e.dur, 20) * 1000), y0: 0, y1: 1, fillcolor: col, opacity: e.source === 'machine' ? 0.35 : 0.15, line: { width: 0 } }); }
  const nrows = hasOx ? 6 : 5; const dom = (k) => { const h = 1 / nrows, gap = 0.035; return [1 - (k + 1) * h + gap, 1 - k * h - gap / 2]; };
  const layout = { margin: { l: 36, r: 10, t: 10, b: 30 }, showlegend: false, shapes, hovermode: 'x', dragmode: 'pan', xaxis: { type: 'date', tickformat: '%H:%M' },
    yaxis: { domain: dom(0), title: { text: 'cmH2O', font: { size: 10 } }, range: [0, 21] }, yaxis2: { domain: dom(1), title: { text: 'leak', font: { size: 10 } }, range: [0, 60] }, yaxis3: { domain: dom(2), title: { text: 'FL', font: { size: 10 } }, range: [0, 1] }, yaxis4: { domain: dom(3), title: { text: 'Vt', font: { size: 10 } }, range: [0, 1200] }, yaxis5: { domain: dom(4), title: { text: 'vent', font: { size: 10 } }, range: [0, 2.5] } };
  if (hasOx) layout.yaxis6 = { domain: dom(5), title: { text: 'SpO2', font: { size: 10 } }, range: [80, 100] };
  Plotly.newPlot('ch-night', tr, layout, { displayModeBar: false, responsive: true, scrollZoom: true });
  const ev = n.sessions.flatMap(ses => [...ses.machine, ...ses.app].map(e => ({ e, ses }))).sort((a, b) => a.e.start - b.e.start).filter(x => x.e.label !== 'Flow Limitation Run' || x.e.dur >= 60);
  const list = $('evlist'); list.innerHTML = ev.length ? '' : '<p class="muted">No events.</p>';
  for (const { e, ses } of ev) { const d = document.createElement('div'); d.className = 'evt'; d.innerHTML = `<span class="t">${SS.fmtTime(e.start)}:${String(e.start.getSeconds()).padStart(2, '0')}</span><span class="pill" style="background:${EVC[e.label] || C.grey}">${e.source}</span><span class="l">${e.label} ${e.dur ? e.dur.toFixed(0) + ' s' : ''}<br><span class="muted">${e.detail}</span></span>`; d.onclick = () => zoomEvent(ses, e); list.appendChild(d); }
}
function zoomEvent(ses, e) {
  if (!ses.flow) return; const fs = ses.fs; const off = (e.start - ses.start) / 1000; const a = Math.max(0, Math.floor((off - 40) * fs)), b = Math.min(ses.flow.length, Math.ceil((off + Math.max(e.dur, 10) + 40) * fs));
  const xs = [], ys = []; for (let i = a; i < b; i++) { xs.push(i / fs - off); ys.push(ses.flow[i] * 60); }
  $('zoomcard').style.display = 'block';
  Plotly.newPlot('ch-zoom', [{ x: xs, y: ys, mode: 'lines', line: { color: C.blue, width: 1 }, name: 'flow L/min' }], { margin: { l: 36, r: 10, t: 24, b: 30 }, title: { text: `${e.label}, ${e.dur ? e.dur.toFixed(0) + ' s, ' : ''}${SS.fmtTime(e.start)}`, font: { size: 12 } }, xaxis: { title: { text: 'seconds from event start', font: { size: 10 } } }, shapes: [{ type: 'rect', x0: 0, x1: Math.max(e.dur, 1), y0: 0, y1: 1, yref: 'paper', fillcolor: EVC[e.label] || C.grey, opacity: 0.18, line: { width: 0 } }, { type: 'line', x0: xs[0], x1: xs[xs.length - 1], y0: 0, y1: 0, line: { color: '#ccc', width: 1 } }] }, { displayModeBar: false, responsive: true });
  $('zoomnote').textContent = 'Shaded = the event. Positive is inhaling, negative exhaling. A flat line with the airway closed is an obstructive apnea; a flat line after a big sigh with the airway open is usually a central.';
  $('zoomcard').scrollIntoView({ behavior: 'smooth' });
}

// ---------------------------------------------------------------- Claude
const SYSTEM = `You are a sleep-therapy data analyst helping a CPAP user understand their own ResMed AirSense data. Give plain, direct, well-reasoned answers with no filler. Use the numbers in the CONTEXT block; do not invent data. Say when something is not in the data and what would answer it. Pressure settings are prescribed: discuss trade-offs and what to raise with the prescriber rather than instructing changes. Never use dashes in prose. Keep answers tight.`;
function buildContext(a, b) {
  const sel = nights.filter(n => n.date >= a && n.date <= b); const diag = parseFloat($('diag').value) || null;
  const syn = $('syntext').innerText; const cols = ['date', 'hours', 'mode', 'AHI', 'OA', 'CA', 'H', 'arousals', 'app_AHI', 'app_unflagged', 'press_min', 'press_med', 'press_95', 'press_max', 'press_at_max_pct', 'leak_med', 'leak_95', 'leak_pct_large', 'flowlim_95', 'flowlim_minutes', 'rr_med', 'tv_med', 'mv_med', 'spo2_mean', 'spo2_min', 'spo2_pct_lt90', 'ODI'];
  const fmt = (v) => typeof v === 'number' ? (Number.isFinite(v) ? +v.toFixed(2) : '') : v;
  const table = [cols.join('\t'), ...sel.map(n => cols.map(c => fmt(n.stats[c])).join('\t'))].join('\n');
  const evs = []; for (const n of sel) for (const s of n.sessions) for (const e of [...s.machine, ...s.app].sort((x, y) => x.start - y.start)) { if (e.label === 'Flow Limitation Run') continue; const i2 = Math.max(0, Math.floor((e.start - s.start) / 2000)); const pr = s.ch.Press, lk = s.ch.Leak; evs.push(`${SS.label(n.date)} ${SS.fmtTime(e.start)} ${e.label} [${e.source}] ${e.dur.toFixed(0)}s P=${pr ? pr[Math.min(i2, pr.length - 1)].toFixed(1) : '?'} leak=${lk ? (lk[Math.min(i2, lk.length - 1)] * 60).toFixed(0) : '?'} ${e.detail}`); }
  const [tot, hit] = SS.validation(sel);
  return `CONTEXT\nDate range ${a} to ${b}. Nights with data: ${sel.length}.\n\n=== Rule based synopsis ===\n${syn}\n\n=== Per night statistics (tab separated; P cmH2O, leak L/min, app = SleepScope's own flow scoring, machine = ResMed) ===\n${table}\n\n=== Events ===\n${evs.slice(0, 400).join('\n')}${evs.length > 400 ? `\n... ${evs.length - 400} more omitted` : ''}\n\n=== Method notes ===\nResMed stamps event end; app subtracts duration. App hypopnea = 30% flow drop >= 10 s without desaturation check (over-counts). On this data the app reproduced ${hit} of ${tot} machine apneas. Obstructive vs central comes only from the machine.`;
}
async function callClaude(messages, system) {
  const key = $('apikey').value.trim(); if (!key) throw new Error('No API key saved.');
  const r = await fetch('https://api.anthropic.com/v1/messages', { method: 'POST', headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' }, body: JSON.stringify({ model: $('model').value.trim() || 'claude-sonnet-5-5', max_tokens: 2000, system, messages }) });
  const j = await r.json(); if (!r.ok) throw new Error(`API error ${r.status}: ${(j.error && j.error.message) || r.statusText}`);
  const text = (j.content || []).filter(b => b.type === 'text').map(b => b.text).join(''); if (!text.trim()) throw new Error('The API returned no text (stop reason ' + j.stop_reason + ').'); return text;
}
const sysWithAbout = () => SYSTEM + ($('about').value.trim() ? `\nAbout the user, in their words: ${$('about').value.trim()}\n` : '');
async function claudeSynopsis(force) {
  if (!nights.length || !$('apikey').value.trim() || claudeBusy) return; let a = $('d0').value, b = $('d1').value; if (a > b) [a, b] = [b, a];
  const sel = nights.filter(n => n.date >= a && n.date <= b); const sig = sel.map(n => `${n.date}:${n.hours.toFixed(3)}:${n.stats.AHI.toFixed(3)}:${n.stats.spo2_mean}`).join('|') + '|' + $('diag').value + '|' + $('about').value;
  const cache = store.get('synCache', {}); if (!force && cache[sig]) { $('claudetext').innerHTML = md(cache[sig]); $('claudestatus').textContent = 'From cache. Press Ask Claude now to refresh.'; return; }
  claudeBusy = true; $('claudestatus').textContent = 'Asking Claude… (30 to 60 s)'; $('claudesyn').disabled = true;
  try {
    const text = await callClaude([{ role: 'user', content: buildContext(a, b) + '\n\nTASK: Write a synopsis of this CPAP data for the user, in plain language, as a short report with these headings: What the data shows; What it means for you; What is going well; What to watch; Questions for the prescriber. Use the numbers in the context. Where the rule based synopsis and your own reading differ, say so. Keep it under 500 words. No dashes in prose.' }], sysWithAbout());
    cache[sig] = text; const keys = Object.keys(cache); if (keys.length > 20) delete cache[keys[0]]; store.set('synCache', cache);
    $('claudetext').innerHTML = md(text); $('claudestatus').textContent = `Claude synopsis for ${a} to ${b}.`; saveAnswer('Synopsis ' + a + ' to ' + b, text);
  } catch (e) { $('claudestatus').textContent = 'Claude synopsis failed: ' + e.message; }
  claudeBusy = false; $('claudesyn').disabled = false;
}
$('claudesyn').onclick = () => claudeSynopsis(true);
function md(t) { return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/^### (.*)$/gm, '<h4>$1</h4>').replace(/^## (.*)$/gm, '<h3>$1</h3>').replace(/^# (.*)$/gm, '<h2>$1</h2>').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^[-*] (.*)$/gm, '<li>$1</li>').replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>').replace(/\n{2,}/g, '</p><p>').replace(/\n/g, '<br>'); }
function saveAnswer(q, a) { const list = store.get('answers', []); list.unshift({ when: new Date().toISOString(), q, a }); store.set('answers', list.slice(0, 200)); }
function showSaved() { const box = $('savedbox'); box.style.display = box.style.display === 'none' ? 'block' : 'none'; const list = store.get('answers', []); $('savedlist').innerHTML = list.length ? list.map(x => `<div class="q">${new Date(x.when).toLocaleString()} · ${x.q.replace(/</g, '&lt;')}</div><div class="a">${md(x.a)}</div>`).join('') : '<p class="muted">Nothing saved yet.</p>'; }
$('savedbtn').onclick = showSaved; $('newconv').onclick = () => { history = []; $('chat').innerHTML = '<p class="muted">New conversation. Your next question carries the current data range.</p>'; };
$('sendbtn').onclick = async () => {
  const q = $('q').value.trim(); if (!q) return; if (!nights.length) { $('askstatus').textContent = 'Load data first.'; return; } let a = $('d0').value, b = $('d1').value; if (a > b) [a, b] = [b, a];
  if (!history.length) history.push({ role: 'user', content: buildContext(a, b) + '\n\nQUESTION: ' + q }); else history.push({ role: 'user', content: q });
  const chat = $('chat'); chat.insertAdjacentHTML('beforeend', `<div class="q">You</div><div class="a">${q.replace(/</g, '&lt;')}</div>`); $('q').value = ''; $('sendbtn').disabled = true; $('askstatus').textContent = 'Waiting for Claude… (a long answer can take 30 to 60 s)'; chat.scrollTop = chat.scrollHeight;
  try { const text = await callClaude(history, sysWithAbout()); history.push({ role: 'assistant', content: text }); chat.insertAdjacentHTML('beforeend', `<div class="q" style="color:${C.orange}">Claude</div><div class="a">${md(text)}</div>`); saveAnswer(q, text); $('askstatus').textContent = 'Saved on this phone.'; }
  catch (e) { history.pop(); chat.insertAdjacentHTML('beforeend', `<div class="q" style="color:${C.red}">Error</div><div class="a">${e.message}</div>`); $('askstatus').textContent = 'Not answered.'; }
  $('sendbtn').disabled = false; chat.scrollTop = chat.scrollHeight;
};
$('testbtn').onclick = async () => { const key = $('apikey').value.trim(); if (!key) { $('teststatus').textContent = 'Enter a key first.'; return; } $('teststatus').textContent = 'Testing…'; try { const r = await fetch('https://api.anthropic.com/v1/models', { headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'anthropic-dangerous-direct-browser-access': 'true' } }); const j = await r.json(); if (!r.ok) throw new Error(`API error ${r.status}: ${(j.error && j.error.message) || ''}`); $('teststatus').textContent = 'Connection OK. Models: ' + j.data.map(m => m.id).join(', '); } catch (e) { $('teststatus').textContent = 'Failed: ' + e.message; } };
['apikey', 'model', 'about'].forEach(id => { $(id).value = store.get(id, $(id).value); $(id).onchange = () => { store.set(id, $(id).value.trim()); if (id === 'apikey') { $('st4').textContent = $(id).value.trim() ? '✔ Key saved' : 'No key'; $('st4').className = 'status' + ($(id).value.trim() ? ' ok' : ''); claudeSynopsis(false); } }; });
if ($('apikey').value) { $('st4').textContent = '✔ Key saved'; $('st4').className = 'status ok'; }
$('diag').value = store.get('diag', '') || '';

// ---------------------------------------------------------------- help text and startup
$('helptext').innerHTML = `
<h3>What you need</h3><p>An SD card reader for the phone: Lightning to SD (older iPhones) or USB-C to SD (iPhone 15 and later). Any brand works; the Apple ones are the surest. The card is a standard full-size SD.</p>
<h3>1. Get the card into the phone</h3><p>Take the card out of the machine (press it in and it springs out; the machine keeps working). Put it in the reader and plug the reader into the phone. Open the <b>Files</b> app; the card appears under Browse as a drive (often "NO NAME" or "RESMED").</p>
<h3>2. Make a zip of DATALOG</h3><p>In Files, open the card, long-press the <b>DATALOG</b> folder, choose <b>Compress</b>. A file <b>DATALOG.zip</b> appears next to it. For a year of data this can be a few hundred MB and take a minute.</p>
<h3>3. Load it</h3><p>Back here, tap <b>Choose zip or files</b>, pick DATALOG.zip, wait for the progress bar. The phone re-scores every night from the raw airflow (about a second per night). The last load is remembered on the phone, so you only re-pick when there is new data.</p>
<h3>4. Put the card back</h3><p>The machine records only when the card is in. Delete the zip from the card if you made it there (or make it in iCloud Drive instead).</p>
<h3>5. Add to the home screen</h3><p>In Safari tap the Share button, then <b>Add to Home Screen</b>. SleepScope then opens like an app, full screen, and works offline.</p>
<h3>6. Connect Claude</h3><p>On a computer or the phone, go to console.anthropic.com, sign in, add a few dollars under Billing, create a key under API Keys (starts with sk-ant-). Paste it on the Ask tab and press Test connection. The key stays on this phone.</p>
<h3>7. Oximeter</h3><p>In the O2Ring's app, export the night as CSV and share it to Files, then Import oximeter CSV here.</p>
<h3>The numbers in plain words</h3><ul><li><b>Hours:</b> four hours on 70% of nights is the insurer's floor; six or more is where people feel it.</li><li><b>AHI:</b> under 5 normal, 5 to 15 mild, 15 to 30 moderate, over 30 severe. The app's flow-only AHI is a ceiling, always higher.</li><li><b>Leak:</b> 95th percentile under 24 L/min.</li><li><b>Flow limitation:</b> narrowing short of an event; fragments sleep without raising AHI.</li><li><b>SpO2 / ODI:</b> needs the ring; ODI under 5 and almost no time under 90% is the goal.</li></ul>`;
(async () => {
  if ('serviceWorker' in navigator) { try { navigator.serviceWorker.register('sw.js'); } catch (e) {} }
  try { const last = await idb.get('last'); if (last && last.files) { $('loadmsg').textContent = 'Reloading ' + last.label + ' from last time…'; await loadFiles(last.files, last.label); } } catch (e) {}
})();
