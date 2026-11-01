/* SleepScope engine for the browser: EDF parsing, night grouping, scoring, synopsis. Mirrors the desktop Python. */
'use strict';
const SS = (() => {
  // ---------------------------------------------------------------- EDF
  const txt = (u8, a, b) => new TextDecoder('latin1').decode(u8.subarray(a, b)).trim();
  function parseHeader(u8) {
    const d = txt(u8, 168, 176), t = txt(u8, 176, 184);
    const [dd, mm, yy0] = d.split('.').map(Number); const yy = yy0 + (yy0 < 85 ? 2000 : 1900);
    const [H, M, S] = t.split('.').map(Number);
    return { start: new Date(yy, mm - 1, dd, H, M, S), hdr: +txt(u8, 184, 192), nrec: +txt(u8, 236, 244), recdur: +txt(u8, 244, 252), nsig: +txt(u8, 252, 256) };
  }
  function readEdf(buf, keepLabels) {
    const u8 = new Uint8Array(buf); const h = parseHeader(u8); const ns = h.nsig; let o = 256;
    const f = (len) => { const out = []; for (let i = 0; i < ns; i++) { out.push(txt(u8, o, o + len)); o += len; } return out; };
    const labels = f(16); f(80); const dims = f(8); const pmin = f(8).map(Number), pmax = f(8).map(Number), dmin = f(8).map(Number), dmax = f(8).map(Number); f(80); const spr = f(8).map(Number); f(32);
    const dv = new DataView(buf); const sigs = {}; const recBytes = spr.reduce((a, b) => a + b, 0) * 2;
    for (let s = 0; s < ns; s++) {
      if (/Crc/i.test(labels[s])) continue;
      const n = spr[s] * h.nrec; const arr = new Float32Array(n); const gain = (pmax[s] - pmin[s]) / (dmax[s] - dmin[s]); const off = pmin[s] - dmin[s] * gain;
      let pre = 0; for (let k = 0; k < s; k++) pre += spr[k] * 2;
      let i = 0;
      for (let r = 0; r < h.nrec; r++) { let p = h.hdr + r * recBytes + pre; for (let k = 0; k < spr[s]; k++, p += 2) arr[i++] = dv.getInt16(p, true) * gain + off; }
      sigs[keepLabels ? labels[s] : labels[s].split('.')[0]] = { data: arr, fs: spr[s] / h.recdur, dim: dims[s] };
    }
    return { ...h, duration: h.nrec * h.recdur, sigs };
  }
  function parseAnnotations(buf) {
    const u8 = new Uint8Array(buf); const h = parseHeader(u8); const data = new TextDecoder('latin1').decode(u8.subarray(h.hdr));
    const out = []; const re = /([+-]\d+(?:\.\d+)?)(?:\x15(\d+(?:\.\d+)?))?\x14([^\x14\x00]*)\x14/g; let m;
    while ((m = re.exec(data))) { const lab = m[3].trim(); if (!lab || lab === 'Recording starts') continue; out.push({ end: new Date(h.start.getTime() + parseFloat(m[1]) * 1000), dur: m[2] ? parseFloat(m[2]) : 0, label: lab }); }
    return { start: h.start, events: out };
  }
  const nightDate = (d) => { const x = new Date(d.getTime() - 12 * 3600e3); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };

  // ---------------------------------------------------------------- build sessions from a file map {name: ArrayBuffer}
  async function buildSessions(files, progress) {
    const names = Object.keys(files); const brps = names.filter(n => /_BRP\.edf$/i.test(n)).sort();
    const sessions = [];
    for (let i = 0; i < brps.length; i++) {
      if (progress) progress(i, brps.length, brps[i].split('/').pop()); await new Promise(r => setTimeout(r, 0));
      const stem = brps[i].replace(/_BRP\.edf$/i, ''); const folder = brps[i].substring(0, brps[i].lastIndexOf('/') + 1);
      let brp; try { brp = readEdf(files[brps[i]]); } catch (e) { continue; }
      if (brp.duration < 300) continue;
      const s = { start: brp.start, duration: brp.duration, flow: brp.sigs.Flow ? brp.sigs.Flow.data : null, press25: brp.sigs.Press ? brp.sigs.Press.data : null, fs: brp.sigs.Flow ? brp.sigs.Flow.fs : 25, ch: {}, spo2: null, pulse: null, machine: [], app: [] };
      const pld = files[stem + '_PLD.edf']; if (pld) { try { const p = readEdf(pld); for (const k in p.sigs) s.ch[k] = p.sigs[k].data; } catch (e) {} }
      const sa = files[stem + '_SA2.edf'] || files[stem + '_SAD.edf']; if (sa) { try { const p = readEdf(sa); if (p.sigs.SpO2) s.spo2 = p.sigs.SpO2.data; if (p.sigs.Pulse) s.pulse = p.sigs.Pulse.data; } catch (e) {} }
      for (const n of names) {
        if (!n.startsWith(folder) || !/_(EVE|CSL)\.edf$/i.test(n)) continue;
        let a; try { a = parseAnnotations(files[n]); } catch (e) { continue; }
        const dt = (s.start - a.start) / 1000; if (dt < -5 || dt > 90) continue;
        for (const e of a.events) s.machine.push({ label: e.label, start: new Date(e.end.getTime() - e.dur * 1000), dur: e.dur, source: 'machine', detail: '' });
      }
      s.machine.sort((a, b) => a.start - b.start); s.hasOx = !!(s.spo2 && s.spo2.some(v => v > 0));
      sessions.push(s);
    }
    const nights = {}; for (const s of sessions) (nights[nightDate(s.start)] ||= []).push(s);
    return Object.keys(nights).sort().map(d => ({ date: d, sessions: nights[d].sort((a, b) => a.start - b.start), hours: nights[d].reduce((a, s) => a + s.duration, 0) / 3600 }));
  }

  // ---------------------------------------------------------------- scoring
  function lowpassAbs(flow, fs, fc) { // one-pole IIR forward+backward approx, then abs
    const a = Math.exp(-2 * Math.PI * fc / fs); const n = flow.length; const y = new Float32Array(n); let s = 0;
    for (let i = 0; i < n; i++) { s = a * s + (1 - a) * flow[i]; y[i] = s; } s = 0;
    for (let i = n - 1; i >= 0; i--) { s = a * s + (1 - a) * y[i]; y[i] = Math.abs(s); } return y;
  }
  function ventRatio(s) {
    const fs = s.fs, f = lowpassAbs(s.flow, fs, 1.5), n = Math.floor(s.duration), k = Math.round(3 * fs); const x = new Float32Array(n);
    // 3 s moving mean sampled at 1 Hz
    const cs = new Float64Array(f.length + 1); for (let i = 0; i < f.length; i++) cs[i + 1] = cs[i] + f[i];
    for (let i = 0; i < n; i++) { const c = Math.round(i * fs); const a = Math.max(0, c - (k >> 1)), b = Math.min(f.length, c + (k >> 1)); x[i] = b > a ? (cs[b] - cs[a]) / (b - a) : 0; }
    const r = new Float32Array(n); const W = 120; const win = [];
    for (let i = 0; i < n; i++) {
      if (i >= W) { win.length = 0; for (let j = i - W; j < i; j++) win.push(x[j]); win.sort((a, b) => a - b); const base = Math.max(win[Math.floor(0.7 * (W - 1))], 1e-4); r[i] = x[i] / base; }
      else r[i] = Math.min(1, x[i] / Math.max(1e-4, x.subarray(0, Math.max(1, i + 1)).reduce((a, b) => a + b, 0) / (i + 1)));
    }
    return r;
  }
  function runs(mask) { const out = []; let i = 0; const n = mask.length; while (i < n) { if (mask[i]) { let j = i; while (j < n && mask[j]) j++; out.push([i, j]); i = j; } else i++; } return out; }
  function scoreSession(s) {
    s.app = []; if (!s.flow) return;
    const r = ventRatio(s); s.vent = r; const n = r.length; const mask = new Uint8Array(n); for (let i = 0; i < n; i++) mask[i] = r[i] < 0.7 ? 1 : 0;
    for (const [a, b] of runs(mask)) {
      if (b - a < 10 || b - a > 150) continue; let lowest = 1;
      for (let j = a; j + 8 <= b; j++) { let m = 0; for (let k = j; k < j + 8; k++) m += r[k]; m /= 8; if (m < lowest) lowest = m; }
      let mean = 0; for (let k = a; k < b; k++) mean += r[k]; mean /= (b - a);
      const st = new Date(s.start.getTime() + a * 1000);
      if (lowest < 0.25) {
        const m = s.machine.find(e => /Apnea/.test(e.label) && e.start >= new Date(st.getTime() - 15000) && e.start <= new Date(st.getTime() + (b - a) * 1000 + 5000));
        s.app.push({ label: m ? m.label : 'Apnea (unflagged by machine)', start: st, dur: b - a, source: 'app', detail: `flow fell to ${Math.round(lowest * 100)}% of baseline` + (m ? `; machine scored ${m.dur} s` : '') });
      } else s.app.push({ label: 'Hypopnea', start: st, dur: b - a, source: 'app', detail: `flow ${Math.round(mean * 100)}% of baseline (flow only, unconfirmed)` });
    }
    const fl = s.ch.FlowLim; if (fl) { const m2 = new Uint8Array(fl.length); for (let i = 0; i < fl.length; i++) m2[i] = fl[i] >= 0.2 ? 1 : 0; for (const [a, b] of runs(m2)) { if (2 * (b - a) >= 10) { let mx = 0, mn = 0; for (let k = a; k < b; k++) { mn += fl[k]; if (fl[k] > mx) mx = fl[k]; } s.app.push({ label: 'Flow Limitation Run', start: new Date(s.start.getTime() + 2000 * a), dur: 2 * (b - a), source: 'app', detail: `FlowLim mean ${(mn / (b - a)).toFixed(2)}, peak ${mx.toFixed(2)}` }); } } }
    const lk = s.ch.Leak; if (lk) { const m3 = new Uint8Array(lk.length); for (let i = 0; i < lk.length; i++) m3[i] = lk[i] * 60 > 24 ? 1 : 0; for (const [a, b] of runs(m3)) { if (2 * (b - a) >= 60) { let mx = 0, mn = 0; for (let k = a; k < b; k++) { mn += lk[k] * 60; if (lk[k] * 60 > mx) mx = lk[k] * 60; } s.app.push({ label: 'Large Leak', start: new Date(s.start.getTime() + 2000 * a), dur: 2 * (b - a), source: 'app', detail: `mean ${Math.round(mn / (b - a))} L/min, peak ${Math.round(mx)}` }); } } }
    s.app.sort((a, b) => a.start - b.start);
  }
  const pct = (arr, q) => { if (!arr.length) return NaN; const a = Float64Array.from(arr).sort(); const i = (a.length - 1) * q; const lo = Math.floor(i), hi = Math.ceil(i); return a[lo] + (a[hi] - a[lo]) * (i - lo); };
  const cat = (ss, k, sc = 1) => { const parts = ss.filter(s => s.ch[k]).map(s => s.ch[k]); const n = parts.reduce((a, p) => a + p.length, 0); const out = new Float64Array(n); let o = 0; for (const p of parts) { for (let i = 0; i < p.length; i++) out[o++] = p[i] * sc; } return out; };
  const mean = (a) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
  function nightStats(nt) {
    const ss = nt.sessions, hrs = nt.hours; const pr = cat(ss, 'Press'), leak = cat(ss, 'Leak', 60), fl = cat(ss, 'FlowLim'), sn = cat(ss, 'Snore'), rr = cat(ss, 'RespRate'), tv = cat(ss, 'TidVol', 1000), mv = cat(ss, 'MinVent'), epr = cat(ss, 'EprPress');
    const mev = ss.flatMap(s => s.machine), aev = ss.flatMap(s => s.app); const cnt = (ev, l) => ev.filter(e => e.label === l).length;
    const OA = cnt(mev, 'Obstructive Apnea'), CA = cnt(mev, 'Central Apnea'), H = cnt(mev, 'Hypopnea'), UA = cnt(mev, 'Unclassified Apnea'), AR = cnt(mev, 'Arousal');
    const appAp = aev.filter(e => /Apnea/.test(e.label)).length, appH = cnt(aev, 'Hypopnea'), appFL = cnt(aev, 'Flow Limitation Run');
    const pmax = pr.length ? Math.max(...pr) : NaN, pmin = pr.length ? Math.min(...pr) : NaN; const atMax = pr.length ? pr.filter(v => v >= pmax - 0.1).length / pr.length : NaN;
    const skip = Math.max(Math.floor(pr.length * 0.15), Math.min(900, pr.length >> 1)); const after = pr.subarray(skip); let mode = 'AutoSet';
    if (after.length) { const m = mean(after); const sd = Math.sqrt(mean(after.map(v => (v - m) ** 2))); if (sd < 0.05) mode = 'CPAP'; }
    const spv = []; const puv = []; for (const s of ss) { if (s.spo2) for (let i = 0; i < s.spo2.length; i++) { if (s.spo2[i] > 50 && s.spo2[i] <= 100) spv.push(s.spo2[i]); if (s.pulse && s.pulse[i] > 30 && s.pulse[i] < 200) puv.push(s.pulse[i]); } }
    let odi = 0; if (spv.length > 120) { let i = 60; while (i < spv.length) { let mx = 0; for (let j = i - 60; j < i; j++) if (spv[j] > mx) mx = spv[j]; if (spv[i] <= mx - 3) { odi++; i += 20; } else i++; } }
    const leaks = aev.filter(e => e.label === 'Large Leak');
    const g = (a) => a.length ? a : null;
    return {
      date: nt.date, hours: hrs, sessions: ss.length, mode, starts: ss.map(s => fmtTime(s.start)).join(', '), ends: ss.map(s => fmtTime(new Date(s.start.getTime() + s.duration * 1000))).join(', '),
      OA, CA, H, UA, arousals: AR, AHI: hrs ? (OA + CA + H + UA) / hrs : 0, CAI: hrs ? CA / hrs : 0,
      app_apneas: appAp, app_unflagged: cnt(aev, 'Apnea (unflagged by machine)'), app_hypopneas: appH, app_AHI: hrs ? (appAp + appH) / hrs : 0, app_flowlim_runs: appFL,
      press_min: pmin, press_max: pmax, press_med: pct(pr, 0.5), press_95: pct(pr, 0.95), press_at_max_pct: atMax * 100, epr: (epr.length && epr.length === pr.length) ? pct(pr.map((v, i) => v - epr[i]), 0.5) : NaN,
      leak_med: pct(leak, 0.5), leak_95: pct(leak, 0.95), leak_max: leak.length ? Math.max(...leak) : NaN, leak_pct_large: leak.length ? 100 * leak.filter(v => v > 24).length / leak.length : NaN, leak_episodes: leaks.length, leak_minutes: leaks.reduce((a, e) => a + e.dur, 0) / 60,
      flowlim_95: pct(fl, 0.95), flowlim_mean: mean(Array.from(fl)), flowlim_minutes: fl.length ? fl.filter(v => v >= 0.2).length * 2 / 60 : NaN, snore_95: pct(sn, 0.95),
      rr_med: pct(rr.filter(v => v > 0), 0.5), tv_med: pct(tv.filter(v => v > 0), 0.5), mv_med: pct(mv.filter(v => v > 0), 0.5),
      spo2_mean: spv.length ? mean(spv) : NaN, spo2_min: spv.length ? Math.min(...spv) : NaN, spo2_pct_lt90: spv.length ? 100 * spv.filter(v => v < 90).length / spv.length : NaN, spo2_minutes_lt88: spv.length ? spv.filter(v => v < 88).length / 60 : NaN,
      ODI: spv.length > 600 ? odi / (spv.length / 3600) : NaN, pulse_mean: puv.length ? mean(puv) : NaN, pulse_min: puv.length ? Math.min(...puv) : NaN,
    };
  }
  function pressureLabel(st) { const lo = st.press_min, hi = st.press_max; if (!Number.isFinite(lo) || !Number.isFinite(hi)) return ''; return st.mode === 'CPAP' ? `CPAP ${hi.toFixed(0)}` : `AutoSet ${lo.toFixed(0)} to ${hi.toFixed(0)}`; }
  function fmtTime(d) { return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
  function label(dateStr) { const [y, m, d] = dateStr.split('-').map(Number); const dt = new Date(y, m - 1, d); return dt.toLocaleDateString(undefined, { weekday: 'short', month: 'numeric', day: 'numeric' }); }

  // ---------------------------------------------------------------- synopsis (same rules as desktop)
  const fin = (v) => Number.isFinite(v);
  function wmean(ns, k) { let num = 0, den = 0; for (const n of ns) { const v = n.stats[k]; if (fin(v)) { num += v * n.hours; den += n.hours; } } return den ? num / den : NaN; }
  function amean(ns, k) { const v = ns.map(n => n.stats[k]).filter(fin); return v.length ? mean(v) : NaN; }
  function settingsRuns(ns) { const out = []; for (const n of ns) { const s = n.stats; const key = [s.mode, fin(s.press_min) ? Math.round(s.press_min) : null, fin(s.press_max) ? Math.round(s.press_max) : null].join('|'); if (out.length && out[out.length - 1].key === key) out[out.length - 1].nights.push(n); else out.push({ key, mode: s.mode, lo: fin(s.press_min) ? Math.round(s.press_min) : '?', hi: fin(s.press_max) ? Math.round(s.press_max) : '?', nights: [n] }); } return out; }
  function synopsis(nights, start, end, diag) {
    const sel = nights.filter(n => n.date >= start && n.date <= end); if (!sel.length) return '<p>No therapy nights in that range.</p>';
    const d0 = new Date(start), d1 = new Date(end); const allDays = Math.round((d1 - d0) / 86400e3) + 1; const have = new Set(sel.map(n => n.date));
    const missing = []; for (let i = 0; i < allDays; i++) { const d = new Date(d0.getTime() + i * 86400e3); const k = d.toISOString().slice(0, 10); if (!have.has(k)) missing.push(k.slice(5)); }
    const hours = sel.map(n => n.hours), totH = hours.reduce((a, b) => a + b, 0), n4 = hours.filter(h => h >= 4).length, comp = 100 * n4 / allDays;
    const ahi = wmean(sel, 'AHI'), ahiApp = wmean(sel, 'app_AHI'); const OA = sel.reduce((a, n) => a + n.stats.OA, 0), CA = sel.reduce((a, n) => a + n.stats.CA, 0), H = sel.reduce((a, n) => a + n.stats.H, 0), UA = sel.reduce((a, n) => a + n.stats.UA, 0); const tot = OA + CA + H + UA; const cai = totH ? CA / totH : 0;
    const leak95 = amean(sel, 'leak_95'), leakPct = wmean(sel, 'leak_pct_large'), leakNights = sel.filter(n => n.stats.leak_pct_large > 5); const fl95 = amean(sel, 'flowlim_95'), flMin = amean(sel, 'flowlim_minutes');
    const rr = amean(sel, 'rr_med'), tv = amean(sel, 'tv_med'), mv = amean(sel, 'mv_med'); const hasOx = sel.some(n => fin(n.stats.spo2_mean)); const unflag = sel.reduce((a, n) => a + n.stats.app_unflagged, 0);
    const H_ = []; const h2 = (t) => H_.push(`<h3>${t}</h3>`); const p = (t) => H_.push(`<p>${t}</p>`); const med = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    H_.push(`<h2>Synopsis, ${label(start)} to ${label(end)}</h2>`);
    p(`${sel.length} nights of therapy data over ${allDays} calendar nights, ${totH.toFixed(1)} hours on the machine, averaging ${(totH / sel.length).toFixed(1)} hours per night used.` + (missing.length ? ` No data for ${missing.length} night${missing.length > 1 ? 's' : ''} (${missing.slice(0, 8).join(', ')}${missing.length > 8 ? ', ...' : ''}): either the machine was not used or the card was out.` : ''));
    h2('Usage');
    if (comp >= 70 && totH / sel.length >= 6) p(`Usage is solid: ${n4} of ${allDays} nights reached 4 hours (${comp.toFixed(0)}%), and the typical night ran ${med(hours).toFixed(1)} hours. That is the pattern that produces the daytime benefit; keep it.`);
    else if (comp >= 70) p(`${n4} of ${allDays} nights reached 4 hours (${comp.toFixed(0)}%), which meets the usual compliance definition, but the typical night is only ${med(hours).toFixed(1)} hours. The treated hours look good; the hours after the mask comes off are untreated sleep, and that is where the remaining risk sits.`);
    else p(`Only ${n4} of ${allDays} nights reached 4 hours (${comp.toFixed(0)}%). Below 70% is where insurers and sleep clinics call usage non-compliant, and more to the point it means most of your sleep is untreated. The quality of the treated hours is covered below; the quantity is the problem to solve first.`);
    const splits = sel.filter(n => n.stats.sessions > 1); if (splits.length) p(`${splits.length} night${splits.length > 1 ? 's' : ''} had the mask off and back on mid-night (${splits.slice(0, 6).map(n => label(n.date)).join(', ')}). A gap is lost treatment but is normal; a gap every night usually means something is waking you (leak, pressure, dry mouth, bathroom).`);
    h2('Breathing events during therapy');
    if (ahi < 5) p(`The machine scored an AHI of ${ahi.toFixed(1)} events per hour over the range. Under 5 is the normal range on the standard severity scale (5 to 15 mild, 15 to 30 moderate, over 30 severe). While the mask is on, the apnea is controlled.`);
    else if (ahi < 15) p(`The machine scored an AHI of ${ahi.toFixed(1)} events per hour, which is residual mild sleep apnea on treatment (normal is under 5). The breakdown below says where the leftover events come from.`);
    else if (ahi < 30) p(`The machine scored an AHI of ${ahi.toFixed(1)} events per hour, moderate sleep apnea despite treatment. This needs to go to whoever manages the prescription with this report in hand.`);
    else p(`The machine scored an AHI of ${ahi.toFixed(1)} events per hour, severe sleep apnea despite treatment. Take this report to the prescriber promptly.`);
    if (diag) { const red = diag > 0 ? 100 * (1 - ahi / diag) : 0; p(`Against your diagnostic AHI of ${diag.toFixed(0)}, that is a ${red.toFixed(0)}% reduction in events while on therapy. Untreated events disturb sleep and, when they drop oxygen, stress the heart and blood vessels; removing most of them is the direct effect of the machine.`); }
    if (tot) { const mix = []; if (OA) mix.push(`${OA} obstructive apnea${OA > 1 ? 's' : ''} (${Math.round(100 * OA / tot)}%)`); if (CA) mix.push(`${CA} central (${Math.round(100 * CA / tot)}%)`); if (H) mix.push(`${H} hypopnea${H > 1 ? 's' : ''} (${Math.round(100 * H / tot)}%)`); if (UA) mix.push(`${UA} unclassified (${Math.round(100 * UA / tot)}%)`); p('Event mix: ' + mix.join(', ') + '.'); }
    if (CA && cai > 5 && CA / tot > 0.5) p(`Central apneas dominate (index ${cai.toFixed(1)}/h). Centrals are the brain not sending the signal to breathe, and when they appear on CPAP in numbers they can be caused by the pressure itself (treatment emergent central apnea). This is a conversation for the sleep physician.`);
    else if (CA) p(`The ${CA} central apnea${CA > 1 ? 's' : ''} (index ${cai.toFixed(1)}/h) ${CA > 1 ? 'are' : 'is'} below the treatment-emergent threshold (central index over 5 with centrals making up more than half of events). A few centrals after a sigh or an arousal are normal physiology. Nothing to act on unless the count climbs.`);
    p(`The app's own flow-only scoring finds ${ahiApp.toFixed(1)} reduced-breathing events per hour. That number is always higher than the machine's because it counts every 30% dip in airflow lasting 10 s, whether or not it dropped your oxygen or woke you. Read it as the ceiling on what a lab would score, not as the AHI.` + (unflag ? ` It also found ${unflag} pause${unflag > 1 ? 's' : ''} the machine did not flag.` : ''));
    h2('Pressure and settings'); const rns = settingsRuns(sel);
    if (rns.length > 1) {
      p(`Settings changed ${rns.length - 1} time${rns.length > 2 ? 's' : ''} in this range. Settings are read from the pressure trace, so the minimum on AutoSet nights can show the ramp floor rather than the set minimum. Comparing AHI across the runs:`);
      H_.push('<ul>' + rns.map(r => `<li>${label(r.nights[0].date)}${r.nights.length > 1 ? ' to ' + label(r.nights[r.nights.length - 1].date) : ''}: ${r.mode === 'AutoSet' ? 'AutoSet ' + r.lo + ' to ' + r.hi : 'CPAP fixed ' + r.hi}, AHI ${wmean(r.nights, 'AHI').toFixed(1)}, flow limitation 95th ${amean(r.nights, 'flowlim_95').toFixed(2)}, leak 95th ${amean(r.nights, 'leak_95').toFixed(0)} L/min, ${r.nights.reduce((a, n) => a + n.hours, 0).toFixed(1)} h</li>`).join('') + '</ul>');
      p('If AHI and flow limitation held steady while the ceiling came down, the lower setting is doing the job. If flow limitation rose, the airway is being held open less firmly even though the event count did not move. Single nights swing a lot, so give each setting several nights before judging it.');
    } else { const r = rns[0]; p(`Settings were constant: ${r.mode === 'AutoSet' ? 'AutoSet ' + r.lo + ' to ' + r.hi : 'fixed CPAP at ' + r.hi} cmH2O.`); }
    const auto = sel.filter(n => n.stats.mode === 'AutoSet'); if (auto.length) { const am = wmean(auto, 'press_at_max_pct'); p(`On AutoSet nights the machine spent ${am.toFixed(0)}% of the time at its ceiling, with a median pressure of ${amean(auto, 'press_med').toFixed(1)} and a 95th percentile of ${amean(auto, 'press_95').toFixed(1)} cmH2O.` + (am > 20 ? ' Above about 20% at the ceiling means the machine wanted more than it was allowed; whether that matters depends on whether events or flow limitation got through.' : ' It had room to work; the ceiling was not a constraint.')); p(`A fixed pressure near the 95th percentile (${amean(auto, 'press_95').toFixed(0)} cmH2O) is the usual starting point if you move to CPAP mode. That is a question for the prescriber, not a change to make on your own.`); }
    h2('Flow limitation');
    if (!fin(fl95)) p('No flow limitation channel in these nights.'); else if (fl95 < 0.15) p(`Flow limitation (the airway narrowing short of a scored event) is low: 95th percentile ${fl95.toFixed(2)}, ${flMin.toFixed(0)} minutes a night above 0.2. The airway is being held open cleanly.`);
    else if (fl95 < 0.35) p(`Flow limitation is moderate: 95th percentile ${fl95.toFixed(2)}, about ${flMin.toFixed(0)} minutes a night above 0.2. This does not count toward AHI but it fragments sleep. If you wake unrefreshed with a low AHI, this is usually why, and it is the number that responds to a slightly higher minimum pressure or EPR change.`);
    else p(`Flow limitation is high: 95th percentile ${fl95.toFixed(2)}, about ${flMin.toFixed(0)} minutes a night above 0.2. Even with a low AHI, that much flattened breathing means the pressure is not fully splinting the airway. This is worth raising.`);
    h2('Mask seal');
    if (!fin(leak95)) p('No leak channel in these nights.'); else if (leak95 < 24 && !leakNights.length) p(`Leak is under control: 95th percentile ${leak95.toFixed(0)} L/min against ResMed's 24 L/min line, with ${leakPct.toFixed(1)}% of therapy time in large leak. The mask fits.`);
    else p(`Leak was a problem on ${leakNights.length} night${leakNights.length > 1 ? 's' : ''} (${leakNights.map(n => `${label(n.date)} (${n.stats.leak_pct_large.toFixed(0)}% of the night)`).join(', ')}); overall 95th percentile ${leak95.toFixed(0)} L/min. During large leak the machine cannot hold pressure or score events reliably, so therapy is being lost. Leak that starts mid-night and holds steady is usually mouth opening or a shifted cushion; leak that spikes and recovers is movement.`);
    h2('Breathing mechanics');
    if (fin(rr) && fin(tv) && fin(mv)) p(`Median respiratory rate ${rr.toFixed(0)} breaths per minute, tidal volume ${tv.toFixed(0)} mL, minute ventilation ${mv.toFixed(1)} L/min. ` + ((rr >= 12 && rr <= 20 && tv >= 400 && tv <= 600 && mv >= 5 && mv <= 8) ? 'All within the usual adult ranges during sleep (about 12 to 20 breaths/min, 400 to 600 mL, 5 to 8 L/min).' : 'One or more of these sits outside the usual adult sleep ranges (about 12 to 20 breaths/min, 400 to 600 mL, 5 to 8 L/min). Machine-estimated volumes are approximate; a value a little outside the band is common.')); else p('Breathing rate and volume channels were not present for these nights.');
    h2('Oxygen');
    if (hasOx) { const ox = sel.filter(n => fin(n.stats.spo2_mean)); const ms = wmean(ox, 'spo2_mean'), mn = Math.min(...ox.map(n => n.stats.spo2_min)), lt90 = wmean(ox, 'spo2_pct_lt90'), odi = wmean(ox, 'ODI'); const lt88 = amean(ox, 'spo2_minutes_lt88');
      p(`Oximetry on ${ox.length} night${ox.length > 1 ? 's' : ''}: mean SpO2 ${ms.toFixed(1)}%, lowest reading ${mn.toFixed(0)}%, ${lt90.toFixed(1)}% of the night below 90%, 3% desaturation index ${odi.toFixed(1)} per hour.`);
      if (lt88 >= 5) p(`Time below 88% averaged ${lt88.toFixed(0)} minutes a night. Five minutes or more below 88% in a night is the threshold insurers and physicians use for nocturnal hypoxemia; this is worth raising with the prescriber.`);
      if (odi < 5 && lt90 < 1) p('That is a normal oxygen profile. The point of treating apnea is to stop the repeated oxygen dips that load the heart and blood vessels; on these nights that is happening.'); else if (odi < 15) p('A mild number of desaturations is getting through. Match them against the events in the Night view: if they line up with flagged events the pressure is slightly short; if they occur with no event, look at leak and position.'); else p('Significant desaturation is occurring despite therapy. Take this to the prescriber; it is the result that changes management.'); }
    else p('No oximeter data in this range. AHI counts the events; it does not say what they did to your oxygen. Import an O2Ring CSV and this section fills in.');
    h2('What this means for you'); const items = [`Treated hours are ${ahi < 5 ? 'well' : 'not fully'} controlled (AHI ${ahi.toFixed(1)}).`];
    if (comp < 70 || totH / sel.length < 6) items.push('The biggest gain available is more hours per night with the mask on.'); if (leakNights.length) items.push('Fix the seal on the nights leak climbed; that is lost therapy.'); if (fl95 >= 0.15) items.push('Flow limitation is the number to watch if you feel unrefreshed despite a low AHI.'); if (!hasOx) items.push('Add oximetry to see the oxygen side; it is half the picture and currently missing.'); if (rns.length > 1) items.push('Hold one setting for at least a week before judging it; single nights swing too much to compare settings on.');
    H_.push('<ul>' + items.map(i => `<li>${i}</li>`).join('') + '</ul>');
    p('<i>This synopsis is computed from the card data by fixed rules. It is a reading of the numbers, not medical advice. Use it to ask better questions.</i>');
    return H_.join('\n');
  }

  // ---------------------------------------------------------------- oximeter CSV
  function importOximeterCsv(text, nights) {
    const lines = text.split(/\r?\n/).filter(l => l.trim()); if (lines.length < 2) return 0; const hdr = lines[0].split(',').map(h => h.trim().toLowerCase());
    const col = (...keys) => hdr.findIndex(h => keys.some(k => h.includes(k))); const ti = col('time', 'date'), si = col('spo2', 'oxygen', 'o2'), pi = col('pulse', 'hr', 'heart'); if (ti < 0 || si < 0) return 0;
    const parse = (s) => { s = s.trim(); let m = s.match(/^(\d{1,2}):(\d{2}):(\d{2})(?:\s*(AM|PM))?\s+(\d{1,2})\/(\d{1,2})\/(\d{4})$/i); if (m) { let h = +m[1]; if (m[4]) { if (/pm/i.test(m[4]) && h < 12) h += 12; if (/am/i.test(m[4]) && h === 12) h = 0; } return new Date(+m[7], +m[5] - 1, +m[6], h, +m[2], +m[3]); } m = s.match(/^(\d{4})[-\/](\d{1,2})[-\/](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})/); if (m) return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]); m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})(?:\s*(AM|PM))?$/i); if (m) { let h = +m[4]; if (m[7]) { if (/pm/i.test(m[7]) && h < 12) h += 12; if (/am/i.test(m[7]) && h === 12) h = 0; } return new Date(+m[3], +m[1] - 1, +m[2], h, +m[5], +m[6]); } return null; };
    const ts = [], sp = [], pu = []; for (let i = 1; i < lines.length; i++) { const c = lines[i].split(','); const t = parse(c[ti] || ''); const v = parseFloat(c[si]); if (!t || !Number.isFinite(v)) continue; ts.push(t.getTime() / 1000); sp.push(v); pu.push(pi >= 0 ? parseFloat(c[pi]) : NaN); }
    let filled = 0;
    for (const nt of nights) for (const s of nt.sessions) {
      const a = s.start.getTime() / 1000, b = a + s.duration; const idx = []; for (let i = 0; i < ts.length; i++) if (ts[i] >= a - 60 && ts[i] <= b + 60) idx.push(i); if (idx.length < 30) continue;
      const n = Math.floor(s.duration); s.spo2 = new Float32Array(n).fill(-1); s.pulse = new Float32Array(n).fill(-1); let j = 0;
      for (let k = 0; k < n; k++) { const t = a + k; while (j + 1 < idx.length && ts[idx[j + 1]] <= t) j++; const i0 = idx[j], i1 = idx[Math.min(j + 1, idx.length - 1)]; if (t < ts[i0] - 30 || t > ts[i1] + 30) continue; const w = ts[i1] > ts[i0] ? (t - ts[i0]) / (ts[i1] - ts[i0]) : 0; const ww = Math.max(0, Math.min(1, w)); s.spo2[k] = sp[i0] + (sp[i1] - sp[i0]) * ww; s.pulse[k] = pu[i0] + (pu[i1] - pu[i0]) * ww; }
      s.hasOx = true; filled++;
    }
    return filled;
  }
  function readStr(buf) {
    try { const e = readEdf(buf, true); const days = []; for (let i = 0; i < e.nrec; i++) { const d = new Date(e.start.getTime() + i * 86400e3); days.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`); }
      const signals = {}; for (const k in e.sigs) { const sg = e.sigs[k]; const per = Math.max(1, Math.round(sg.data.length / e.nrec)); const v = []; for (let i = 0; i < e.nrec; i++) v.push(sg.data[i * per]); signals[k] = v; } return { days, signals }; } catch (err) { return null; }
  }
  function settingsSummary(nights, str) {
    const fin = Number.isFinite; const out = {};
    if (nights.length) { const mins = nights.map(n => n.stats.press_min).filter(fin), maxs = nights.map(n => n.stats.press_max).filter(fin); out.press_min = mins.length ? Math.min(...mins) : NaN; out.press_max = maxs.length ? Math.max(...maxs) : NaN; out.mode = [...new Set(nights.map(n => n.stats.mode))].sort().join('/'); const e = nights.map(n => n.stats.epr).filter(fin).sort((a, b) => a - b); out.epr = e.length ? e[e.length >> 1] : NaN; }
    out.str_found = false;
    if (str && str.signals && nights.length) {
      const find = (...pats) => Object.keys(str.signals).find(l => pats.some(p => p.test(l))); const idx = nights.map(n => str.days.indexOf(n.date)).filter(i => i >= 0);
      const val = (lab) => { if (!lab || !idx.length) return null; const v = idx.map(i => str.signals[lab][i]).filter(x => fin(x) && x >= 0); return v.length ? [Math.min(...v), Math.max(...v)] : null; };
      out.hum_on = val(find(/HumEnable/i, /Hum.*Enab/i)); out.hum = val(find(/HumLevel/i, /Humid.*Level/i, /^S\.Hum$/)); out.temp_on = val(find(/TempEnable/i, /Temp.*Enab/i)); out.temp = val(find(/S\.Temp$/, /TubeTemp/i, /Temp$/)); out.climate = val(find(/ClimateControl/i, /Climate/i));
      out.set_min = val(find(/MinPress/i)); out.set_max = val(find(/MaxPress/i)); out.set_cpap = val(find(/S\.C\.Press/, /C\.Press/, /CPAP.*Press/i)); out.str_found = true;
    }
    return out;
  }
  function settingsText(sm) {
    const rng = (v) => v ? (Math.abs(v[0] - v[1]) < 1e-6 ? `${+v[0].toFixed(1)}` : `${+v[0].toFixed(1)} to ${+v[1].toFixed(1)}`) : null; const b = (t) => `<b>${t}</b>`; const parts = []; const fin = Number.isFinite;
    if (sm.set_min && sm.set_max && sm.set_max[1] > 0 && sm.set_min[1] !== sm.set_max[1]) parts.push(`Pressure set ${b('low ' + rng(sm.set_min) + ', high ' + rng(sm.set_max) + ' cmH2O')} (AutoSet)`);
    else if (sm.set_cpap && sm.set_cpap[1] > 0 && (sm.mode || '').startsWith('CPAP')) parts.push(`Pressure set ${b(rng(sm.set_cpap) + ' cmH2O')} (CPAP)`);
    else if (fin(sm.press_min)) parts.push(sm.mode === 'CPAP' ? `Pressure ${b('fixed ' + sm.press_max.toFixed(0) + ' cmH2O')} (ramp from ${sm.press_min.toFixed(0)}, from the trace)` : `Pressure ${b('low ' + sm.press_min.toFixed(0) + ', high ' + sm.press_max.toFixed(0) + ' cmH2O')} (${sm.mode}, from the trace)`);
    if (fin(sm.epr) && sm.epr > 0) parts.push(`EPR ${b(sm.epr.toFixed(0))}`);
    if (sm.str_found) {
      if (sm.hum_on && sm.hum_on[1] === 0) parts.push(`Humidifier ${b('off')}`); else if (sm.hum) parts.push(`Humidity ${b(rng(sm.hum))}` + (sm.climate && sm.climate[1] > 0 ? ' (Climate Control auto)' : '')); else parts.push('Humidity: not in this STR file');
      if (sm.temp_on && sm.temp_on[1] === 0) parts.push(`Tube heat ${b('off')}`); else if (sm.temp) parts.push(`Tube temp ${b(rng(sm.temp) + (sm.temp[1] > 45 ? ' °F' : ' °C'))}`); else parts.push('Tube temp: not in this STR file');
    } else parts.push('Humidity and tube temp: include STR.edf from the card root in the zip to see them');
    return parts.join(' &nbsp;·&nbsp; ');
  }
  function validation(nights) { let total = 0, hit = 0; for (const nt of nights) for (const s of nt.sessions) for (const m of s.machine) { if (!/Apnea/.test(m.label)) continue; total++; if (s.app.some(e => /Apnea/.test(e.label) && e.start >= new Date(m.start.getTime() - 15000) && m.start <= new Date(e.start.getTime() + e.dur * 1000 + 5000))) hit++; } return [total, hit]; }
  return { readEdf, parseAnnotations, buildSessions, scoreSession, nightStats, synopsis, importOximeterCsv, validation, label, fmtTime, pct, readStr, settingsSummary, settingsText, pressureLabel };
})();
if (typeof module !== 'undefined') module.exports = SS;
