/* Apple Health on the phone: streamed export.zip parser and a Shortcuts CSV importer. */
'use strict';
const AH = (() => {
  const KEEP = { 'HKCategoryTypeIdentifierSleepAnalysis': 'sleep', 'HKQuantityTypeIdentifierHeartRate': 'hr', 'HKQuantityTypeIdentifierOxygenSaturation': 'spo2', 'HKQuantityTypeIdentifierRespiratoryRate': 'rr', 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN': 'hrv' };
  const STAGE = { InBed: 'InBed', Awake: 'Awake', AsleepCore: 'Core', AsleepDeep: 'Deep', AsleepREM: 'REM', AsleepUnspecified: 'Asleep', Asleep: 'Asleep' };
  const pd = (s) => { const m = s.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/); return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null; };
  const nightKey = (d) => { const x = new Date(d.getTime() - 12 * 3600e3); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };

  /** Stream export.zip (or export.xml) and return {sleep:[{s,e,stage,src}], hr:[[t,v]], spo2:[[t,v]], rr:[[t,v]], hrv:[[t,v]]} with times in ms. */
  async function readExport(file, sinceMs, progress) {
    const out = { sleep: [], hr: [], spo2: [], rr: [], hrv: [] }; let carry = ''; let bytes = 0; const total = file.size;
    const re = /<Record\s+type="([^"]+)"([^>]*?)\/?>/g;
    const attr = (s, k) => { const m = s.match(new RegExp(k + '="([^"]*)"')); return m ? m[1] : null; };
    const handle = (text) => {
      let m; let last = 0;
      while ((m = re.exec(text))) {
        last = re.lastIndex; const kind = KEEP[m[1]]; if (!kind) continue; const a = m[2];
        const st = attr(a, 'startDate'); if (!st) continue; const sd = pd(st); if (!sd || sd.getTime() < sinceMs) continue;
        if (kind === 'sleep') { const ed = pd(attr(a, 'endDate') || ''); if (!ed) continue; const v = attr(a, 'value') || ''; out.sleep.push({ s: sd.getTime(), e: ed.getTime(), stage: STAGE[v.replace('HKCategoryValueSleepAnalysis', '')] || v, src: attr(a, 'sourceName') || '' }); }
        else { let v = parseFloat(attr(a, 'value')); if (!Number.isFinite(v)) continue; if (kind === 'spo2' && v <= 1) v *= 100; out[kind].push([sd.getTime(), v]); }
      }
      return text.slice(Math.max(last, text.length - 4000));   // keep a tail in case a record straddles chunks
    };
    const dec = new TextDecoder('utf-8');
    const feed = (chunk) => { bytes += chunk.length; carry = handle(carry + dec.decode(chunk, { stream: true })); if (progress) progress(bytes, total); };
    if (/\.zip$/i.test(file.name)) {
      const z = await JSZip.loadAsync(file); const name = Object.keys(z.files).find(n => /export\.xml$/i.test(n) && !n.includes('__MACOSX')); if (!name) throw new Error('export.xml not found inside the zip');
      await new Promise((res, rej) => { z.file(name).internalStream('uint8array').on('data', feed).on('error', rej).on('end', res).resume(); });
    } else {
      const reader = file.stream().getReader(); for (;;) { const { done, value } = await reader.read(); if (done) break; feed(value); await new Promise(r => setTimeout(r, 0)); }
    }
    for (const k of ['hr', 'spo2', 'rr', 'hrv']) out[k].sort((a, b) => a[0] - b[0]); out.sleep.sort((a, b) => a.s - b.s);
    return out;
  }

  /** CSV from the SleepScope Shortcut (type,start,end,value per line, any order of columns tolerated) or any CSV with those headers. */
  function readShortcutCsv(text) {
    const out = { sleep: [], hr: [], spo2: [], rr: [], hrv: [] };
    const parseDate = (s) => { s = (s || '').trim().replace(/\bat\b/, '').replace(/\s+/g, ' '); let d = pd(s); if (d) return d; const t = Date.parse(s); return Number.isNaN(t) ? null : new Date(t); };
    const lines = text.split(/\r?\n/).filter(l => l.trim()); if (!lines.length) return out;
    let hdr = lines[0].toLowerCase().split(',').map(x => x.trim()); let start = 1; let ti = hdr.indexOf('type'), si = hdr.findIndex(h => h.startsWith('start')), ei = hdr.findIndex(h => h.startsWith('end')), vi = hdr.indexOf('value');
    if (ti < 0) { ti = 0; si = 1; ei = 2; vi = 3; start = 0; }
    for (let i = start; i < lines.length; i++) {
      const c = splitCsv(lines[i]); if (c.length < 4) continue; const type = (c[ti] || '').toLowerCase(); const sd = parseDate(c[si]), ed = parseDate(c[ei]); const raw = (c[vi] || '').trim(); if (!sd) continue;
      if (type.includes('sleep')) { if (!ed) continue; const v = raw.toLowerCase(); const stage = v.includes('deep') ? 'Deep' : v.includes('rem') ? 'REM' : v.includes('core') ? 'Core' : v.includes('awake') ? 'Awake' : v.includes('bed') ? 'InBed' : 'Asleep'; out.sleep.push({ s: sd.getTime(), e: ed.getTime(), stage, src: 'Shortcut' }); }
      else { let v = parseFloat(raw.replace(/[^\d.\-]/g, '')); if (!Number.isFinite(v)) continue; const k = type.includes('heart rate var') || type.includes('hrv') ? 'hrv' : type.includes('heart') ? 'hr' : type.includes('oxygen') || type.includes('spo2') ? 'spo2' : type.includes('respir') ? 'rr' : null; if (!k) continue; if (k === 'spo2' && v <= 1) v *= 100; out[k].push([sd.getTime(), v]); }
    }
    for (const k of ['hr', 'spo2', 'rr', 'hrv']) out[k].sort((a, b) => a[0] - b[0]); out.sleep.sort((a, b) => a.s - b.s);
    return out;
  }
  function splitCsv(line) { const out = []; let cur = '', q = false; for (const ch of line) { if (ch === '"') q = !q; else if (ch === ',' && !q) { out.push(cur); cur = ''; } else cur += ch; } out.push(cur); return out; }

  /** Attach per-night summaries: night.apple = {stages, hr, spo2, asleep_h, deep_min, rem_min, core_min, awake_min, hr_mean, hr_min, spo2_min, spo2_mean, hrv, rr}. Returns nights matched. */
  function attach(data, nights) {
    const by = {}; const bucket = (k) => (by[k] ||= { sleep: [], hr: [], spo2: [], rr: [], hrv: [] });
    for (const r of data.sleep) bucket(nightKey(new Date(r.s))).sleep.push(r);
    for (const k of ['hr', 'spo2', 'rr', 'hrv']) for (const [t, v] of data[k]) bucket(nightKey(new Date(t)))[k].push([t, v]);
    let count = 0;
    for (const nt of nights) {
      const d = by[nt.date]; if (!d) { nt.apple = null; continue; }
      const srcs = {}; for (const r of d.sleep) (srcs[r.src] ||= new Set()).add(r.stage); const best = Object.keys(srcs).sort((a, b) => srcs[b].size - srcs[a].size)[0];
      const stages = d.sleep.filter(r => r.src === best); const mins = (n) => stages.filter(r => r.stage === n).reduce((a, r) => a + (r.e - r.s) / 60000, 0);
      let w0 = Infinity, w1 = -Infinity; for (const r of stages) { w0 = Math.min(w0, r.s); w1 = Math.max(w1, r.e); }
      const inWin = (arr) => stages.length ? arr.filter(([t]) => t >= w0 && t <= w1) : arr;
      const hr = inWin(d.hr), sp = inWin(d.spo2), hrv = d.hrv.filter(([t]) => !stages.length || (t >= w0 - 3600e3 && t <= w1 + 3600e3)), rr = inWin(d.rr);
      const mean = (a) => a.length ? a.reduce((x, [, v]) => x + v, 0) / a.length : NaN; const min = (a) => a.length ? Math.min(...a.map(x => x[1])) : NaN;
      const asleep = mins('Core') + mins('Deep') + mins('REM') + mins('Asleep');
      nt.apple = { stages, hr, spo2: sp, asleep_h: stages.length ? asleep / 60 : NaN, deep_min: mins('Deep'), rem_min: mins('REM'), core_min: mins('Core'), awake_min: mins('Awake'), inbed_h: mins('InBed') / 60, hr_mean: mean(hr), hr_min: min(hr), spo2_mean: mean(sp), spo2_min: min(sp), hrv: mean(hrv), rr: mean(rr) };
      if (stages.length || hr.length) count++;
    }
    return count;
  }
  /** Compact form for IndexedDB persistence. */
  const pack = (data) => JSON.stringify(data); const unpack = (s) => JSON.parse(s);
  return { readExport, readShortcutCsv, attach, pack, unpack };
})();
