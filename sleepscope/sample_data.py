"""Synthetic sample card in ResMed's file layout, for first-run demos and tests.

Generates DATALOG/YYYYMMDD/*_BRP.edf, _PLD.edf, _SA2.edf and _EVE.edf plus Identification.json for a made-up patient
("SAMPLE") from a breathing model: sinusoidal breaths with slow drift, scattered obstructive and central apneas and
hypopneas, flow limited stretches, a leak episode on one night, a split night, and AutoSet pressure that rises after events.
No real person's data is involved. Writing uses pyedflib; the EVE annotation file is written by hand in EDF+ format
with ResMed's convention (the stamp marks the END of each event).
"""
from __future__ import annotations
import os, json, datetime as dt, random
import numpy as np

FS = 25


def _edf_annotations(path, start: dt.datetime, events, duration_s):
    """Minimal EDF+C file with one annotation channel; events = [(onset_s, dur_s, label)], onset_s = END time (ResMed)."""
    rec_dur = 1.0; n_rec = 1
    tals = b'+0\x14\x14Recording starts\x14\x00'
    for onset, dur, lab in events:
        tals += f'+{onset:.0f}'.encode() + (f'\x15{dur:.0f}'.encode() if dur else b'') + b'\x14' + lab.encode() + b'\x14\x00'
    ns = (len(tals) + 1) // 2 + 1
    tals = tals.ljust(ns * 2, b'\x00')
    hdr = b'0'.ljust(8) + b'SAMPLE'.ljust(80) + b'Startdate X X X X'.ljust(80) + start.strftime('%d.%m.%y').encode() + start.strftime('%H.%M.%S').encode()
    hdr += str(256 + 256).encode().ljust(8) + b'EDF+C'.ljust(44) + str(n_rec).encode().ljust(8) + str(int(rec_dur)).encode().ljust(8) + b'1'.ljust(4)
    hdr += b'EDF Annotations'.ljust(16) + b''.ljust(80) + b''.ljust(8) + b'-1'.ljust(8) + b'1'.ljust(8) + b'-32768'.ljust(8) + b'32767'.ljust(8) + b''.ljust(80) + str(ns).encode().ljust(8) + b''.ljust(32)
    with open(path, 'wb') as f:
        f.write(hdr); f.write(tals)


def make_session(start: dt.datetime, hours: float, rng: random.Random, pmin=5.0, pmax=12.0, leak_episode=False, oximeter=True):
    n = int(hours * 3600 * FS); t = np.arange(n) / FS
    rr = 14 + 1.5 * np.sin(t / 900) + rng.uniform(-0.5, 0.5)
    phase = np.cumsum(rr / 60 / FS) * 2 * np.pi
    amp = 0.45 + 0.05 * np.sin(t / 1300)
    breath = np.sin(phase); breath = np.where(breath > 0, breath, 0.6 * breath)   # expiration a bit smaller, longer
    flow = amp * breath + rng.gauss(0, 0.004) * np.ones(n)
    flow += np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, 0.01, n)
    press = np.full(n, pmin); leak = np.zeros(n // (2 * FS) + 1); fl = np.zeros_like(leak)
    events = []   # (end_s, dur, label)
    # flow limitation stretches: flatten inspiration, raise FL channel
    k = 0
    while k < hours:
        if rng.random() < 0.35:
            a = int((k * 3600 + rng.uniform(0, 2400)) * FS); b = min(n, a + int(rng.uniform(120, 600) * FS))
            seg = flow[a:b]; flow[a:b] = np.where(seg > 0, np.minimum(seg, 0.22), seg)
            fl[a // (2 * FS):b // (2 * FS)] = rng.uniform(0.25, 0.6)
            press[a:] = np.minimum(pmax, press[a:] + 0.5)
        k += 1
    # events
    n_ev = int(hours * rng.uniform(0.8, 3.0))
    for _ in range(n_ev):
        s0 = rng.uniform(600, hours * 3600 - 120); kind = rng.choices(['Obstructive Apnea', 'Central Apnea', 'Hypopnea'], [5, 2, 4])[0]
        dur = rng.uniform(10, 22) if 'Apnea' in kind else rng.uniform(12, 30)
        a, b = int(s0 * FS), int((s0 + dur) * FS)
        if kind == 'Hypopnea': flow[a:b] *= 0.4
        elif kind == 'Central Apnea': flow[a:b] = np.random.default_rng(1).normal(0, 0.01, b - a)
        else: flow[a:b] = np.random.default_rng(2).normal(0, 0.02, b - a)
        flow[b:b + 3 * FS] *= 1.8   # recovery breaths
        events.append((s0 + dur, dur if 'Apnea' in kind else 0, kind))
        if rng.random() < 0.3: events.append((s0 + dur + 5, 0, 'Arousal'))
        if 'Apnea' in kind or rng.random() < 0.5: press[b:] = np.minimum(pmax, press[b:] + 1.0)
    # pressure decays slowly back toward min
    for i in range(1, len(press), 2 * FS):
        press[i:i + 2 * FS] = np.maximum(pmin, press[i - 1] - 0.02) if press[i] <= press[i - 1] else press[i:i + 2 * FS]
    press = np.minimum(press, pmax)
    # ramp
    ramp = min(n, 20 * 60 * FS); press[:ramp] = np.linspace(4.0, press[ramp - 1], ramp)
    if leak_episode:
        a = int(hours * 3600 * 0.55 / 2); b = a + 40 * 30
        leak[a:b] = 0.5 + 0.05 * np.sin(np.arange(b - a) / 20)
    leak += np.abs(np.random.default_rng(3).normal(0, 0.03, len(leak)))
    m2 = len(leak)
    p2 = press[::2 * FS][:m2]; p2 = np.pad(p2, (0, m2 - len(p2)), 'edge')
    mask = p2 - 1.0 * (0.5 + 0.5 * np.sin(np.arange(m2)))
    rr2 = np.pad(rr[::2 * FS][:m2], (0, max(0, m2 - len(rr[::2 * FS]))), 'edge')
    tv = 0.48 + 0.04 * np.sin(np.arange(m2) / 50); mv = tv * rr2
    snore = np.zeros(m2); snore[np.random.default_rng(4).random(m2) < 0.01] = 0.3
    spo2 = None; pulse = None
    if oximeter:
        m1 = int(hours * 3600); spo2 = 95.5 + np.convolve(np.random.default_rng(5).normal(0, 0.5, m1), np.ones(15) / 15, 'same'); pulse = 58 + 4 * np.sin(np.arange(m1) / 600) + np.random.default_rng(6).normal(0, 1, m1)
        for end_s, dur, lab in events:
            if lab in ('Obstructive Apnea', 'Central Apnea', 'Hypopnea'):
                c = int(end_s) + 20; spo2[max(0, c - 10):c + 15] -= rng.uniform(2, 5); pulse[c - 5:c + 10] += 8
        spo2 = np.clip(spo2, 80, 100)
    return dict(flow=flow.astype(np.float32), press=press.astype(np.float32), mask=mask, epr=p2 - 2, leak=leak, rr=rr2, tv=tv, mv=mv, snore=snore, fl=fl[:m2], spo2=spo2, pulse=pulse, events=events, n=n)


def write_card(root, nights=7, seed=7, first_date: dt.date | None = None):
    import pyedflib
    rng = random.Random(seed)
    first_date = first_date or (dt.date.today() - dt.timedelta(days=nights + 1))
    os.makedirs(os.path.join(root, 'DATALOG'), exist_ok=True)
    json.dump({'FlowGenerator': {'IdentificationProfiles': {'Product': {'SerialNumber': '00000000000', 'ProductName': 'AirSense 11 AutoSet (sample data)', 'ProductCode': '0'},
               'Software': {'ApplicationIdentifier': 'sample'}}}}, open(os.path.join(root, 'Identification.json'), 'w'))
    for d in range(nights):
        date = first_date + dt.timedelta(days=d)
        folder = os.path.join(root, 'DATALOG', date.strftime('%Y%m%d')); os.makedirs(folder, exist_ok=True)
        start = dt.datetime.combine(date, dt.time(22, rng.randint(0, 59)))
        plan = [(start, rng.uniform(5.5, 7.5))] if d != 3 else [(start, 3.2), (start + dt.timedelta(hours=3.6), 2.8)]
        pmax = 12.0 if d < 4 else 9.0
        for st, hrs in plan:
            s = make_session(st, hrs, rng, pmax=pmax, leak_episode=(d == nights - 2), oximeter=True)
            stem = os.path.join(folder, st.strftime('%Y%m%d_%H%M%S'))
            dur = int(hrs * 3600)
            def sig(label, dim, data, fs, pmin, pmax_):
                return dict(label=label, dimension=dim, sample_frequency=fs, physical_min=pmin, physical_max=pmax_, digital_min=-32768, digital_max=32767, transducer='', prefilter=''), data
            # BRP
            w = pyedflib.EdfWriter(stem + '_BRP.edf', 2, file_type=pyedflib.FILETYPE_EDFPLUS); w.setStartdatetime(st); w.setDatarecordDuration(1)
            hs, ds = zip(sig('Flow.40ms', 'L/s', s['flow'][:dur * FS], FS, -2, 2), sig('Press.40ms', 'cmH2O', s['press'][:dur * FS], FS, 0, 30))
            w.setSignalHeaders(list(hs)); w.writeSamples([np.asarray(x, dtype=np.float64) for x in ds]); w.close()
            # PLD at 0.5 Hz: record duration 2 s with 1 sample per record
            m2 = dur // 2
            chans = [('MaskPress.2s', 'cmH2O', s['mask'], 0, 30), ('Press.2s', 'cmH2O', s['press'][::2 * FS], 0, 30), ('EprPress.2s', 'cmH2O', s['epr'], 0, 30), ('Leak.2s', 'L/s', s['leak'], 0, 2),
                     ('RespRate.2s', 'bpm', s['rr'], 0, 50), ('TidVol.2s', 'L', s['tv'], 0, 3), ('MinVent.2s', 'L/min', s['mv'], 0, 30), ('Snore.2s', '', s['snore'], 0, 5), ('FlowLim.2s', '', s['fl'], 0, 1)]
            w = pyedflib.EdfWriter(stem + '_PLD.edf', len(chans), file_type=pyedflib.FILETYPE_EDFPLUS); w.setStartdatetime(st); w.setDatarecordDuration(2)
            hs = []; ds = []
            for lab, dim, data, lo, hi in chans:
                data = np.asarray(data, dtype=np.float64)[:m2]; data = np.pad(data, (0, m2 - len(data)), 'edge')
                h, _ = sig(lab, dim, data, 1, lo, hi); h['sample_frequency'] = 1; hs.append(h); ds.append(np.clip(data, lo, hi))
            w.setSignalHeaders(hs); w.writeSamples(ds); w.close()
            # SA2
            w = pyedflib.EdfWriter(stem + '_SA2.edf', 2, file_type=pyedflib.FILETYPE_EDFPLUS); w.setStartdatetime(st); w.setDatarecordDuration(1)
            hs, ds = zip(sig('Pulse.1s', 'bpm', s['pulse'][:dur], 1, -1, 250), sig('SpO2.1s', '%', s['spo2'][:dur], 1, -1, 100))
            w.setSignalHeaders(list(hs)); w.writeSamples([np.asarray(x, dtype=np.float64) for x in ds]); w.close()
            # EVE (ResMed convention: stamp = end)
            _edf_annotations(stem[:-2] + '00_EVE.edf' if False else os.path.join(folder, (st - dt.timedelta(seconds=8)).strftime('%Y%m%d_%H%M%S') + '_EVE.edf'),
                             st - dt.timedelta(seconds=8), [(e + 8, d_, l) for e, d_, l in sorted(s['events'])], dur)
    return root


if __name__ == '__main__':
    import sys
    print(write_card(sys.argv[1] if len(sys.argv) > 1 else 'sample_card'))
