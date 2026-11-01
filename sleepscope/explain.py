"""Plain language explanations for each chart: what it shows, what stands out in this data, what to improve and how.
Rule based and deterministic. Used by the Overview tab (all nights) and the Night tab (one night)."""
from __future__ import annotations
import numpy as np

FL_THRESH = 0.20


def _fin(v): return v is not None and isinstance(v, (int, float, np.floating)) and np.isfinite(v)


def _block(title, what, found, improve):
    h = f"<h4 style='margin:10px 0 2px;color:#1d4f91'>{title}</h4><p style='margin:0 0 4px'><b>What it shows.</b> {what}</p>"
    if found: h += "<p style='margin:0 0 4px'><b>What stands out.</b> " + ' '.join(found) + "</p>"
    if improve: h += "<p style='margin:0 0 6px;color:#0f6e4f'><b>What to improve and how.</b> " + ' '.join(improve) + "</p>"
    return h


def overview(nights) -> str:
    if not nights: return ''
    S = [n.stats for n in nights]; L = [n.label for n in nights]; N = len(nights)
    def g(k): return np.array([s.get(k, np.nan) for s in S], dtype=float)
    out = []
    # ---- usage
    h = g('hours'); low = [L[i] for i in range(N) if h[i] < 4]; split = [L[i] for i in range(N) if S[i]['sessions'] > 1]
    found, imp = [], []
    if low: found.append(f"{len(low)} of {N} nights were under 4 hours ({', '.join(low[:6])}{', ...' if len(low) > 6 else ''}).")
    if N > 1: found.append(f"Shortest {h.min():.1f} h ({L[int(h.argmin())]}), longest {h.max():.1f} h ({L[int(h.argmax())]}).")
    if split: found.append(f"Mask came off and went back on mid-night on {len(split)} night{'s' if len(split) > 1 else ''}.")
    if h.mean() < 6: imp.append("Hours are the single biggest lever. Aim for the mask on at lights-out and left on until you get up; every untreated hour is an hour of the original apnea.")
    if split: imp.append("For the mid-night gaps, note what woke you (leak noise, dry mouth, pressure, bathroom). Dry mouth with the mask off points to mouth breathing: a chin strap or mouth tape, or a full-face mask. Pressure discomfort on falling asleep: ask about EPR or a longer ramp.")
    if not imp: imp.append("Usage is where it should be. Keep the routine.")
    out.append(_block('Usage (hours)', "How long the mask was on each night. The dashed line is 4 hours, the minimum insurers and clinics count as a used night; most people feel the benefit at six or more.", found, imp))
    # ---- AHI
    ahi = g('AHI'); app = g('app_AHI'); hi = [L[i] for i in range(N) if ahi[i] >= 5]
    found, imp = [], []
    found.append(f"Machine AHI averages {np.nanmean(ahi):.1f} per hour; the app's flow-only count averages {np.nanmean(app):.1f}.")
    if hi: found.append(f"Above 5 on {', '.join(hi)}.")
    elif N > 1: found.append(f"Worst night {L[int(np.nanargmax(ahi))]} at {np.nanmax(ahi):.1f}, still under the 5 line.")
    gap = app - ahi; big = [L[i] for i in range(N) if gap[i] > 4]
    if big: found.append(f"The app count runs well above the machine's on {', '.join(big)}: many breaths shrank by a third or more without the machine calling an event, which usually means flow limitation or shallow breathing rather than closures.")
    if hi: imp.append("A night over 5 needs a reason: look at that night's leak first (leak hides and causes events), then at whether events cluster in one part of the night (position, REM) or spread evenly (pressure short). Take a run of such nights to the prescriber with the Statistics export.")
    else: imp.append("Nothing to fix here; the treated hours are controlled. If you feel unrefreshed anyway, the flow limitation and leak charts are where to look, not this one.")
    out.append(_block('AHI: machine vs app', "Breathing events per hour of use. Blue is what the machine scored (apneas plus hypopneas). Orange is the app re-scoring from the raw airflow, which counts every dip of 30% or more and so is always higher; read it as a ceiling. Violet is the app's RDI, which adds flow-limited runs ending in a recovery breath. Under 5 is normal; 5 to 15 mild; over 15 needs attention.", found, imp))
    # ---- event mix
    OA, CA, H = g('OA'), g('CA'), g('H'); tot = OA.sum() + CA.sum() + H.sum()
    found, imp = [], []
    if tot: found.append(f"Over the range: {int(OA.sum())} obstructive, {int(CA.sum())} central, {int(H.sum())} hypopneas.")
    cai = g('CAI'); cen = [L[i] for i in range(N) if cai[i] > 5 and CA[i] > OA[i] + H[i]]
    if cen: found.append(f"Centrals dominated on {', '.join(cen)}.")
    elif CA.sum(): found.append("Centrals are a minority and scattered, the pattern of normal post-sigh pauses.")
    if cen: imp.append("Centrals outnumbering obstructives on CPAP can be caused by the pressure itself. This is for the sleep physician, not a home adjustment; bring the Events export.")
    elif OA.sum() > H.sum() and np.nanmean(g('press_at_max_pct')) > 20: imp.append("Obstructives while the machine sits at its ceiling means it wanted more pressure than allowed. Ask whether the maximum can come up a step.")
    else: imp.append("The mix is unremarkable. Hypopneas (partial narrowing) respond to a slightly higher minimum pressure or EPR change if they ever climb; obstructives to the maximum.")
    out.append(_block('Machine events by type', "What kind of events the machine saw. Red: obstructive apnea, the airway closed. Violet: central apnea, the airway open but no breathing effort, the brain paused. Orange: hypopnea, airflow partly reduced. A few centrals after a sigh are normal; many on CPAP are a question for the doctor.", found, imp))
    # ---- pressure
    pmin, pmax, p95, pmed, atmax = g('press_min'), g('press_max'), g('press_95'), g('press_med'), g('press_at_max_pct')
    found, imp = [], []
    modes = {s['mode'] for s in S}; chg = [L[i] for i in range(1, N) if abs(pmax[i] - pmax[i - 1]) > 0.5 or S[i]['mode'] != S[i - 1]['mode']]
    if chg: found.append(f"Settings changed before {', '.join(chg)}.")
    ceiling = [L[i] for i in range(N) if S[i]['mode'] == 'AutoSet' and atmax[i] > 20]
    if ceiling: found.append(f"On AutoSet nights the machine sat at its ceiling more than a fifth of the time on {', '.join(ceiling)}; it wanted more than it was allowed.")
    if 'AutoSet' in modes: found.append(f"95th percentile pressure on AutoSet nights averages {np.nanmean([p95[i] for i in range(N) if S[i]['mode'] == 'AutoSet']):.1f} cmH2O; that is the number a fixed setting is usually based on.")
    if ceiling and not any(ahi[i] >= 5 for i in range(N) if L[i] in ceiling): imp.append("Hitting the ceiling without events getting through is tolerable; hitting it with flow limitation rising is the case for raising the maximum by 1 cmH2O. Either way it is a prescriber conversation.")
    elif ceiling: imp.append("Ceiling plus events getting through is the clearest signal that the maximum is set too low. Ask for it to be raised.")
    if chg: imp.append("Hold each setting at least a week before judging it; single nights swing too much.")
    if not imp: imp.append("Pressure has room to work and is not being capped. Nothing to change.")
    out.append(_block('Set pressure', "The pressure the machine delivered each night: the shaded band runs from the lowest to the highest it used, green is the median (half the night below it), blue the 95th percentile (it was above this only 5% of the time). The red dashed line is the highest reached; on AutoSet nights that is usually the ceiling you set.", found, imp))
    # ---- leak
    l95, lpct = g('leak_95'), g('leak_pct_large'); bad = [(L[i], lpct[i]) for i in range(N) if lpct[i] > 5]
    found, imp = [], []
    if bad: found.append("Large leak on " + ', '.join(f"{a} ({b:.0f}% of the night)" for a, b in bad) + ".")
    else: found.append(f"Every night's 95th percentile stayed under 24 L/min (worst {np.nanmax(l95):.0f} on {L[int(np.nanargmax(l95))]}). The mask fits.")
    if bad: imp.append("Open the worst night and look at when leak started. Starting mid-night and holding steady: mouth opening, so a chin strap, mouth tape, or a full-face mask. Spiking and recovering: the cushion moving on a position change; re-seat the mask while lying in your sleeping position, check the cushion for wear (replace at 1 to 3 months), and loosen rather than tighten, since over-tight straps buckle the cushion.")
    else: imp.append("Keep the cushion clean (daily wipe) and replace it on schedule; a seal that is good now drifts as the silicone ages.")
    out.append(_block('Leak', "Air escaping around the mask or from the mouth, beyond the vent the mask is designed to have. Aqua is the median, orange the 95th percentile. Above the red line (24 L/min) the machine cannot hold its pressure or score events reliably, so therapy is being lost, not just data.", found, imp))
    # ---- flow limitation
    f95, fmin = g('flowlim_95'), g('flowlim_minutes'); hiFL = [L[i] for i in range(N) if f95[i] >= 0.3]
    found, imp = [], []
    found.append(f"95th percentile averages {np.nanmean(f95):.2f}, about {np.nanmean(fmin):.0f} minutes a night above 0.2.")
    if hiFL: found.append(f"Highest on {', '.join(hiFL)}.")
    if N > 2:
        trend = np.polyfit(np.arange(N), f95, 1)[0] * N
        if trend > 0.08: found.append("Rising across the range as the pressure ceiling came down.")
    if hiFL or np.nanmean(f95) >= 0.2: imp.append("Flow limitation is the number that answers 'why am I tired with a good AHI'. It responds to a slightly higher minimum pressure (the airway is splinted before it narrows) or to EPR being reduced from 3 to 2 or 1; both are prescriber conversations. Nasal congestion and alcohol in the evening both raise it.")
    else: imp.append("Low. The airway is being held open cleanly; nothing to change.")
    out.append(_block('Flow limitation', "Narrowing of the airway short of an event: the breath gets through but flattened, like breathing through a straw that is being pinched. It does not count in AHI yet it fragments sleep, because each run of flattened breaths tends to end in a small arousal. 0 is none; above 0.2 for long stretches is worth attention.", found, imp))
    # ---- breathing mechanics
    rr, tv, mv = g('rr_med'), g('tv_med'), g('mv_med')
    found, imp = [], []
    odd = [L[i] for i in range(N) if not (12 <= rr[i] <= 20 and 400 <= tv[i] <= 600 and 5 <= mv[i] <= 8)]
    found.append(f"Rate {np.nanmean(rr):.0f}/min, tidal volume {np.nanmean(tv):.0f} mL, minute ventilation {np.nanmean(mv):.1f} L/min on average.")
    if odd and len(odd) < N: found.append(f"Outside the usual sleep ranges on {', '.join(odd)}.")
    elif odd: found.append("Slightly outside the usual sleep ranges most nights; machine volume estimates are approximate.")
    imp.append("These rarely need action on their own. Minute ventilation well above 8 night after night can mean over-breathing from pressure that is too high; well below 5 suggests shallow breathing. Mention a persistent shift to the prescriber; a single night means nothing.")
    out.append(_block('Breathing: rate and volume', "How you breathed while on therapy: breaths per minute, air per breath (tidal volume), and air per minute. Adults asleep typically run 12 to 20 breaths a minute, 400 to 600 mL a breath, 5 to 8 litres a minute.", found, imp))
    # ---- SpO2 or time at max
    sp = g('spo2_mean')
    if np.isfinite(sp).any():
        smin, lt90, odi = g('spo2_min'), g('spo2_pct_lt90'), g('ODI'); found, imp = [], []
        found.append(f"Mean SpO2 {np.nanmean(sp):.1f}%, lowest reading {np.nanmin(smin):.0f}%, ODI {np.nanmean(odi):.1f} per hour.")
        lowN = [L[i] for i in range(N) if smin[i] < 88 or lt90[i] > 2 or odi[i] >= 10]
        if lowN: found.append(f"Desaturation worth a look on {', '.join(lowN)}.")
        if lowN: imp.append("Open those nights and see whether the dips line up with flagged events (pressure short) or with leak, or with nothing (position, or the ring slipped). Five minutes or more under 88% in a night is the threshold physicians act on; bring it to the prescriber.")
        else: imp.append("Oxygen is holding. This is the number that says the therapy is protecting you; nothing to change.")
        out.append(_block('SpO2 and ODI', "Blood oxygen from the ring. Mean and minimum SpO2, and ODI, the number of 3% dips per hour. ODI under 5 and almost no time under 90% is the goal; this is the clearest measure of whether events are harming you.", found, imp))
    else:
        found, imp = [], []
        hi_pct = [L[i] for i in range(N) if S[i]['mode'] == 'AutoSet' and atmax[i] > 20]
        if hi_pct: found.append(f"At the ceiling more than 20% of the time on {', '.join(hi_pct)}.")
        per = g('periodic_windows'); pw = [L[i] for i in range(N) if per[i] >= 3]
        if pw: found.append(f"Several periodic-breathing windows on {', '.join(pw)}.")
        elif per.sum() == 0: found.append("No periodic (Cheyne-Stokes) breathing pattern found.")
        imp.append("Add an oximeter to replace this panel with oxygen data; AHI counts events but cannot say what they did to your oxygen." + (" If periodic windows cluster on one night, open it and look for a slow wax-and-wane in the ventilation trace; that pattern belongs in front of a physician." if pw else ''))
        out.append(_block('Time at maximum pressure, periodic breathing', "Blue bars: the share of each night the machine spent pinned at its ceiling (fixed-pressure nights show 100% by definition). Magenta: five-minute windows where breathing waxed and waned on a 30 to 90 second cycle, the Cheyne-Stokes pattern.", found, imp))
    return "<div style='font-size:12.5px;line-height:1.4'>" + ''.join(out) + "</div>"


def night(nt) -> str:
    s = nt.stats; ss = nt.sessions; out = []
    mev = [e for x in ss for e in x.machine_events]; aev = [e for x in ss for e in x.app_events]
    # pressure
    found, imp = [], []
    if s['mode'] == 'CPAP': found.append(f"Fixed at {s['press_max']:.0f} cmH2O after the ramp.")
    else: found.append(f"Ranged {s['press_min']:.0f} to {s['press_max']:.0f}, median {s['press_med']:.1f}, 95th percentile {s['press_95']:.1f}; at the ceiling {s['press_at_max_pct']:.0f}% of the night.")
    if s['mode'] != 'CPAP' and s['press_at_max_pct'] > 20: imp.append("The machine wanted more than its ceiling for a good part of the night. If events or flow limitation show up during those stretches, that argues for a higher maximum; raise it with the prescriber.")
    else: imp.append("Watch where the blue line steps up: each step is the machine reacting to narrowing. Steps that fall in one part of the night often mean back sleeping or REM.")
    out.append(_block('Pressure', "Blue is the pressure the machine chose, moment to moment; aqua is what was actually in the mask (it dips on each breath out when EPR is on); grey is the exhale pressure. Coloured bands are events: red obstructive, violet central, orange hypopnea, yellow arousal.", found, imp))
    # leak
    found, imp = [], []
    leaks = [e for e in aev if e.label == 'Large Leak']
    if leaks: found.append(f"{len(leaks)} large-leak episode{'s' if len(leaks) > 1 else ''}, {s['leak_minutes']:.0f} minutes total, worst starting {leaks[0].start.strftime('%H:%M')}.")
    else: found.append(f"95th percentile {s['leak_95']:.0f} L/min; no sustained large leak.")
    if leaks: imp.append("A leak that climbs and holds for many minutes is the mouth opening or the cushion unseated. Check whether tidal volume (below) fell during the same stretch: if it did, the leak cost you ventilation. Chin strap or mouth tape for mouth leak; re-seat and loosen for cushion leak.")
    else: imp.append("Brief spikes are normal (turning over, adjusting the mask). Nothing to change.")
    out.append(_block('Leak', "Air escaping, in litres a minute, above what the mask vents by design. The red dashed line is 24 L/min; above it the machine cannot hold pressure or score reliably.", found, imp))
    # flow limitation and snore
    found, imp = [], []
    fl_runs = [e for e in aev if e.label == 'Flow Limitation Run']
    found.append(f"95th percentile {s['flowlim_95']:.2f}, {s['flowlim_minutes']:.0f} minutes above 0.2 in {len(fl_runs)} run{'s' if len(fl_runs) != 1 else ''}; snore 95th percentile {s['snore_95']:.2f}.")
    if s['flowlim_95'] >= 0.3: imp.append("Heavy flattening. If the runs cluster late in the night (REM) or while leak is high, those are the causes; if they are everywhere, the minimum pressure is likely a step low. Prescriber conversation.")
    else: imp.append("Short runs are normal. Look for runs that end in a tall recovery breath on the flow panel: those likely woke you briefly.")
    out.append(_block('Flow limitation and snore', "Violet: how flattened each breath was (0 round and free, 1 fully flattened). Pink: snore vibration. Both are the airway narrowing without closing.", found, imp))
    # ventilation ratio
    found, imp = [], []
    unflag = [e for e in aev if e.label == 'Apnea (unflagged by machine)']; hyp = [e for e in aev if e.label == 'Hypopnea']
    found.append(f"The app found {len(hyp)} flow-only hypopnea{'s' if len(hyp) != 1 else ''}" + (f" and {len(unflag)} pause{'s' if len(unflag) != 1 else ''} the machine did not flag" if unflag else '') + ".")
    imp.append("Dips below the orange line (70%) are reduced breathing; below the red line (25%) is a pause. Tap or step to one and look at the raw flow: a flat line with a struggle to restart is obstructive; a flat line right after a big sigh is usually a harmless central. Many dips with no machine events usually means shallow breathing or leak, not closures.")
    out.append(_block('Ventilation vs baseline', "Each second's breathing compared with the previous two minutes. 1.0 is normal; this is the trace the app scores from.", found, imp))
    # rr, vt, mv
    found, imp = [], []
    found.append(f"Rate {s['rr_med']:.0f}/min, tidal volume {s['tv_med']:.0f} mL, minute ventilation {s['mv_med']:.1f} L/min (medians).")
    imp.append("A sudden drop in tidal volume while leak rises is leak stealing air. A slow climb in breathing rate through the night with a low volume can be the airway narrowing. Big spikes are sighs and are normal.")
    out.append(_block('Respiratory rate, tidal volume, minute ventilation', "How fast, how deep, and how much per minute.", found, imp))
    if np.isfinite(s.get('spo2_mean', np.nan)):
        found, imp = [], []
        found.append(f"SpO2 mean {s['spo2_mean']:.1f}%, min {s['spo2_min']:.0f}%, {s['spo2_pct_lt90']:.1f}% of the night under 90%, ODI {s['ODI']:.1f}; pulse mean {s['pulse_mean']:.0f}.")
        if s['spo2_min'] < 88 or s['ODI'] >= 10: imp.append("Line the dips up with the event bands above. Dips on events: pressure short. Dips with leak: fix the leak. Dips with neither: position, or the ring slipped. Five minutes under 88% is the level physicians act on.")
        else: imp.append("Oxygen held. A pulse that stays flat with no sawtooth is the heart not being startled by events.")
        out.append(_block('SpO2 and pulse', "Blood oxygen and heart rate from the ring, second by second. The dashed line is 90%.", found, imp))
    if getattr(nt, 'apple', None) and nt.apple.get('stages'):
        a = nt.apple; found, imp = [], []
        found.append(f"Watch: asleep {a['asleep_h']:.1f} h, deep {a['deep_min']:.0f} min, REM {a['rem_min']:.0f} min, awake {a['awake_min']:.0f} min; machine on {nt.hours:.1f} h.")
        if a['asleep_h'] > nt.hours + 0.5: imp.append(f"About {a['asleep_h'] - nt.hours:.1f} h of sleep had no mask on. That untreated sleep is the easiest gain available.")
        else: imp.append("The machine covered the sleep the Watch saw. Compare deep and REM minutes across nights with and without leak; treated sleep should show more of both.")
        out.append(_block('Apple Watch', "Sleep stages from the Watch (motion and heart rate, not EEG, so approximate), its heart rate, and its SpO2 spot checks.", found, imp))
    return "<div style='font-size:12.5px;line-height:1.4'>" + ''.join(out) + "</div>"


# ----------------------------------------------------------------------------- click explanations for the 3D landscape
EVENT_WORDS = {
    'Obstructive Apnea': ("Obstructive apnea", "the airway closed completely for {dur:.0f} seconds while you kept trying to breathe. Airflow stopped, then restarted with a bigger breath. One or two a night is normal; a cluster at one time of night usually means back sleeping or REM, and a cluster at a low pressure means the pressure was short.", "If these line up with a low pressure or sit at the ceiling, that is the case for a higher setting; raise it with the prescriber. If they cluster in one stretch, try side sleeping."),
    'Central Apnea': ("Central apnea", "breathing paused for {dur:.0f} seconds with the airway open: the brain simply did not send the signal. After a sigh or an arousal this is normal physiology and harmless.", "Nothing to do for a few scattered ones. If centrals start to outnumber obstructives, or come in waves, that is a question for the sleep physician, not a setting change."),
    'Hypopnea': ("Hypopnea", "airflow dropped by about a third or more for at least ten seconds without stopping: the airway narrowed, not closed.", "Hypopneas respond to a slightly higher minimum pressure or to less EPR; a prescriber conversation. Check leak at the same moment first, since leak can create them."),
    'Unclassified Apnea': ("Apnea", "airflow stopped for {dur:.0f} seconds; the machine could not tell whether the airway was closed or open.", "Look at the raw flow around it in the Night tab."),
    'Arousal': ("Arousal", "a brief wake-up the machine inferred from a sudden change in breathing.", "A few per hour are normal. Many, with low AHI, point at flow limitation or leak as the thing disturbing sleep."),
}


def point(kind, **c) -> str:
    """Plain language for a clicked element. kind: 'event' | 'terrain' | 'floor' | 'water' | 'pressure' | 'stage'."""
    t = c.get('time', ''); n = c.get('night', '')
    if kind == 'event':
        name, what, do = EVENT_WORDS.get(c['label'], (c['label'], 'an event the machine flagged.', ''))
        head = f"<b>{name}</b>, {n} at {t}"
        body = what.format(dur=c.get('dur', 0))
        extra = []
        if c.get('press') is not None: extra.append(f"Pressure at the time {c['press']:.1f} cmH2O" + (" (at the ceiling)" if c.get('at_ceiling') else ""))
        if c.get('leak') is not None: extra.append(f"leak {c['leak']:.0f} L/min" + (" (large)" if c['leak'] > 24 else ""))
        return f"{head}<br>{body}" + (f"<br><i>{', '.join(extra)}.</i>" if extra else '') + f"<br><b>What to do:</b> {do}"
    if kind == 'floor':
        return f"<b>Mask off</b>, {n} at {t}<br>Grey floor means no therapy was running: the mask was off, or the machine was not on. Sleep during this time is untreated, the same as before you had the machine.<br><b>What to do:</b> if this is mid-night, note what woke you; if it is the start or end of the night, it is the difference between time in bed and time on therapy."
    if kind == 'water':
        return f"<b>Large leak</b>, {n} at {t}: {c.get('leak', 0):.0f} L/min<br>Air was escaping faster than the machine can compensate (over 24 L/min). It cannot hold its pressure or score events reliably in a pool like this, so therapy is being lost here, not just data.<br><b>What to do:</b> a pool that starts mid-night and holds is mouth opening (chin strap, mouth tape, or a full-face mask). One that comes and goes is the cushion shifting; re-seat it lying in your sleeping position and loosen rather than tighten."
    if kind == 'pressure':
        return f"<b>Pressure</b>, {n} at {t}: {c.get('press', 0):.1f} cmH2O<br>The white line is what the machine was delivering. On AutoSet it climbs when it senses narrowing and drifts back down when breathing is easy; a line that sits flat against the top is the machine pinned at its ceiling.<br><b>What to do:</b> nothing for the line itself. If it is at the ceiling while pillars or yellow terrain appear, the maximum is a step low; raise it with the prescriber."
    if kind == 'stage':
        st = c.get('stage', '')
        words = {'Deep': 'Deep sleep, the physically restorative kind. Adults get most of it in the first half of the night.', 'Core': 'Core (light) sleep, the bulk of a normal night.', 'REM': 'REM, dreaming sleep, when muscles relax most and the airway is at its floppiest; events often cluster here.', 'Awake': 'Awake, as judged by the Watch from movement and heart rate.', 'InBed': 'In bed but not asleep.', 'Asleep': 'Asleep (the Watch did not separate stages).'}.get(st, st)
        return f"<b>Apple Watch: {st}</b>, {n} at {t}<br>{words}<br>Ribbon over grey floor is sleep with the mask off: untreated sleep.<br><b>What to do:</b> the ribbon should be covered by the strip. Where it is not, that is the gain available by keeping the mask on."
    # terrain
    op = c.get('openness', 1.0); fl = c.get('fl', 0.0); lk = c.get('leak', 0.0); pr = c.get('press')
    if op >= 0.6: level, meaning = "breathing freely", "a high green plateau: full, easy breaths. This is what a well-treated stretch looks like."
    elif op >= 0.25: level, meaning = "airway narrowing", "a yellow dip: breaths were getting through but shrunken or flattened, the airway partly collapsing on each breath in. This does not count as an event yet it fragments sleep."
    else: level, meaning = "airflow stopped", "a red crater: airflow fell to almost nothing. If there is no pillar here the machine did not flag it; look at the raw flow in the Night tab."
    detail = f"Openness {op:.2f} (1 is free, 0 is stopped)" + (f", leak {lk:.0f} L/min" if lk else '') + (f", pressure {pr:.1f} cmH2O" if pr is not None else '')
    do = {"breathing freely": "nothing; this is the goal.", "airway narrowing": "yellow stretches are what a slightly higher minimum pressure or less EPR smooths out; if they coincide with a leak pool, fix the seal first. Both are prescriber conversations.", "airflow stopped": "a crater with a pillar is an event already explained by the pillar; a crater without one is worth looking at in the Night tab."}[level]
    return f"<b>{level.capitalize()}</b>, {n} at {t}<br>{meaning}<br><i>{detail}.</i><br><b>What to do:</b> {do}"
