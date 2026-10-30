"""Equipment: what the user breathes through, how they use it, and what is worth discussing with their care team.

The profile (machine, mask, supplies) is stored in the app settings on this PC. Usage patterns are computed from the loaded
nights every time data loads, so the findings update as more nights come in. Every finding names the pattern in the data that
produced it, and every option is phrased as something to review with the prescriber or equipment supplier.

Sources behind the rules (checked October 2026):
  Replacement intervals  CMS (Medicare) PAP supply schedule as published by ResMed and hospital DME pages: full face cushion
                         1 a month, nasal cushion and pillows 2 a month, mask frame 1 per 3 months, headgear and chinstrap
                         1 per 6 months, tubing (plain or heated) 1 per 3 months, disposable filter 2 a month,
                         non-disposable filter and water chamber 1 per 6 months.
  Mask type              Andrade RGS et al. Nasal versus oronasal CPAP for OSA treatment: a meta-analysis. Chest 2018;153(3):665-674.
                         Compared with nasal masks, oronasal (full face) masks were associated with about 1.5 cmH2O higher
                         pressure, about 2.8 events/h higher residual AHI and about 48 min/night less use.
  Large leak             ResMed AirSense large leak line, 24 L/min.
  Product examples       Manufacturer pages (ResMed, Fisher & Paykel) and a national DME supplier's mask list. Availability
                         varies by country and supplier, and every mask needs a prescription and a proper fitting.
"""
from __future__ import annotations
import json, datetime as dt, html
import numpy as np

LEAK_LARGE = 24.0

MASK_TYPES = ['', 'Nasal pillows', 'Nasal, over the nose', 'Nasal cradle, under the nose', 'Full face, over the nose',
              'Full face, compact below the nose bridge', 'Other']
MACHINE_BRANDS = ['', 'ResMed', 'Fisher & Paykel', 'Philips Respironics', 'React Health', 'Other']
MASK_BRANDS = ['', 'ResMed', 'Fisher & Paykel', 'Philips Respironics', 'React Health', 'Other']
SIZES = ['', 'XS', 'S', 'S/M', 'M', 'M/L', 'L', 'Wide', 'XL', 'Petite', 'Standard']


def kind(mask_type: str) -> str:
    """Collapse the mask type to 'pillows', 'nasal', 'full' or ''."""
    t = (mask_type or '').lower()
    if 'pillow' in t: return 'pillows'
    if t.startswith('nasal'): return 'nasal'
    if 'full' in t: return 'full'
    return ''


# Examples by category, listed alphabetically by brand so no maker is favoured. Checked against manufacturer and supplier pages, October 2026.
CATALOG = {
    'Nasal pillows': ['Fisher & Paykel Brevida', 'Fisher & Paykel Nova Micro', 'Fisher & Paykel Solo (pillows cushion)', 'React Health Rio II', 'ResMed AirFit P10', 'ResMed AirFit P30i'],
    'Nasal, over the nose': ['Fisher & Paykel Eson 2', 'Fisher & Paykel Evora Nasal', 'Fisher & Paykel Solo Nasal', 'ResMed AirFit N20', 'ResMed AirTouch N20 (foam cushion)'],
    'Nasal cradle, under the nose': ['Philips DreamWear Nasal', 'ResMed AirFit N30', 'ResMed AirFit N30i', 'ResMed AirTouch N30i (foam cushion)'],
    'Full face, over the nose': ['Fisher & Paykel Simplus', 'Fisher & Paykel Vitera', 'React Health Siesta', 'ResMed AirFit F20', 'ResMed AirTouch F20 (foam cushion)'],
    'Full face, compact below the nose bridge': ['Philips Amara View', 'Philips DreamWear Full Face', 'ResMed AirFit F30', 'ResMed AirFit F30i', 'ResMed AirFit F40'],
}
MODEL_SUGGESTIONS = sorted({m for v in CATALOG.values() for m in v})
BRAND_PREFIX = {'ResMed ': 'ResMed', 'Fisher & Paykel ': 'Fisher & Paykel', 'Philips Respironics ': 'Philips Respironics', 'Philips ': 'Philips Respironics', 'React Health ': 'React Health'}


def split_brand(model: str):
    """'ResMed AirFit F30i' -> ('ResMed', 'AirFit F30i'); ('', model) when no known brand leads the text."""
    for pre, brand in BRAND_PREFIX.items():
        if (model or '').startswith(pre): return brand, model[len(pre):].strip()
    return '', model

# (key, label, days, applies to mask kinds or None for all)
SUPPLIES = [
    ('cushion', 'Cushion or pillows', None, None),         # interval depends on mask kind, see cushion_days()
    ('frame', 'Mask frame', 91, None),
    ('headgear', 'Headgear', 182, None),
    ('chinstrap', 'Chinstrap', 182, None),
    ('tubing', 'Tubing', 91, None),
    ('filter', 'Filter (disposable)', 15, None),
    ('chamber', 'Water chamber', 182, None),
]


def cushion_days(mask_type):
    return 30 if kind(mask_type) == 'full' else 15


# ----------------------------------------------------------------------------- profile storage
EMPTY = dict(machine_brand='', machine_model='', humidifier='', heated_tube='', mask_type='', mask_brand='', mask_model='',
             mask_size='', chinstrap='', mask_since='', notes='', replaced={}, history=[])


def load_profile(settings) -> dict:
    raw = settings.value('equipment', '')
    try: p = json.loads(raw) if raw else {}
    except Exception: p = {}
    out = dict(EMPTY); out.update({k: v for k, v in p.items() if k in EMPTY})
    out['replaced'] = dict(out.get('replaced') or {}); out['history'] = list(out.get('history') or [])
    return out


def save_profile(settings, profile: dict, change_date: dt.date | None = None) -> dict:
    """Store the profile. When the mask changed, the old one goes into history with the date the new one started,
    so nights before and after the change can be compared."""
    old = load_profile(settings)
    key = lambda p: (p.get('mask_type', ''), p.get('mask_brand', ''), p.get('mask_model', ''), p.get('mask_size', ''))
    if any(key(old)) and key(old) != key(profile):
        d = (change_date or dt.date.today()).isoformat()
        hist = list(old.get('history') or [])
        hist.append(dict(until=d, mask_type=old['mask_type'], mask_brand=old['mask_brand'], mask_model=old['mask_model'], mask_size=old['mask_size']))
        profile['history'] = hist[-20:]
        profile['mask_since'] = d
    else:
        profile['history'] = old.get('history') or []
    settings.setValue('equipment', json.dumps(profile))
    return profile


def mask_text(p) -> str:
    b, m = p.get('mask_brand') or '', p.get('mask_model') or ''
    if b and m.lower().startswith(b.split()[0].lower()): b = ''
    parts = [x for x in (b, m) if x]
    bits = [' '.join(parts) or 'model not recorded']
    if p.get('mask_type'): bits.append(p['mask_type'].lower())
    if p.get('mask_size'): bits.append(f"size {p['mask_size']}")
    if p.get('chinstrap') == 'Yes': bits.append('with chinstrap')
    return ', '.join(bits)


def machine_text(p, ident=None) -> str:
    model = p.get('machine_model') or (ident or {}).get('model') or ''
    brand = p.get('machine_brand') or ('ResMed' if model else '')
    s = ' '.join(x for x in (brand, model) if x) or 'not recorded'
    extra = []
    if p.get('humidifier'): extra.append(f"humidifier {p['humidifier'].lower()}")
    if p.get('heated_tube'): extra.append('heated tube' if p['heated_tube'] == 'Yes' else 'standard tube')
    return s + (f" ({', '.join(extra)})" if extra else '')


def has_any(p) -> bool:
    return any(p.get(k) for k in ('machine_model', 'mask_type', 'mask_brand', 'mask_model'))


# ----------------------------------------------------------------------------- usage patterns
def _night_leak_profile(nt):
    """Per night: fraction of therapy time in large leak in each third of the night, leak episode durations (s),
    sessions that ended within 5 min of a large leak, and leak medians at low and high set pressure."""
    lk_all, pr_all = [], []
    for s in nt.sessions:
        lk = s.ch.get('Leak'); pr = s.ch.get('Press')
        if lk is None: continue
        lk_all.append(lk * 60.0)
        pr_all.append(pr[:len(lk)] if pr is not None and len(pr) >= len(lk) else np.full(len(lk), np.nan))
    if not lk_all: return None
    lk = np.concatenate(lk_all); pr = np.concatenate(pr_all)
    thirds = [float((part > LEAK_LARGE).mean()) if len(part) else np.nan for part in np.array_split(lk, 3)]
    eps = [e.duration for s in nt.sessions for e in s.app_events if e.label == 'Large Leak']
    ended = 0
    for s in nt.sessions[:-1]:          # the last session's end is the morning, not a removal
        if any(e.label == 'Large Leak' and (s.end - e.end).total_seconds() <= 300 for e in s.app_events): ended += 1
    lo_hi = (np.nan, np.nan)
    ok = np.isfinite(pr)
    if ok.sum() > 300 and np.nanpercentile(pr, 90) - np.nanpercentile(pr, 10) >= 2:
        q1, q3 = np.nanpercentile(pr[ok], [25, 75])
        lo = lk[ok & (pr <= q1)]; hi = lk[ok & (pr >= q3)]
        if len(lo) > 60 and len(hi) > 60: lo_hi = (float(np.median(lo)), float(np.median(hi)))
    return dict(thirds=thirds, episodes=eps, ended_after_leak=ended, leak_lo_p=lo_hi[0], leak_hi_p=lo_hi[1])


def analyse(nights, profile, window=30) -> dict:
    """Usage patterns over the most recent `window` nights. Returns {'findings': [...], 'options': [...], 'summary': {...}}.
    A finding is {'id', 'title', 'evidence', 'level'} where level is 'good', 'watch' or 'act'."""
    sel = list(nights[-window:]) if nights else []
    out = {'findings': [], 'options': [], 'summary': {}, 'n': len(sel)}
    if not sel: return out
    k = kind(profile.get('mask_type', ''))
    F = out['findings']; O = out['options']
    def find(id_, title, evidence, level='watch'): F.append(dict(id=id_, title=title, evidence=evidence, level=level))
    def opt(title, why, examples=None, from_=None): O.append(dict(title=title, why=why, examples=examples or [], source=from_))

    hours = np.array([n.hours for n in sel]); S = [n.stats for n in sel]
    def g(key): return np.array([s.get(key, np.nan) for s in S], dtype=float)
    multi = [n for n in sel if len(n.sessions) > 1]
    pct4 = 100 * (hours >= 4).mean()
    leak95 = g('leak_95'); p95 = g('press_95')
    prof = [p for p in (_night_leak_profile(n) for n in sel) if p]
    eps = np.array([d for p in prof for d in p['episodes']]) if prof else np.array([])
    sustained = int((eps >= 600).sum()); brief = int((eps < 180).sum())
    ended = sum(p['ended_after_leak'] for p in prof)
    th = np.array([p['thirds'] for p in prof]) if prof else np.zeros((0, 3))
    late = float(np.nanmean(th[:, 2])) * 100 if len(th) else np.nan; early = float(np.nanmean(th[:, 0])) * 100 if len(th) else np.nan
    lohi = np.array([(p['leak_lo_p'], p['leak_hi_p']) for p in prof if np.isfinite(p['leak_lo_p'])])
    out['summary'] = dict(nights=len(sel), mean_hours=float(hours.mean()), pct_4h=float(pct4), split_nights=len(multi),
                          leak95_median=float(np.nanmedian(leak95)) if np.isfinite(leak95).any() else np.nan,
                          leak_nights=int((leak95 > LEAK_LARGE).sum()), sustained_leaks=sustained, brief_leaks=brief,
                          ended_after_leak=ended, late_leak_pct=late, early_leak_pct=early,
                          ahi=float(np.nansum(g('OA') + g('CA') + g('H') + g('UA')) / hours.sum()) if hours.sum() else np.nan,
                          press95_median=float(np.nanmedian(p95)) if np.isfinite(p95).any() else np.nan)
    sm = out['summary']
    rng = f'the last {len(sel)} night{"s" if len(sel) != 1 else ""}'

    # --- hours and removals
    if pct4 < 70 or hours.mean() < 6:
        find('hours', 'Short nights on the mask',
             f'Over {rng} the mask was on {hours.mean():.1f} h a night on average and {pct4:.0f}% of nights reached 4 hours.', 'act' if pct4 < 70 else 'watch')
    else:
        find('hours', 'Consistent use', f'Over {rng} the mask was on {hours.mean():.1f} h a night and {pct4:.0f}% of nights reached 4 hours.', 'good')
    if len(multi) >= max(2, 0.3 * len(sel)):
        find('removals', 'Mask off and back on during the night',
             f'{len(multi)} of {len(sel)} nights had more than one session' + (f'; {ended} of those breaks came within 5 minutes of a large leak, so leak looks like part of the reason.' if ended else '.'))

    # --- leak
    if np.isfinite(leak95).any():
        if sm['leak_nights'] == 0 and sustained == 0:
            find('seal', 'Mask seal is holding', f'95th percentile leak was under {LEAK_LARGE:.0f} L/min on every night (median {sm["leak95_median"]:.0f} L/min).', 'good')
        else:
            find('seal', 'Leak above the large leak line',
                 f'95th percentile leak passed {LEAK_LARGE:.0f} L/min on {sm["leak_nights"]} of {len(sel)} nights (median {sm["leak95_median"]:.0f} L/min); '
                 f'{len(eps)} large leak episode{"s" if len(eps) != 1 else ""} in all, {sustained} lasting 10 minutes or more and {brief} under 3 minutes.', 'act' if sm['leak_nights'] >= 0.3 * len(sel) else 'watch')
        if sustained >= 3 and sustained >= brief:
            find('sustained', 'Long, steady leaks rather than brief spikes',
                 f'{sustained} leak episodes lasted 10 minutes or more. A leak that sets in and holds usually means the mouth has opened or the cushion has shifted; '
                 'brief spikes that recover are more often movement.' + (' With a nasal or pillows mask, this is the pattern mouth leak leaves.' if k in ('nasal', 'pillows') else ''))
        elif brief >= 5 and brief > 2 * sustained:
            find('spikes', 'Brief leak spikes', f'{brief} large leaks under 3 minutes that recovered on their own. That pattern usually follows turning over, so fit at the sides of the face and headgear tension matter more than cushion size.')
        if np.isfinite(late) and np.isfinite(early) and late > 5 and late >= 2 * max(early, 1):
            find('late', 'Leak builds late in the night',
                 f'Large leak took {late:.0f}% of the last third of the night against {early:.0f}% of the first third. Later sleep has more REM, when jaw and face muscles relax most, '
                 'so a mask that seals at bedtime can open up toward morning.')
        if len(lohi) >= 3:
            lo, hi = np.nanmedian(lohi[:, 0]), np.nanmedian(lohi[:, 1])
            if hi > 12 and hi >= 1.5 * max(lo, 1):
                find('pressure_leak', 'Leak rises with pressure',
                     f'Median leak was {lo:.0f} L/min in the lowest quarter of set pressure and {hi:.0f} L/min in the highest. The seal holds at low pressure and gives way as the machine raises it.')
        if len(sel) >= 10:
            x = np.array([(n.date - sel[0].date).days for n in sel], float); y = leak95; m = np.isfinite(y)
            if m.sum() >= 8:
                slope = np.polyfit(x[m], y[m], 1)[0] * 30
                if slope >= 4 and np.nanmean(y[m][-7:]) > 15:
                    find('trend', 'Leak creeping up over the weeks', f'95th percentile leak has risen about {slope:.0f} L/min per month across {rng}. A slow rise is the typical sign of a cushion losing its shape.')

    # --- residual events and pressure
    if np.isfinite(sm['ahi']) and sm['ahi'] >= 5:
        find('ahi', 'Events getting through', f'Machine AHI over {rng} was {sm["ahi"]:.1f} per hour (under 5 is the usual target).', 'act' if sm['ahi'] >= 10 else 'watch')
    if np.isfinite(sm['press95_median']) and sm['press95_median'] >= 13:
        find('pressure', 'Higher pressure range', f'95th percentile pressure was {sm["press95_median"]:.1f} cmH2O on a typical night.')
    cai = np.nansum(g('CA')) / hours.sum() if hours.sum() else 0
    if cai > 5 and np.nansum(g('CA')) > 0.5 * max(1, np.nansum(g('OA') + g('CA') + g('H') + g('UA'))):
        find('central', 'Central apneas dominate', f'Central apnea index {cai:.1f}/h, more than half of all events. A mask change does not address this; it is a question for the sleep physician about the device type and settings.', 'act')

    # --- supplies
    for item, label, days in supplies_due(profile):
        if days is not None and days < 0:
            find('supply_' + item, f'{label} past its usual replacement date', f'Recorded as replaced {-days + _interval(item, profile)} days ago; the usual interval is {_interval(item, profile)} days.', 'watch')

    ids = {f['id'] for f in F}
    has_leak = sm.get('leak_nights', 0) >= max(2, 0.2 * len(sel)) or bool(ids & {'sustained', 'late', 'pressure_leak', 'trend', 'spikes'})

    # --- options, each tied to the pattern that raised it
    if not k:
        opt('Record your mask type, brand, model and size',
            'The suggestions get specific once SleepScope knows which mask you use. The type matters most: nasal pillows, nasal, or full face.')
        if has_leak:
            opt('Take the leak pattern to your equipment supplier', 'The findings above say when and how the mask leaks. That is what a fitter needs to choose between a new cushion, a different size, a chinstrap or a different mask type.', None, 'Leak')
    cushion_old = 'supply_cushion' in ids
    if has_leak and ('trend' in ids or cushion_old):
        opt('Replace the cushion before anything else', 'Leak is up and the cushion is ' + ('past its replacement date' if cushion_old else 'the usual suspect when leak rises slowly') + '. '
            'A new cushion is the cheapest thing to rule out. The Medicare schedule allows one a month for full face masks and two a month for nasal and pillows masks, and many plans follow it.',
            from_='Leak creeping up' if 'trend' in ids else 'Leak with an old cushion')
    elif cushion_old:
        opt('Replace the cushion', 'It is past the usual interval. Silicone softens and loses its shape with nightly use, and the leak that follows tends to creep up slowly.', from_='Supplies')
    if k in ('nasal', 'pillows') and ('sustained' in ids or 'late' in ids):
        opt('Ask about a chinstrap or a mask that covers the mouth',
            'Long, steady leaks with a nasal or pillows mask usually mean the mouth opens during sleep. A chinstrap is the usual first step; '
            'if it does not hold, a compact full face mask that rests below the nose bridge keeps much of the nasal mask feel. '
            'Heated humidification is often added at the same time, because mouth leak dries the nose and throat.',
            CATALOG['Full face, compact below the nose bridge'], 'Long, steady leaks' if 'sustained' in ids else 'Leak late in the night')
    short = 'removals' in ids or any(f['id'] == 'hours' and f['level'] != 'good' for f in F)
    if k == 'full' and not has_leak and ('ahi' in ids or ('pressure' in ids and short)):
        opt('Ask whether a nasal mask is worth a trial',
            'Your full face mask is sealing, but events or pressure are on the high side. In a 2018 meta-analysis (Andrade et al., Chest) full face masks needed about '
            '1.5 cmH2O more pressure and left about 2.8 more events per hour than nasal masks. If you were moved to full face for mouth breathing, a nasal mask '
            'with a chinstrap is sometimes tried; your sleep physician will know whether that applies to you. If the full face mask was chosen for a blocked nose, this does not apply.',
            CATALOG['Nasal cradle, under the nose'] + CATALOG['Nasal pillows'][:3], 'Events or pressure on a full face mask')
    if k == 'full' and has_leak:
        opt('Get the full face mask refitted, or try a different cushion size or style',
            'Full face masks most often leak at the bridge of the nose or the corners of the mouth, and a size that fits lying on your back can lift when you turn. '
            'Equipment suppliers can do a fitting with the machine running. A compact design that rests below the nose bridge avoids the bridge leak; a memory foam cushion suits some faces better.',
            CATALOG['Full face, compact below the nose bridge'] + ['ResMed AirTouch F20 (foam cushion)'], 'Leak on a full face mask')
    if k == 'pillows' and ('pressure_leak' in ids or ('pressure' in ids and has_leak)):
        opt('Ask about a nasal cushion mask in place of pillows',
            'Leak climbs as pressure rises. Pillows seal inside the nostrils on a small area, and some people find a nasal cushion that sits on or around the nose holds better and feels gentler at higher pressure.',
            CATALOG['Nasal, over the nose'] + CATALOG['Nasal cradle, under the nose'], 'Leak rises with pressure')
    if k == 'nasal' and 'pressure_leak' in ids and 'sustained' not in ids:
        opt('Check the cushion size and headgear with the supplier', 'Leak climbs as pressure rises while the nose seal otherwise holds. A size change or a different cushion style often fixes this; '
            'overtightening the headgear usually makes it worse.', CATALOG['Nasal, over the nose'], 'Leak rises with pressure')
    if 'spikes' in ids:
        opt('Look at a mask with the tube on top of the head', 'Brief leaks that follow movement are often the tube pulling the mask off the face. Top-of-head tube designs move with you.',
            ['Fisher & Paykel Solo', 'Philips DreamWear Full Face', 'Philips DreamWear Nasal', 'ResMed AirFit F30i', 'ResMed AirFit N30i', 'ResMed AirFit P30i'], 'Brief leak spikes')
    if 'removals' in ids or ('hours' in ids and pct4 < 70):
        opt('Bring the mask to your next follow up', 'Short nights and mid-night removals are the most common reason therapy underperforms, and comfort is often behind them. '
            'Clinics and suppliers expect to swap masks in the first months; say what wakes you (leak noise, dryness, pressure on the nose, feeling closed in).',
            None, 'Short nights or removals')
    if 'central' in ids:
        opt('Raise the central apneas with the sleep physician', 'This is the one pattern a mask change will not fix. It needs a clinician to review the device type and settings.', None, 'Central apneas')
    if not O and k:
        opt('Nothing in the data argues for a change', f'Your {mask_text(profile)} is sealing and the events are controlled. Keep replacing the cushion on schedule.')
    return out


def _interval(item, profile):
    if item == 'cushion': return cushion_days(profile.get('mask_type', ''))
    return next(d for i, _, d, _ in SUPPLIES if i == item)


def supplies_due(profile, today=None):
    """[(item, label, days_left or None)] for each supply with a recorded date. Negative days_left = overdue."""
    today = today or dt.date.today(); out = []
    for item, label, _, _ in SUPPLIES:
        if item == 'chinstrap' and profile.get('chinstrap') != 'Yes': continue
        d = (profile.get('replaced') or {}).get(item)
        if not d: out.append((item, label, None)); continue
        try: dd = dt.date.fromisoformat(d)
        except ValueError: out.append((item, label, None)); continue
        out.append((item, label, _interval(item, profile) - (today - dd).days))
    return out


def before_after(nights, change_date: dt.date, window=30):
    """Compare up to `window` nights before and after an equipment change. Returns rows (label, before, after) or None."""
    b = [n for n in nights if n.date < change_date][-window:]; a = [n for n in nights if n.date >= change_date][:window]
    if len(b) < 3 or len(a) < 3: return None
    def m(ns, key):
        v = np.array([n.stats.get(key, np.nan) for n in ns], float); return float(np.nanmean(v)) if np.isfinite(v).any() else np.nan
    def wahi(ns):
        h = sum(n.hours for n in ns); return sum(n.stats.get('OA', 0) + n.stats.get('CA', 0) + n.stats.get('H', 0) + n.stats.get('UA', 0) for n in ns) / h if h else np.nan
    rows = [('Nights compared', f'{len(b)}', f'{len(a)}'),
            ('Hours a night', f"{np.mean([n.hours for n in b]):.1f}", f"{np.mean([n.hours for n in a]):.1f}"),
            ('Nights with mask off and on', f"{sum(len(n.sessions) > 1 for n in b)}", f"{sum(len(n.sessions) > 1 for n in a)}"),
            ('AHI (machine)', f'{wahi(b):.1f}', f'{wahi(a):.1f}'),
            ('Leak 95th percentile, L/min', f"{m(b, 'leak_95'):.0f}", f"{m(a, 'leak_95'):.0f}"),
            ('Time in large leak, %', f"{m(b, 'leak_pct_large'):.1f}", f"{m(a, 'leak_pct_large'):.1f}"),
            ('Flow limitation 95th', f"{m(b, 'flowlim_95'):.2f}", f"{m(a, 'flowlim_95'):.2f}"),
            ('Pressure 95th, cmH2O', f"{m(b, 'press_95'):.1f}", f"{m(a, 'press_95'):.1f}")]
    return rows


# ----------------------------------------------------------------------------- text for the report, synopsis and Claude
LEVEL_COLOUR = {'good': '#008300', 'watch': '#b77f00', 'act': '#e34948'}


def report_html(nights, profile, ident=None) -> str:
    r = analyse(nights, profile); e = html.escape
    H = ['<h2>Your equipment and how you use it</h2>',
         f'<p><b>Machine:</b> {e(machine_text(profile, ident))}<br><b>Mask:</b> {e(mask_text(profile))}'
         + (f"<br><b>In use since:</b> {e(profile['mask_since'])}" if profile.get('mask_since') else '') + '</p>']
    if not nights:
        H.append('<p>Load an SD card (or the sample data) and this page reads how the mask is being used: hours, removals, when and how it leaks, and how leak behaves as pressure changes.</p>')
    else:
        H.append(f'<h3>What the data shows (last {r["n"]} nights)</h3><ul>')
        for f in r['findings']:
            H.append(f"<li><b style='color:{LEVEL_COLOUR[f['level']]}'>{e(f['title'])}.</b> {e(f['evidence'])}</li>")
        H.append('</ul><h3>Options to review with your doctor or equipment supplier</h3>')
        for o in r['options']:
            H.append(f"<p><b>{e(o['title'])}</b>" + (f" <span style='color:#8a8985'>(from: {e(o['source'])})</span>" if o.get('source') else '') + f"<br>{e(o['why'])}")
            cur = (profile.get('mask_model') or '').lower()
            ex = [x for x in o['examples'] if not cur or not split_brand(x)[1].lower().startswith(cur)]
            if ex: H.append(f"<br><span style='color:#52514e'>Examples of this type: {e(', '.join(ex))}.</span>")
            H.append('</p>')
    due = supplies_due(profile)
    if any(d is not None for _, _, d in due):
        H.append('<h3>Supplies</h3><ul>')
        for item, label, d in due:
            if d is None: continue
            H.append(f"<li>{e(label)}: " + (f"<b style='color:#e34948'>{-d} days past</b> the usual {_interval(item, profile)} day interval" if d < 0 else f'due in {d} days') + '</li>')
        H.append('</ul><p style="color:#8a8985">Intervals follow the Medicare (CMS) PAP supply schedule. Replace sooner if a part is torn, stiff or no longer seals.</p>')
    for hst in reversed(profile.get('history') or []):
        try: cd = dt.date.fromisoformat(hst['until'])
        except Exception: continue
        rows = before_after(nights, cd) if nights else None
        old = mask_text(hst)
        H.append(f'<h3>Before and after the change on {cd:%b %d, %Y}</h3><p>From {e(old)} to {e(mask_text(profile))}.</p>')
        if rows:
            H.append('<table cellpadding="4" style="border-collapse:collapse"><tr><th align="left"></th><th>Before</th><th>After</th></tr>'
                     + ''.join(f'<tr><td>{e(a)}</td><td align="center">{b}</td><td align="center">{c}</td></tr>' for a, b, c in rows) + '</table>')
        else:
            H.append('<p style="color:#52514e">Needs at least three nights on each side of the change to compare.</p>')
        break
    H.append('<p style="color:#8a8985"><i>These are patterns in the card data and general fitting guidance, not medical advice. Masks need a prescription and a proper fitting; '
             'take any change to the prescriber or equipment supplier. Product names are examples of each type, listed by brand in alphabetical order, and availability varies.</i></p>')
    return '\n'.join(H)


def synopsis_html(nights, profile, ident=None) -> str:
    """Short section for the Synopsis tab."""
    if not has_any(profile) and not nights: return ''
    r = analyse(nights, profile); e = html.escape
    parts = [f'<h3>Equipment</h3><p>Machine: {e(machine_text(profile, ident))}. Mask: {e(mask_text(profile))}.</p>']
    flagged = [f for f in r['findings'] if f['level'] != 'good']
    if flagged:
        parts.append('<p>Usage patterns: ' + ' '.join(f"{e(f['title'])}: {e(f['evidence'])}" for f in flagged[:4]) + '</p>')
    if r['options']:
        parts.append('<p>Worth discussing with the prescriber or supplier: ' + '; '.join(e(o['title'].lower()) for o in r['options'][:4]) + '. The Equipment tab gives the reasons and examples.</p>')
    return '\n'.join(parts)


def context_text(nights, profile, ident=None) -> str:
    """Block for the Ask Claude context."""
    r = analyse(nights, profile)
    lines = ['=== Equipment (entered by the user) ===', f'Machine: {machine_text(profile, ident)}', f'Mask: {mask_text(profile)}']
    if profile.get('mask_since'): lines.append(f"Mask in use since {profile['mask_since']}")
    for h in profile.get('history') or []: lines.append(f"Earlier mask until {h['until']}: {mask_text(h)}")
    for item, label, d in supplies_due(profile):
        if d is not None: lines.append(f"{label}: {'overdue by ' + str(-d) + ' days' if d < 0 else 'due in ' + str(d) + ' days'}")
    if profile.get('notes'): lines.append(f"User's equipment notes: {profile['notes']}")
    lines.append(f"=== Usage patterns computed by the app (last {r['n']} nights) ===")
    lines += [f"[{f['level']}] {f['title']}: {f['evidence']}" for f in r['findings']]
    lines.append('=== Options the app raised for discussion with the clinician ===')
    lines += [f"{o['title']} (from: {o.get('source') or 'general'})" for o in r['options']]
    return '\n'.join(lines)
