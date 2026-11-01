"""Independent scoring from the raw 25 Hz flow signal.

Everything here is computed from the waveform. The machine's own events are kept alongside so the two can be
compared. Where the app cannot know something it says so: obstructive vs central needs the forced oscillation
signal only the machine has; hypopnea confirmation normally needs SpO2 or EEG arousal.

Ventilation envelope
  |low-pass(flow, 1.5 Hz)| averaged over 3 s, sampled at 1 Hz. Baseline = 70th percentile of the preceding 2 min.
  ratio = envelope / baseline.

Events (app)
  Apnea           ratio < 0.70 for >= 10 s AND some 8 s block inside the run averages < 0.25
  Hypopnea        ratio < 0.70 for >= 10 s, not meeting the apnea test. Flow only: 30% reduction without a
                  desaturation or arousal check, so this over-counts relative to a lab score.
  Flow Lim Run    machine FlowLim channel >= 0.20 for >= 10 s. Marked RERA-like when a recovery breath
                  (peak inspiratory flow >= 1.5x the breath baseline) follows within 10 s.
  Large Leak      leak > 24 L/min for >= 60 s
  Periodic        autocorrelation of the breath amplitude envelope: a peak in the 30 to 90 s band with
                  correlation > 0.5 in a 5 min window is flagged as periodic (Cheyne-Stokes like) breathing.

Breath metrics (descriptive, per breath)
  Ti, Te, I:E, peak inspiratory flow, peak expiratory flow, PIF/PEF, tidal volume (integrated inspiratory flow),
  mid-inspiratory plateau ratio (mean of middle 50% of inspiration / peak).
"""
from __future__ import annotations
import datetime as dt
import numpy as np
from scipy.signal import butter, filtfilt
from .loader import Session, Event, Night

HYPO_RATIO = 0.70
APNEA_RATIO = 0.25
MIN_EVENT_S = 10
MAX_EVENT_S = 150
BASELINE_S = 120
FL_THRESH = 0.20
LEAK_LARGE = 24.0


def _lowpass(x, fs, fc=2.0):
    b, a = butter(2, fc / (fs / 2))
    return filtfilt(b, a, x)


# ----------------------------------------------------------------------------- breaths
def detect_breaths(flow: np.ndarray, fs: float) -> dict:
    if flow is None or len(flow) < fs * 30:
        return {}
    f = _lowpass(flow.astype(np.float64), fs)
    pos = f > 0.02; neg = f < -0.02
    state = 0; starts = []
    for i in range(len(f)):
        if state <= 0 and pos[i]:
            state = 1; starts.append(i)
        elif state == 1 and neg[i]:
            state = -1
    starts = np.array(starts)
    if len(starts) < 3:
        return {}
    cols = dict(t0=[], t1=[], ti=[], te=[], pif=[], pef=[], vt=[], plateau=[])
    for k in range(len(starts) - 1):
        a, b = starts[k], starts[k + 1]
        if b - a < fs * 0.6 or b - a > fs * 20:
            continue
        seg = f[a:b]
        negs = np.where(seg < 0)[0]
        ins_end = negs[0] if len(negs) else len(seg)
        insp = seg[:ins_end]
        if len(insp) < fs * 0.3:
            continue
        peak = insp.max()
        if peak < 0.03:
            continue
        m0, m1 = int(len(insp) * 0.25), int(len(insp) * 0.75)
        mid = insp[m0:m1] if m1 > m0 else insp
        cols['t0'].append(a / fs); cols['t1'].append(b / fs); cols['ti'].append(ins_end / fs)
        cols['te'].append((b - a - ins_end) / fs); cols['pif'].append(peak)
        cols['pef'].append(float(-seg[ins_end:].min()) if ins_end < len(seg) else 0.0)
        cols['vt'].append(float(insp.sum() / fs)); cols['plateau'].append(float(mid.mean() / peak))
    out = {k: np.array(v) for k, v in cols.items()}
    out['ie'] = out['ti'] / np.maximum(out['te'], 0.1)
    out['rr'] = 60.0 / np.maximum(out['t1'] - out['t0'], 0.1)
    out['pifpef'] = out['pif'] / np.maximum(out['pef'], 1e-3)
    # rolling baseline amplitude (median PIF of preceding 2 min)
    base = np.empty(len(out['t0'])); j = 0
    for i in range(len(base)):
        while out['t0'][i] - out['t0'][j] > BASELINE_S: j += 1
        w = out['pif'][j:i] if i > j else out['pif'][max(0, i - 5):i + 1]
        base[i] = np.median(w) if len(w) else out['pif'][i]
    out['baseline'] = base
    out['ratio'] = out['pif'] / np.maximum(base, 1e-3)
    return out


# ----------------------------------------------------------------------------- ventilation envelope
def ventilation_ratio(s: Session):
    """1 Hz arrays: envelope (L/s), baseline, ratio."""
    fs = s.fs
    f = np.abs(_lowpass(s.flow.astype(np.float64), fs, 1.5))
    n = int(s.duration); k = int(3 * fs)
    c = np.convolve(f, np.ones(k) / k, 'same')
    idx = np.minimum((np.arange(n) * fs).astype(int), len(c) - 1)
    x = c[idx]
    base = np.ones(n) * max(x[:BASELINE_S].mean(), 1e-4)
    # rolling 70th percentile; sliding window in blocks for speed
    for i in range(BASELINE_S, n):
        base[i] = np.percentile(x[i - BASELINE_S:i], 70)
    r = x / np.maximum(base, 1e-4)
    r[:BASELINE_S] = np.minimum(r[:BASELINE_S], 1.0)
    return x, base, r


def _runs(mask):
    out = []; i = 0; n = len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]: j += 1
            out.append((i, j)); i = j
        else:
            i += 1
    return out


def score_session(s: Session) -> list[Event]:
    ev = []
    if s.flow is None:
        return ev
    s.breaths = detect_breaths(s.flow, s.fs)
    x, base, r = ventilation_ratio(s)
    s.vent_ratio = r
    for a, b in _runs(r < HYPO_RATIO):
        if MIN_EVENT_S <= b - a <= MAX_EVENT_S:
            seg = r[a:b]
            lowest = min(seg[j:j + 8].mean() for j in range(len(seg) - 7)) if len(seg) >= 8 else seg.mean()
            if lowest < APNEA_RATIO:
                lab, det = 'Apnea', f'flow fell to {lowest * 100:.0f}% of baseline'
            else:
                lab, det = 'Hypopnea', f'flow {seg.mean() * 100:.0f}% of baseline (flow only, unconfirmed)'
            ev.append(Event(lab, s.start + dt.timedelta(seconds=int(a)), float(b - a), 'app', det))
    # type apneas from the machine's FOT classification when it flagged the same event
    for e in ev:
        if e.label == 'Apnea':
            m = [m for m in s.machine_events if 'Apnea' in m.label and
                 (e.start - dt.timedelta(seconds=15)) <= m.start <= e.end + dt.timedelta(seconds=5)]
            if m:
                e.label = m[0].label; e.detail += f'; machine scored {m[0].duration:.0f} s'
            else:
                e.label = 'Apnea (unflagged by machine)'
    # flow limitation runs from the machine channel, recovery breath from the app's breaths
    fl = s.ch.get('FlowLim')
    if fl is not None and s.breaths:
        br = s.breaths
        for a, b in _runs(fl >= FL_THRESH):
            dur = 2 * (b - a)
            if dur >= MIN_EVENT_S:
                t_end = 2 * b
                after = (br['t0'] >= t_end - 2) & (br['t0'] <= t_end + 10)
                recovery = bool(after.any() and (br['ratio'][after] >= 1.5).any())
                ev.append(Event('Flow Limitation Run', s.start + dt.timedelta(seconds=2 * a), float(dur), 'app',
                                f'FlowLim mean {fl[a:b].mean():.2f}, peak {fl[a:b].max():.2f}' + (', recovery breath (RERA-like)' if recovery else '')))
    ev.extend(leak_episodes(s))
    for st, period, corr in periodic_breathing(s):
        ev.append(Event('Periodic Breathing', s.start + dt.timedelta(seconds=st), 300.0, 'app', f'cycle {period} s, correlation {corr:.2f}'))
    ev.sort(key=lambda e: e.start)
    s.app_events = ev
    return ev


def periodic_breathing(s: Session, win_s=300, step_s=60):
    br = s.breaths
    if not br or len(br['t0']) < 50:
        return []
    n = int(s.duration); env = np.zeros(n)
    for a, b, p in zip(br['t0'], br['t1'], br['pif']):
        env[int(a):min(n, int(np.ceil(b)))] = p
    out = []
    for st in range(0, n - win_s, step_s):
        x = env[st:st + win_s]
        if x.std() < 1e-3 or (x == 0).mean() > 0.3:
            continue
        x = x - x.mean()
        x = x - np.convolve(x, np.ones(31) / 31, 'same')      # remove slow drift so only true cycles correlate
        ac = np.correlate(x, x, 'full')[win_s - 1:]
        ac /= ac[0] + 1e-9
        lo, hi = 30, 90
        k = lo + int(np.argmax(ac[lo:hi]))
        if lo < k < hi - 1 and ac[k] > 0.5 and ac[k] > ac[k - 1] and ac[k] > ac[k + 1] and ac[k] > ac[lo:hi].mean() + 0.2:
            out.append((st, k, float(ac[k])))
    # merge overlapping windows
    merged = []
    for w in out:
        if merged and w[0] - merged[-1][0] <= win_s:
            continue
        merged.append(w)
    return merged


def leak_episodes(s: Session, thresh=LEAK_LARGE, min_s=60):
    leak = s.ch.get('Leak')
    if leak is None: return []
    lm = leak * 60.0
    out = []
    for i, j in _runs(lm > thresh):
        if (j - i) * 2 >= min_s:
            out.append(Event('Large Leak', s.start + dt.timedelta(seconds=2 * i), float(2 * (j - i)), 'app',
                             f'mean {lm[i:j].mean():.0f} L/min, peak {lm[i:j].max():.0f}'))
    return out


# ----------------------------------------------------------------------------- night statistics
def validation_summary(nights):
    """How many machine apneas the app's own detector reproduced on the loaded card."""
    total = hit = 0
    for nt in nights:
        for s in nt.sessions:
            for m in s.machine_events:
                if 'Apnea' not in m.label: continue
                total += 1
                if any('Apnea' in e.label and (e.start - dt.timedelta(seconds=15)) <= m.start <= e.end + dt.timedelta(seconds=5) for e in s.app_events): hit += 1
    return total, hit


def night_stats(nt: Night) -> dict:
    ss = nt.sessions; hrs = nt.hours
    def cat(key, scale=1.0):
        arr = [s.ch[key] for s in ss if key in s.ch]
        return np.concatenate(arr) * scale if arr else np.array([])
    pr = cat('Press'); leak = cat('Leak', 60.0); fl = cat('FlowLim'); sn = cat('Snore')
    rr = cat('RespRate'); tv = cat('TidVol', 1000.0); mv = cat('MinVent'); epr = cat('EprPress')
    mev = [e for s in ss for e in s.machine_events]; aev = [e for s in ss for e in s.app_events]
    def cnt(evs, lab): return sum(1 for e in evs if e.label == lab)
    OA, CA, H, AR, UA = (cnt(mev, k) for k in ('Obstructive Apnea', 'Central Apnea', 'Hypopnea', 'Arousal', 'Unclassified Apnea'))
    app_ap = sum(1 for e in aev if 'Apnea' in e.label); app_hy = cnt(aev, 'Hypopnea')
    app_fl = cnt(aev, 'Flow Limitation Run'); app_rera = sum(1 for e in aev if e.label == 'Flow Limitation Run' and 'RERA' in e.detail)
    app_unflag = cnt(aev, 'Apnea (unflagged by machine)')
    pmax = float(pr.max()) if len(pr) else np.nan; pmin = float(pr.min()) if len(pr) else np.nan
    at_max = float((pr >= pmax - 0.1).mean()) if len(pr) else np.nan
    after_ramp = pr[max(int(len(pr) * 0.15), min(900, len(pr) // 2)):] if len(pr) > 20 else pr
    mode = 'CPAP' if len(after_ramp) and after_ramp.std() < 0.05 else 'AutoSet'
    sp = np.concatenate([s.spo2 for s in ss if s.spo2 is not None]) if any(s.spo2 is not None for s in ss) else np.array([])
    spv = sp[(sp > 50) & (sp <= 100)]
    pu = np.concatenate([s.pulse for s in ss if s.pulse is not None]) if any(s.pulse is not None for s in ss) else np.array([])
    puv = pu[(pu > 30) & (pu < 200)]
    odi = 0
    if len(spv) > 120:
        i = 60
        while i < len(spv):
            if spv[i] <= spv[i - 60:i].max() - 3: odi += 1; i += 20
            else: i += 1
    breaths = [s.breaths for s in ss if s.breaths]
    def bcat(k): return np.concatenate([b[k] for b in breaths]) if breaths else np.array([])
    plateau, ie, pifpef, ti = bcat('plateau'), bcat('ie'), bcat('pifpef'), bcat('ti')
    leaks = [e for e in aev if e.label == 'Large Leak']; pb = cnt(aev, 'Periodic Breathing')
    fl_minutes = float((fl >= FL_THRESH).sum() * 2 / 60) if len(fl) else np.nan
    d = dict(
        date=nt.date, label=nt.label, sessions=len(ss), hours=hrs, mode=mode,
        starts=', '.join(s.start.strftime('%H:%M') for s in ss), ends=', '.join(s.end.strftime('%H:%M') for s in ss),
        OA=OA, CA=CA, H=H, UA=UA, arousals=AR, AHI=(OA + CA + H + UA) / hrs if hrs else 0, CAI=CA / hrs if hrs else 0,
        app_apneas=app_ap, app_unflagged=app_unflag, app_hypopneas=app_hy, app_AHI=(app_ap + app_hy) / hrs if hrs else 0,
        app_flowlim_runs=app_fl, app_RERA_like=app_rera, app_RDI=(app_ap + app_hy + app_rera) / hrs if hrs else 0,
        press_min=pmin, press_max=pmax, press_med=float(np.median(pr)) if len(pr) else np.nan,
        press_95=float(np.percentile(pr, 95)) if len(pr) else np.nan, press_at_max_pct=at_max * 100,
        epr=float(np.median(pr - epr)) if len(epr) and len(pr) == len(epr) else np.nan,
        leak_med=float(np.median(leak)) if len(leak) else np.nan, leak_95=float(np.percentile(leak, 95)) if len(leak) else np.nan,
        leak_max=float(leak.max()) if len(leak) else np.nan, leak_pct_large=float((leak > LEAK_LARGE).mean() * 100) if len(leak) else np.nan,
        leak_episodes=len(leaks), leak_minutes=sum(e.duration for e in leaks) / 60,
        flowlim_95=float(np.percentile(fl, 95)) if len(fl) else np.nan, flowlim_mean=float(fl.mean()) if len(fl) else np.nan,
        flowlim_minutes=fl_minutes, snore_95=float(np.percentile(sn, 95)) if len(sn) else np.nan,
        rr_med=float(np.median(rr[rr > 0])) if len(rr) and (rr > 0).any() else np.nan,
        tv_med=float(np.median(tv[tv > 0])) if len(tv) and (tv > 0).any() else np.nan,
        mv_med=float(np.median(mv[mv > 0])) if len(mv) and (mv > 0).any() else np.nan,
        breaths=int(len(ie)), ti_med=float(np.median(ti)) if len(ti) else np.nan, ie_med=float(np.median(ie)) if len(ie) else np.nan,
        pifpef_med=float(np.median(pifpef)) if len(pifpef) else np.nan, plateau_med=float(np.median(plateau)) if len(plateau) else np.nan,
        periodic_windows=pb,
        spo2_mean=float(spv.mean()) if len(spv) else np.nan, spo2_min=float(spv.min()) if len(spv) else np.nan,
        spo2_pct_lt90=float((spv < 90).mean() * 100) if len(spv) else np.nan, spo2_pct_lt88=float((spv < 88).mean() * 100) if len(spv) else np.nan, ODI=odi / (len(spv) / 3600) if len(spv) > 600 else np.nan, spo2_minutes_lt88=float((spv < 88).sum() / 60) if len(spv) else np.nan,
        pulse_mean=float(puv.mean()) if len(puv) else np.nan, pulse_min=float(puv.min()) if len(puv) else np.nan, pulse_max=float(puv.max()) if len(puv) else np.nan,
    )
    d['setting'] = pressure_label(d)
    nt.stats = d
    return d


STAT_COLUMNS = [
    ('label', 'Night', ''), ('hours', 'Hours', '{:.2f}'), ('sessions', 'Sess', '{}'), ('mode', 'Mode', ''), ('setting', 'Pressure setting', ''),
    ('AHI', 'AHI machine', '{:.2f}'), ('OA', 'OA', '{}'), ('CA', 'CA', '{}'), ('H', 'H', '{}'), ('arousals', 'Arousal', '{}'),
    ('app_AHI', 'AHI app', '{:.2f}'), ('app_unflagged', 'Unflagged AP', '{}'), ('app_RDI', 'RDI app', '{:.2f}'), ('app_flowlim_runs', 'FL runs', '{}'), ('app_RERA_like', 'RERA-like', '{}'),
    ('press_min', 'P min', '{:.1f}'), ('press_med', 'P med', '{:.1f}'), ('press_95', 'P 95%', '{:.1f}'), ('press_max', 'P max', '{:.1f}'),
    ('press_at_max_pct', '% at max', '{:.0f}'), ('epr', 'EPR', '{:.0f}'),
    ('leak_med', 'Leak med', '{:.1f}'), ('leak_95', 'Leak 95%', '{:.1f}'), ('leak_pct_large', '% large leak', '{:.1f}'), ('leak_minutes', 'Leak min', '{:.0f}'),
    ('flowlim_95', 'FlowLim 95%', '{:.2f}'), ('flowlim_minutes', 'FL minutes', '{:.0f}'), ('snore_95', 'Snore 95%', '{:.2f}'),
    ('rr_med', 'RR', '{:.1f}'), ('tv_med', 'Vt mL', '{:.0f}'), ('mv_med', 'MV', '{:.1f}'), ('ti_med', 'Ti s', '{:.2f}'), ('ie_med', 'I:E', '{:.2f}'), ('pifpef_med', 'PIF/PEF', '{:.2f}'),
    ('periodic_windows', 'Periodic', '{}'),
    ('spo2_mean', 'SpO2 mean', '{:.1f}'), ('spo2_min', 'SpO2 min', '{:.0f}'), ('spo2_pct_lt90', '% <90', '{:.1f}'), ('spo2_pct_lt88', '% <88', '{:.1f}'), ('ODI', 'ODI', '{:.1f}'),
    ('pulse_mean', 'Pulse', '{:.0f}'),
]
_FMT = {k: f for k, _, f in STAT_COLUMNS}


def fmt(key, val):
    if val is None or (isinstance(val, float) and np.isnan(val)): return ''
    try: return (_FMT.get(key) or '{}').format(val)
    except Exception: return str(val)


# ----------------------------------------------------------------------------- settings highlight
import re as _re
def settings_summary(nights, str_data=None):
    """Hi/low pressure, mode, EPR, and humidifier/tube settings for a set of nights.
    Pressure comes from the trace (verified). Humidity and temperature come from STR.edf when loaded; the STR signal names
    are matched loosely (HumLevel, Temp, ClimateControl, HumEnable, TempEnable) because they vary by firmware."""
    out = {}
    if nights:
        pmin = min(n.stats['press_min'] for n in nights if np.isfinite(n.stats.get('press_min', np.nan)) or False) if any(np.isfinite(n.stats.get('press_min', np.nan)) for n in nights) else np.nan
        pmax = max(n.stats['press_max'] for n in nights if np.isfinite(n.stats.get('press_max', np.nan))) if any(np.isfinite(n.stats.get('press_max', np.nan)) for n in nights) else np.nan
        modes = {n.stats['mode'] for n in nights}
        out.update(press_min=pmin, press_max=pmax, mode='/'.join(sorted(modes)), epr=float(np.nanmedian([n.stats.get('epr', np.nan) for n in nights])) if nights else np.nan,
                   press_95=float(np.nanmean([n.stats.get('press_95', np.nan) for n in nights])))
    if str_data and 'signals' in str_data and nights:
        sig = str_data['signals']; days = str_data['days']
        def find(*pats):
            for lab in sig:
                if any(_re.search(p, lab, _re.I) for p in pats): return lab
            return None
        idx = [days.index(n.date) for n in nights if n.date in days]
        def val(lab):
            if not lab or not idx: return None
            v = [sig[lab][i] for i in idx if i < len(sig[lab])]
            v = [x for x in v if np.isfinite(x) and x >= 0]
            return (min(v), max(v)) if v else None
        hum_on = val(find(r'HumEnable', r'Hum.*Enab')); hum = val(find(r'HumLevel', r'Humid.*Level', r'^S\.Hum$'))
        temp_on = val(find(r'TempEnable', r'Temp.*Enab')); temp = val(find(r'S\.Temp$', r'TubeTemp', r'Temp$'))
        cc = val(find(r'ClimateControl', r'Climate')); smin = val(find(r'MinPress')); smax = val(find(r'MaxPress')); cpap = val(find(r'S\.C\.Press', r'C\.Press', r'CPAP.*Press'))
        out.update(hum=hum, hum_on=hum_on, temp=temp, temp_on=temp_on, climate=cc, set_min=smin, set_max=smax, set_cpap=cpap, str_found=True)
    else:
        out['str_found'] = False
    return out


def pressure_label(stats):
    """Short pressure setting text for a night, from the trace: 'AutoSet 4 to 12' or 'CPAP 9'."""
    lo, hi = stats.get('press_min', np.nan), stats.get('press_max', np.nan)
    if not (np.isfinite(lo) and np.isfinite(hi)): return ''
    return f"CPAP {hi:.0f}" if stats.get('mode') == 'CPAP' else f"AutoSet {lo:.0f} to {hi:.0f}"


def settings_text(sm, html=True):
    def rng(v, fmt='{:g}'):
        if v is None: return None
        a, b = v; return fmt.format(a) if abs(a - b) < 1e-6 else f"{fmt.format(a)} to {fmt.format(b)}"
    b = (lambda t: f'<b>{t}</b>') if html else (lambda t: t)
    parts = []
    if sm.get('set_min') and sm.get('set_max') and sm['set_max'][1] > 0 and (sm.get('set_min')[1] != sm.get('set_max')[1]):
        parts.append(f"Pressure set {b('low ' + rng(sm['set_min']) + ', high ' + rng(sm['set_max']) + ' cmH2O')} (AutoSet)")
    elif sm.get('set_cpap') and sm['set_cpap'][1] > 0 and sm.get('mode', '').startswith('CPAP'):
        parts.append(f"Pressure set {b(rng(sm['set_cpap']) + ' cmH2O')} (CPAP)")
    elif np.isfinite(sm.get('press_min', np.nan)):
        if sm.get('mode') == 'CPAP': parts.append('Pressure ' + b(f"fixed {sm['press_max']:.0f} cmH2O") + f" (ramp from {sm['press_min']:.0f}, from the trace)")
        else: parts.append('Pressure ' + b(f"low {sm['press_min']:.0f}, high {sm['press_max']:.0f} cmH2O") + f" ({sm.get('mode', '')}, from the trace)")
    if np.isfinite(sm.get('epr', np.nan)) and sm['epr'] > 0: parts.append(f"EPR {b(f'{sm["epr"]:.0f}')}")
    if sm.get('str_found'):
        if sm.get('hum_on') and sm['hum_on'][1] == 0: parts.append(f"Humidifier {b('off')}")
        elif sm.get('hum') is not None: parts.append(f"Humidity {b(rng(sm['hum']))}" + (' (Climate Control auto)' if sm.get('climate') and sm['climate'][1] > 0 else ''))
        else: parts.append('Humidity: not in this STR file')
        if sm.get('temp_on') and sm['temp_on'][1] == 0: parts.append(f"Tube heat {b('off')}")
        elif sm.get('temp') is not None:
            lo, hi = sm['temp']; unit = '°F' if hi > 45 else '°C'
            parts.append(f"Tube temp {b(rng(sm['temp']) + ' ' + unit)}")
        else: parts.append('Tube temp: not in this STR file')
    else:
        parts.append('Humidity and tube temp: open the card root (STR.edf) to see them')
    return '   ·   '.join(parts)
