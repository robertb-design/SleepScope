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
    summary_only: bool = False          # card was out: only the machine's daily summary (STR.edf) exists
    str_summary: dict | None = None
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
    st = read_str(card_root)
    out = sorted(out + summary_nights(st, out), key=lambda n: n.date)
    return {'root': card_root, 'datalog': datalog, 'identification': read_identification(card_root),
            'str': st, 'nights': out}


# ----------------------------------------------------------------------------- external oximeter CSV (Wellue O2Ring, Checkme, generic)
O2RING_RAW_NAME = re.compile(r'^\d{14}$')


def is_o2ring_raw(path):
    """A recording as saved by Wellue O2 Insight Pro: file named yyyymmddHHMMSS (no extension), 10 byte header starting
    01 03, then 3 bytes per second (SpO2 %, pulse bpm, motion; 255 = no reading), then a 48 byte footer.
    Verified against ViHealth CSV exports of the same nights, every second identical."""
    if not O2RING_RAW_NAME.match(os.path.basename(path)): return False
    try:
        if os.path.getsize(path) < 58 + 3 * 60: return False
        with open(path, 'rb') as f: h = f.read(2)
        return h == b'\x01\x03'
    except OSError:
        return False


def import_o2ring_raw(path, nights):
    d = open(path, 'rb').read()
    n = (len(d) - 58) // 3 if (len(d) - 58) % 3 == 0 else (len(d) - 10) // 3
    a = np.frombuffer(d[10:10 + 3 * n], dtype=np.uint8).reshape(n, 3).astype(float)
    t0 = dt.datetime.strptime(os.path.basename(path), '%Y%m%d%H%M%S').timestamp()
    sp, pu, mo = a[:, 0], a[:, 1], a[:, 2]
    sp[(sp == 255) | (sp < 50) | (sp > 100)] = np.nan; pu[(pu == 255) | (pu < 25)] = np.nan; mo[mo == 255] = np.nan
    return _attach_oximetry(t0 + np.arange(n, dtype=float), sp, pu, mo, np.zeros(n), True, False, nights)


def import_oximeter_csv(path, nights):
    if is_o2ring_raw(path): return import_o2ring_raw(path, nights)
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
    mi = col('motion', 'movement', 'activity'); ai = [i for i, h in enumerate(hdr) if 'reminder' in h or 'alarm' in h or 'vibrat' in h]
    if ti is None or si is None: return 0
    fmts = ['%H:%M:%S %b %d %Y', '%I:%M:%S %p %b %d %Y', '%I:%M:%S%p %b %d, %Y', '%I:%M:%S %p %b %d, %Y', '%H:%M:%S %b %d, %Y', '%b %d %Y %H:%M:%S', '%d %b %Y %H:%M:%S', '%H:%M:%S %m/%d/%Y', '%I:%M:%S %p %m/%d/%Y', '%m/%d/%Y %I:%M:%S %p', '%Y-%m-%d %I:%M:%S %p', '%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%d/%m/%Y %H:%M:%S', '%H:%M:%S %d/%m/%Y', '%Y-%m-%dT%H:%M:%S']
    ts, sp, pu, mo, al = [], [], [], [], []
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
        if not 50 <= s <= 100: s = np.nan          # O2 Insight Pro writes 255 for no reading; ViHealth writes --
        try: p = float(r[pi]) if pi is not None else np.nan
        except ValueError: p = np.nan
        if not 25 <= p <= 250: p = np.nan
        try: mv = float(r[mi]) if mi is not None and len(r) > mi else np.nan
        except ValueError: mv = np.nan
        flag = 0.0
        for i in ai:
            try: flag = max(flag, float(r[i]) if len(r) > i and r[i].strip() not in ('', '--') else 0.0)
            except ValueError: pass
        ts.append(t); sp.append(s); pu.append(p); mo.append(mv); al.append(flag)
    if not ts: return 0
    ts = np.array([t.timestamp() for t in ts]); sp = np.array(sp); pu = np.array(pu); mo = np.array(mo); al = np.array(al)
    return _attach_oximetry(ts, sp, pu, mo, al, mi is not None, bool(ai), nights)


def _attach_oximetry(ts, sp, pu, mo, al, has_motion, has_alerts, nights):
    """Resample 1 Hz oximeter samples (epoch seconds) onto each overlapping session. Returns sessions filled."""
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
            if has_motion and np.any(~np.isnan(mo[m])):
                s.motion = np.nan_to_num(np.interp(grid, ts[m], np.nan_to_num(mo[m], nan=0.0), left=np.nan, right=np.nan), nan=-1).astype(np.float32)
            else: s.motion = None
            s.ox_alerts = [dt.datetime.fromtimestamp(float(t)) for t in ts[m][al[m] > 0]] if has_alerts else []
            filled += 1
    return filled


# ----------------------------------------------------------------------------- find companion files near the card
def find_companion_files(folders, max_depth=2):
    """Look through the given folders (a few levels deep) for oximeter CSV exports (Wellue O2Ring and similar: a header
    with a time column and an oxygen/SpO2 column) and SleepScope Health Shortcut files. Returns (oximeter_paths, health_paths)."""
    ox, health = [], []
    seen = set()
    for folder in folders:
        if not folder or not os.path.isdir(folder): continue
        folder = os.path.abspath(folder)
        if folder in seen: continue
        seen.add(folder); base_depth = folder.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(folder):
            if dirpath.count(os.sep) - base_depth >= max_depth: dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d.lower() not in ('datalog', 'node_modules', 'appdata')]
            for fn in filenames:
                low = fn.lower()
                path = os.path.join(dirpath, fn)
                if O2RING_RAW_NAME.match(fn):
                    if is_o2ring_raw(path): ox.append(path)
                    continue
                if not low.endswith(('.csv', '.txt')): continue
                try:
                    if os.path.getsize(path) > 200 * 1024 * 1024: continue
                    with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f: head = f.readline().lower()
                except OSError: continue
                if ('oxygen' in head or 'spo2' in head) and ('time' in head or 'date' in head): ox.append(path)
                elif low.endswith('.txt') and (head.startswith('sleep,') or head.startswith('heart rate,') or head.startswith('blood oxygen,')): health.append(path)
    return sorted(set(ox)), sorted(set(health))


# ----------------------------------------------------------------------------- nights the card missed: machine summary from STR.edf
def str_day(str_data, label, i):
    """All samples of one STR signal for day index i (some signals, such as MaskOn and MaskOff, carry several per day)."""
    sig = str_data['signals'].get(label); n = len(str_data['days'])
    if sig is None or n == 0: return np.array([])
    spr = max(1, len(sig) // n)
    return np.asarray(sig[i * spr:(i + 1) * spr], dtype=float)


def _str_label(sig, *names):
    low = {k.lower(): k for k in sig}
    for nm in names:
        if nm.lower() in low: return low[nm.lower()]
    return None


def summary_nights(str_data, nights):
    """Nights inside the loaded range that have a machine summary in STR.edf but no DATALOG files (card was out).
    Sessions come from the MaskOn/MaskOff minutes (counted from the STR day start, noon); if those are missing or
    disagree with the day's duration, one session of the right length is placed at 22:00."""
    if not (str_data and 'signals' in str_data and nights): return []
    sig = str_data['signals']; days = str_data['days']; have = {n.date for n in nights}
    lo, hi = min(have), max(have)
    t0 = str_data.get('start').time() if str_data.get('start') else dt.time(12)
    L = lambda *a: _str_label(sig, *a)
    ldur, lon, loff = L('Duration', 'OnDuration'), L('MaskOn'), L('MaskOff')
    def v1(lab, i):
        if not lab: return np.nan
        x = str_day(str_data, lab, i); x = x[np.isfinite(x)]
        return float(x[0]) if len(x) else np.nan
    out = []
    for i, d in enumerate(days):
        if d in have or d < lo or d > hi: continue
        dur = v1(ldur, i)
        if not np.isfinite(dur) or dur < 5: continue          # minutes
        day0 = dt.datetime.combine(d, t0); sess = []
        if lon and loff:
            for a, b in zip(str_day(str_data, lon, i), str_day(str_data, loff, i)):
                if np.isfinite(a) and np.isfinite(b) and a >= 0 and b > a and b <= 1440:
                    sess.append(Session(start=day0 + dt.timedelta(minutes=float(a)), duration=float(b - a) * 60, folder='', stem='STR'))
        if not sess or abs(sum(s.duration for s in sess) / 60 - dur) > max(20, 0.25 * dur):
            sess = [Session(start=dt.datetime.combine(d, dt.time(22)), duration=dur * 60, folder='', stem='STR')]
        def g(*names):
            return v1(L(*names), i)
        lk = [g('Leak.50'), g('Leak.95'), g('Leak.Max')]
        if all(not np.isfinite(x) or x < 3 for x in lk): lk = [x * 60 if np.isfinite(x) else x for x in lk]   # L/s to L/min
        tv = g('TidVol.50'); tv = tv * 1000 if np.isfinite(tv) and tv < 5 else tv
        nt = Night(d, sess, summary_only=True)
        nt.str_summary = dict(hours=dur / 60, AHI=g('AHI'), AI=g('AI'), HI=g('HI'), OAI=g('OAI'), CAI=g('CAI'), UAI=g('UAI'),
                              leak_med=lk[0], leak_95=lk[1], leak_max=lk[2], press_med=g('MaskPress.50'), press_95=g('MaskPress.95'),
                              press_max=g('MaskPress.Max'), rr_med=g('RespRate.50'), tv_med=tv, mv_med=g('MinVent.50'),
                              exact_times=sess[0].start != dt.datetime.combine(d, dt.time(22)))
        out.append(nt)
    return out
