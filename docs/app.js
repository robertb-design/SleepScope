/* SleepScope phone app: UI, storage, charts, Claude. */
'use strict';
const $ = (id) => document.getElementById(id);
const C = { blue: '#2a78d6', green: '#1baf7a', violet: '#6250d6', orange: '#eb6834', red: '#e34948', amber: '#eda100', grey: '#8a8985', aqua: '#1baf7a' };
const EVC = { 'Obstructive Apnea': C.red, 'Central Apnea': C.violet, 'Hypopnea': C.orange, 'Arousal': C.amber, 'Unclassified Apnea': C.grey, 'Apnea (unflagged by machine)': C.red, 'Flow Limitation Run': C.violet, 'Large Leak': C.orange };
let nights = []; let history = []; let claudeBusy = false; let selectedNight = null; let strData = null; let autoOpenSynopsis = false;
const store = { get: (k, d) => { try { const v = localStorage.getItem('ss_' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } }, set: (k, v) => { try { localStorage.setItem('ss_' + k, JSON.stringify(v)); } catch (e) {} } };

// ---------------------------------------------------------------- navigation
function go(p) { document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.id === 'p-' + p)); document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.p === p)); window.scrollTo(0, 0); if (p === 'nights' && nights.length) drawOverview(); if (p === 'land' && nights.length) drawLandscape(); }
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
  const out = {}; for (const [k, v] of Object.entries(files)) { const parts = k.split('/'); const name = parts.pop(); if (/^STR\.edf$/i.test(name)) { out['STR.edf'] = v; continue; } const folder = parts.length ? parts.pop() : (name.match(/^(\d{8})_/) || [, 'x'])[1]; out[folder + '/' + name] = v; } return out;
}
async function loadFiles(files, label) {
  const strKey = Object.keys(files).find(k => /(^|\/)STR\.edf$/i.test(k)); strData = strKey ? SS.readStr(files[strKey]) : null;
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
  $('d0').value = last.date; $('d1').value = last.date;
  if (appleData) { const n = AH.attach(appleData, nights); if (n) { $('st6').textContent = '✔ Watch data present'; $('st6').className = 'status ok'; } }
  renderSynopsis(); fillNightTable(); if ($('p-nights').classList.contains('active')) drawOverview();
  if (autoOpenSynopsis) { autoOpenSynopsis = false; go('syn'); }
}
$('filein').onchange = async (e) => { const list = [...e.target.files]; if (!list.length) return; try { const files = normalise(await filesFromInputs(list)); await loadFiles(files, list.length === 1 ? list[0].name : list.length + ' files'); try { await idb.put('last', { files, label: list.length === 1 ? list[0].name : list.length + ' files', when: Date.now() }); } catch (err) {} } catch (err) { $('loadmsg').textContent = 'Could not read that: ' + err; } e.target.value = ''; };
$('samplebtn').onclick = async () => { $('loadmsg').textContent = 'Fetching sample card…'; try { const r = await fetch('sample.zip'); const z = await JSZip.loadAsync(await r.arrayBuffer()); const files = {}; for (const [name, entry] of Object.entries(z.files)) if (!entry.dir && /\.edf$/i.test(name)) files[name] = await entry.async('arraybuffer'); await loadFiles(normalise(files), 'sample card'); } catch (e) { $('loadmsg').textContent = 'Sample not available offline yet: ' + e; } };
let appleData = null;
$('applein').onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return; if (!nights.length) { $('applemsg').textContent = 'Load the card first.'; return; }
  const since = new Date(nights[0].date + 'T00:00').getTime() - 86400e3; $('applemsg').textContent = 'Reading ' + f.name + '…';
  try {
    if (/\.(zip|xml)$/i.test(f.name)) appleData = await AH.readExport(f, since, (b, t) => { $('applemsg').textContent = `Scanning ${f.name}: ${(b / 1048576).toFixed(0)} MB read`; });
    else appleData = AH.readShortcutCsv(await f.text());
    const n = AH.attach(appleData, nights); try { await idb.put('apple', AH.pack(appleData)); } catch (err) {}
    $('applemsg').textContent = `${appleData.sleep.length.toLocaleString()} sleep records, ${appleData.hr.length.toLocaleString()} heart rate, ${appleData.spo2.length.toLocaleString()} SpO2 samples. Matched to ${n} of ${nights.length} nights.`;
    $('st6').textContent = n ? '✔ Watch data present' : 'No matching nights'; $('st6').className = 'status' + (n ? ' ok' : ''); renderSynopsis(); if ($('p-nights').classList.contains('active')) drawOverview();
  } catch (err) { $('applemsg').textContent = 'Could not read that: ' + err.message; }
  e.target.value = '';
};
$('oxin').onchange = async (e) => { const f = e.target.files[0]; if (!f || !nights.length) return; const n = SS.importOximeterCsv(await f.text(), nights); for (const nt of nights) nt.stats = SS.nightStats(nt); afterLoad(); alert(`SpO2 attached to ${n} session(s) by timestamp.`); e.target.value = ''; };

// ---------------------------------------------------------------- synopsis
function quick(days) { if (!nights.length) return; const last = nights[nights.length - 1].date; $('d1').value = last; $('d0').value = days ? (nights.find(n => n.date >= addDays(last, -(days - 1))) || nights[0]).date : nights[0].date; renderSynopsis(); }
function addDays(iso, d) { const x = new Date(iso); x.setDate(x.getDate() + d); return x.toISOString().slice(0, 10); }
function renderSynopsis() {
  if (!nights.length) return; let a = $('d0').value, b = $('d1').value; if (a > b) [a, b] = [b, a];
  const diag = parseFloat($('diag').value) || null; store.set('diag', diag);
  $('syntext').innerHTML = SS.synopsis(nights, a, b, diag) + appleSection(a, b);
  if ($('landmode').value === 'night') $('landmode').value = 'range';
  if ($('p-land').classList.contains('active')) drawLandscape();
  claudeSynopsis(false);
}
['d0', 'd1', 'diag'].forEach(id => $(id).onchange = renderSynopsis);

function appleSection(a, b) {
  const ah = nights.filter(n => n.date >= a && n.date <= b && n.apple); if (!ah.length) return '';
  const m = (k) => { const v = ah.map(n => n.apple[k]).filter(Number.isFinite); return v.length ? v.reduce((x, y) => x + y, 0) / v.length : NaN; };
  const mn = (k) => { const v = ah.map(n => n.apple[k]).filter(Number.isFinite); return v.length ? Math.min(...v) : NaN; };
  let t = `<h3>Apple Watch</h3><p>Watch data on ${ah.length} night${ah.length > 1 ? 's' : ''}: asleep ${m('asleep_h').toFixed(1)} h, deep ${m('deep_min').toFixed(0)} min, REM ${m('rem_min').toFixed(0)} min, awake ${m('awake_min').toFixed(0)} min, overnight heart rate ${m('hr_mean').toFixed(0)} bpm` + (Number.isFinite(m('hrv')) ? `, HRV ${m('hrv').toFixed(0)} ms` : '') + (Number.isFinite(mn('spo2_min')) ? `, Watch SpO2 minimum ${mn('spo2_min').toFixed(0)}%` : '') + '.</p>';
  const cov = ah.filter(n => n.apple.asleep_h > 0).map(n => 100 * Math.min(n.hours, n.apple.asleep_h) / n.apple.asleep_h); if (cov.length) t += `<p>The machine covered about ${(cov.reduce((x, y) => x + y, 0) / cov.length).toFixed(0)}% of the sleep the Watch recorded. The gap is untreated sleep; closing it is worth more than any pressure change.</p>`;
  return t;
}
// ---------------------------------------------------------------- charts
function drawOverview() {
  const k = Math.max(1, Math.ceil(nights.length / 10)); const x = nights.map((n, i) => (nights.length > 6 ? SS.label(n.date).split(' ').pop() : SS.label(n.date)));
  const tickvals = x.filter((_, i) => i % k === 0 || i === x.length - 1); const S = nights.map(n => n.stats); $('ovexplain').innerHTML = EX.overview(nights);
  Plotly.react('ch-usage', [{ type: 'bar', x, y: nights.map(n => +n.hours.toFixed(2)), marker: { color: C.blue }, name: 'Hours' }], { title: { text: 'Usage (hours), dashed = 4 h', font: { size: 13 } }, margin: { l: 34, r: 10, t: 30, b: 60 }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 4, y1: 4, line: { dash: 'dash', color: '#52514e', width: 1 } }], yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -45, tickvals, tickfont: { size: 10 } } }, { displayModeBar: false, responsive: true });
  Plotly.react('ch-ahi', [
    { type: 'bar', x, y: S.map(s => +s.AHI.toFixed(2)), marker: { color: C.blue }, name: 'AHI machine' },
    { type: 'bar', x, y: S.map(s => +s.app_AHI.toFixed(2)), marker: { color: C.orange }, name: 'AHI app (flow only)' }],
    { title: { text: 'AHI per night, dashed = 5', font: { size: 13 } }, barmode: 'group', margin: { l: 34, r: 10, t: 30, b: 60 }, legend: { orientation: 'h', y: -0.35, font: { size: 10 } }, yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -45, tickvals, tickfont: { size: 10 } }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 5, y1: 5, line: { dash: 'dash', color: C.red, width: 1 } }] }, { displayModeBar: false, responsive: true });
  Plotly.react('ch-leak', [{ type: 'bar', x, y: S.map(s => +s.leak_95.toFixed(1)), marker: { color: S.map(s => s.leak_95 > 24 ? C.red : C.aqua) }, name: 'Leak 95th' }],
    { title: { text: 'Leak, 95th percentile (L/min), dashed = 24', font: { size: 13 } }, margin: { l: 34, r: 10, t: 30, b: 60 }, yaxis: { rangemode: 'tozero' }, xaxis: { tickangle: -45, tickvals, tickfont: { size: 10 } }, shapes: [{ type: 'line', x0: -0.5, x1: x.length - 0.5, y0: 24, y1: 24, line: { dash: 'dash', color: C.red, width: 1 } }] }, { displayModeBar: false, responsive: true });
}
function fillNightTable() {
  const tb = $('nighttbl').tBodies[0]; tb.innerHTML = '';
  nights.forEach((n, i) => { const s = n.stats; const tr = document.createElement('tr'); tr.innerHTML = `<td>${SS.label(n.date)}</td><td>${n.hours.toFixed(2)}</td><td>${SS.pressureLabel(s)}</td><td>${s.AHI.toFixed(2)}</td><td>${Number.isFinite(s.leak_95) ? s.leak_95.toFixed(1) : ''}</td><td>${Number.isFinite(s.press_95) ? s.press_95.toFixed(1) : ''}</td>`; tr.onclick = () => showNight(i); tb.appendChild(tr); });
}
function showNight(i) {
  const n = nights[i]; const s = n.stats; selectedNight = n; $('landmode').value = 'night'; document.querySelectorAll('#nighttbl tbody tr').forEach((tr, k) => tr.classList.toggle('sel', k === i));
  const box = $('nightdetail'); box.innerHTML = `<div class="card"><h3 style="margin:0 0 6px">${new Date(n.date + 'T12:00').toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</h3>
    <div class="row" style="gap:6px"><button style="--c:#6250d6;padding:4px 10px;font-size:12px" onclick="go('land')">View in 3D</button><span class="pill" style="background:${C.blue}">${n.hours.toFixed(1)} h</span><span class="pill" style="background:${s.AHI < 5 ? C.green : C.red}">AHI ${s.AHI.toFixed(1)}</span><span class="pill" style="background:${C.violet}">${s.mode} ${Number.isFinite(s.press_min) ? Math.round(s.press_min) + ' to ' + Math.round(s.press_max) : ''}</span><span class="pill" style="background:${s.leak_95 > 24 ? C.red : C.grey}">leak 95th ${Number.isFinite(s.leak_95) ? s.leak_95.toFixed(0) : '?'}</span><span class="pill" style="background:${C.amber}">FL 95th ${Number.isFinite(s.flowlim_95) ? s.flowlim_95.toFixed(2) : '?'}</span>${Number.isFinite(s.spo2_mean) ? `<span class="pill" style="background:${C.red}">SpO2 min ${s.spo2_min.toFixed(0)} · ODI ${s.ODI.toFixed(1)}</span>` : ''}</div>
    <div class="hl">SETTINGS &nbsp; ${SS.settingsText(SS.settingsSummary([n], strData))}</div><p class="muted" style="margin:8px 0 0">Sessions: ${n.sessions.map(x => { const pr = x.ch.Press; if (!pr || !pr.length) return SS.fmtTime(x.start); const skip = Math.max(Math.floor(pr.length * 0.15), Math.min(900, pr.length >> 1)); const t = pr.subarray(skip); let m = 0; for (const v of t) m += v; m /= t.length || 1; let sd = 0; for (const v of t) sd += (v - m) ** 2; sd = Math.sqrt(sd / (t.length || 1)); let lo = Infinity, hi = -Infinity; for (const v of pr) { if (v < lo) lo = v; if (v > hi) hi = v; } return `${SS.fmtTime(x.start)} (${sd < 0.05 ? 'CPAP ' + hi.toFixed(0) : lo.toFixed(0) + ' to ' + hi.toFixed(0)})`; }).join(', ')}. OA ${s.OA}, CA ${s.CA}, H ${s.H}, arousals ${s.arousals}. RR ${s.rr_med.toFixed(0)}, Vt ${s.tv_med.toFixed(0)} mL, MV ${s.mv_med.toFixed(1)}.</p></div>
    <div class="card"><div id="ch-night" style="width:100%;height:${520 + (Number.isFinite(s.spo2_mean) ? 100 : 0) + (n.apple && n.apple.stages.length ? 200 : 0)}px"></div><div class="key"><span><i style="background:${C.red}"></i>obstructive</span><span><i style="background:${C.violet}"></i>central</span><span><i style="background:${C.orange}"></i>hypopnea</span><span><i style="background:${C.amber}"></i>arousal</span><span>lighter bands = app events</span></div></div>
    <div class="card"><details><summary>What these panels mean, what stands out tonight, what to improve</summary><div id="ntexplain"></div></details></div>
    <div class="card"><b>Events</b> <span class="muted">(tap one to see the airflow around it)</span><div id="evlist"></div></div><div class="card" id="zoomcard" style="display:none"><div id="ch-zoom" style="width:100%;height:240px"></div><div class="muted" id="zoomnote"></div></div>`;
  box.scrollIntoView({ behavior: 'smooth' }); $('ntexplain').innerHTML = EX.night(n);
  const t0 = n.sessions[0].start; const tr = []; const shapes = [];
  const series = (k, sc, name, color, yaxis) => { const xs = [], ys = []; for (const ses of n.sessions) { const a = ses.ch[k]; if (!a) continue; for (let i = 0; i < a.length; i++) { xs.push(new Date(ses.start.getTime() + 2000 * i)); ys.push(a[i] * sc); } xs.push(null); ys.push(null); } if (xs.length) tr.push({ x: xs, y: ys, mode: 'lines', line: { color, width: 1 }, name, yaxis, hoverinfo: 'x+y+name' }); };
  series('Press', 1, 'Set pressure', C.blue, 'y'); series('MaskPress', 1, 'Mask pressure', C.aqua, 'y'); series('Leak', 60, 'Leak L/min', C.orange, 'y2'); series('FlowLim', 1, 'Flow limitation', C.violet, 'y3'); series('Snore', 1, 'Snore', '#e87ba4', 'y3'); series('TidVol', 1000, 'Tidal volume mL', C.green, 'y4');
  for (const ses of n.sessions) if (ses.vent) { const xs = [], ys = []; for (let i = 0; i < ses.vent.length; i += 2) { xs.push(new Date(ses.start.getTime() + 1000 * i)); ys.push(ses.vent[i]); } tr.push({ x: xs, y: ys, mode: 'lines', line: { color: C.aqua, width: 1 }, name: 'Ventilation vs baseline', yaxis: 'y5' }); }
  const hasOx = n.sessions.some(x => x.hasOx); const hasAp = !!(n.apple && (n.apple.stages.length || n.apple.hr.length));
  if (hasOx) for (const ses of n.sessions) if (ses.spo2) { const xs = [], ys = [], yp = []; for (let i = 0; i < ses.spo2.length; i += 5) { xs.push(new Date(ses.start.getTime() + 1000 * i)); ys.push(ses.spo2[i] > 0 ? ses.spo2[i] : null); yp.push(ses.pulse && ses.pulse[i] > 0 ? ses.pulse[i] : null); } tr.push({ x: xs, y: ys, mode: 'lines', line: { color: C.red, width: 1 }, name: 'SpO2 %', yaxis: 'y6' }); tr.push({ x: xs, y: yp, mode: 'lines', line: { color: C.orange, width: 1 }, name: 'Pulse', yaxis: 'y6' }); }
  for (const ses of n.sessions) for (const e of [...ses.machine, ...ses.app]) { const col = EVC[e.label]; if (!col) continue; shapes.push({ type: 'rect', xref: 'x', yref: 'paper', x0: e.start, x1: new Date(e.start.getTime() + Math.max(e.dur, 20) * 1000), y0: 0, y1: 1, fillcolor: col, opacity: e.source === 'machine' ? 0.35 : 0.15, line: { width: 0 } }); }
  if (hasAp) {
    const ord = { InBed: 0, Deep: 1, Core: 2, Asleep: 2, REM: 3, Awake: 4 }; const cols = { InBed: '#d9d8d3', Deep: '#0f6e4f', Core: C.blue, Asleep: C.blue, REM: C.violet, Awake: C.orange };
    for (const r of n.apple.stages) shapes.push({ type: 'rect', xref: 'x', yref: hasOx ? 'y7' : 'y6', x0: new Date(r.s), x1: new Date(r.e), y0: (ord[r.stage] ?? 2) - 0.4, y1: (ord[r.stage] ?? 2) + 0.4, fillcolor: cols[r.stage] || C.grey, line: { width: 0 } });
    if (n.apple.hr.length) tr.push({ x: n.apple.hr.map(([t]) => new Date(t)), y: n.apple.hr.map(([, v]) => v), mode: 'lines', line: { color: C.red, width: 1 }, name: 'Watch HR', yaxis: hasOx ? 'y8' : 'y7' });
    if (n.apple.spo2.length) tr.push({ x: n.apple.spo2.map(([t]) => new Date(t)), y: n.apple.spo2.map(([, v]) => v), mode: 'markers', marker: { color: n.apple.spo2.map(([, v]) => v < 90 ? C.red : C.blue), size: 5 }, name: 'Watch SpO2', yaxis: hasOx ? 'y8' : 'y7' });
  }
  const nrows = (hasOx ? 6 : 5) + (hasAp ? 2 : 0); const dom = (k) => { const h = 1 / nrows, gap = 0.035; return [1 - (k + 1) * h + gap, 1 - k * h - gap / 2]; };
  const layout = { margin: { l: 36, r: 10, t: 10, b: 30 }, showlegend: false, shapes, hovermode: 'x', dragmode: 'pan', xaxis: { type: 'date', tickformat: '%H:%M' },
    yaxis: { domain: dom(0), title: { text: 'cmH2O', font: { size: 10 } }, range: [0, 21] }, yaxis2: { domain: dom(1), title: { text: 'leak', font: { size: 10 } }, range: [0, 60] }, yaxis3: { domain: dom(2), title: { text: 'FL', font: { size: 10 } }, range: [0, 1] }, yaxis4: { domain: dom(3), title: { text: 'Vt', font: { size: 10 } }, range: [0, 1200] }, yaxis5: { domain: dom(4), title: { text: 'vent', font: { size: 10 } }, range: [0, 2.5] } };
  if (hasOx) layout.yaxis6 = { domain: dom(5), title: { text: 'SpO2', font: { size: 10 } }, range: [80, 100] };
  if (hasAp) { const k = hasOx ? 6 : 5; layout['yaxis' + (k + 1)] = { domain: dom(k), tickvals: [0, 1, 2, 3, 4], ticktext: ['bed', 'deep', 'core', 'REM', 'wake'], range: [-0.6, 4.6], tickfont: { size: 9 } }; layout['yaxis' + (k + 2)] = { domain: dom(k + 1), title: { text: 'Watch', font: { size: 10 } }, range: [40, 110] }; }
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


// ---------------------------------------------------------------- 3D landscape (WebGL via Plotly)
const LB = { bin: 120, t0: 19, t1: 33, Z: 6 }; LB.n = (LB.t1 - LB.t0) * 3600 / LB.bin;
let landCam = 'over';
function nightGrids(n) {
  const W = LB.n; const op = new Array(W).fill(NaN), lk = new Array(W).fill(NaN), pr = new Array(W).fill(NaN);
  const [y, m, d] = n.date.split('-').map(Number); const base = new Date(y, m - 1, d, LB.t0, 0, 0).getTime();
  for (const s of n.sessions) {
    const fl = s.ch.FlowLim, leak = s.ch.Leak, press = s.ch.Press, vr = s.vent; const n2 = fl ? fl.length : (press ? press.length : 0); const step = LB.bin / 2;
    for (let i2 = 0; i2 < n2; i2 += step) {
      const b = Math.floor((s.start.getTime() + 2000 * i2 - base) / 1000 / LB.bin); if (b < 0 || b >= W) continue; const j = Math.min(i2 + step, n2);
      let f = 0; if (fl) { let a = 0; for (let k = i2; k < j; k++) a += fl[k]; f = a / (j - i2); }
      let v = 1; if (vr) { const a1 = 2 * i2, a2 = Math.min(2 * j, vr.length); if (a2 > a1) { let a = 0; for (let k = a1; k < a2; k++) a += Math.min(vr[k], 1); v = a / (a2 - a1); } }
      op[b] = v * (1 - 0.7 * f);
      if (leak) { let a = 0; for (let k = i2; k < j; k++) a += leak[k]; lk[b] = 60 * a / (j - i2); }
      if (press) { let a = 0; for (let k = i2; k < j; k++) a += press[k]; pr[b] = a / (j - i2); }
    }
  }
  return { op, lk, pr, base };
}
function drawLandscape() {
  if (!nights.length) return; const mode = $('landmode').value; let sel;
  if (mode === 'night' && selectedNight) sel = [selectedNight];
  else if (mode === 'all') sel = nights.slice(-60);
  else { let a = $('d0').value, b = $('d1').value; if (a > b) [a, b] = [b, a]; sel = nights.filter(n => n.date >= a && n.date <= b); if (!sel.length) sel = nights.slice(-14); }
  sel = sel.slice().reverse(); const N = sel.length; const W = LB.n;
  const xs = Array.from({ length: W }, (_, i) => i * 0.25); const traces = []; const sw = 5, gap = 7;
  const scale = [[0, '#c9c8c3'], [0.165, '#c9c8c3'], [0.1667, '#e34948'], [0.5, '#eda100'], [1, '#1baf7a']]; // value -0.2 .. 1 : grey floor then red->yellow->green
  const pil = { 'Obstructive Apnea': { x: [], y: [], z: [], c: C.red }, 'Central Apnea': { x: [], y: [], z: [], c: C.violet }, 'Hypopnea': { x: [], y: [], z: [], c: C.orange } };
  sel.forEach((n, k) => {
    const { op, lk, pr, base } = nightGrids(n); const y0 = k * gap;
    const z = op.map(v => Number.isNaN(v) ? -0.15 * LB.Z : Math.min(1, Math.max(0, v)) * LB.Z); const col = op.map(v => Number.isNaN(v) ? -0.2 : Math.min(1, Math.max(0, v)));
    const zz = z.map((v, i) => { let a = 0, c = 0; for (let j = Math.max(0, i - 2); j <= Math.min(W - 1, i + 2); j++) { a += z[j]; c++; } return a / c; });
    traces.push({ type: 'surface', x: xs, y: [y0 - sw / 2, y0, y0 + sw / 2], z: [zz, zz, zz], surfacecolor: [col, col, col], colorscale: scale, cmin: -0.2, cmax: 1, showscale: false, hoverinfo: 'skip', lighting: { ambient: 0.75, diffuse: 0.6, specular: 0.05 }, name: SS.label(n.date) });
    const zw = lk.map(v => v > 24 ? 0.55 * LB.Z : null); if (zw.some(v => v !== null)) traces.push({ type: 'surface', x: xs, y: [y0 - sw / 2, y0, y0 + sw / 2], z: [zw, zw, zw], surfacecolor: [zw.map(() => 1), zw.map(() => 1), zw.map(() => 1)], colorscale: [[0, '#2a78d6'], [1, '#2a78d6']], showscale: false, opacity: 0.6, hoverinfo: 'skip' });
    const px = [], pz = []; pr.forEach((v, i) => { if (!Number.isNaN(v)) { px.push(xs[i]); pz.push(LB.Z * (1.15 + (v - 4) / 12)); } else { px.push(null); pz.push(null); } });
    traces.push({ type: 'scatter3d', mode: 'lines', x: px, y: px.map(() => y0), z: pz, line: { color: '#ffffff', width: 3 }, hoverinfo: 'skip', name: 'pressure' });
    if (n.apple && n.apple.stages.length) {
      const stageCol = { Deep: 0.1, Core: 0.35, Asleep: 0.35, REM: 0.6, Awake: 0.85, InBed: 1.0 }; const rib = new Array(W).fill(null); const rc = new Array(W).fill(0);
      for (const r of n.apple.stages) { const b0 = Math.max(0, Math.floor((r.s - base) / 1000 / LB.bin)), b1 = Math.min(W, Math.ceil((r.e - base) / 1000 / LB.bin)); for (let b = b0; b < b1; b++) { if (r.stage === 'InBed' && rib[b] !== null) continue; rib[b] = 0.25 * LB.Z; rc[b] = stageCol[r.stage] ?? 0.35; } }
      traces.push({ type: 'surface', x: xs, y: [y0 - sw / 2 - 1.9, y0 - sw / 2 - 1.1, y0 - sw / 2 - 0.3], z: [rib, rib, rib], surfacecolor: [rc, rc, rc], colorscale: [[0, '#0f6e4f'], [0.3, '#2a78d6'], [0.5, '#2a78d6'], [0.7, '#6250d6'], [0.9, '#eb6834'], [1, '#d9d8d3']], cmin: 0, cmax: 1, showscale: false, hoverinfo: 'skip', opacity: 0.95 });
      if (n.apple.hr.length) { const hx = [], hz = []; for (const [t, v] of n.apple.hr) { const b = (t - base) / 1000 / LB.bin; if (b < 0 || b >= W) continue; hx.push(b * 0.25); hz.push(LB.Z * (1.6 + (v - 40) / 80)); } traces.push({ type: 'scatter3d', mode: 'lines', x: hx, y: hx.map(() => y0 - sw / 2 - 1.1), z: hz, line: { color: C.red, width: 2 }, hoverinfo: 'skip' }); }
    }
    for (const s of n.sessions) for (const e of s.machine) { const g = pil[e.label]; if (!g) continue; const b = (e.start.getTime() - base) / 1000 / LB.bin; if (b < 0 || b >= W) continue; const x = b * 0.25, z0 = Math.max(0, zz[Math.floor(b)]); const h = LB.Z * (/Apnea/.test(e.label) ? 0.9 : 0.6); g.x.push(x, x, null); g.y.push(y0, y0, null); g.z.push(z0, z0 + h, null); (g.sz ||= []).push(0, 4, 0); }
  });
  for (const [lab, g] of Object.entries(pil)) if (g.x.length) traces.push({ type: 'scatter3d', mode: 'lines+markers', x: g.x, y: g.y, z: g.z, line: { color: g.c, width: 6 }, marker: { color: g.c, size: g.sz }, name: lab, hoverinfo: 'name' });
  const ticks = []; for (let h = LB.t0; h <= LB.t1; h += 2) ticks.push(h);
  const layout = { margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: false, paper_bgcolor: '#f6f5f2', annotations: [{ text: N === 1 ? SS.label(sel[0].date) : `${N} nights, ${SS.label(sel[N - 1].date)} to ${SS.label(sel[0].date)}`, xref: 'paper', yref: 'paper', x: 0, y: 1, showarrow: false, font: { size: 12, color: '#52514e' } }], scene: {
      xaxis: { tickvals: ticks.map(h => (h - LB.t0) * 3600 / LB.bin * 0.25), ticktext: ticks.map(h => `${String(h % 24).padStart(2, '0')}:00`), title: { text: '' }, showbackground: false, showgrid: false, zeroline: false, showspikes: false },
      yaxis: { tickvals: sel.map((_, k) => k * gap), ticktext: sel.map(n => SS.label(n.date)), title: { text: '' }, showbackground: false, showgrid: false, zeroline: false, showspikes: false },
      zaxis: { visible: false, range: [-2, 2.6 * LB.Z], showspikes: false }, aspectmode: 'manual', aspectratio: { x: 2.2, y: Math.max(0.6, 0.11 * N), z: 0.45 }, camera: cams(N)[landCam], dragmode: 'orbit' } };
  $('landhl').innerHTML = 'SETTINGS &nbsp; ' + SS.settingsText(SS.settingsSummary(sel, strData));
  Plotly.react('ch-land', traces, layout, { displayModeBar: false, responsive: true });
}
function cams(N) { const c = { x: 0, y: 0, z: 0 }; return { over: { eye: { x: -0.85, y: -1.75, z: 1.05 }, center: { x: 0, y: 0, z: 0.05 } }, along: { eye: { x: -1.9, y: -0.4, z: 0.35 }, center: { x: 0, y: 0, z: -0.1 } }, top: { eye: { x: 0, y: -0.01, z: 1.9 }, center: c } }; }
function landView(v) { landCam = v; drawLandscape(); }

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
  try { const ap = await idb.get('apple'); if (ap) appleData = AH.unpack(ap); } catch (e) {}
  try { const last = await idb.get('last'); if (last && last.files) { autoOpenSynopsis = true; $('loadmsg').textContent = 'Reloading ' + last.label + ' from last time…'; await loadFiles(last.files, last.label); } } catch (e) {}
})();
