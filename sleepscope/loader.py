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
import os, zipfile, re, json, glob, datetime as dt
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
    no_mask: bool = False               # no CPAP this night: ring and/or Watch only; sessions are stand-ins spanning the recording
    @property
    def hours(self): return 0.0 if self.no_mask else sum(s.duration for s in self.sessions) / 3600.0
    @property
    def span_hours(self): return sum(s.duration for s in self.sessions) / 3600.0
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


HISTORY_NAME = 'Card history'


def card_parts(root):
    """(card_root, datalog) for a card root, its DATALOG folder, or a copy of the date folders; (None, None) if no card data."""
    if not root or not os.path.isdir(root): return None, None
    root = root.rstrip('\\/')
    if os.path.basename(root).upper() == 'DATALOG': return os.path.dirname(root), root
    if os.path.isdir(os.path.join(root, 'DATALOG')): return root, os.path.join(root, 'DATALOG')
    if glob.glob(os.path.join(root, '*', '*_BRP.edf')): return root, root
    return None, None


def sync_to_history(source, history, progress=None):
    """Copy every night folder from a card (or an old card copy) into the history folder: new nights, and nights that grew
    (a night still recording when the card was last read). Machine files (STR.edf, Identification) are taken when newer.
    Nothing is ever deleted from the history. Returns the number of night folders copied."""
    import shutil
    card_root, datalog = card_parts(source)
    if not datalog or os.path.abspath(datalog).startswith(os.path.abspath(history)): return 0
    hdl = os.path.join(history, 'DATALOG'); os.makedirs(hdl, exist_ok=True); copied = 0
    days = sorted(d for d in os.listdir(datalog) if d.isdigit() and os.path.isdir(os.path.join(datalog, d)))
    for i, d in enumerate(days):
        src, dst = os.path.join(datalog, d), os.path.join(hdl, d)
        files = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
        need = [f for f in files if not os.path.exists(os.path.join(dst, f)) or os.path.getsize(os.path.join(dst, f)) < os.path.getsize(os.path.join(src, f))]
        if need:
            os.makedirs(dst, exist_ok=True)
            for f in need: shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
            copied += 1
        if progress and i % 5 == 0: progress(i, len(days), f'Keeping a copy of {d}')
    for f in ('STR.edf', 'Identification.json', 'Identification.crc', 'Identification.tgt'):
        sp, dp = os.path.join(card_root, f), os.path.join(history, f)
        if os.path.isfile(sp) and (not os.path.exists(dp) or os.path.getmtime(sp) > os.path.getmtime(dp) + 1):
            if f == 'STR.edf' and os.path.exists(dp):                 # keep the old machine summary too; a re-initialised card starts a new one
                os.makedirs(os.path.join(history, 'STR older'), exist_ok=True)
                shutil.copy2(dp, os.path.join(history, 'STR older', f"STR {dt.datetime.fromtimestamp(os.path.getmtime(dp)):%Y-%m-%d}.edf"))
            shutil.copy2(sp, dp)
    return copied


def sync_zip_to_history(zpath, history):
    """Seed or top up the history from a SleepScope card.zip (the phone copy holds the last 45 nights and STR.edf):
    night files that are missing or smaller in the history are extracted. Returns night folders touched."""
    hdl = os.path.join(history, 'DATALOG'); touched = set()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            parts = info.filename.split('/')
            if len(parts) == 3 and parts[0] == 'DATALOG' and parts[1].isdigit() and parts[2]:
                dst = os.path.join(hdl, parts[1], parts[2])
                if not os.path.exists(dst) or os.path.getsize(dst) < info.file_size:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    with z.open(info) as src, open(dst, 'wb') as out: out.write(src.read())
                    touched.add(parts[1])
            elif len(parts) == 1 and parts[0] in ('STR.edf', 'Identification.json', 'Identification.crc') and not os.path.exists(os.path.join(history, parts[0])):
                with z.open(info) as src, open(os.path.join(history, parts[0]), 'wb') as out: out.write(src.read())
    return len(touched)


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
    data = (t0 + np.arange(n, dtype=float), sp, pu, mo, np.zeros(n), True, False)
    return data if nights is None else _attach_oximetry(*data, nights)


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
    if not ts: return None if nights is None else 0
    ts = np.array([t.timestamp() for t in ts]); sp = np.array(sp); pu = np.array(pu); mo = np.array(mo); al = np.array(al)
    data = (ts, sp, pu, mo, al, mi is not None, bool(ai))
    return data if nights is None else _attach_oximetry(*data, nights)


def _attach_oximetry(ts, sp, pu, mo, al, has_motion, has_alerts, nights):
    """Resample 1 Hz oximeter samples (epoch seconds) onto each overlapping session. Returns sessions filled."""
    filled = 0
    for nt in nights:
        for s in nt.sessions:
            a, b = s.start.timestamp(), s.end.timestamp()
            m = (ts >= a - 60) & (ts <= b + 60)
            if m.sum() < 30: continue
            grid = a + np.arange(int(s.duration))
            # interpolate only inside this recording, and only across gaps under 10 s, so two files of one night merge cleanly
            tt = ts[m]; inside = (grid >= tt[0]) & (grid <= tt[-1])
            j = np.clip(np.searchsorted(tt, grid), 1, len(tt) - 1); gap = (tt[j] - tt[j - 1]) > 10
            def lay(old, vals):
                new = np.interp(grid, tt, vals, left=np.nan, right=np.nan); new[~inside | gap] = np.nan
                new = np.nan_to_num(new, nan=-1).astype(np.float32)
                if old is not None and len(old) == len(new): new = np.where(new >= 0, new, old).astype(np.float32)
                return new
            prev_sp = getattr(s, 'spo2', None) if isinstance(getattr(s, 'spo2', None), np.ndarray) else None
            prev_pu = getattr(s, 'pulse', None) if isinstance(getattr(s, 'pulse', None), np.ndarray) else None
            s.spo2 = lay(prev_sp, sp[m]); s.pulse = lay(prev_pu, pu[m])
            prev_mo = getattr(s, 'motion', None) if isinstance(getattr(s, 'motion', None), np.ndarray) else None
            if has_motion and np.any(~np.isnan(mo[m])): s.motion = lay(prev_mo, np.nan_to_num(mo[m], nan=0.0))
            elif prev_mo is None: s.motion = None
            new_al = [dt.datetime.fromtimestamp(float(t)) for t in ts[m][al[m] > 0]] if has_alerts else []
            s.ox_alerts = sorted(set((getattr(s, 'ox_alerts', None) or []) + new_al))
            filled += 1
    return filled


# ----------------------------------------------------------------------------- find companion files near the card
def find_companion_files(folders, max_depth=6):
    """Look through the given folders (a few levels deep) for oximeter CSV exports (Wellue O2Ring and similar: a header
    with a time column and an oxygen/SpO2 column), SleepScope Health Shortcut files and Apple Health exports (export.zip or the
    unzipped apple_health_export/export.xml). Returns (oximeter_paths, health_paths)."""
    ox, health = [], []
    seen = set()
    for folder in folders:
        if not folder or not os.path.isdir(folder): continue
        folder = os.path.abspath(folder)
        if folder in seen: continue
        seen.add(folder); base_depth = folder.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(folder):
            if dirpath.count(os.sep) - base_depth >= max_depth: dirnames[:] = []
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d.lower() not in ('datalog', 'node_modules', 'appdata', '_to_delete', '_internal')]
            if os.path.basename(dirpath).lower() == 'apple_health_export':        # unzipped Health export: take export.xml, skip its ECG csvs and routes,
                dirnames[:] = [d for d in dirnames if d.lower() not in ('electrocardiograms', 'workout-routes')]   # but keep looking for nested copies
                if 'export.xml' in filenames: health.append(os.path.join(dirpath, 'export.xml'))
                filenames = [f for f in filenames if f.lower().endswith('.zip')]
            for fn in filenames:
                low = fn.lower()
                path = os.path.join(dirpath, fn)
                if low == 'sleepscope card.zip': continue
                if low.endswith('.zip') and 'export' in low:                        # Health export.zip (export.zip, export (1).zip ...)
                    try:
                        with zipfile.ZipFile(path) as zz:
                            if any(n.endswith('apple_health_export/export.xml') for n in zz.namelist()): health.append(path)
                    except Exception: pass
                    continue
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
def no_mask_ring_nights(recordings, nights):
    """Ring recordings that matched no CPAP session become nights of their own, marked no_mask, when the machine has
    nothing for that night (a night the mask could not be worn). A stand-in session spans each recording so the oxygen,
    pulse and motion code works unchanged. Returns the new nights, already carrying their ring data."""
    have = {n.date: n for n in nights}; new = {}
    for rec in recordings:
        ts = rec[0]
        if ts is None or len(ts) < 600: continue                         # under 10 minutes is not a night
        start = dt.datetime.fromtimestamp(float(ts[0])); d = night_date(start)
        old = have.get(d)
        if old is not None and not getattr(old, 'no_mask', False): continue   # the machine has this night (card out nights included)
        nt = new.get(d) or old
        if nt is None: nt = new[d] = Night(d, [], no_mask=True)
        nt.sessions.append(Session(start=start, duration=float(ts[-1] - ts[0]) + 1, folder='', stem='RING'))
        nt.sessions.sort(key=lambda x: x.start)
        _attach_oximetry(*rec, [nt])
    return list(new.values())


def health_export_date(path):
    """The ExportDate Apple writes near the top of export.xml (zip member or file), else the file time. Used to pick the newest export."""
    import re as _re
    try:
        if path.lower().endswith('.zip'):
            with zipfile.ZipFile(path) as z:
                name = next(n for n in z.namelist() if n.endswith('apple_health_export/export.xml'))
                with z.open(name) as f: head = f.read(20000)
        else:
            with open(path, 'rb') as f: head = f.read(20000)
        m = _re.search(rb'<ExportDate value="([^"]+)"', head)
        if m: return dt.datetime.strptime(m.group(1).decode()[:19], '%Y-%m-%d %H:%M:%S').timestamp()
    except Exception:
        pass
    try: return os.path.getmtime(path)
    except OSError: return 0.0


def ring_start(path):
    """Start of a ring recording (epoch s) from its first sample, for de-duplicating the same night saved several ways."""
    try:
        d = import_oximeter_csv(path, None)
        if d is not None and len(d[0]): return float(d[0][0]), int(np.isfinite(d[1]).sum())
    except Exception:
        pass
    return None, 0


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
