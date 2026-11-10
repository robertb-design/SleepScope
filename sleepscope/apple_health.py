"""Apple Health import.

Reads the export the Health app produces (Profile picture > Export All Health Data > export.zip, which contains
apple_health_export/export.xml). The file can be hundreds of MB, so it is streamed with iterparse and only the
record types below are kept:

  HKCategoryTypeIdentifierSleepAnalysis     sleep stages (InBed, Awake, AsleepCore, AsleepDeep, AsleepREM, AsleepUnspecified)
  HKQuantityTypeIdentifierHeartRate         bpm
  HKQuantityTypeIdentifierOxygenSaturation  fraction (0 to 1)
  HKQuantityTypeIdentifierRespiratoryRate   breaths/min
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN  ms
  HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances  Watch breathing disturbances, one value per night
      (Apple reports it as an average rate per hour of sleep; verified one record per Watch night on a real export)

The export can be given as export.zip, as the unzipped apple_health_export folder, or as export.xml itself.

Each night (noon to noon) gets a dict on night.apple with the stage intervals, 1 min heart rate, SpO2 samples and summary numbers.
Writing CPAP data back into Apple Health is not possible from Windows; only an iOS app can write to HealthKit.
"""
from __future__ import annotations
import os, zipfile, datetime as dt, tempfile
import numpy as np
import xml.etree.ElementTree as ET
from .loader import night_date

KEEP = {
    'HKCategoryTypeIdentifierSleepAnalysis': 'sleep',
    'HKQuantityTypeIdentifierHeartRate': 'hr',
    'HKQuantityTypeIdentifierOxygenSaturation': 'spo2',
    'HKQuantityTypeIdentifierRespiratoryRate': 'rr',
    'HKQuantityTypeIdentifierHeartRateVariabilitySDNN': 'hrv',
    'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances': 'bd',
}
EMPTY = lambda: {k: [] for k in KEEP.values()}
STAGE = {'HKCategoryValueSleepAnalysisInBed': 'InBed', 'HKCategoryValueSleepAnalysisAwake': 'Awake',
         'HKCategoryValueSleepAnalysisAsleepCore': 'Core', 'HKCategoryValueSleepAnalysisAsleepDeep': 'Deep',
         'HKCategoryValueSleepAnalysisAsleepREM': 'REM', 'HKCategoryValueSleepAnalysisAsleepUnspecified': 'Asleep',
         'HKCategoryValueSleepAnalysisAsleep': 'Asleep'}


def _parse_dt(s):
    # "2026-10-28 23:41:12 -0400" -> naive local time (the machine's clock is also local)
    return dt.datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')


def export_xml_path(path):
    """Resolve export.zip, an unzipped apple_health_export folder (or its parent), or export.xml. Returns (kind, path)."""
    if os.path.isdir(path):
        for c in (os.path.join(path, 'export.xml'), os.path.join(path, 'apple_health_export', 'export.xml')):
            if os.path.isfile(c): return 'xml', c
        raise ValueError('export.xml not found in that folder')
    return ('zip' if path.lower().endswith('.zip') else 'xml'), path


def read_export(path, date_from: dt.date | None = None, progress=None):
    """Return dict of lists: sleep [(start, end, stage, source)], hr/spo2/rr/hrv/bd [(t, value)].
    Streams the file line by line with a regex (Apple writes one Record per line), which is several times faster
    than a full XML parse and keeps memory flat on exports of hundreds of MB."""
    import re
    out = EMPTY()
    kind, p = export_xml_path(path)
    if kind == 'zip':
        z = zipfile.ZipFile(p)
        name = next((n for n in z.namelist() if n.endswith('export.xml') and '__MACOSX' not in n), None)
        if not name: raise ValueError('export.xml not found in the zip')
        f = z.open(name)
    else:
        f = open(p, 'rb')
    typ_re = re.compile(rb'<Record type="([^"]+)"')
    att = {k: re.compile(k.encode() + rb'="([^"]*)"') for k in ('startDate', 'endDate', 'value', 'sourceName')}
    keep = {k.encode(): v for k, v in KEEP.items()}
    cutoff = (date_from - dt.timedelta(days=1)).strftime('%Y-%m-%d').encode() if date_from else b''
    n = 0
    for line in f:
        m = typ_re.search(line)
        if not m: continue
        n += 1
        if progress and n % 200000 == 0: progress(n)
        k = keep.get(m.group(1))
        if not k: continue
        try:
            sd = att['startDate'].search(line).group(1)
            if sd[:10] < cutoff: continue
            st = _parse_dt(sd.decode())
            val = att['value'].search(line).group(1).decode('utf-8', 'ignore')
            if k == 'sleep':
                src = att['sourceName'].search(line); src = src.group(1).decode('utf-8', 'ignore') if src else ''
                stage = val.replace('HKCategoryValueSleepAnalysis', ''); stage = STAGE.get('HKCategoryValueSleepAnalysis' + stage, stage)
                out['sleep'].append((st, _parse_dt(att['endDate'].search(line).group(1).decode()), stage, src))
            else:
                v = float(val)
                if k == 'spo2' and v <= 1.0: v *= 100
                out[k].append((st, v))
        except Exception:
            pass
    f.close()
    for key in out: out[key].sort()
    return out


def to_sync(data, since: dt.date | None = None):
    """Compact JSON-ready copy for the phone (written into SleepScope card.zip as health.json). Times are local wall clock text."""
    f = lambda t: t.strftime('%Y-%m-%d %H:%M:%S')
    lim = dt.datetime.combine(since, dt.time()) - dt.timedelta(days=1) if since else dt.datetime.min
    o = {'sleep': [{'s': f(a), 'e': f(b), 'stage': c, 'src': d} for a, b, c, d in data['sleep'] if a >= lim]}
    for k in ('hr', 'spo2', 'rr', 'hrv', 'bd'): o[k] = [[f(t), round(v, 3)] for t, v in data.get(k, []) if t >= lim]
    return o


def read_shortcut_csv(path):
    """Read the small file the SleepScope Health Shortcut writes on the phone: one line per record,
    type,start,end,value (Shortcuts' default date wording such as "Nov 1, 2026 at 1:20 AM" is accepted, so is yyyy-MM-dd HH:mm:ss).
    Returns the same dict shape as read_export."""
    import re
    out = EMPTY()
    MON = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
    def pdate(x):
        x = re.sub(r'\s+', ' ', x.strip().replace(' at ', ' ')).replace('\u202f', ' ')
        for f in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y %H:%M:%S', '%m/%d/%y %I:%M %p', '%m/%d/%Y %I:%M %p'):
            try: return dt.datetime.strptime(x, f)
            except ValueError: pass
        m = re.match(r'^([A-Za-z]{3})[a-z]*\.? (\d{1,2}),? (\d{4}) (\d{1,2}):(\d{2})(?::(\d{2}))? ?([AaPp][Mm])?$', x)
        if m and m.group(1).lower() in MON:
            h = int(m.group(4)); ap = (m.group(7) or '').lower()
            if ap == 'pm' and h < 12: h += 12
            if ap == 'am' and h == 12: h = 0
            return dt.datetime(int(m.group(3)), MON[m.group(1).lower()], int(m.group(2)), h, int(m.group(5)), int(m.group(6) or 0))
        return None
    def split(line):
        cells, cur, q = [], '', False
        for ch in line:
            if ch == '"': q = not q
            elif ch == ',' and not q: cells.append(cur); cur = ''
            else: cur += ch
        cells.append(cur)
        merged = []; i = 0
        while i < len(cells):                                          # re-join "Nov 1" + " 2026 at ..." split by the comma in the date
            t = cells[i].strip()
            if re.match(r'^[A-Za-z]{3,9}\.? \d{1,2}$', t) and i + 1 < len(cells) and re.match(r'^\s*\d{4}', cells[i + 1]): merged.append(t + ', ' + cells[i + 1].strip()); i += 2
            else: merged.append(cells[i]); i += 1
        return merged
    for line in open(path, 'r', encoding='utf-8-sig', errors='ignore'):
        c = split(line.rstrip('\n'))
        if len(c) < 4: continue
        typ = c[0].strip().lower()
        if typ in ('type',): continue
        sd = pdate(c[1]); ed = pdate(c[2]); raw = c[3].strip()
        if sd is None: continue
        if 'sleep' in typ:
            if ed is None: continue
            v = raw.lower(); stage = 'Deep' if 'deep' in v else 'REM' if 'rem' in v else 'Core' if 'core' in v else 'Awake' if 'awake' in v else 'InBed' if 'bed' in v else 'Asleep'
            out['sleep'].append((sd, ed, stage, 'Shortcut'))
        else:
            try: v = float(re.sub(r'[^\d.\-]', '', raw))
            except ValueError: continue
            k = 'hrv' if ('heart rate var' in typ or 'hrv' in typ) else 'hr' if 'heart' in typ else 'spo2' if ('oxygen' in typ or 'spo2' in typ) else 'rr' if 'respir' in typ else None
            if not k: continue
            if k == 'spo2' and v <= 1: v *= 100
            out[k].append((sd, v))
    for k in ('hr', 'spo2', 'rr', 'hrv'): out[k].sort()
    out['sleep'].sort()
    return out


def attach(data, nights):
    """Attach per-night Apple summaries to night.apple and refresh the Watch columns in night.stats. Returns nights matched."""
    keys = ('hr', 'spo2', 'rr', 'hrv', 'bd')
    new = lambda: {'sleep': [], **{k: [] for k in keys}}
    by_night = {}
    for st, en, stage, src in data['sleep']:
        by_night.setdefault(night_date(st), new())['sleep'].append((st, en, stage, src))
    for k in keys:
        for t, v in data.get(k, []):
            by_night.setdefault(night_date(t), new())[k].append((t, v))
    count = 0
    for nt in nights:
        d = by_night.get(nt.date)
        if not d: nt.apple = None; _refresh_stats(nt); continue
        # prefer Watch stages over phone InBed-only records: keep the source with the most stage detail
        srcs = {}
        for st, en, stage, src in d['sleep']: srcs.setdefault(src, set()).add(stage)
        best = max(srcs, key=lambda s: len(srcs[s])) if srcs else None
        stages = [(st, en, stage) for st, en, stage, src in d['sleep'] if src == best]
        mins = lambda name: sum((en - st).total_seconds() for st, en, s in stages if s == name) / 60
        asleep = sum(mins(k) for k in ('Core', 'Deep', 'REM', 'Asleep'))
        hr = sorted(d['hr']); sp = sorted(d['spo2']); hrv = d['hrv']; rr = d['rr']
        if stages:
            w0 = min(st for st, _, _ in stages); w1 = max(en for _, en, _ in stages)
            hr_n = [(t, v) for t, v in hr if w0 <= t <= w1]; sp_n = [(t, v) for t, v in sp if w0 <= t <= w1]
            hrv = [(t, v) for t, v in hrv if w0 - dt.timedelta(hours=1) <= t <= w1 + dt.timedelta(hours=1)]; rr = [(t, v) for t, v in rr if w0 <= t <= w1]
        else:
            hr_n, sp_n = hr, sp
        # share of Watch sleep that happened with the mask on: overlap of asleep stages with the machine sessions
        cover = np.nan
        if stages and asleep > 0:
            if nt.sessions:
                ses = [(s.start, s.end) for s in nt.sessions]
                ov = 0.0
                for st, en, stg in stages:
                    if stg not in ('Core', 'Deep', 'REM', 'Asleep'): continue
                    for a0, a1 in ses:
                        lo, hi = max(st, a0), min(en, a1)
                        if hi > lo: ov += (hi - lo).total_seconds() / 60
                cover = min(100.0, 100 * ov / asleep)
            elif nt.hours:
                cover = min(100.0, 100 * nt.hours * 60 / asleep)
        bd = [v for _, v in d['bd']]
        if not stages and not bd:                                     # daytime samples only: the Watch was not worn to bed
            nt.apple = None; _refresh_stats(nt); continue
        nt.apple = dict(
            stages=stages, hr=hr_n, spo2=sp_n, source=best,
            asleep_h=asleep / 60 if stages else np.nan, deep_min=mins('Deep') if stages else np.nan, rem_min=mins('REM') if stages else np.nan,
            core_min=mins('Core') if stages else np.nan, awake_min=mins('Awake') if stages else np.nan, inbed_h=mins('InBed') / 60 if stages else np.nan,
            hr_mean=float(np.mean([v for _, v in hr_n])) if hr_n else np.nan, hr_min=float(np.min([v for _, v in hr_n])) if hr_n else np.nan,
            spo2_mean=float(np.mean([v for _, v in sp_n])) if sp_n else np.nan, spo2_min=float(np.min([v for _, v in sp_n])) if sp_n else np.nan,
            hrv=float(np.mean([v for _, v in hrv])) if hrv else np.nan, rr=float(np.median([v for _, v in rr])) if rr else np.nan,
            bd=float(np.mean(bd)) if bd else np.nan, cover_pct=cover,
        )
        _refresh_stats(nt)
        count += 1
    return count


def watch_fields(nt):
    """The Watch columns for the nights table (NaN when there is no Watch data for the night)."""
    a = getattr(nt, 'apple', None) or {}
    g = lambda k: a.get(k, np.nan)
    dr = g('deep_min') + g('rem_min') if a.get('stages') else np.nan
    return dict(w_bd=g('bd'), w_asleep=g('asleep_h') if a.get('stages') else np.nan, w_cover=g('cover_pct'), w_deeprem=dr, w_hrv=g('hrv'), w_rr=g('rr'))


def _refresh_stats(nt):
    if isinstance(getattr(nt, 'stats', None), dict) and nt.stats: nt.stats.update(watch_fields(nt))


def write_sample_export(path, nights):
    """Create a small synthetic export.xml for testing the importer (dev use only)."""
    rows = ['<?xml version="1.0" encoding="UTF-8"?>', '<HealthData locale="en_US">']
    for nt in nights:
        s = nt.sessions[0]; t = s.start - dt.timedelta(minutes=20); end = nt.sessions[-1].end + dt.timedelta(minutes=40)
        rows.append(f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" value="HKCategoryValueSleepAnalysisInBed" startDate="{t:%Y-%m-%d %H:%M:%S} -0400" endDate="{end:%Y-%m-%d %H:%M:%S} -0400"/>')
        cur = t; i = 0
        while cur < end:
            stage = ['Core', 'Deep', 'Core', 'REM', 'Awake'][i % 5]; dur = [40, 25, 35, 20, 4][i % 5]
            e = min(end, cur + dt.timedelta(minutes=dur))
            rows.append(f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" value="HKCategoryValueSleepAnalysisAsleep{stage if stage != "Awake" else ""}{"" if stage != "Awake" else ""}" startDate="{cur:%Y-%m-%d %H:%M:%S} -0400" endDate="{e:%Y-%m-%d %H:%M:%S} -0400"/>'.replace('AsleepAwake', 'Awake').replace('SleepAnalysisAsleep"', 'SleepAnalysisAwake"') if stage == 'Awake' else
                        f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Apple Watch" value="HKCategoryValueSleepAnalysisAsleep{stage}" startDate="{cur:%Y-%m-%d %H:%M:%S} -0400" endDate="{e:%Y-%m-%d %H:%M:%S} -0400"/>')
            cur = e; i += 1
        cur = t
        while cur < end:
            rows.append(f'<Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch" unit="count/min" value="{55 + 8 * np.random.rand():.0f}" startDate="{cur:%Y-%m-%d %H:%M:%S} -0400" endDate="{cur:%Y-%m-%d %H:%M:%S} -0400"/>')
            if i % 7 == 0: rows.append(f'<Record type="HKQuantityTypeIdentifierOxygenSaturation" sourceName="Apple Watch" unit="%" value="{0.93 + 0.05 * np.random.rand():.2f}" startDate="{cur:%Y-%m-%d %H:%M:%S} -0400" endDate="{cur:%Y-%m-%d %H:%M:%S} -0400"/>')
            cur += dt.timedelta(minutes=2); i += 1
        rows.append(f'<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" sourceName="Apple Watch" unit="ms" value="38" startDate="{t + dt.timedelta(hours=2):%Y-%m-%d %H:%M:%S} -0400" endDate="{t + dt.timedelta(hours=2):%Y-%m-%d %H:%M:%S} -0400"/>')
    rows.append('</HealthData>')
    open(path, 'w').write('\n'.join(rows))
