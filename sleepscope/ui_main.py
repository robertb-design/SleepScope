from __future__ import annotations
import os, sys, json, csv, html, datetime as dt
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets, QtGui
from . import loader, scoring, synopsis, apple_health, explain
from .theme import C, EVENT_COLORS, style_plot
from .ui_night import NightView
from .ui_ask import AskView, AskWorker, build_context, SYSTEM as ASK_SYSTEM
import hashlib
from .ui_landscape import LandscapeView
from .ui_notes import NotesView
from .ui_help import HelpView
from .ui_update import UpdateView
from .ui_home import HomeView
from .branding import Page, LogoWidget, app_icon

SETTINGS = QtCore.QSettings('SleepScope', 'SleepScope')


class LoadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int, str)
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    def __init__(self, root, history=None, extra=()):
        super().__init__(); self.root, self.history, self.extra = root, history, list(extra)
    def run(self):
        try:
            src = self.root; self.copied = 0
            if self.history:                                          # keep our own copy of every night, then read from it
                os.makedirs(self.history, exist_ok=True)
                for x in self.extra + [self.root]:
                    try: self.copied += loader.sync_to_history(x, self.history, lambda i, n, m: self.progress.emit(i, n, m))
                    except Exception: pass
                if loader.card_parts(self.history)[1] and os.listdir(os.path.join(self.history, 'DATALOG')): src = self.history
            data = loader.scan(src, progress=lambda i, n, name: self.progress.emit(i, n, 'Reading ' + name))
            data['card_root'] = self.root; data['history'] = src == self.history
            nights = data['nights']
            for i, nt in enumerate(nights):
                self.progress.emit(i, len(nights), 'Scoring ' + nt.label)
                for s in nt.sessions:
                    scoring.score_session(s)
                scoring.night_stats(nt)
            self.done.emit(data)
        except Exception as e:
            import traceback; self.failed.emit(traceback.format_exc())


class HealthWorker(QtCore.QThread):
    """Reads one Apple Health export off the UI thread (a full export.xml can be several hundred MB)."""
    done = QtCore.Signal(object, object)
    def __init__(self, path, since):
        super().__init__(); self.path, self.since = path, since
    def run(self):
        try: self.done.emit(self.path, apple_health.read_export(self.path, date_from=self.since))
        except Exception as e: self.done.emit(self.path, e)


class PhoneSyncWorker(QtCore.QThread):
    """Writes the card (last 45 nights of DATALOG, STR.edf, Identification) as one zip into a synced folder such as
    Dropbox\\SleepScope, so the phone app can open it without reading the SD card itself."""
    done = QtCore.Signal(str)
    def __init__(self, root, datalog, folder, nights, ring_files=(), health=None):
        super().__init__(); self.root, self.datalog, self.folder, self.nights, self.ring_files, self.health = root, datalog, folder, nights, list(ring_files), health
    def run(self):
        import zipfile, datetime as _dt
        try:
            os.makedirs(self.folder, exist_ok=True)
            keep = {n.date for n in self.nights[-45:]}
            tmp = os.path.join(self.folder, 'SleepScope card.zip.part'); out = os.path.join(self.folder, 'SleepScope card.zip')
            count = 0
            with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=5) as z:
                for name in ('STR.edf', 'Identification.json', 'Identification.tgt', 'Identification.crc'):
                    p_ = os.path.join(self.root, name)
                    if os.path.exists(p_): z.write(p_, name)
                for sub in sorted(os.listdir(self.datalog)):
                    d_ = os.path.join(self.datalog, sub)
                    if not (os.path.isdir(d_) and len(sub) == 8 and sub.isdigit()): continue
                    day = _dt.date(int(sub[:4]), int(sub[4:6]), int(sub[6:]))
                    if day not in keep and (day - _dt.timedelta(days=1)) not in keep: continue
                    for fn in os.listdir(d_):
                        if fn.lower().endswith('.edf'): z.write(os.path.join(d_, fn), f'DATALOG/{sub}/{fn}'); count += 1
                rings = 0
                for rp in self.ring_files:
                    try: z.write(rp, 'O2/' + os.path.basename(rp)); rings += 1
                    except OSError: pass
                about = (SETTINGS.value('about_me', '') or '').strip()
                if about: z.writestr('about.txt', about)                 # About me for the phone's Ask Claude
                if self.health:                                        # Watch nights, trimmed to the card's window, for the phone
                    import json as _json
                    z.writestr('health.json', _json.dumps(apple_health.to_sync(self.health, self.nights[-45].date if len(self.nights) >= 45 else self.nights[0].date)))
            os.replace(tmp, out)
            self.done.emit(f'Phone copy updated: {out} ({os.path.getsize(out) / 1e6:.0f} MB, {count} card files' + (f', {rings} ring files' if rings else '') + (', Watch data' if self.health else '') + ')')
        except Exception as e:
            self.done.emit(f'Phone copy failed: {e}')


class Table(QtWidgets.QTableWidget):
    def __init__(self, headers):
        super().__init__(0, len(headers)); self.setHorizontalHeaderLabels(headers)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False); self.setAlternatingRowColors(True); self.setSortingEnabled(False)
        self.horizontalHeader().setStretchLastSection(True)
    def fill(self, rows):
        self.setRowCount(0); self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QtWidgets.QTableWidgetItem(str(v)); it.setTextAlignment(QtCore.Qt.AlignCenter if c else QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                self.setItem(r, c, it)
        self.resizeColumnsToContents()
    def to_csv(self, path):
        with open(path, 'w', newline='') as f:
            w = csv.writer(f); w.writerow([self.horizontalHeaderItem(c).text() for c in range(self.columnCount())])
            for r in range(self.rowCount()): w.writerow([self.item(r, c).text() if self.item(r, c) else '' for c in range(self.columnCount())])


class BarAxis(pg.AxisItem):
    def __init__(self, labels, *a, **k):
        super().__init__(*a, **k); self.labels = labels
    def tickStrings(self, values, scale, spacing):
        return [self.labels[int(v)] if 0 <= int(round(v)) < len(self.labels) and abs(v - round(v)) < 0.01 else '' for v in values]


def _wrap(text, width=78):
    """Chart captions do not wrap by themselves; long ones widened the column past the window."""
    import textwrap
    return '<br>'.join(textwrap.wrap(text, width)) if text else ''


def draw_pressure_profile(gl, row, nights, scope, captions=True):
    """Two charts: hours spent at each 0.5 cmH2O band, and events per hour of time at that band (machine events, RERA-like runs)."""
    prof = scoring.pressure_profile(nights)
    if not prof: return
    top, rest = scoring.pressure_profile.last_split
    tot = sum(b['minutes'] for b in prof) or 1
    prof = [b for b in prof if b['minutes'] / tot >= 0.005]               # drop start up and ramp slivers
    if not prof: return
    xs = np.array([b['lo'] + 0.25 for b in prof]); hrs = np.array([b['minutes'] / 60 for b in prof])
    rate = np.array([b['rate'] if np.isfinite(b['rate']) and b['minutes'] >= 30 else 0 for b in prof])       # under 30 min a rate is noise
    rr = np.array([b['rera_rate'] if np.isfinite(b['rera_rate']) and b['minutes'] >= 30 else 0 for b in prof])
    def mk(col, title):
        p = gl.addPlot(row=row, col=col); style_plot(p); cap = explain.overview_caption(title) if captions else ''
        p.setTitle(f"<span style='font-size:10pt;color:#0b0b0b'>{title} ({scope})</span>" + (f"<br><span style='font-size:8.5pt;color:#52514e'>{_wrap(cap)}</span>" if cap else ''))
        p.setLabel('bottom', 'pressure, cmH2O'); p.setMouseEnabled(x=False, y=False); p.hideButtons(); p.setXRange(xs.min() - 0.5, xs.max() + 0.5, padding=0)
        p.getAxis('bottom').setTicks([[(b['lo'] + 0.25, f"{b['lo']:g}") for b in prof]]); return p
    p = mk(0, 'Time at pressure'); p.setLabel('left', 'hours')
    p.addItem(pg.BarGraphItem(x=xs, height=hrs, width=0.42, brush=pg.mkBrush(C['blue']), pen=pg.mkPen('w')))
    for x0, h, b in zip(xs, hrs, prof):
        t = pg.TextItem(f"{100 * b['minutes'] / tot:.0f}%", color=C['text2'], anchor=(0.5, 1)); t.setPos(x0, h); p.addItem(t)
    p.setYRange(0, max(hrs) * 1.25 + 0.1)
    p = mk(1, 'Events per hour at each pressure'); p.setLabel('left', 'per hour')
    p.addItem(pg.BarGraphItem(x=xs - 0.11, height=rate, width=0.2, brush=pg.mkBrush(C['red']), pen=pg.mkPen('w')))
    p.addItem(pg.BarGraphItem(x=xs + 0.11, height=rr, width=0.2, brush=pg.mkBrush(C['violet']), pen=pg.mkPen('w')))
    p.setYRange(0, max(1, float(max(rate.max(), rr.max()))) * 1.2)
    if top['minutes']:
        f = lambda v: f'{v:.1f}' if np.isfinite(v) else 'n/a'
        p.setTitle(p.titleLabel.text + f"<br><span style='font-size:9pt;color:#1d4f91'><b>At the top setting</b> ({top['pct']:.0f}% of the time): events {f(top['rate'])}/h, RERA-like {f(top['rera_rate'])}/h"
                   f"<br><b>Below it:</b> events {f(rest['rate'])}/h, RERA-like {f(rest['rera_rate'])}/h</span>")


class OverviewView(QtWidgets.QWidget):
    """One row per chart: the chart on the left, and lined up on the right what it is, your result, and what to do."""
    night_clicked = QtCore.Signal(int)
    ROW_H = 270
    def __init__(self):
        super().__init__(); lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        self.scroll = QtWidgets.QScrollArea(); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.body = QtWidgets.QWidget(); self.body.setStyleSheet('background:white'); self.rows = QtWidgets.QVBoxLayout(self.body)
        self.rows.setContentsMargins(6, 6, 6, 6); self.rows.setSpacing(10); self.scroll.setWidget(self.body); lay.addWidget(self.scroll, 1)
        self.note = QtWidgets.QLabel(''); self.note.setStyleSheet('color:#52514e'); self.note.setWordWrap(True); lay.addWidget(self.note)
        self.gl = self                                             # old callers clear the overview through .gl.clear()
        self.nights = []

    def clear(self):
        while self.rows.count():
            it = self.rows.takeAt(0); w = it.widget()
            if w: w.deleteLater()

    @staticmethod
    def _panel(item, simple):
        """Right hand text: simple one liner, the numbers for these nights, what to do."""
        esc = lambda t: html.escape(t)
        h = f"<div style='font-size:12.5px;line-height:1.45'><div style='font-size:13.5px;font-weight:600;color:#1d4f91;margin-bottom:4px'>{esc(item['title'])}</div>"
        h += f"<p style='margin:0 0 6px'><b>What it is.</b> {esc(simple or item['what'])}</p>"
        if item['found']: h += f"<p style='margin:0 0 6px'><b>Your result.</b> {esc(' '.join(item['found']))}</p>"
        if item['imp']: h += f"<p style='margin:0;color:#0f6e4f'><b>What to do.</b> {esc(' '.join(item['imp']))}</p>"
        return explain.spell_out(h + '</div>')

    def _row(self, item, simple, cols=1):
        """A chart row: GraphicsLayoutWidget on the left, explanation on the right. Returns the chart widget."""
        fr = QtWidgets.QFrame(); fr.setStyleSheet('QFrame#row { border:1px solid #e6e5e2; border-radius:6px; background:white; }'); fr.setObjectName('row')
        hl = QtWidgets.QHBoxLayout(fr); hl.setContentsMargins(6, 6, 10, 6); hl.setSpacing(12)
        gl = pg.GraphicsLayoutWidget(); gl.setBackground('w'); gl.setFixedHeight(self.ROW_H); gl.ci.layout.setHorizontalSpacing(18)
        hl.addWidget(gl, 3 if cols == 1 else 4)
        lab = QtWidgets.QLabel(self._panel(item, simple) if item else ''); lab.setWordWrap(True); lab.setTextFormat(QtCore.Qt.RichText)
        lab.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft); lab.setStyleSheet('border:none; color:#1d1d1b'); lab.setMinimumWidth(320)
        hl.addWidget(lab, 2); self.rows.addWidget(fr); return gl

    def set_nights(self, nights):
        self.clear(); self.nights = nights
        if not nights: self.note.setText(''); return
        items = {it['title']: it for it in explain.overview_items(nights)}
        labs = [n.label for n in nights]; x = np.arange(len(nights)); S = [n.stats for n in nights]
        def g(k): return np.array([s.get(k, np.nan) for s in S], dtype=float)
        def plot(key, title, unit='', cap_key=None):
            gl = self._row(items.get(key), explain.overview_caption(cap_key or title))
            p = gl.addPlot(row=0, col=0, axisItems={'bottom': BarAxis(labs, orientation='bottom')}); style_plot(p)
            p.setTitle(f"<span style='font-size:10.5pt;color:#0b0b0b'>{title}</span>")
            p.setLabel('left', unit); p.setMouseEnabled(x=False, y=False); p.hideButtons()
            ax = p.getAxis('bottom'); ax.setStyle(tickFont=QtGui.QFont('Segoe UI', 8), autoExpandTextSpace=True)
            short = len(labs) > 6; k = max(1, int(np.ceil(len(labs) / 14)))
            ticks = [(i, (labs[i].split(' ')[-1] if short else labs[i]) if i % k == 0 or i == len(labs) - 1 else '') for i in range(len(labs))]
            ax.setTicks([ticks]); p.setXRange(-0.6, len(labs) - 0.4, padding=0)
            p.scene().sigMouseClicked.connect(lambda ev, p=p: self._click(ev, p)); return p
        def bars(p, vals, color, width=0.6, off=0.0):
            b = pg.BarGraphItem(x=x + off, height=np.nan_to_num(vals), width=width, brush=pg.mkBrush(color), pen=pg.mkPen('w')); p.addItem(b); return b
        # usage
        p = plot('Usage (hours)', 'Usage (hours)', 'h'); bars(p, g('hours'), C['blue']); p.setYRange(0, np.nanmax(g('hours')) * 1.3 + 0.5); p.addLine(y=4, pen=pg.mkPen(C['text2'], style=QtCore.Qt.DashLine))
        for i, v in enumerate(g('hours')):
            t = pg.TextItem(f'{v:.1f}', color=C['text2'], anchor=(0.5, 1)); t.setPos(i, v); p.addItem(t)
        # AHI
        p = plot('AHI: machine vs app', 'AHI: machine (blue), app recheck (orange), app RDI (violet line); dashed = 5', '/h', 'AHI')
        bars(p, g('AHI'), C['blue'], 0.28, -0.15); bars(p, g('app_AHI'), C['orange'], 0.28, 0.15)
        p.plot(x, g('app_RDI'), pen=pg.mkPen(C['violet'], width=2), symbol='o', symbolBrush=C['violet'], symbolPen=None, symbolSize=7)
        p.addLine(y=5, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine))
        # events
        p = plot('Machine events by type', 'Machine events: obstructive (red), central (violet), hypopnea (orange)', 'count', 'Machine events')
        base = np.zeros(len(x))
        for k, c in (('OA', C['red']), ('CA', C['violet']), ('H', C['orange'])):
            v = np.nan_to_num(g(k)); p.addItem(pg.BarGraphItem(x=x, y0=base, height=v, width=0.6, brush=pg.mkBrush(c), pen=pg.mkPen('w'))); base += v
        # pressure
        p = plot('Set pressure', 'Pressure: min to max (band), median (aqua), 95th percentile (blue), top (red dashed)', 'cmH2O', 'Set pressure')
        lo, hi = g('press_min'), g('press_max')
        p.addItem(pg.FillBetweenItem(pg.PlotDataItem(x, lo), pg.PlotDataItem(x, hi), brush=pg.mkBrush(42, 120, 214, 35)))
        p.plot(x, g('press_95'), pen=pg.mkPen(C['blue'], width=2), symbol='o', symbolBrush=C['blue'], symbolPen=None, symbolSize=7)
        p.plot(x, g('press_med'), pen=pg.mkPen(C['aqua'], width=2), symbol='o', symbolBrush=C['aqua'], symbolPen=None, symbolSize=7)
        p.plot(x, hi, pen=pg.mkPen(C['red'], width=1, style=QtCore.Qt.DashLine))
        lo_v = np.nanmin(lo) if np.isfinite(lo).any() else 4; hi_v = np.nanmax(hi) if np.isfinite(hi).any() else 12
        p.setYRange(max(0, np.floor(lo_v) - 1), np.ceil(hi_v) + 1)
        # leak
        p = plot('Leak', 'Leak: median (aqua), 95th percentile (orange); dashed = 24 L/min', 'L/min', 'Leak')
        bars(p, g('leak_med'), C['aqua'], 0.28, -0.15); bars(p, g('leak_95'), C['orange'], 0.28, 0.15); p.addLine(y=24, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine))
        # flow limitation
        p = plot('Flow limitation', 'Flow limitation: minutes above 0.2 (violet bars), 95th percentile x100 (orange line)', 'min', 'Flow limitation')
        bars(p, g('flowlim_minutes'), C['violet']); p.plot(x, g('flowlim_95') * 100, pen=pg.mkPen(C['orange'], width=2), symbol='o', symbolBrush=C['orange'], symbolPen=None, symbolSize=7)
        # breathing
        p = plot('Breathing: rate and volume', 'Breathing: rate bpm (blue), minute ventilation L/min (aqua), tidal volume / 50 mL (green)', '', 'Breathing')
        bars(p, g('rr_med'), C['blue'], 0.2, -0.22); bars(p, g('mv_med'), C['aqua'], 0.2, 0.0); bars(p, g('tv_med') / 50, C['green'], 0.2, 0.22)
        # oxygen, or time at max without a ring
        if np.isfinite(g('spo2_mean')).any():
            p = plot('SpO2 and ODI', 'Oxygen: mean (blue), lowest (red); ODI dips per hour (orange labels)', '%', 'SpO2')
            p.plot(x, g('spo2_mean'), pen=pg.mkPen(C['blue'], width=2), symbol='o', symbolBrush=C['blue'], symbolPen=None)
            p.plot(x, g('spo2_min'), pen=pg.mkPen(C['red'], width=2), symbol='o', symbolBrush=C['red'], symbolPen=None)
            smn = g('spo2_min'); low = np.nanmin(smn) if np.isfinite(smn).any() else 85; top_y = 101
            p.setYRange(max(50, np.floor(low) - 3), top_y + 2)
            for i, v in enumerate(g('ODI')):
                if np.isfinite(v): t = pg.TextItem(f'{v:.1f}', color=C['orange'], anchor=(0.5, 0)); t.setPos(i, top_y + 1.5); p.addItem(t)
        else:
            p = plot('Time at maximum pressure, periodic breathing', 'Time at max pressure, % of night (blue); periodic breathing windows (magenta)', '%', 'Time at max')
            bars(p, g('press_at_max_pct'), C['blue']); p.plot(x, g('periodic_windows'), pen=pg.mkPen(C['magenta'], width=2), symbol='o', symbolBrush=C['magenta'], symbolPen=None)
        # time at pressure (two charts, one explanation)
        key = 'Time at pressure, events per hour at each pressure'
        if key in items:
            gl = self._row(items[key], 'Left: hours at each pressure. Right: events per hour of time at that pressure; red is machine events, violet is flattened breathing that ends in a recovery breath.', cols=2)
            draw_pressure_profile(gl, 0, [n for n in nights if n.sessions], 'all nights', captions=False)
        self.rows.addStretch(1)
        tot_h = sum(n.hours for n in nights); ev = sum(s['OA'] + s['CA'] + s['H'] + s['UA'] for s in S)
        self.note.setText(f"{len(nights)} nights, {tot_h:.1f} h, mean {tot_h / len(nights):.2f} h a night, machine AHI {ev / tot_h:.2f} overall. Click a bar to open that night.")

    def _click(self, ev, p):
        if ev.double(): return
        x = p.vb.mapSceneToView(ev.scenePos()).x(); i = int(round(x))
        if 0 <= i < len(self.nights): self.night_clicked.emit(i)


class BreathView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        self.gl = pg.GraphicsLayoutWidget(); self.gl.setBackground('w'); self.gl.ci.layout.setVerticalSpacing(18); self.gl.setMinimumHeight(5 * 300)
        sc = QtWidgets.QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QtWidgets.QFrame.NoFrame); sc.setWidget(self.gl); lay.addWidget(sc, 1)
        self.note = QtWidgets.QLabel(''); self.note.setStyleSheet('color:#52514e'); lay.addWidget(self.note)
    def set_night(self, nt):
        self.gl.clear()
        if nt is None: return
        brs = [s.breaths for s in nt.sessions if s.breaths]
        if not brs: return
        def cat(k): return np.concatenate([b[k] for b in brs])
        specs = [('ti', 'Inspiratory time', 's', (0, 5)), ('te', 'Expiratory time', 's', (0, 8)), ('ie', 'I:E ratio', '', (0, 3)),
                 ('pif', 'Peak inspiratory flow', 'L/min', (0, 90), 60), ('pifpef', 'PIF / PEF', '', (0, 2.5)), ('vt', 'Tidal volume (integrated)', 'mL', (0, 1500), 1000),
                 ('plateau', 'Mid-inspiratory plateau ratio', '', (0.5, 1.0)), ('rr', 'Breath rate', 'bpm', (0, 40)), ('ratio', 'PIF vs 2 min baseline', 'x', (0, 3))]
        for i, sp in enumerate(specs):
            k, title, unit, rng = sp[:4]; sc = sp[4] if len(sp) > 4 else 1
            v = cat(k) * sc; v = v[np.isfinite(v)]
            p = self.gl.addPlot(row=i // 3, col=i % 3); style_plot(p); p.setTitle(f'{title}  (median {np.median(v):.2f})', size='10pt', color='#0b0b0b'); p.setLabel('bottom', unit)
            y, edges = np.histogram(np.clip(v, *rng), bins=50, range=rng)
            p.addItem(pg.BarGraphItem(x0=edges[:-1], x1=edges[1:], height=y, brush=pg.mkBrush(C['blue']), pen=pg.mkPen('w')))
        # pressure vs events
        p = self.gl.addPlot(row=3, col=0, colspan=3); style_plot(p); p.setTitle('Events by set pressure at onset (machine: filled, app: hollow)', size='10pt', color='#0b0b0b'); p.setLabel('bottom', 'cmH2O')
        labs = ['Obstructive Apnea', 'Central Apnea', 'Hypopnea', 'Flow Limitation Run', 'Large Leak']
        for j, lab in enumerate(labs):
            for s in nt.sessions:
                for e in s.machine_events + s.app_events:
                    if e.label != lab or 'Press' not in s.ch: continue
                    i2 = int((e.start - s.start).total_seconds() / 2); pr = s.ch['Press'][min(i2, len(s.ch['Press']) - 1)]
                    it = pg.ScatterPlotItem([pr], [j + np.random.uniform(-0.2, 0.2)], size=9, brush=pg.mkBrush(EVENT_COLORS[lab]) if e.source == 'machine' else pg.mkBrush('w'), pen=pg.mkPen(EVENT_COLORS[lab], width=1.5))
                    p.addItem(it)
        p.getAxis('left').setTicks([[(j, l) for j, l in enumerate(labs)]]); p.setYRange(-0.6, len(labs) - 0.4); p.setXRange(3, 21)
        draw_pressure_profile(self.gl, 4, [nt], nt.label)
        self.note.setText(f'{sum(len(b["t0"]) for b in brs)} breaths segmented from the 25 Hz flow. Plateau ratio: mean of middle 50% of inspiration over its peak (a half sine scores about 0.90; above 0.95 is a flat top). PIF/PEF well below 0.7 with a long Ti is the inspiratory shape seen during flow limited runs.')


class SynopsisView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); self.nights = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout(); lay.addLayout(bar)
        bar.addWidget(QtWidgets.QLabel('From')); self.d0 = QtWidgets.QDateEdit(calendarPopup=True); self.d0.setDisplayFormat('MMM d, yyyy'); bar.addWidget(self.d0)
        bar.addWidget(QtWidgets.QLabel('to')); self.d1 = QtWidgets.QDateEdit(calendarPopup=True); self.d1.setDisplayFormat('MMM d, yyyy'); bar.addWidget(self.d1)
        for lab, days in (('Last night', 1), ('Last 7', 7), ('Last 14', 14), ('Last 30', 30), ('All', None)):
            b = QtWidgets.QPushButton(lab); b.clicked.connect(lambda _, d=days: self.quick(d)); bar.addWidget(b)
        bar.addSpacing(16); bar.addWidget(QtWidgets.QLabel('Diagnostic AHI (from your sleep study, optional)'))
        self.diag = QtWidgets.QDoubleSpinBox(); self.diag.setRange(0, 200); self.diag.setDecimals(0); self.diag.setSpecialValueText('not set')
        self.diag.setValue(float(SETTINGS.value('diag_ahi', 0))); self.diag.valueChanged.connect(lambda v: SETTINGS.setValue('diag_ahi', v)); bar.addWidget(self.diag)
        bar.addStretch()
        gen = QtWidgets.QPushButton('Generate'); gen.setDefault(True); gen.clicked.connect(self.generate); bar.addWidget(gen)
        cp = QtWidgets.QPushButton('Copy'); cp.clicked.connect(self.copy); bar.addWidget(cp)
        sv = QtWidgets.QPushButton('Save HTML…'); sv.clicked.connect(self.save); bar.addWidget(sv)
        split = QtWidgets.QSplitter(); lay.addWidget(split, 1)
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0)
        lt = QtWidgets.QLabel('Rule based synopsis (computed on this PC)'); lt.setStyleSheet('font-weight:700; color:#1d4f91; padding:4px'); ll.addWidget(lt)
        self.text = QtWidgets.QTextBrowser(); self.text.setOpenExternalLinks(True); self.text.setStyleSheet('font-size:13px; padding:8px'); ll.addWidget(self.text)
        right = QtWidgets.QWidget(); rl = QtWidgets.QVBoxLayout(right); rl.setContentsMargins(0, 0, 0, 0)
        rbar = QtWidgets.QHBoxLayout(); rl.addLayout(rbar)
        rt = QtWidgets.QLabel("Claude's reading of the same data"); rt.setStyleSheet('font-weight:700; color:#eb6834; padding:4px'); rbar.addWidget(rt); rbar.addStretch()
        self.auto = QtWidgets.QCheckBox('Automatic when data loads'); self.auto.setChecked(SETTINGS.value('auto_claude', 'true') == 'true')
        self.auto.toggled.connect(lambda v: SETTINGS.setValue('auto_claude', 'true' if v else 'false')); rbar.addWidget(self.auto)
        self.claude_btn = QtWidgets.QPushButton('Ask Claude now'); self.claude_btn.clicked.connect(lambda: self.ask_claude(force=True)); rbar.addWidget(self.claude_btn)
        self.claude_text = QtWidgets.QTextBrowser(); self.claude_text.setOpenExternalLinks(True); self.claude_text.setStyleSheet('font-size:13px; padding:8px'); rl.addWidget(self.claude_text)
        self.claude_status = QtWidgets.QLabel(''); self.claude_status.setStyleSheet('color:#52514e; padding:2px 4px'); rl.addWidget(self.claude_status)
        split.addWidget(left); split.addWidget(right); split.setSizes([600, 600])
        self.worker = None; self._claude_key = None; self.on_range = None
        self.claude_text.setHtml('<p style="color:#52514e">Claude reads the statistics, events and the rule based synopsis for the selected range and writes its own account: what the data shows, what it means for you, and what to ask the prescriber. It runs by itself when data loads if an API key is saved on the Ask Claude tab (a few cents per run; the same data is not sent twice).</p>')
        self.d0.dateChanged.connect(self.generate); self.d1.dateChanged.connect(self.generate); self.diag.valueChanged.connect(self.generate)
    def set_nights(self, nights):
        self.nights = nights
        if not nights: return
        self.d0.blockSignals(True); self.d1.blockSignals(True)
        self.d0.setDate(QtCore.QDate(nights[-1].date)); self.d1.setDate(QtCore.QDate(nights[-1].date))   # opens on the most recent night
        self.d0.blockSignals(False); self.d1.blockSignals(False); self.generate()
    def quick(self, days):
        if not self.nights: return
        last = self.nights[-1].date; first = self.nights[0].date if days is None else max(self.nights[0].date, last - dt.timedelta(days=days - 1))
        self.d0.blockSignals(True); self.d0.setDate(QtCore.QDate(first)); self.d0.blockSignals(False); self.d1.setDate(QtCore.QDate(last))
    def generate(self):
        if not self.nights: return
        a = self.d0.date().toPython(); b = self.d1.date().toPython()
        if a > b: a, b = b, a
        self.html = synopsis.generate(self.nights, a, b, self.diag.value() or None); self.text.setHtml(self.html)
        if self.on_range: self.on_range(a, b)
        if self.auto.isChecked(): self.ask_claude(force=False)
    # ---- Claude narrative
    def ask_claude(self, force=False):
        if not self.nights: return
        key = SETTINGS.value('api_key', '').strip()
        if not key:
            self.claude_status.setText('No API key saved. Add one on the Ask Claude tab and this fills in automatically.'); return
        if self.worker and self.worker.isRunning(): return
        a = self.d0.date().toPython(); b = self.d1.date().toPython()
        if a > b: a, b = b, a
        sel = [n for n in self.nights if a <= n.date <= b]
        if not sel: return
        sig = hashlib.md5(('|'.join(f"{n.date}:{n.hours:.3f}:{n.stats.get('AHI', 0):.3f}:{n.stats.get('spo2_mean', 0)}" for n in sel) + f"|{self.diag.value()}|{SETTINGS.value('about_me', '')}").encode()).hexdigest()
        cache = SETTINGS.value('claude_synopsis_cache', {}) or {}
        if not force and sig in cache:
            self.claude_text.setMarkdown(cache[sig]); self.claude_status.setText(f'Shown from cache ({a} to {b}). Press Ask Claude now to refresh.'); return
        if not force and len(cache) >= 1 and SETTINGS.value('auto_claude', 'true') != 'true': return
        ctx = build_context(self.nights, a, b, self.diag.value() or None)
        about = SETTINGS.value('about_me', '').strip()
        prompt = (ctx + "\n\nTASK: Write a synopsis of this CPAP data for the user, in plain language, as a short report with these headings: "
                  "What the data shows; What it means for you; What is going well; What to watch; Questions for the prescriber. "
                  "Use the numbers in the context. Where the rule based synopsis and your own reading differ, say so. Keep it under 500 words. No dashes in prose.")
        self._claude_key = sig; self._range = (a, b)
        self.claude_status.setText(f'Asking {SETTINGS.value("model", "claude-sonnet-5-5")}... (a long answer can take 30 to 60 s)'); self.claude_btn.setEnabled(False)
        sysmsg = ASK_SYSTEM + (f'\nAbout the user, in their words: {about}\n' if about else '')
        self.worker = AskWorker(key, SETTINGS.value('model', 'claude-sonnet-5-5'), sysmsg, [{'role': 'user', 'content': prompt}])
        self.worker.done.connect(self._claude_done); self.worker.failed.connect(self._claude_fail); self.worker.start()
    def _claude_done(self, text):
        self.claude_btn.setEnabled(True); self.claude_text.setMarkdown(text)
        cache = SETTINGS.value('claude_synopsis_cache', {}) or {}
        cache[self._claude_key] = text
        if len(cache) > 30: cache = dict(list(cache.items())[-30:])
        SETTINGS.setValue('claude_synopsis_cache', cache)
        a, b = self._range; self.claude_status.setText(f'Claude synopsis for {a} to {b}, saved to your notes folder.')
        try:
            folder = SETTINGS.value('ask_folder', os.path.join(os.path.expanduser('~'), 'Documents', 'SleepScope'))
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f'claude_synopsis_{dt.date.today():%Y-%m-%d}.md'), 'w', encoding='utf-8') as f:
                f.write(f"# Claude synopsis, data {a} to {b}, written {dt.datetime.now():%B %d, %Y %H:%M}\n\n{text}\n")
        except Exception: pass
    def _claude_fail(self, msg):
        self.claude_btn.setEnabled(True); self.claude_status.setText('Claude synopsis failed: ' + msg)
    def copy(self): QtWidgets.QApplication.clipboard().setText(self.text.toPlainText() + '\n\n==== Claude\'s reading ====\n\n' + self.claude_text.toPlainText())
    def save(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save synopsis', 'sleepscope_synopsis.html', 'HTML (*.html)')
        if p: open(p, 'w', encoding='utf-8').write('<html><body style="font-family:Segoe UI,Arial;max-width:800px;margin:auto">' + getattr(self, 'html', '') + "<hr><h2>Claude's reading</h2>" + self.claude_text.toHtml() + '</body></html>')


METHODS = """
<h2>What SleepScope computes, and how far to trust it</h2>
<p><b>Source files.</b> Everything comes from the SD card: BRP (flow and pressure, 25 Hz), PLD (2 s channels: mask pressure, set pressure,
EPR pressure, leak, respiratory rate, tidal volume, minute ventilation, snore, flow limitation), SA2/SAD (1 s SpO2 and pulse when an
oximeter is paired, otherwise the file reads -1), EVE and CSL (the machine's event annotations), STR.edf (daily summary) and Identification.</p>
<p><b>Event timestamps.</b> ResMed stamps the <i>end</i> of each event in the EVE file. SleepScope subtracts the duration so markers sit on
the actual pause. Other software that plots the stamp directly draws events 10 to 20 s late. Hypopneas and arousals carry no duration.</p>
<p><b>Machine values (verified data).</b> AHI machine, OA, CA, H, arousal, pressures, leak, flow limitation channel, snore, RR, Vt, MV,
SpO2 and pulse are read as recorded. Nothing is re-derived.</p>
<p><b>App scoring (computed here, independent of the machine).</b></p>
<ul>
<li><b>Ventilation envelope:</b> |low-pass(flow, 1.5 Hz)| averaged over 3 s at 1 Hz. Baseline = 70th percentile of the preceding 2 min.</li>
<li><b>Apnea:</b> envelope below 70% of baseline for at least 10 s, with some 8 s block below 25%. The Statistics tab footer and the Ask Claude context report how many machine apneas the detector reproduced on the loaded card (on the author's test card, 17 to 18 of 19, the misses having 30 to 40% residual flow and being called hypopneas instead). The app cannot tell obstructive from central (that needs the machine's forced
oscillation test), so it borrows the machine's label when the machine flagged the same event and otherwise reports "Apnea (unflagged by machine)".</li>
<li><b>Hypopnea (flow only):</b> envelope below 70% for at least 10 s without the apnea test. A lab score also requires a 3 to 4% desaturation or an EEG arousal,
which the app cannot see unless an oximeter is attached, so this count is an upper bound. The AHI (app) is therefore higher than the machine's and should be read
as "events that would count if every one caused a desaturation".</li>
<li><b>Flow limitation runs:</b> the machine's own FlowLim channel at or above 0.20 for at least 10 s. Marked RERA-like when a recovery breath (peak inspiratory flow
at least 1.5x the recent median) follows within 10 s. RDI (app) = apneas + hypopneas + RERA-like, per hour.</li>
<li><b>Large leak:</b> above 24 L/min for at least 60 s (ResMed's large leak line).</li>
<li><b>Periodic breathing:</b> autocorrelation of the breath amplitude envelope in 5 min windows; a peak at 30 to 90 s with correlation above 0.5 is flagged.
Zero windows across a night means no Cheyne-Stokes pattern was found.</li>
<li><b>Mode:</b> "CPAP" when set pressure is flat after the first 15% of the session, otherwise "AutoSet". Inferred from pressure, not read from settings
(STR.edf carries the settings when present on the card).</li>
<li><b>ODI:</b> dips of 3% or more below the median of the preceding 2 minutes, lasting 10 s or longer, per hour of oximetry. Dips that coincide (within 10 s) with ring motion of 30 or more are treated as sensor artifact and left out; the count left out is shown separately.</li>
<li><b>Hypopnea confirmation:</b> when the ring covers an app hypopnea, it counts only if SpO2 falls 3 points or more below the 2 minute pre-event median during the event or within 30 s after it, or the pulse rises 6 bpm or more within 15 s after it (a stand-in for an EEG arousal, which home equipment cannot see). The H confirmed column shows how many passed. Without the ring, hypopneas stay flow only and are counted.</li>
<li><b>Large leak:</b> app events whose midpoint falls inside a large-leak run (over 24 L/min for 60 s or more) are listed but not counted in the app's AHI, RDI or flow limitation counts, because the flow signal is unreliable while air is escaping. The In leak column counts them. Machine events are never altered.</li>
<li><b>Pressure setting column:</b> taken from the machine's own daily settings record (STR.edf) when the card has it; otherwise from the trace with each session's ramp (up to 45 minutes) excluded, marked (trace).</li>
</ul>
<p><b>Breath metrics</b> are descriptive only and do not generate events: Ti, Te, I:E, PIF, PEF, PIF/PEF, integrated tidal volume, plateau ratio.
The machine's flow limitation index is proprietary and could not be reproduced from breath shape alone, which is why the machine channel is used for runs.</p>
<p><b>3D Landscape.</b> One strip per night. Height = openness = min(ventilation ratio, 1) x (1 - 0.7 x machine flow limitation), averaged over 2 minute bins
and lightly smoothed. Grey = mask off. Blue pools = leak over 24 L/min. Pillars = machine events. Magenta line = set pressure (4 cmH2O at the strip, rising with pressure).
It is a picture of the same numbers the other tabs show, arranged so a week reads at a glance.</p>
<p><b>Synopsis tab.</b> The plain English report is generated by fixed rules from the per-night statistics (thresholds: AHI under 5 controlled;
usage 4 h on 70% of nights; leak 95th percentile under 24 L/min; central index over 5 with centrals above half of events flagged; ODI under 5 normal;
five minutes or more under 88% in a night flagged). It is deterministic: the same data always produces the same text. It does not use an online service.</p>
<p><b>Apple Health.</b> Import either the small sleepscope_health.txt the SleepScope Health Shortcut writes on the phone (see How to use), or the full export.zip the Health app produces (Profile picture, Export All Health Data). Sleep stages, heart rate, HRV, respiratory
rate and Watch SpO2 are matched to each night. The Watch's stages come from motion and heart rate, not EEG, so treat them as approximate.
Writing CPAP data into Apple Health needs an iOS app and cannot be done from Windows.</p>
<p><b>This is not a medical device.</b> Use it to understand the data and to bring better questions to the person who manages the prescription.</p>
"""


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('SleepScope'); self.resize(1500, 950)
        self.data = None; self.nights = []
        tb = self.addToolBar('Main'); tb.setMovable(False); tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        from .updater import Updater
        self.updater = Updater(self, SETTINGS); QtCore.QTimer.singleShot(800, lambda: self.updater.check(quiet=True))   # every start
        tb.addWidget(LogoWidget(30))
        from . import version as _ver
        vtxt = 'from source' if _ver.VERSION == 'source' else 'v' + _ver.VERSION
        self.setWindowTitle(f'SleepScope {vtxt}')
        vl = QtWidgets.QLabel(f'  {vtxt}  '); vl.setStyleSheet('color:#52514e; font-weight:600'); vl.setToolTip('SleepScope version. Click the logo for the About box.'); tb.addWidget(vl)
        tb.addSeparator()
        tb.addAction('Open SD card…', self.open_card); tb.addAction('Reload', self.reload); tb.addAction('Load sample data', self.load_sample); tb.addAction('Close data', self.close_data)
        tb.addAction('Import oximeter CSV…', self.import_oximeter); tb.addAction('Import Apple Health…', self.import_apple); tb.addAction('Companion folder…', self.set_companion_folder); tb.addAction('Phone copy…', self.set_phone_folder); tb.addAction('Check for updates', lambda: self.updater.check(quiet=False)); tb.addSeparator()
        tb.addAction('Export statistics CSV', lambda: self.export_table(self.stats_table, 'sleepscope_nights.csv'))
        tb.addAction('Export events CSV', self.export_events); tb.addAction('Save chart as PNG', self.save_png)
        self.progress = QtWidgets.QProgressBar(); self.progress.setFixedWidth(220); self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)

        split = QtWidgets.QSplitter(); self.setCentralWidget(split)
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(4, 4, 0, 4)
        self.night_table = Table(['Night', 'Hours', 'Pressure setting', 'AHI', 'AHI app', 'Leak 95', 'P 95'])
        self.night_table.itemSelectionChanged.connect(self._night_selected); ll.addWidget(self.night_table)
        from . import explain as _ex
        for ci, k in enumerate(['label', 'hours', 'setting', 'AHI', 'app_AHI', 'leak_95', 'press_95']):
            it = self.night_table.horizontalHeaderItem(ci)
            if it is not None: it.setToolTip(_ex.COLUMN_HELP.get(k, ''))
        self.device_label = QtWidgets.QLabel(''); self.device_label.setWordWrap(True); self.device_label.setStyleSheet('color:#52514e'); ll.addWidget(self.device_label)
        left.setMinimumWidth(440); split.addWidget(left)

        self.tabs = QtWidgets.QTabWidget(); split.addWidget(self.tabs); split.setSizes([470, 1030])
        self.home = HomeView(); self.home.action.connect(self._home_action); self.tabs.addTab(self.home, 'Start here')
        self.update_view = UpdateView(); self.tabs.addTab(Page(self.update_view, 'Update', 'The morning routine: ring, Watch, card, phone. Bring last night in.', '#1baf7a'), 'Update')
        self.tabs.addTab(Page(HelpView(), 'How to use', 'Everything from the card reader to the Claude key, step by step.', '#1d4f91'), 'How to use')
        self.overview = OverviewView(); self.overview.night_clicked.connect(self.select_night); self.tabs.addTab(Page(self.overview, 'Overview', 'Trends across nights. Click a bar to open that night.', '#2a78d6'), 'Overview')
        self.synopsis = SynopsisView(); self.tabs.addTab(Page(self.synopsis, 'Synopsis', 'Plain English report for any date range, with Claude\'s reading beside it.', '#1baf7a'), 'Synopsis')
        self.landscape = LandscapeView(); self.synopsis.on_range = lambda a, b: self.landscape.set_range(a, b); self.tabs.addTab(Page(self.landscape, '3D Landscape', 'A week as terrain. Height is how freely you breathed. Click any pillar, pool or patch of ground for a plain language explanation.', '#6250d6'), '3D Landscape')
        self.ask = AskView(); self.tabs.addTab(Page(self.ask, 'Ask Claude', 'Questions about your results, answered from your numbers and saved for later.', '#eb6834'), 'Ask Claude')
        self.notes = NotesView(); self.tabs.addTab(Page(self.notes, 'Saved answers', 'Everything Claude has written for you, searchable.', '#d95926'), 'Saved answers')
        self.notes.continue_requested.connect(self._continue_conversation)
        self.ask.answer_saved.connect(self.notes.refresh); self.ask.key_saved.connect(lambda: (self._refresh_home(), self.synopsis.ask_claude(force=False)))
        self.night_view = NightView(); self.tabs.addTab(Page(self.night_view, 'Night', 'One night, every breath. Step through events, zoom from 30 seconds to the whole night, hover for values.', '#2a78d6'), 'Night')
        ev_w = QtWidgets.QWidget(); evl = QtWidgets.QVBoxLayout(ev_w); evl.setContentsMargins(4, 4, 4, 4)
        self.ev_filter = QtWidgets.QComboBox(); self.ev_filter.addItems(['All', 'Machine only', 'App only', 'Apneas', 'Hypopneas', 'Flow limitation', 'Leak', 'Periodic'])
        self.ev_filter.currentIndexChanged.connect(self._fill_events); evl.addWidget(self.ev_filter)
        self.ev_table = Table(['Time', 'Type', 'Source', 'Dur s', 'Set P', 'Mask P', 'Leak', 'FlowLim', 'Detail']); self.ev_table.doubleClicked.connect(self._event_dbl)
        evl.addWidget(self.ev_table); self.tabs.addTab(Page(ev_w, 'Events', 'Every event the machine scored and every one the app found. Double-click to see it.', '#e34948'), 'Events')
        self.breaths = BreathView(); self.tabs.addTab(Page(self.breaths, 'Breaths', 'Breath by breath mechanics, and events against the pressure they happened at.', '#1baf7a'), 'Breaths')
        self.stats_table = Table([h for _, h, _ in scoring.STAT_COLUMNS]); self.tabs.addTab(Page(self.stats_table, 'Statistics', 'Every number for every night. Hover a column heading for what it means. Export to CSV from the toolbar.', '#eda100'), 'Statistics')
        dev = QtWidgets.QWidget(); dl = QtWidgets.QVBoxLayout(dev); self.dev_text = QtWidgets.QLabel(''); self.dev_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        dl.addWidget(self.dev_text); self.str_table = Table(['Day']); dl.addWidget(self.str_table); self.tabs.addTab(Page(dev, 'Device and settings', 'Machine identity and the machine\'s own daily summary when the card root is opened.', '#8a8985'), 'Device and settings')
        meth = QtWidgets.QTextBrowser(); meth.setHtml(METHODS); self.tabs.addTab(Page(meth, 'Methods', 'How every number is computed and how far to trust it.', '#1d4f91'), 'Methods')
        self.tabs.currentChanged.connect(self._tab_changed)
        self._refresh_home()
        last = SETTINGS.value('root', ''); hist = self.history_folder()
        if (last and os.path.isdir(last)) or (hist and os.path.isdir(os.path.join(hist, 'DATALOG'))):
            QtCore.QTimer.singleShot(200, lambda: self.load(last if last and os.path.isdir(last) else hist))
        else:
            self.statusBar().showMessage('Open the SD card (the card root or its DATALOG folder), or click Load sample data to try the app with made-up data.')

    # ------------------------------------------------------------------ loading
    def open_card(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select the SD card root or DATALOG folder', SETTINGS.value('root', ''))
        if d: self.load(d)
    def close_data(self):
        """Forget the remembered folder and show the app as a new user sees it."""
        SETTINGS.remove('root'); self.data = None; self.nights = []; self.current = None
        self.night_table.setRowCount(0); self.stats_table.setRowCount(0); self.ev_table.setRowCount(0); self.device_label.setText(''); self.dev_text.setText('')
        self.overview.gl.clear(); self.breaths.gl.clear(); self.night_view.set_night(None); self.synopsis.text.setHtml('<p>No data loaded.</p>')
        if hasattr(self.landscape, 'gl'):
            for it in self.landscape.items: self.landscape.gl.removeItem(it)
            self.landscape.items = []
        self._refresh_home(); self.tabs.setCurrentIndex(0); self.statusBar().showMessage('Data closed. Open an SD card or load the sample data.')
    def load_sample(self):
        from . import sample_data
        base = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'SleepScope', 'sample_card')
        if not os.path.isdir(os.path.join(base, 'DATALOG')):
            self.statusBar().showMessage('Generating a synthetic sample card (seven nights, made-up patient)...'); QtWidgets.QApplication.processEvents()
            try: sample_data.write_card(base)
            except Exception as e: QtWidgets.QMessageBox.critical(self, 'Sample data', str(e)); return
        self.load(base)
    def reload(self):
        if self.data: self.load(self.data['root'])
    def load(self, root):
        if getattr(self, 'worker', None) is not None and self.worker.isRunning():
            return
        hist0 = self.history_folder()
        if root and loader.card_parts(root)[1] and not (hist0 and os.path.abspath(root).startswith(os.path.abspath(hist0))): SETTINGS.setValue('root', root)
        self.progress.setVisible(True); self.progress.setValue(0)
        hist = self.history_folder(); extra = self._old_card_copies() if hist and not os.path.isdir(os.path.join(hist, 'DATALOG')) else []
        self.worker = LoadWorker(root, hist, extra); self.worker.progress.connect(self._progress); self.worker.done.connect(self._loaded); self.worker.failed.connect(self._failed); self.worker.start()
    def _progress(self, i, n, msg):
        self.progress.setMaximum(max(n, 1)); self.progress.setValue(i); self.statusBar().showMessage(msg)
    def _failed(self, tb):
        self.progress.setVisible(False); QtWidgets.QMessageBox.critical(self, 'Load failed', tb)
    def _loaded(self, data):
        self.data = data; self.nights = data['nights']; self.progress.setVisible(False)
        ident = data.get('identification') or {}
        self.device_label.setText(f"{ident.get('model', 'Unknown device')}  SN {ident.get('serial', '?')}\n{data['datalog']}")
        kept = getattr(self.worker, 'copied', 0) if getattr(self, 'worker', None) else 0
        src = "SleepScope's own copy (Card history)" if data.get('history') else data['datalog']
        card_in = bool(loader.card_parts(data.get('card_root'))[1]) and not str(data.get('card_root', '')).startswith(str(self.history_folder() or '~~'))
        self.statusBar().showMessage(f"{len(self.nights)} nights loaded from {src}" + (f"; {kept} new or updated nights copied from the card" if kept else '') + ('' if card_in else '; card not in the PC, showing everything kept so far'))
        self.night_view.str_data = data.get('str') if isinstance(data.get('str'), dict) and 'signals' in data.get('str') else None; self.landscape.str_data = self.night_view.str_data
        scoring.apply_str_settings(self.nights, self.night_view.str_data)
        self._fill_nights(); self.overview.set_nights(self.nights); self._fill_stats(); self._fill_device(); self.synopsis.set_nights(self.nights); self.ask.set_nights(self.nights); self.ask.set_card_root(data.get('root')); self.ask.set_profile_folder(self.phone_folder()); self.notes.set_card_root(data.get('root')); self.landscape.set_nights(self.nights); self._refresh_home()
        if self.nights: self._auto_companions(data.get('root'))
        if self.nights: self._phone_sync()
        if self.nights: self.select_night(len(self.nights) - 1); self.landscape.mode.setCurrentIndex(0); self._show_tab(self.synopsis)
        if not self.nights: QtWidgets.QMessageBox.information(self, 'No data', 'No sessions of 5 minutes or longer were found under that folder.')

    def _fill_nights(self):
        rows = []
        for n in self.nights:
            s = n.stats
            rows.append([n.label, f"{s['hours']:.2f}", s.get('setting') or scoring.pressure_label(s), scoring.fmt('AHI', s['AHI']), scoring.fmt('app_AHI', s['app_AHI']) or ('card out' if s.get('summary_only') else ''), scoring.fmt('leak_95', s['leak_95']), scoring.fmt('press_95', s['press_95'])])
        self.night_table.fill(rows)
    def _fill_stats(self):
        if hasattr(self, 'ask'): self.ask.refresh_context()          # ring and Watch attach after the first fill
        self.stats_table.fill([[scoring.fmt(k, n.stats.get(k)) for k, _, _ in scoring.STAT_COLUMNS] for n in self.nights])
        from . import explain as _ex
        for ci, (k, lab, _) in enumerate(scoring.STAT_COLUMNS):
            it = self.stats_table.horizontalHeaderItem(ci)
            if it is not None and k in _ex.COLUMN_HELP: it.setToolTip(f'<b>{lab}</b><br>{_ex.COLUMN_HELP[k]}')
        total, hit = scoring.validation_summary(self.nights)
        self.stats_table.setToolTip(f'App detector reproduced {hit} of {total} machine-scored apneas on this card.')
        self.statusBar().showMessage(f"{len(self.nights)} nights loaded. App detector reproduced {hit} of {total} machine-scored apneas on this card.")
    def _fill_device(self):
        ident = self.data.get('identification') or {}; st = self.data.get('str')
        txt = '<br>'.join(f'<b>{k}</b>: {v}' for k, v in ident.items())
        if st is None: txt += '<br><br>STR.edf not found under the card root, so machine settings and the machine\'s daily summary are not available. Copy the whole card (including STR.edf) to see them.'
        elif 'error' in st: txt += f"<br><br>STR.edf could not be read: {st['error']}"
        self.dev_text.setText(txt)
        if st and 'signals' in st:
            labels = list(st['signals'].keys()); self.str_table.setColumnCount(1 + len(labels)); self.str_table.setHorizontalHeaderLabels(['Day'] + labels)
            rows = []
            for i, d in enumerate(st['days']):
                rows.append([d.strftime('%Y-%m-%d')] + [f"{st['signals'][l][i]:g}" for l in labels])
            self.str_table.fill(rows)

    # ------------------------------------------------------------------ night selection
    def select_night(self, i):
        self.night_table.selectRow(i)
    def _night_selected(self):
        rows = self.night_table.selectionModel().selectedRows()
        if not rows: return
        nt = self.nights[rows[0].row()]; self.current = nt
        self.night_view.set_night(nt); self.breaths.set_night(nt); self._fill_events(); self.landscape.set_selected(nt)
        if self.tabs.widget(self.tabs.currentIndex()) is self.home: self._show_tab(self.night_view)
    def _show_tab(self, inner):
        for i in range(self.tabs.count()):
            wdg = self.tabs.widget(i)
            if wdg is inner or getattr(wdg, 'inner', None) is inner: self.tabs.setCurrentIndex(i); return
    def _home_action(self, a):
        if a == 'open': self.open_card()
        elif a == 'synopsis': self._show_tab(self.synopsis)
        elif a == 'landscape': self._show_tab(self.landscape)
        elif a == 'ask': self._show_tab(self.ask); self.ask.key.setFocus()
        elif a == 'oximeter': self.import_oximeter()
        elif a == 'apple': self.import_apple()
    def _refresh_home(self):
        ox = any(s.has_oximetry for n in self.nights for s in n.sessions); ap = any(getattr(n, 'apple', None) for n in self.nights)
        self.home.update_status(self.nights, SETTINGS.value('api_key', ''), ox, ap)
    def _tab_changed(self, i):
        if self.tabs.widget(i) is getattr(self, 'home', None): self._refresh_home()
        if self.tabs.widget(i) is getattr(self, 'notes', None): self.notes.refresh()
        if getattr(self.tabs.widget(i), 'inner', None) is getattr(self, 'update_view', None): self.update_view.refresh()
    def _continue_conversation(self, pairs):
        self.ask.load_history(pairs); self._show_tab(self.ask)
    def _fill_events(self):
        nt = getattr(self, 'current', None)
        if nt is None: return
        f = self.ev_filter.currentText(); rows = []; self._ev_objs = []
        for s in nt.sessions:
            for e in sorted(s.machine_events + s.app_events, key=lambda e: e.start):
                if f == 'Machine only' and e.source != 'machine': continue
                if f == 'App only' and e.source != 'app': continue
                if f == 'Apneas' and 'Apnea' not in e.label: continue
                if f == 'Hypopneas' and e.label != 'Hypopnea': continue
                if f == 'Flow limitation' and e.label != 'Flow Limitation Run': continue
                if f == 'Leak' and e.label != 'Large Leak': continue
                if f == 'Periodic' and e.label != 'Periodic Breathing': continue
                i2 = int((e.start - s.start).total_seconds() / 2)
                def g(k, sc=1, fm='{:.1f}'):
                    a = s.ch.get(k); return fm.format(a[min(i2, len(a) - 1)] * sc) if a is not None and len(a) else ''
                rows.append([e.start.strftime('%H:%M:%S'), e.label, e.source, f'{e.duration:.0f}', g('Press'), g('MaskPress'), g('Leak', 60, '{:.0f}'), g('FlowLim', 1, '{:.2f}'), e.detail])
                self._ev_objs.append(e)
        self.ev_table.fill(rows)
    def _event_dbl(self, idx):
        e = self._ev_objs[idx.row()]; self._show_tab(self.night_view); self.night_view.goto_event(e)

    # ------------------------------------------------------------------ oximeter and export
    def companion_folders(self, root):
        home = os.path.expanduser('~')
        cands = [root, os.path.dirname(root) if root else None, SETTINGS.value('ox_folder', ''), self.phone_folder(),
                 *[self._find_sleepscope_folder(r) for r in self.sync_roots()],
                 os.path.join(home, 'Dropbox'), os.path.join(home, 'Dropbox', 'SleepScope'), os.path.join(home, 'Dropbox', 'O2Ring'),
                 os.path.join(home, 'OneDrive'), os.path.join(home, 'Downloads'), os.path.join(home, 'Documents', 'SleepScope')]
        return [c for c in cands if c]
    def history_folder(self):
        """Where SleepScope keeps its own copy of every night: Sleepscope/Card history in Dropbox, else beside the user's settings."""
        folder = self.phone_folder()
        if folder: return os.path.join(folder, loader.HISTORY_NAME)
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'SleepScope', loader.HISTORY_NAME)

    def _old_card_copies(self):
        """Earlier hand-made card copies in the Sleepscope folder (for example 'Card archive Oct 20 to Nov 3'), merged in once."""
        folder = self.phone_folder(); out = []
        if not folder or not os.path.isdir(folder): return out
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if name in (loader.HISTORY_NAME, '_to_delete') or not os.path.isdir(p): continue
            if loader.card_parts(p)[1]: out.append(p)
        return out

    RING_ARCHIVE = 'Ring archive'

    def _ring_archive(self, ox_files):
        """One file per ring recording. Every recording found anywhere is copied once into Sleepscope/Ring archive, so
        deleting it in O2 Insight Pro or ViHealth no longer loses the night; copies of the same recording (ViHealth CSV,
        PC CSV, raw file) are reduced to the one with the most readings. Returns the files to import."""
        import shutil
        folder = self.phone_folder(); arch = os.path.join(folder, self.RING_ARCHIVE) if folder else None
        idx_path = os.path.join(arch, 'index.json') if arch else None; idx = {}
        if arch:
            try: os.makedirs(arch, exist_ok=True)
            except OSError: arch = None
        if idx_path:
            try:
                with open(idx_path, encoding='utf-8') as f: idx = json.load(f)
            except Exception: idx = {}
        groups = {}
        for p in ox_files:
            try: st_ = os.stat(p); key = f"{os.path.basename(p)}|{st_.st_size}|{int(st_.st_mtime)}"
            except OSError: continue
            if key not in idx: idx[key] = list(loader.ring_start(p))
            start, nvalid = idx[key]
            if not start: continue
            groups.setdefault(int(start // 60), []).append((nvalid, p.startswith(arch) if arch else False, p))
        chosen = []
        for g in groups.values():
            g.sort(key=lambda r: (r[0], r[1]), reverse=True); best = g[0][2]
            if arch and not best.startswith(arch):
                dst = os.path.join(arch, os.path.basename(best))
                try:
                    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(best): shutil.copy2(best, dst)
                    best = dst
                except OSError: pass
            chosen.append(best)
        if idx_path:
            try:
                with open(idx_path, 'w', encoding='utf-8') as f: json.dump(idx, f)
            except OSError: pass
        return sorted(chosen)

    def _auto_companions(self, root):
        """Find ring recordings and Apple Health exports anywhere in the Sleepscope folder (and near the card), keep them, attach them."""
        self.apple_data = None; self.ring_files = []
        try:
            ox_files, health_files = loader.find_companion_files(self.companion_folders(root))
        except Exception:
            return
        try: ox_files = self._ring_archive(ox_files)
        except Exception: pass
        self.ring_files = ox_files
        filled = 0; used = 0
        for p in ox_files:
            try: n = loader.import_oximeter_csv(p, self.nights)
            except Exception: n = 0
            if n: filled += n; used += 1
        # Apple Health: Watch nights.json is the running record; the newest export (by the date inside it) is read once and merged in
        folder = self.phone_folder(); store, meta = (apple_health.load_store(folder) if folder else (None, {}))
        exports = [p for p in health_files if not p.lower().endswith(('.txt', '.csv'))]
        newest = max(exports, key=loader.health_export_date) if exports else None
        if newest and loader.health_export_date(newest) > meta.get('export_date', 0) + 1:
            if not (getattr(self, 'health_worker', None) and self.health_worker.isRunning()):
                since = min(self.nights[0].date, dt.date.today() - dt.timedelta(days=60))
                self.statusBar().showMessage('Reading the new Apple Health export in the background; Watch nights appear when it finishes…')
                self.health_worker = HealthWorker(newest, since); self.health_worker.done.connect(lambda p, d, f=folder, s=store: self._health_read(p, d, f, s)); self.health_worker.start()
        hmatched = 0
        if store:
            self.apple_data = store; hmatched = apple_health.attach(store, self.nights)
        else:
            for p in health_files:
                if not p.lower().endswith(('.txt', '.csv')) or hmatched: continue
                try:
                    data = apple_health.read_shortcut_csv(p); hmatched = max(hmatched, apple_health.attach(data, self.nights))
                    if hmatched: self.apple_data = data
                except Exception:
                    pass
        self._companions_done(filled, used, hmatched)

    def _health_read(self, path, data, folder, store):
        if isinstance(data, Exception):
            self.statusBar().showMessage(f'Could not read the Apple Health export ({data}).'); return
        merged = apple_health.merge(store, data)
        if folder:
            try: apple_health.save_store(folder, merged, {'export_date': loader.health_export_date(path), 'source': os.path.basename(os.path.dirname(path)) + '/' + os.path.basename(path)})
            except OSError: pass
        self.apple_data = merged; n = apple_health.attach(merged, self.nights)
        self._companions_done(0, 0, n, refresh=True)
        if folder and self.phone_folder(): self._phone_sync()

    def _companions_done(self, filled, used, hmatched, refresh=False):
        if filled or hmatched or refresh:
            for nt in self.nights: scoring.night_stats(nt)
            self._fill_stats(); self.overview.set_nights(self.nights); self.synopsis.set_nights(self.nights); self.landscape.set_nights(self.nights); self._refresh_home()
            parts = []
            if filled: parts.append(f'ring: {used} recording{"s" if used != 1 else ""}, oxygen on {filled} session{"s" if filled != 1 else ""}')
            if hmatched: parts.append(f'Apple Watch: {hmatched} night{"s" if hmatched != 1 else ""}')
            self.statusBar().showMessage(f'{len(self.nights)} nights loaded. ' + '; '.join(parts) + '.')

    @staticmethod
    def sync_roots():
        """Dropbox and OneDrive roots on this PC. Covers 'Dropbox', team folders named '<Team> Dropbox', and the paths
        the Dropbox app records in info.json."""
        home = os.path.expanduser('~'); roots = []
        for base in (os.environ.get('LOCALAPPDATA', ''), os.environ.get('APPDATA', '')):
            info = os.path.join(base, 'Dropbox', 'info.json') if base else ''
            if info and os.path.exists(info):
                try:
                    with open(info, encoding='utf-8') as fh:
                        for v in json.load(fh).values():
                            if isinstance(v, dict) and v.get('path'): roots.append(v['path'])
                except Exception: pass
        try:
            for name in os.listdir(home):
                if (name == 'Dropbox' or name.endswith(' Dropbox') or name == 'OneDrive' or name.startswith('OneDrive - ')) and os.path.isdir(os.path.join(home, name)):
                    roots.append(os.path.join(home, name))
        except OSError: pass
        out = []
        for r in roots:
            r = os.path.normpath(r)
            if os.path.isdir(r) and r not in out: out.append(r)
        out.sort(key=lambda r: 'onedrive' in r.lower())          # Dropbox first
        return out
    @staticmethod
    def _find_sleepscope_folder(root):
        """An existing folder named SleepScope (any case) at the root or one level down, such as a team member folder."""
        try:
            for name in os.listdir(root):
                if name.lower() == 'sleepscope' and os.path.isdir(os.path.join(root, name)): return os.path.join(root, name)
            for name in sorted(os.listdir(root)):
                sub = os.path.join(root, name)
                if name.startswith('.') or not os.path.isdir(sub): continue
                try:
                    for n2 in os.listdir(sub):
                        if n2.lower() == 'sleepscope' and os.path.isdir(os.path.join(sub, n2)): return os.path.join(sub, n2)
                except OSError: pass
        except OSError: pass
        return None
    def phone_folder(self):
        f = SETTINGS.value('phone_folder', '')
        if f == 'off': return None
        if f: return f
        roots = self.sync_roots()
        for r in roots:
            hit = self._find_sleepscope_folder(r)
            if hit: return hit
        return os.path.join(roots[0], 'SleepScope') if roots else None
    def _phone_sync(self):
        folder = self.phone_folder()
        if not folder or not self.data or not self.data.get('datalog') or not os.path.isdir(self.data['datalog']): return
        if os.path.abspath(self.data['root']).startswith(os.path.abspath(folder)): return      # loading from the phone copy itself
        if getattr(self, 'sync_worker', None) is not None and self.sync_worker.isRunning(): return
        try:
            import time as _t
            ring = [p_ for p_ in (getattr(self, 'ring_files', None) or loader.find_companion_files(self.companion_folders(self.data.get('root')))[0]) if _t.time() - os.path.getmtime(p_) < 60 * 86400]
        except Exception: ring = []
        self.sync_worker = PhoneSyncWorker(self.data['root'], self.data['datalog'], folder, self.nights, ring, getattr(self, 'apple_data', None))
        self.sync_worker.done.connect(lambda msg: self.statusBar().showMessage(msg, 15000)); self.sync_worker.start()
    def set_phone_folder(self):
        cur = self.phone_folder() or os.path.expanduser('~')
        box = QtWidgets.QMessageBox(self); box.setWindowTitle('Phone copy')
        box.setText(f"Every time a card is opened, SleepScope saves it as one file, SleepScope card.zip, in a synced folder so the phone app can open it.\n\nNow: {self.phone_folder() or 'off'}")
        b1 = box.addButton('Choose folder…', QtWidgets.QMessageBox.AcceptRole); b2 = box.addButton('Turn off', QtWidgets.QMessageBox.DestructiveRole); box.addButton('Close', QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b1:
            d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Synced folder for the phone copy, for example Dropbox\\SleepScope', cur)
            if d: SETTINGS.setValue('phone_folder', d); self._phone_sync()
        elif box.clickedButton() is b2:
            SETTINGS.setValue('phone_folder', 'off'); self.statusBar().showMessage('Phone copy turned off.')
    def set_companion_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Folder where the O2Ring CSV exports (and the Health Shortcut file) are saved, for example Dropbox\\SleepScope', SETTINGS.value('ox_folder', os.path.expanduser('~')))
        if not d: return
        SETTINGS.setValue('ox_folder', d)
        if self.nights: self._auto_companions(self.data.get('root') if self.data else None)
        else: self.statusBar().showMessage('Companion folder set to ' + d)
    def import_oximeter(self):
        if not self.nights: return
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Oximeter CSV export (Wellue O2Ring, Checkme, generic)', '', 'CSV (*.csv);;All files (*)')
        if not p: return
        n = loader.import_oximeter_csv(p, self.nights)
        for nt in self.nights: scoring.night_stats(nt)
        self._fill_stats(); self.overview.set_nights(self.nights); self._night_selected(); self.synopsis.generate(); self.landscape.set_nights(self.nights); self._refresh_home()
        QtWidgets.QMessageBox.information(self, 'Oximeter import', f'SpO2 and pulse attached to {n} session(s) by timestamp.')
    def import_apple(self):
        if not self.nights: return
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Apple Health: export.zip, export.xml, or the Shortcut file (sleepscope_health.txt)', '', 'Apple Health (*.zip *.xml *.txt *.csv);;All files (*)')
        if not p: return
        self.statusBar().showMessage('Reading Apple Health file...'); QtWidgets.QApplication.processEvents()
        try:
            if p.lower().endswith(('.txt', '.csv')): data = apple_health.read_shortcut_csv(p)
            else: data = apple_health.read_export(p, date_from=self.nights[0].date, progress=lambda n: (self.statusBar().showMessage(f'Reading Apple Health export: {n:,} records'), QtWidgets.QApplication.processEvents()))
            n = apple_health.attach(data, self.nights); self.apple_data = data
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Apple Health import', str(e)); return
        self._fill_stats(); self._night_selected(); self.synopsis.generate(); self.landscape.set_nights(self.nights); self._refresh_home()
        QtWidgets.QMessageBox.information(self, 'Apple Health import', f'{len(data["sleep"]):,} sleep records, {len(data.get("bd", [])):,} breathing disturbance nights, {len(data["hr"]):,} heart rate samples, {len(data["spo2"]):,} SpO2 samples read.\nMatched to {n} of {len(self.nights)} nights.\n\nTip: leave export.zip (or the unzipped export folder) in the Sleepscope folder and SleepScope picks it up by itself on every load.')
    def export_table(self, table, default):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save CSV', default, 'CSV (*.csv)')
        if p: table.to_csv(p); self.statusBar().showMessage('Saved ' + p)
    def export_events(self):
        if not self.nights: return
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save events CSV', 'sleepscope_events.csv', 'CSV (*.csv)')
        if not p: return
        with open(p, 'w', newline='') as f:
            w = csv.writer(f); w.writerow(['night', 'start', 'end', 'duration_s', 'type', 'source', 'detail'])
            for nt in self.nights:
                for s in nt.sessions:
                    for e in sorted(s.machine_events + s.app_events, key=lambda e: e.start):
                        w.writerow([nt.date, e.start.isoformat(), e.end.isoformat(), f'{e.duration:.0f}', e.label, e.source, e.detail])
        self.statusBar().showMessage('Saved ' + p)
    def save_png(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save PNG', 'sleepscope.png', 'PNG (*.png)')
        if p: self.tabs.currentWidget().grab().save(p); self.statusBar().showMessage('Saved ' + p)


def main():
    from . import theme
    app = QtWidgets.QApplication(sys.argv); app.setApplicationName('SleepScope'); theme.apply(app)
    def excepthook(t, v, tb):
        import traceback; msg = ''.join(traceback.format_exception(t, v, tb)); print(msg, file=sys.stderr)
        QtWidgets.QMessageBox.critical(None, 'SleepScope error', msg)
    sys.excepthook = excepthook
    app.setWindowIcon(app_icon())
    w = MainWindow(); w.setWindowIcon(app_icon()); w.show()
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]): w.load(sys.argv[1])
    sys.exit(app.exec())
