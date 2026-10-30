"""Plain English synopsis over a date range. Rule based, deterministic, works offline.

Thresholds used (stated in the text so the reader can check them):
  AHI < 5 controlled, 5 to 15 mild residual, > 15 poorly controlled (AASM severity bands)
  Compliance: >= 4 h on >= 70% of nights (the Medicare/insurer definition)
  Leak: 95th percentile < 24 L/min (ResMed large leak line)
  Central apnea index > 5 with CA > 50% of events: raise with the prescriber
  SpO2: time below 88% over 5 minutes in a night is the threshold insurers use for nocturnal hypoxemia
  ODI (3%) < 5 normal, 5 to 15 mild, > 15 significant
"""
from __future__ import annotations
import datetime as dt
import numpy as np


def _mean(nights, key):
    v = np.array([n.stats.get(key, np.nan) for n in nights], dtype=float)
    return float(np.nanmean(v)) if np.isfinite(v).any() else np.nan


def _wmean(nights, key):
    v = np.array([n.stats.get(key, np.nan) for n in nights], dtype=float); h = np.array([n.hours for n in nights])
    m = np.isfinite(v)
    return float((v[m] * h[m]).sum() / h[m].sum()) if m.any() and h[m].sum() else np.nan


def _settings_runs(nights):
    """Group consecutive nights with the same (mode, min, max) so settings changes can be described."""
    runs = []
    for n in nights:
        s = n.stats; key = (s['mode'], None if not np.isfinite(s['press_min']) else round(s['press_min']), None if not np.isfinite(s['press_max']) else round(s['press_max']))
        if runs and runs[-1]['key'] == key:
            runs[-1]['nights'].append(n)
        else:
            runs.append({'key': key, 'nights': [n]})
    return runs


def generate(nights, start: dt.date, end: dt.date, diagnostic_ahi: float | None = None) -> str:
    sel = [n for n in nights if start <= n.date <= end]
    if not sel:
        return '<p>No therapy nights in that range.</p>'
    # calendar nights in range that have no data
    all_days = (end - start).days + 1
    have = {n.date for n in sel}
    missing = [start + dt.timedelta(d) for d in range(all_days) if (start + dt.timedelta(d)) not in have]
    hours = np.array([n.hours for n in sel]); tot_h = hours.sum()
    nights_4h = int((hours >= 4).sum())
    compliance_pct = 100 * nights_4h / all_days
    ahi = _wmean(sel, 'AHI'); ahi_app = _wmean(sel, 'app_AHI'); rdi = _wmean(sel, 'app_RDI')
    OA = sum(n.stats['OA'] for n in sel); CA = sum(n.stats['CA'] for n in sel); H = sum(n.stats['H'] for n in sel); UA = sum(n.stats['UA'] for n in sel)
    tot_ev = OA + CA + H + UA
    cai = CA / tot_h if tot_h else 0
    leak95 = _mean(sel, 'leak_95'); leak_pct = _wmean(sel, 'leak_pct_large'); leak_nights = [n for n in sel if n.stats['leak_pct_large'] > 5]
    fl95 = _mean(sel, 'flowlim_95'); fl_min = _mean(sel, 'flowlim_minutes')
    p95 = _mean(sel, 'press_95'); pmed = _mean(sel, 'press_med'); at_max = _mean(sel, 'press_at_max_pct')
    has_ox = any(np.isfinite(n.stats.get('spo2_mean', np.nan)) for n in sel)
    unflag = sum(n.stats['app_unflagged'] for n in sel); periodic = sum(n.stats['periodic_windows'] for n in sel)
    rr = _mean(sel, 'rr_med'); tv = _mean(sel, 'tv_med'); mv = _mean(sel, 'mv_med')
    rng = f"{start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"
    H_ = []  # html parts
    def h2(t): H_.append(f'<h3>{t}</h3>')
    def p(t): H_.append(f'<p>{t}</p>')

    H_.append(f'<h2>Synopsis, {rng}</h2>')
    p(f'{len(sel)} nights of therapy data over {all_days} calendar nights, {tot_h:.1f} hours on the machine, averaging {tot_h / len(sel):.1f} hours per night used.'
      + (f' No data for {len(missing)} night{"s" if len(missing) > 1 else ""} ({", ".join(d.strftime("%m/%d") for d in missing[:8])}{", ..." if len(missing) > 8 else ""}): either the machine was not used or the card was out.' if missing else ''))

    # ---- usage
    h2('Usage')
    if compliance_pct >= 70 and tot_h / len(sel) >= 6:
        p(f'Usage is solid: {nights_4h} of {all_days} nights reached 4 hours ({compliance_pct:.0f}%), and the typical night ran {np.median(hours):.1f} hours. That is the pattern that produces the daytime benefit; keep it.')
    elif compliance_pct >= 70:
        p(f'{nights_4h} of {all_days} nights reached 4 hours ({compliance_pct:.0f}%), which meets the usual compliance definition, but the typical night is only {np.median(hours):.1f} hours. The treated hours look good; the hours after the mask comes off are untreated sleep, and that is where the remaining risk sits. The benefit you get tracks hours per night more than anything else in this report.')
    else:
        p(f'Only {nights_4h} of {all_days} nights reached 4 hours ({compliance_pct:.0f}%). Below 70% is where insurers and sleep clinics call usage non-compliant, and more to the point it means most of your sleep is untreated. The quality of the treated hours is fine (see below); the quantity is the problem to solve first.')
    splits = [n for n in sel if n.stats['sessions'] > 1]
    if splits:
        p(f'{len(splits)} night{"s" if len(splits) > 1 else ""} had the mask off and back on mid-night ({", ".join(n.label for n in splits[:6])}). A gap is lost treatment but is normal; a gap every night usually means something is waking you (leak, pressure, dry mouth, bathroom). Worth noting what it was.')

    # ---- breathing events
    h2('Breathing events during therapy')
    if ahi < 5:
        p(f'The machine scored an AHI of {ahi:.1f} events per hour over the range. Under 5 is the normal range on the standard severity scale (5 to 15 mild, 15 to 30 moderate, over 30 severe). While the mask is on, the apnea is controlled.')
    elif ahi < 15:
        p(f'The machine scored an AHI of {ahi:.1f} events per hour, which is residual mild sleep apnea on treatment (normal is under 5; 15 to 30 moderate, over 30 severe). The breakdown below says where the leftover events come from and whether pressure or leak is the likely reason.')
    elif ahi < 30:
        p(f'The machine scored an AHI of {ahi:.1f} events per hour, moderate sleep apnea despite treatment. This needs to go to whoever manages the prescription with this report in hand.')
    else:
        p(f'The machine scored an AHI of {ahi:.1f} events per hour, severe sleep apnea despite treatment. Take this report to the prescriber promptly.')
    if diagnostic_ahi:
        red = 100 * (1 - ahi / diagnostic_ahi) if diagnostic_ahi > 0 else 0
        p(f'Against your diagnostic AHI of {diagnostic_ahi:.0f}, that is a {red:.0f}% reduction in events while on therapy. Untreated events disturb sleep and, when they drop oxygen, stress the heart and blood vessels; removing most of them is the direct effect of the machine.')
    if tot_ev:
        mix = []
        if OA: mix.append(f'{OA} obstructive apnea{"s" if OA > 1 else ""} ({100 * OA / tot_ev:.0f}%)')
        if CA: mix.append(f'{CA} central ({100 * CA / tot_ev:.0f}%)')
        if H: mix.append(f'{H} hypopnea{"s" if H > 1 else ""} ({100 * H / tot_ev:.0f}%)')
        if UA: mix.append(f'{UA} unclassified apnea{"s" if UA > 1 else ""} ({100 * UA / tot_ev:.0f}%)')
        p('Event mix: ' + ', '.join(mix) + '.')
    if CA and cai > 5 and CA / tot_ev > 0.5:
        p(f'Central apneas dominate (index {cai:.1f}/h). Centrals are the brain not sending the signal to breathe, and when they appear on CPAP in numbers they can be caused by the pressure itself (treatment emergent central apnea). This is a conversation for the sleep physician; it is the one pattern in this report that can mean the machine type is wrong.')
    elif CA:
        p(f'The {CA} central apnea{"s" if CA > 1 else ""} (index {cai:.1f}/h) {"are" if CA > 1 else "is"} below the treatment-emergent threshold (central index over 5 with centrals making up more than half of events). A few centrals after a sigh or an arousal are normal physiology; look at them in the Night tab to see whether yours follow that pattern. Nothing to act on unless the count climbs.')
    if periodic:
        p(f'The periodic breathing detector flagged {periodic} five-minute window{"s" if periodic > 1 else ""} with a 30 to 90 second waxing and waning cycle. A handful across a week can be noise; a cluster on one night, or several every night, is a Cheyne-Stokes pattern that should be looked at in the Night tab and raised with the prescriber.')
    else:
        p('The periodic breathing detector found no 30 to 90 second waxing and waning cycle in any five-minute window. That pattern (Cheyne-Stokes) is associated with heart failure; the detector is a screen, not a diagnosis, but a clean result is reassuring.')
    p(f'The app\'s own flow-only scoring finds {ahi_app:.1f} reduced-breathing events per hour (RDI {rdi:.1f} when flow limitation runs with a recovery breath are included). That number is always higher than the machine\'s because it counts every 30% dip in airflow lasting 10 s, whether or not it dropped your oxygen or woke you. Read it as the ceiling on what a lab would score, not as the AHI.'
      + (f' It also found {unflag} pause{"s" if unflag > 1 else ""} the machine did not flag; look at them in the Night tab to judge whether they are real.' if unflag else ''))

    # ---- pressure
    h2('Pressure and settings')
    runs = _settings_runs(sel)
    if len(runs) > 1:
        desc = '; '.join(f"{r['nights'][0].label}{' to ' + r['nights'][-1].label if len(r['nights']) > 1 else ''}: {r['key'][0]} {r['key'][1]} to {r['key'][2]}" if r['key'][0] == 'AutoSet' else f"{r['nights'][0].label}{' to ' + r['nights'][-1].label if len(r['nights']) > 1 else ''}: CPAP fixed {r['key'][2]}" for r in runs)
        p(f'Settings changed {len(runs) - 1} time{"s" if len(runs) > 2 else ""} in this range ({desc}). Settings read from the pressure trace, so the min on AutoSet nights can show the ramp floor rather than the set minimum. Comparing AHI across the runs:')
        H_.append('<ul>' + ''.join(f"<li>{r['nights'][0].label}{' to ' + r['nights'][-1].label if len(r['nights']) > 1 else ''}: AHI {_wmean(r['nights'], 'AHI'):.1f}, flow limitation 95th {_mean(r['nights'], 'flowlim_95'):.2f}, leak 95th {_mean(r['nights'], 'leak_95'):.0f} L/min, {sum(n.hours for n in r['nights']):.1f} h</li>" for r in runs) + '</ul>')
        p('If AHI and flow limitation held steady while the ceiling came down, the lower setting is doing the job. If flow limitation rose, the airway is being held open less firmly even though the event count did not move; that shows up as lighter sleep before it shows up as AHI. Single nights swing a lot, so give each setting several nights before judging it.')
    else:
        r = runs[0]['key']
        p(f"Settings were constant: {'AutoSet ' + str(r[1]) + ' to ' + str(r[2]) if r[0] == 'AutoSet' else 'fixed CPAP at ' + str(r[2])} cmH2O.")
    if any(n.stats['mode'] == 'AutoSet' for n in sel):
        auto = [n for n in sel if n.stats['mode'] == 'AutoSet']
        am = _wmean(auto, 'press_at_max_pct')
        p(f'On AutoSet nights the machine spent {am:.0f}% of the time at its ceiling, with a median pressure of {_mean(auto, "press_med"):.1f} and a 95th percentile of {_mean(auto, "press_95"):.1f} cmH2O.'
          + (' Above about 20% at the ceiling means the machine wanted more than it was allowed; whether that matters depends on whether events or flow limitation got through, which the sections above answer.' if am > 20 else ' It had room to work; the ceiling was not a constraint.'))
        p(f'A fixed pressure near the 95th percentile ({_mean(auto, "press_95"):.0f} cmH2O) is the usual starting point if you move to CPAP mode. That is a question for the prescriber, not a change to make on your own.')

    # ---- flow limitation
    h2('Flow limitation')
    if not np.isfinite(fl95):
        p('No flow limitation channel in these nights.')
    elif fl95 < 0.15:
        p(f'Flow limitation (the airway narrowing short of a scored event) is low: 95th percentile {fl95:.2f}, {fl_min:.0f} minutes a night above 0.2. The airway is being held open cleanly.')
    elif fl95 < 0.35:
        p(f'Flow limitation is moderate: 95th percentile {fl95:.2f}, about {fl_min:.0f} minutes a night above 0.2. This does not count toward AHI but it fragments sleep: each run of flattened breaths tends to end in a small arousal. If you wake unrefreshed with a low AHI, this is usually why, and it is the number that responds to a slightly higher minimum pressure or EPR change.')
    else:
        p(f'Flow limitation is high: 95th percentile {fl95:.2f}, about {fl_min:.0f} minutes a night above 0.2. Even with a low AHI, that much flattened breathing means the pressure is not fully splinting the airway. Expect fragmented sleep. This is worth raising.')

    # ---- leak
    h2('Mask seal')
    if not np.isfinite(leak95):
        p('No leak channel in these nights.')
    elif leak95 < 24 and not leak_nights:
        p(f'Leak is under control: 95th percentile {leak95:.0f} L/min against ResMed\'s 24 L/min line, with {leak_pct:.1f}% of therapy time in large leak. The mask fits.')
    else:
        p(f'Leak was a problem on {len(leak_nights)} night{"s" if len(leak_nights) > 1 else ""} ({", ".join(f"{n.label} ({n.stats["leak_pct_large"]:.0f}% of the night)" for n in leak_nights)}); overall 95th percentile {leak95:.0f} L/min. During large leak the machine cannot hold pressure or score events reliably, so therapy is being lost, not just data. Check the tidal volume panel against the leak panel on those nights: if volume falls while leak is high, the leak is costing you ventilation. Leak that starts mid-night and holds steady is usually mouth opening or a shifted cushion; leak that spikes and recovers is movement.')

    # ---- breathing mechanics
    h2('Breathing mechanics')
    if np.isfinite(rr) and np.isfinite(tv) and np.isfinite(mv):
        p(f'Median respiratory rate {rr:.0f} breaths per minute, tidal volume {tv:.0f} mL, minute ventilation {mv:.1f} L/min. '
          + ('All within the usual adult ranges during sleep (about 12 to 20 breaths/min, 400 to 600 mL, 5 to 8 L/min).' if 12 <= rr <= 20 and 400 <= tv <= 600 and 5 <= mv <= 8 else 'One or more of these sits outside the usual adult sleep ranges (about 12 to 20 breaths/min, 400 to 600 mL, 5 to 8 L/min). Machine-estimated volumes are approximate; a value a little outside the band is common. Minute ventilation well above 8 can mean over-ventilation, well below 5 suggests shallow breathing; worth mentioning to the prescriber if it persists.'))
    else:
        p('Breathing rate and volume channels were not present for these nights.')

    # ---- oximetry
    h2('Oxygen')
    if has_ox:
        ox = [n for n in sel if np.isfinite(n.stats.get('spo2_mean', np.nan))]
        mean_sp = _wmean(ox, 'spo2_mean'); min_sp = min(n.stats['spo2_min'] for n in ox); lt90 = _wmean(ox, 'spo2_pct_lt90'); odi = _wmean(ox, 'ODI')
        min_lt88 = sum(n.stats['spo2_pct_lt88'] * n.hours * 60 / 100 for n in ox if 'spo2_pct_lt88' in n.stats) if all('spo2_pct_lt88' in n.stats for n in ox) else None
        p(f'Oximetry on {len(ox)} night{"s" if len(ox) > 1 else ""}: mean SpO2 {mean_sp:.1f}%, lowest reading {min_sp:.0f}%, {lt90:.1f}% of the night below 90%, 3% desaturation index {odi:.1f} per hour.')
        lt88_min = sum(n.stats.get('spo2_minutes_lt88', 0) or 0 for n in ox) / len(ox)
        if lt88_min >= 5:
            p(f'Time below 88% averaged {lt88_min:.0f} minutes a night. Five minutes or more below 88% in a night is the threshold insurers and physicians use for nocturnal hypoxemia; this is worth raising with the prescriber.')
        if odi < 5 and lt90 < 1:
            p('That is a normal oxygen profile. The point of treating apnea is to stop the repeated oxygen dips that load the heart and blood vessels; on these nights that is happening. This is the number that most directly says the therapy is protecting you.')
        elif odi < 15:
            p('A mild number of desaturations is getting through. Match them against the events in the Night tab: if they line up with flagged events the pressure is slightly short; if they occur with no event, look at leak and position.')
        else:
            p('Significant desaturation is occurring despite therapy. Take this to the prescriber; it is the result that changes management.')
        p(f'Pulse averaged {_wmean(ox, "pulse_mean"):.0f} bpm overnight. A steady overnight pulse with no sawtooth pattern is the heart not being repeatedly startled by events.')
    else:
        p('No oximeter data in this range. AHI counts the events; it does not say what they did to your oxygen. Attach the ring and this section fills in with mean and minimum SpO2, time under 90%, and the desaturation index, which together are the clearest measure of whether the therapy is protecting your heart and brain.')

    # ---- apple health
    ah = [n for n in sel if getattr(n, 'apple', None)]
    if ah:
        h2('Apple Watch')
        asleep = np.array([n.apple.get('asleep_h', np.nan) for n in ah]); deep = np.array([n.apple.get('deep_min', np.nan) for n in ah]); rem = np.array([n.apple.get('rem_min', np.nan) for n in ah])
        awake = np.array([n.apple.get('awake_min', np.nan) for n in ah]); hr = np.array([n.apple.get('hr_mean', np.nan) for n in ah]); hrv = np.array([n.apple.get('hrv', np.nan) for n in ah]); wsp = np.array([n.apple.get('spo2_min', np.nan) for n in ah])
        p(f'Watch data on {len(ah)} night{"s" if len(ah) > 1 else ""}: asleep {np.nanmean(asleep):.1f} h, deep {np.nanmean(deep):.0f} min, REM {np.nanmean(rem):.0f} min, awake {np.nanmean(awake):.0f} min, overnight heart rate {np.nanmean(hr):.0f} bpm'
          + (f', HRV {np.nanmean(hrv):.0f} ms' if np.isfinite(hrv).any() else '') + (f', Watch SpO2 minimum {np.nanmin(wsp):.0f}%' if np.isfinite(wsp).any() else '') + '.')
        on = [n for n in ah if np.isfinite(n.apple.get('asleep_h', np.nan))]
        if on:
            cov = [100 * min(n.hours, n.apple['asleep_h']) / n.apple['asleep_h'] for n in on if n.apple['asleep_h'] > 0]
            if cov: p(f'The machine covered about {np.mean(cov):.0f}% of the sleep the Watch recorded. The gap is untreated sleep; closing it is worth more than any pressure change.')
        p('Deep and REM minutes, and a falling overnight heart rate and rising HRV over weeks, are the Watch-side evidence that treated sleep is restorative. Compare nights with the mask on all night against split nights.')

    # ---- bottom line
    h2('What this means for you')
    items = []
    items.append(f'Treated hours are {"well" if ahi < 5 else "not fully"} controlled (AHI {ahi:.1f}).')
    if compliance_pct < 70 or tot_h / len(sel) < 6: items.append('The biggest gain available is more hours per night with the mask on.')
    if leak_nights: items.append('Fix the seal on the nights leak climbed; that is lost therapy.')
    if fl95 >= 0.15: items.append('Flow limitation is the number to watch if you feel unrefreshed despite a low AHI.')
    if not has_ox: items.append('Add oximetry to see the oxygen side; it is half the picture and currently missing.')
    if CA and cai > 5 and CA / tot_ev > 0.5: items.append('The central apnea pattern needs the prescriber\'s eyes.')
    if len(runs) > 1: items.append('Hold one setting for at least a week before judging it; single nights swing too much to compare settings on.')
    H_.append('<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>')
    p('<i>This synopsis is computed from the card data by fixed rules (listed in the Methods tab). It is a reading of the numbers, not medical advice, and it cannot see what a sleep study sees: EEG sleep stages, effort belts, or a technician\'s judgement. Use it to ask better questions.</i>')
    return '\n'.join(H_)
