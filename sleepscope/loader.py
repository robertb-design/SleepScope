"""ResMed SD card loader.

Reads the AirSense 10/11 card layout:
  Identification.json / Identification.tgt   device identity
  STR.edf                                     per day summary (settings, machine AHI, leak percentiles)
  DATALOG/YYYYMMDD/*_BRP.edf                  flow + pressure, 25 Hz
  DATALOG/YYYYMMDD/*_PLD.edf                  2 s channels: mask pressure, set pressure, EPR, leak, RR, Vt, MV, snore, flow limitation
  DATALOG/YYYYMMDD/*_SA2.edf                  1 s SpO2 + pulse (only when an oximeter is attached; reads -1 otherwise)
  DATALOG/YYYYMMDD/*_EVE.edf                  event annotations. ResMed stamps the END of each event; onset = stamp - duration.
  DATALOG/YYYYMMDD/*_CSL.edf                  Cheyne-Stokes annotations (same convention)

pyedflib refuses EDF+D files, so the annotation files are parsed by hand.
"""
from __future__ import annotations
import os, re, json, glob, datetime as dt
from dataclasses import dataclass, field
import numpy as np

try:
    import pyedflib
except ImportError:  # pragma: no cover
    pyedflib = None

NIGHT_CUTOFF_HOUR = 12   # sessions before noon belong to the previous calendar night


def _edf_header(path):
    with open(path, 'rb') as f:
        b = f.read(256)
    d = b[168:176].decode('latin1'); t = b[176:184].decode('latin1')
    dd, mm, yy = d.split('.'); yy = int(yy); yy += 2000 if yy < 85 else 1900
    start = dt.datetime(yy, int(mm), int(dd), *map(int, t.split('.')))
    hdr_bytes = int(b[184:192]); n_rec = int(b[236:244]); rec_dur = float(b[244:252]); n_sig = int(b[252:256])
    return start, hdr_bytes, n_rec, rec_dur, n_sig


def parse_annotations(path):
    """Return list of (end_time: datetime, duration_s: float, label: str). ResMed stamps event END."""
    start, hdr, *_ = _edf_header(path)
    with open(path, 'rb') as f:
        f.seek(hdr); data = f.read()
    out = []
    for m in re.finditer(rb'([+-]\d+(?:\.\d+)?)(?:\x15(\d+(?:\.\d+)?))?\x14([^\x14\x00]*)\x14', data):
        txt = m.group(3).decode('latin1').strip()
        if not txt or txt == 'Recording starts':
            continue
        onset = float(m.group(1)); dur = float(m.group(2)) if m.group(2) else 0.0
        out.append((start + dt.timedelta(seconds=onset), dur, txt))
    return out


@dataclass
class Event:
    label: str          # Obstructive Apnea, Central Apnea, Hypopnea, Arousal, RERA, Unclassified Apnea, Flow Limitation Run ...
    start: dt.datetime
    duration: float
    source: str         # 'machine' or 'app'
    detail: str = ''
    @property
    def end(self): return self.start + dt.timedelta(seconds=self.duration)


@dataclass
class Session:
    start: dt.datetime
    duration: float
    folder: str
    stem: str
    flow: np.ndarray | None = None       # L/s, 25 Hz
    press: np.ndarray | None = None      # cmH2O, 25 Hz
    fs: float = 25.0
    ch: dict = field(default_factory=dict)  # 2 s channels, keyed MaskPress, Press, EprPress, Leak, RespRate, TidVol, MinVent, Snore, FlowLim
    spo2: np.ndarray | None = None
    pulse: np.ndarray | None = None
    machine_events: list = field(default_factory=list)
    app_events: list = field(default_factory=list)
    breaths: dict | None = None
    @property
    def end(self): return self.start + dt.timedelta(seconds=self.duration)
    @property
    def has_oximetry(self):
        return self.spo2 is not None and np.any(self.spo2 > 0)


@dataclass
class Night:
    date: dt.date
    sessions: list
    stats: dict = field(default_factory=dict)
    apple: dict | None = None
    @property
    def hours(self): return sum(s.duration for s in self.sessions) / 3600.0
    @property
    def label(self): return self.date.strftime('%a %m/%d')


def night_date(t: dt.datetime) -> dt.date:
    return (t - dt.timedelta(hours=NIGHT_CUTOFF_HOUR)).date()


def read_identification(root):
    for name in ('Identification.json', 'Identification.tgt'):
        p = os.path.join(root, name)
        if os.path.exists(p):
            try:
                if name.endswith('.json'):
                    j = json.load(open(p))
                    prod = j['FlowGenerator']['IdentificationProfiles']['Product']
                    sw = j['FlowGenerator']['IdentificationProfiles']['Software']
                    return {'model': prod.get('ProductName'), 'serial': prod.get('SerialNumber'),
                            'firmware': sw.get('ApplicationIdentifier'), 'file': p}
                txt = open(p, 'r', errors='ignore').read()
                d = dict(re.findall(r'#(\w+)\s+(.+)', txt))
                return {'model': d.get('PNA', '').replace('_', ' '), 'serial': d.get('SRN'), 'firmware': d.get('PVR'), 'file': p}
            except Exception as e:
                return {'model': '?', 'serial': '?', 'firmware': '?', 'file': p, 'error': str(e)}
    return {}


def read_str(root):
    """STR.edf: one record per day. Returns {'days': [date...], 'signals': {label: array}} or None.
    Labels differ by firmware; the UI shows all of them. Common ones: MaskOn, MaskOff, Mode, S.AS.MinPress, S.AS.MaxPress,
    S.C.Press, S.EPR.Level, AHI, AI, HI, CAI, OAI, Leak.50, Leak.95, Leak.Max, MaskPress.50, MaskPress.95, Duration."""
    p = os.path.join(root, 'STR.edf')
    if not os.path.exists(p) or pyedflib is None:
        return None
    try:
        r = pyedflib.EdfReader(p)
        start = r.getStartdatetime(); n = r.datarecords_in_file
        sig = {}
        for i in range(r.signals_in_file):
            lab = r.getLabel(i)
            if 'Crc' in lab: continue
            sig[lab] = r.readSignal(i)
        r.close()
        days = [(start + dt.timedelta(days=i)).date() for i in range(n)]
        return {'days': days, 'signals': sig, 'start': start}
    except Exception as e:
        return {'error': str(e)}


def load_session(brp_path, want_waveforms=True):
    stem = brp_path[:-8]
    folder = os.path.dirname(brp_path)
    start, hdr, n_rec, rec_dur, n_sig = _edf_header(brp_path)
    dur = n_rec * rec_dur
    s = Session(start=start, duration=dur, folder=folder, stem=stem)
    if pyedflib is None:
        return s
    if want_waveforms:
        r = pyedflib.EdfReader(brp_path)
        for i in range(r.signals_in_file):
            lab = r.getLabel(i)
            if lab.startswith('Flow'): s.flow = r.readSignal(i).astype(np.float32); s.fs = r.getSampleFrequency(i)
            elif lab.startswith('Press'): s.press = r.readSignal(i).astype(np.float32)
        r.close()
    pld = stem + '_PLD.edf'
    if os.path.exists(pld):
        r = pyedflib.EdfReader(pld)
        for i in range(r.signals_in_file):
            lab = r.getLabel(i)
            if 'Crc' in lab: continue
            s.ch[lab.split('.')[0]] = r.readSignal(i).astype(np.float32)
        r.close()
    sa = stem + '_SA2.edf'
    if not os.path.exists(sa): sa = stem + '_SAD.edf'
    if os.path.exists(sa):
        try:
            r = pyedflib.EdfReader(sa)
            for i in range(r.signals_in_file):
                lab = r.getLabel(i)
                if lab.startswith('Pulse'): s.pulse = r.readSignal(i).astype(np.float32)
                elif lab.startswith('SpO2'): s.spo2 = r.readSignal(i).astype(np.float32)
            r.close()
        except Exception:
            pass
    # events: EVE/CSL files whose start is within 90 s before this session start
    for ann in glob.glob(os.path.join(folder, '*_EVE.edf')) + glob.glob(os.path.join(folder, '*_CSL.edf')):
        try:
            es, *_ = _edf_header(ann)
        except Exception:
            continue
        if -5 <= (start - es).total_seconds() <= 90:
            for end, d, lab in parse_annotations(ann):
                s.machine_events.append(Event(lab, end - dt.timedelta(seconds=d), d, 'machine'))
    s.machine_events.sort(key=lambda e: e.start)
    return s


def scan(root, min_session_s=300, progress=None):
    """root may be the card root (contains DATALOG) or the DATALOG folder itself."""
    root = root.rstrip('\\/')
    if os.path.basename(root).upper() == 'DATALOG':
        datalog, card_root = root, os.path.dirname(root)
    elif os.path.isdir(os.path.join(root, 'DATALOG')):
        datalog, card_root = os.path.join(root, 'DATALOG'), root
    elif glob.glob(os.path.join(root, '*', '*_BRP.edf')):      # a copy of the date folders without the DATALOG wrapper
        datalog, card_root = root, root
    elif glob.glob(os.path.join(root, '*_BRP.edf')):          # a single date folder
        datalog, card_root = os.path.dirname(root), os.path.dirname(os.path.dirname(root))
    else:
        datalog, card_root = os.path.join(root, 'DATALOG'), root
    brps = sorted(glob.glob(os.path.join(datalog, '*', '*_BRP.edf')))
    sessions = []
    for i, b in enumerate(brps):
        if progress: progress(i, len(brps), os.path.basename(b))
        try:
            _, _, n_rec, rec_dur, _ = _edf_header(b)
        except Exception:
            continue
        if n_rec * rec_dur < min_session_s:
            continue
        sessions.append(load_session(b))
    nights = {}
    for s in sessions:
        nights.setdefault(night_date(s.start), []).append(s)
    out = [Night(d, sorted(ss, key=lambda s: s.start)) for d, ss in sorted(nights.items())]
    return {'root': card_root, 'datalog': datalog, 'identification': read_identification(card_root),
            'str': read_str(card_root), 'nights': out}


# ----------------------------------------------------------------------------- external oximeter CSV (Wellue O2Ring, Checkme, generic)
def import_oximeter_csv(path, nights):
    """Attach SpO2/pulse from a CSV export to matching sessions (resampled to 1 Hz over each session).
    Accepts Wellue/Viatom exports (columns like Time, Oxygen Level, Pulse Rate) and any CSV with a timestamp
    column plus columns containing 'spo2'/'oxygen' and 'pulse'/'hr'. Returns number of sessions filled."""
    import csv
    rows = list(csv.reader(open(path, 'r', encoding='utf-8-sig', errors='ignore')))
    if not rows: return 0
    hdr = [h.strip().lower() for h in rows[0]]
    def col(*keys):
        for i, h in enumerate(hdr):
            if any(k in h for k in keys): return i
        return None
    ti, si, pi = col('time', 'date'), col('spo2', 'oxygen', 'o2'), col('pulse', 'hr', 'heart')
    if ti is None or si is None: return 0
    fmts = ['%H:%M:%S %m/%d/%Y', '%I:%M:%S %p %m/%d/%Y', '%m/%d/%Y %I:%M:%S %p', '%Y-%m-%d %I:%M:%S %p', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%H:%M:%S %d/%m/%Y', '%Y-%m-%dT%H:%M:%S']
    ts, sp, pu = [], [], []
    fmt = None
    for r in rows[1:]:
        if len(r) <= max(ti, si): continue
        raw = r[ti].strip()
        t = None
        if fmt:
            try: t = dt.datetime.strptime(raw, fmt)
            except ValueError: t = None
        if t is None:
            for f in fmts:
                try: t = dt.datetime.strptime(raw, f); fmt = f; break
                except ValueError: continue
        if t is None: continue
        try: s = float(r[si])
        except ValueError: continue
        try: p = float(r[pi]) if pi is not None else np.nan
        except ValueError: p = np.nan
        ts.append(t); sp.append(s); pu.append(p)
    if not ts: return 0
    ts = np.array([t.timestamp() for t in ts]); sp = np.array(sp); pu = np.array(pu)
    filled = 0
    for nt in nights:
        for s in nt.sessions:
            a, b = s.start.timestamp(), s.end.timestamp()
            m = (ts >= a - 60) & (ts <= b + 60)
            if m.sum() < 30: continue
            grid = a + np.arange(int(s.duration))
            s.spo2 = np.interp(grid, ts[m], sp[m], left=np.nan, right=np.nan).astype(np.float32)
            s.pulse = np.interp(grid, ts[m], pu[m], left=np.nan, right=np.nan).astype(np.float32)
            s.spo2 = np.nan_to_num(s.spo2, nan=-1); s.pulse = np.nan_to_num(s.pulse, nan=-1)
            filled += 1
    return filled
