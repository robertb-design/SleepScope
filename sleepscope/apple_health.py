"""Apple Health import.

Reads the export the Health app produces (Profile picture > Export All Health Data > export.zip, which contains
apple_health_export/export.xml). The file can be hundreds of MB, so it is streamed with iterparse and only the
record types below are kept:

  HKCategoryTypeIdentifierSleepAnalysis     sleep stages (InBed, Awake, AsleepCore, AsleepDeep, AsleepREM, AsleepUnspecified)
  HKQuantityTypeIdentifierHeartRate         bpm
  HKQuantityTypeIdentifierOxygenSaturation  fraction (0 to 1)
  HKQuantityTypeIdentifierRespiratoryRate   breaths/min
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN  ms

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
}
STAGE = {'HKCategoryValueSleepAnalysisInBed': 'InBed', 'HKCategoryValueSleepAnalysisAwake': 'Awake',
         'HKCategoryValueSleepAnalysisAsleepCore': 'Core', 'HKCategoryValueSleepAnalysisAsleepDeep': 'Deep',
         'HKCategoryValueSleepAnalysisAsleepREM': 'REM', 'HKCategoryValueSleepAnalysisAsleepUnspecified': 'Asleep',
         'HKCategoryValueSleepAnalysisAsleep': 'Asleep'}


def _parse_dt(s):
    # "2026-10-28 23:41:12 -0400" -> naive local time (the machine's clock is also local)
    return dt.datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')


def read_export(path, date_from: dt.date | None = None, progress=None):
    """Return dict of lists: sleep [(start, end, stage, source)], hr [(t, bpm)], spo2 [(t, pct)], rr [(t, v)], hrv [(t, ms)]."""
    out = {k: [] for k in KEEP.values()}
    if path.lower().endswith('.zip'):
        z = zipfile.ZipFile(path)
        name = next((n for n in z.namelist() if n.endswith('export.xml')), None)
        if not name: raise ValueError('export.xml not found in the zip')
        f = z.open(name)
    else:
        f = open(path, 'rb')
    n = 0
    for ev, el in ET.iterparse(f, events=('end',)):
        if el.tag != 'Record':
            if el.tag not in ('Record', 'MetadataEntry', 'HeartRateVariabilityMetadataList', 'InstantaneousBeatsPerMinute'):
                el.clear()
            continue
        n += 1
        if progress and n % 200000 == 0: progress(n)
        kind = KEEP.get(el.get('type'))
        if kind:
            try:
                st = _parse_dt(el.get('startDate'))
                if date_from is None or st.date() >= date_from - dt.timedelta(days=1):
                    if kind == 'sleep':
                        out['sleep'].append((st, _parse_dt(el.get('endDate')), STAGE.get(el.get('value'), el.get('value')), el.get('sourceName', '')))
                    else:
                        v = float(el.get('value'))
                        if kind == 'spo2' and v <= 1.0: v *= 100
                        out[kind].append((st, v))
            except Exception:
                pass
        el.clear()
    f.close()
    return out


def attach(data, nights):
    """Attach per-night Apple summaries. Returns number of nights with sleep data."""
    by_night = {}
    for st, en, stage, src in data['sleep']:
        by_night.setdefault(night_date(st), {'sleep': [], 'hr': [], 'spo2': [], 'rr': [], 'hrv': []})['sleep'].append((st, en, stage, src))
    for k in ('hr', 'spo2', 'rr', 'hrv'):
        for t, v in data[k]:
            by_night.setdefault(night_date(t), {'sleep': [], 'hr': [], 'spo2': [], 'rr': [], 'hrv': []})[k].append((t, v))
    count = 0
    for nt in nights:
        d = by_night.get(nt.date)
        if not d: nt.apple = None; continue
        # prefer Watch stages over phone InBed-only records: keep the source with the most stage detail
        srcs = {}
        for st, en, stage, src in d['sleep']: srcs.setdefault(src, set()).add(stage)
        best = max(srcs, key=lambda s: len(srcs[s])) if srcs else None
        stages = [(st, en, stage) for st, en, stage, src in d['sleep'] if src == best]
        mins = lambda name: sum((en - st).total_seconds() for st, en, s in stages if s == name) / 60
        asleep = sum(mins(k) for k in ('Core', 'Deep', 'REM', 'Asleep'))
        # heart rate overnight: restrict to the window between first and last sleep record, else the whole night
        hr = sorted(d['hr']); sp = sorted(d['spo2']); hrv = d['hrv']; rr = d['rr']
        if stages:
            w0 = min(st for st, _, _ in stages); w1 = max(en for _, en, _ in stages)
            hr_n = [(t, v) for t, v in hr if w0 <= t <= w1]; sp_n = [(t, v) for t, v in sp if w0 <= t <= w1]
        else:
            hr_n, sp_n = hr, sp
        nt.apple = dict(
            stages=stages, hr=hr_n, spo2=sp_n, source=best,
            asleep_h=asleep / 60 if stages else np.nan, deep_min=mins('Deep') if stages else np.nan, rem_min=mins('REM') if stages else np.nan,
            core_min=mins('Core') if stages else np.nan, awake_min=mins('Awake') if stages else np.nan, inbed_h=mins('InBed') / 60 if stages else np.nan,
            hr_mean=float(np.mean([v for _, v in hr_n])) if hr_n else np.nan, hr_min=float(np.min([v for _, v in hr_n])) if hr_n else np.nan,
            spo2_mean=float(np.mean([v for _, v in sp_n])) if sp_n else np.nan, spo2_min=float(np.min([v for _, v in sp_n])) if sp_n else np.nan,
            hrv=float(np.mean([v for _, v in hrv])) if hrv else np.nan, rr=float(np.median([v for _, v in rr])) if rr else np.nan,
        )
        if stages or hr_n: count += 1
    return count


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
