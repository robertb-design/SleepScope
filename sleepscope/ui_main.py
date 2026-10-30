from __future__ import annotations
import os, sys, json, csv, datetime as dt
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets, QtGui
from . import loader, scoring, synopsis, apple_health
from .theme import C, EVENT_COLORS, style_plot
from .ui_night import NightView
from .ui_ask import AskView
from .ui_landscape import LandscapeView
from .ui_notes import NotesView
from .ui_help import HelpView

SETTINGS = QtCore.QSettings('SleepScope', 'SleepScope')


class LoadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int, str)
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    def __init__(self, root):
        super().__init__(); self.root = root
    def run(self):
        try:
            data = loader.scan(self.root, progress=lambda i, n, name: self.progress.emit(i, n, 'Reading ' + name))
            nights = data['nights']
            for i, nt in enumerate(nights):
                self.progress.emit(i, len(nights), 'Scoring ' + nt.label)
                for s in nt.sessions:
                    scoring.score_session(s)
                scoring.night_stats(nt)
            self.done.emit(data)
        except Exception as e:
            import traceback; self.failed.emit(traceback.format_exc())


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


class OverviewView(QtWidgets.QWidget):
    night_clicked = QtCore.Signal(int)
    def __init__(self):
        super().__init__(); lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        self.gl = pg.GraphicsLayoutWidget(); self.gl.setBackground('w'); lay.addWidget(self.gl)
        self.note = QtWidgets.QLabel(''); self.note.setStyleSheet('color:#52514e'); lay.addWidget(self.note)
    def set_nights(self, nights):
        self.gl.clear(); self.nights = nights
        if not nights: return
        labs = [n.label for n in nights]; x = np.arange(len(nights)); S = [n.stats for n in nights]
        def g(k): return np.array([s.get(k, np.nan) for s in S], dtype=float)
        def plot(row, col, title, unit=''):
            p = self.gl.addPlot(row=row, col=col, axisItems={'bottom': BarAxis(labs, orientation='bottom')}); style_plot(p)
            p.setTitle(title, size='10pt', color='#0b0b0b'); p.setLabel('left', unit); p.setMouseEnabled(x=False, y=False); p.hideButtons()
            p.getAxis('bottom').setTicks([[(i, labs[i]) for i in range(len(labs))]]); p.setXRange(-0.6, len(labs) - 0.4, padding=0)
            p.scene().sigMouseClicked.connect(lambda ev, p=p: self._click(ev, p)); return p
        def bars(p, vals, color, width=0.6, off=0.0, name=None):
            b = pg.BarGraphItem(x=x + off, height=np.nan_to_num(vals), width=width, brush=pg.mkBrush(color), pen=pg.mkPen('w'))
            p.addItem(b); return b
        # usage
        p = plot(0, 0, 'Usage (hours)', 'h'); bars(p, g('hours'), C['blue']); p.setYRange(0, np.nanmax(g('hours')) * 1.2 + 0.5); p.addLine(y=4, pen=pg.mkPen(C['text2'], style=QtCore.Qt.DashLine))
        for i, v in enumerate(g('hours')):
            t = pg.TextItem(f'{v:.1f}', color=C['text2'], anchor=(0.5, 1)); t.setPos(i, v); p.addItem(t)
        # AHI machine vs app
        p = plot(0, 1, 'AHI: machine (blue) vs app flow-only (orange), RDI app (violet line)', '/h')
        bars(p, g('AHI'), C['blue'], 0.28, -0.3); bars(p, g('app_AHI'), C['orange'], 0.28, 0.0)
        p.plot(x, g('app_RDI'), pen=pg.mkPen(C['violet'], width=2), symbol='o', symbolBrush=C['violet'], symbolPen=None, symbolSize=7)
        p.addLine(y=5, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine))
        # events stacked
        p = plot(1, 0, 'Machine events: OA (red), CA (violet), H (orange)', 'count')
        base = np.zeros(len(x))
        for k, c in (('OA', C['red']), ('CA', C['violet']), ('H', C['orange'])):
            v = g(k); b = pg.BarGraphItem(x=x, y0=base, height=v, width=0.6, brush=pg.mkBrush(c), pen=pg.mkPen('w')); p.addItem(b); base += v
        # pressure
        p = plot(1, 1, 'Set pressure: min to max (band), median (aqua), 95th (blue)', 'cmH2O')
        lo, hi = g('press_min'), g('press_max')
        fill = pg.FillBetweenItem(pg.PlotDataItem(x, lo), pg.PlotDataItem(x, hi), brush=pg.mkBrush(42, 120, 214, 35)); p.addItem(fill)
        p.plot(x, g('press_95'), pen=pg.mkPen(C['blue'], width=2), symbol='o', symbolBrush=C['blue'], symbolPen=None, symbolSize=7)
        p.plot(x, g('press_med'), pen=pg.mkPen(C['aqua'], width=2), symbol='o', symbolBrush=C['aqua'], symbolPen=None, symbolSize=7)
        p.plot(x, hi, pen=pg.mkPen(C['red'], width=1, style=QtCore.Qt.DashLine), stepMode=None)
        p.setYRange(3, max(13, np.nanmax(hi) + 1) if np.isfinite(np.nanmax(hi)) else 13)
        # leak
        p = plot(2, 0, 'Leak: median (aqua), 95th percentile (orange); dashed = 24 L/min', 'L/min')
        bars(p, g('leak_med'), C['aqua'], 0.28, -0.3); bars(p, g('leak_95'), C['orange'], 0.28, 0.0); p.addLine(y=24, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine))
        # flow limitation
        p = plot(2, 1, 'Flow limitation: minutes above 0.2 (violet bars), 95th percentile x100 (line)', 'min')
        bars(p, g('flowlim_minutes'), C['violet']); p.plot(x, g('flowlim_95') * 100, pen=pg.mkPen(C['orange'], width=2), symbol='o', symbolBrush=C['orange'], symbolPen=None, symbolSize=7)
        # breathing
        p = plot(3, 0, 'Breathing: RR bpm (blue), MV L/min (aqua), Vt/50 mL (green)', '')
        bars(p, g('rr_med'), C['blue'], 0.2, -0.25); bars(p, g('mv_med'), C['aqua'], 0.2, 0.0); bars(p, g('tv_med') / 50, C['green'], 0.2, 0.25)
        # spo2 if any
        if np.isfinite(g('spo2_mean')).any():
            p = plot(3, 1, 'SpO2: mean (blue), min (red); ODI (orange line)', '%')
            p.plot(x, g('spo2_mean'), pen=pg.mkPen(C['blue'], width=2), symbol='o', symbolBrush=C['blue'], symbolPen=None)
            p.plot(x, g('spo2_min'), pen=pg.mkPen(C['red'], width=2), symbol='o', symbolBrush=C['red'], symbolPen=None)
            p.plot(x, g('ODI'), pen=pg.mkPen(C['orange'], width=2), symbol='o', symbolBrush=C['orange'], symbolPen=None); p.setYRange(0, 100)
        else:
            p = plot(3, 1, 'Time at max pressure (% of night) and periodic breathing windows (magenta)', '%')
            bars(p, g('press_at_max_pct'), C['blue']); p.plot(x, g('periodic_windows'), pen=pg.mkPen(C['magenta'], width=2), symbol='o', symbolBrush=C['magenta'], symbolPen=None)
        tot_h = sum(n.hours for n in nights); ev = sum(s['OA'] + s['CA'] + s['H'] for s in S)
        self.note.setText(f"{len(nights)} nights, {tot_h:.1f} h, mean {tot_h / len(nights):.2f} h/night, machine AHI {ev / tot_h:.2f} overall, app flow-only AHI {np.nanmean(g('app_AHI')):.2f}, app RDI {np.nanmean(g('app_RDI')):.2f}. Click a bar to open that night.")
    def _click(self, ev, p):
        if ev.double(): return
        x = p.vb.mapSceneToView(ev.scenePos()).x(); i = int(round(x))
        if 0 <= i < len(self.nights): self.night_clicked.emit(i)


class BreathView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        self.gl = pg.GraphicsLayoutWidget(); self.gl.setBackground('w'); lay.addWidget(self.gl)
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
        self.note.setText(f'{sum(len(b["t0"]) for b in brs)} breaths segmented from the 25 Hz flow. Plateau ratio: mean of middle 50% of inspiration over its peak (a half sine scores about 0.90; above 0.95 is a flat top). PIF/PEF well below 0.7 with a long Ti is the inspiratory shape seen during flow limited runs.')


class SynopsisView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); self.nights = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout(); lay.addLayout(bar)
        bar.addWidget(QtWidgets.QLabel('From')); self.d0 = QtWidgets.QDateEdit(calendarPopup=True); self.d0.setDisplayFormat('MMM d, yyyy'); bar.addWidget(self.d0)
        bar.addWidget(QtWidgets.QLabel('to')); self.d1 = QtWidgets.QDateEdit(calendarPopup=True); self.d1.setDisplayFormat('MMM d, yyyy'); bar.addWidget(self.d1)
        for lab, days in (('Last 7', 7), ('Last 14', 14), ('Last 30', 30), ('All', None)):
            b = QtWidgets.QPushButton(lab); b.clicked.connect(lambda _, d=days: self.quick(d)); bar.addWidget(b)
        bar.addSpacing(16); bar.addWidget(QtWidgets.QLabel('Diagnostic AHI (from your sleep study, optional)'))
        self.diag = QtWidgets.QDoubleSpinBox(); self.diag.setRange(0, 200); self.diag.setDecimals(0); self.diag.setSpecialValueText('not set')
        self.diag.setValue(float(SETTINGS.value('diag_ahi', 0))); self.diag.valueChanged.connect(lambda v: SETTINGS.setValue('diag_ahi', v)); bar.addWidget(self.diag)
        bar.addStretch()
        gen = QtWidgets.QPushButton('Generate'); gen.setDefault(True); gen.clicked.connect(self.generate); bar.addWidget(gen)
        cp = QtWidgets.QPushButton('Copy'); cp.clicked.connect(self.copy); bar.addWidget(cp)
        sv = QtWidgets.QPushButton('Save HTML…'); sv.clicked.connect(self.save); bar.addWidget(sv)
        self.text = QtWidgets.QTextBrowser(); self.text.setOpenExternalLinks(True); self.text.setStyleSheet('font-size:13px; padding:8px'); lay.addWidget(self.text)
        self.d0.dateChanged.connect(self.generate); self.d1.dateChanged.connect(self.generate); self.diag.valueChanged.connect(self.generate)
    def set_nights(self, nights):
        self.nights = nights
        if not nights: return
        self.d0.blockSignals(True); self.d1.blockSignals(True)
        self.d0.setDate(QtCore.QDate(nights[0].date)); self.d1.setDate(QtCore.QDate(nights[-1].date))
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
    def copy(self): QtWidgets.QApplication.clipboard().setText(self.text.toPlainText())
    def save(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save synopsis', 'sleepscope_synopsis.html', 'HTML (*.html)')
        if p: open(p, 'w', encoding='utf-8').write('<html><body style="font-family:Segoe UI,Arial;max-width:800px;margin:auto">' + getattr(self, 'html', '') + '</body></html>')


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
<li><b>Apnea:</b> envelope below 70% of baseline for at least 10 s, with some 8 s block below 25%. Validated on this card: 18 of 19 machine apneas reproduced;
the one disagreement had 41% residual flow and the app calls it a hypopnea. The app cannot tell obstructive from central (that needs the machine's forced
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
<li><b>ODI:</b> count of SpO2 drops of 3% or more from the preceding 60 s maximum, per hour, when oximetry exists.</li>
</ul>
<p><b>Breath metrics</b> are descriptive only and do not generate events: Ti, Te, I:E, PIF, PEF, PIF/PEF, integrated tidal volume, plateau ratio.
The machine's flow limitation index is proprietary and could not be reproduced from breath shape alone, which is why the machine channel is used for runs.</p>
<p><b>3D Landscape.</b> One strip per night. Height = openness = min(ventilation ratio, 1) x (1 - 0.7 x machine flow limitation), averaged over 2 minute bins
and lightly smoothed. Grey = mask off. Blue pools = leak over 24 L/min. Pillars = machine events. White line = set pressure (4 cmH2O at the strip, rising with pressure).
It is a picture of the same numbers the other tabs show, arranged so a week reads at a glance.</p>
<p><b>Synopsis tab.</b> The plain English report is generated by fixed rules from the per-night statistics (thresholds: AHI under 5 controlled;
usage 4 h on 70% of nights; leak 95th percentile under 24 L/min; central index over 5 with centrals above half of events flagged; ODI under 5 normal;
time under 88% over 5 minutes flagged). It is deterministic: the same data always produces the same text. It does not use an online service.</p>
<p><b>Apple Health.</b> Import the export.zip the Health app produces (Profile picture, Export All Health Data). Sleep stages, heart rate, HRV, respiratory
rate and Watch SpO2 are matched to each night. The Watch's stages come from motion and heart rate, not EEG, so treat them as approximate.
Writing CPAP data into Apple Health needs an iOS app and cannot be done from Windows.</p>
<p><b>This is not a medical device.</b> Use it to understand the data and to bring better questions to the person who manages the prescription.</p>
"""


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('SleepScope'); self.resize(1500, 950)
        self.data = None; self.nights = []
        tb = self.addToolBar('Main'); tb.setMovable(False); tb.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        tb.addAction('Open SD card…', self.open_card); tb.addAction('Reload', self.reload); tb.addAction('Load sample data', self.load_sample)
        tb.addAction('Import oximeter CSV…', self.import_oximeter); tb.addAction('Import Apple Health export…', self.import_apple); tb.addSeparator()
        tb.addAction('Export statistics CSV', lambda: self.export_table(self.stats_table, 'sleepscope_nights.csv'))
        tb.addAction('Export events CSV', self.export_events); tb.addAction('Save chart as PNG', self.save_png)
        self.progress = QtWidgets.QProgressBar(); self.progress.setFixedWidth(220); self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)

        split = QtWidgets.QSplitter(); self.setCentralWidget(split)
        left = QtWidgets.QWidget(); ll = QtWidgets.QVBoxLayout(left); ll.setContentsMargins(4, 4, 0, 4)
        self.night_table = Table(['Night', 'Hours', 'Mode', 'AHI', 'AHI app', 'Leak 95', 'P 95'])
        self.night_table.itemSelectionChanged.connect(self._night_selected); ll.addWidget(self.night_table)
        self.device_label = QtWidgets.QLabel(''); self.device_label.setWordWrap(True); self.device_label.setStyleSheet('color:#52514e'); ll.addWidget(self.device_label)
        left.setMinimumWidth(440); split.addWidget(left)

        self.tabs = QtWidgets.QTabWidget(); split.addWidget(self.tabs); split.setSizes([470, 1030])
        self.tabs.addTab(HelpView(), 'How to use')
        self.overview = OverviewView(); self.overview.night_clicked.connect(self.select_night); self.tabs.addTab(self.overview, 'Overview')
        self.synopsis = SynopsisView(); self.tabs.addTab(self.synopsis, 'Synopsis')
        self.landscape = LandscapeView(); self.tabs.addTab(self.landscape, '3D Landscape')
        self.ask = AskView(); self.tabs.addTab(self.ask, 'Ask Claude')
        self.notes = NotesView(); self.tabs.addTab(self.notes, 'Saved answers')
        self.notes.continue_requested.connect(self._continue_conversation)
        self.ask.answer_saved.connect(self.notes.refresh)
        self.night_view = NightView(); self.tabs.addTab(self.night_view, 'Night')
        ev_w = QtWidgets.QWidget(); evl = QtWidgets.QVBoxLayout(ev_w); evl.setContentsMargins(4, 4, 4, 4)
        self.ev_filter = QtWidgets.QComboBox(); self.ev_filter.addItems(['All', 'Machine only', 'App only', 'Apneas', 'Hypopneas', 'Flow limitation', 'Leak', 'Periodic'])
        self.ev_filter.currentIndexChanged.connect(self._fill_events); evl.addWidget(self.ev_filter)
        self.ev_table = Table(['Time', 'Type', 'Source', 'Dur s', 'Set P', 'Mask P', 'Leak', 'FlowLim', 'Detail']); self.ev_table.doubleClicked.connect(self._event_dbl)
        evl.addWidget(self.ev_table); self.tabs.addTab(ev_w, 'Events')
        self.breaths = BreathView(); self.tabs.addTab(self.breaths, 'Breaths')
        self.stats_table = Table([h for _, h, _ in scoring.STAT_COLUMNS]); self.tabs.addTab(self.stats_table, 'Statistics')
        dev = QtWidgets.QWidget(); dl = QtWidgets.QVBoxLayout(dev); self.dev_text = QtWidgets.QLabel(''); self.dev_text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        dl.addWidget(self.dev_text); self.str_table = Table(['Day']); dl.addWidget(self.str_table); self.tabs.addTab(dev, 'Device and settings')
        meth = QtWidgets.QTextBrowser(); meth.setHtml(METHODS); self.tabs.addTab(meth, 'Methods')
        self.tabs.currentChanged.connect(self._tab_changed)
        last = SETTINGS.value('root', '')
        if last and os.path.isdir(last):
            QtCore.QTimer.singleShot(200, lambda: self.load(last))
        else:
            self.statusBar().showMessage('Open the SD card (the card root or its DATALOG folder), or click Load sample data to try the app with made-up data.')

    # ------------------------------------------------------------------ loading
    def open_card(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select the SD card root or DATALOG folder', SETTINGS.value('root', ''))
        if d: self.load(d)
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
        SETTINGS.setValue('root', root); self.progress.setVisible(True); self.progress.setValue(0)
        self.worker = LoadWorker(root); self.worker.progress.connect(self._progress); self.worker.done.connect(self._loaded); self.worker.failed.connect(self._failed); self.worker.start()
    def _progress(self, i, n, msg):
        self.progress.setMaximum(max(n, 1)); self.progress.setValue(i); self.statusBar().showMessage(msg)
    def _failed(self, tb):
        self.progress.setVisible(False); QtWidgets.QMessageBox.critical(self, 'Load failed', tb)
    def _loaded(self, data):
        self.data = data; self.nights = data['nights']; self.progress.setVisible(False)
        ident = data.get('identification') or {}
        self.device_label.setText(f"{ident.get('model', 'Unknown device')}  SN {ident.get('serial', '?')}\n{data['datalog']}")
        self.statusBar().showMessage(f"{len(self.nights)} nights loaded from {data['datalog']}")
        self._fill_nights(); self.overview.set_nights(self.nights); self._fill_stats(); self._fill_device(); self.synopsis.set_nights(self.nights); self.ask.set_nights(self.nights); self.ask.set_card_root(data.get('root')); self.notes.set_card_root(data.get('root')); self.landscape.set_nights(self.nights)
        if self.nights: self.select_night(len(self.nights) - 1); self.tabs.setCurrentWidget(self.synopsis)
        if not self.nights: QtWidgets.QMessageBox.information(self, 'No data', 'No sessions of 5 minutes or longer were found under that folder.')

    def _fill_nights(self):
        rows = []
        for n in self.nights:
            s = n.stats
            rows.append([n.label, f"{s['hours']:.2f}", s['mode'], f"{s['AHI']:.2f}", f"{s['app_AHI']:.2f}", scoring.fmt('leak_95', s['leak_95']), scoring.fmt('press_95', s['press_95'])])
        self.night_table.fill(rows)
    def _fill_stats(self):
        self.stats_table.fill([[scoring.fmt(k, n.stats.get(k)) for k, _, _ in scoring.STAT_COLUMNS] for n in self.nights])
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
        self.night_view.set_night(nt); self.breaths.set_night(nt); self._fill_events()
        if self.tabs.currentIndex() == 0: self.tabs.setCurrentIndex(1)
    def _tab_changed(self, i):
        if self.tabs.widget(i) is getattr(self, 'notes', None): self.notes.refresh()
    def _continue_conversation(self, pairs):
        self.ask.load_history(pairs); self.tabs.setCurrentWidget(self.ask)
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
        e = self._ev_objs[idx.row()]; self.tabs.setCurrentIndex(1); self.night_view.goto_event(e)

    # ------------------------------------------------------------------ oximeter and export
    def import_oximeter(self):
        if not self.nights: return
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Oximeter CSV export (Wellue O2Ring, Checkme, generic)', '', 'CSV (*.csv);;All files (*)')
        if not p: return
        n = loader.import_oximeter_csv(p, self.nights)
        for nt in self.nights: scoring.night_stats(nt)
        self._fill_stats(); self.overview.set_nights(self.nights); self._night_selected(); self.synopsis.generate(); self.landscape.set_nights(self.nights)
        QtWidgets.QMessageBox.information(self, 'Oximeter import', f'SpO2 and pulse attached to {n} session(s) by timestamp.')
    def import_apple(self):
        if not self.nights: return
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Apple Health export (export.zip or export.xml)', '', 'Apple Health export (*.zip *.xml);;All files (*)')
        if not p: return
        self.statusBar().showMessage('Reading Apple Health export, this can take a minute for a large file...'); QtWidgets.QApplication.processEvents()
        try:
            data = apple_health.read_export(p, date_from=self.nights[0].date, progress=lambda n: (self.statusBar().showMessage(f'Reading Apple Health export: {n:,} records'), QtWidgets.QApplication.processEvents()))
            n = apple_health.attach(data, self.nights)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, 'Apple Health import', str(e)); return
        self._night_selected(); self.synopsis.generate(); self.landscape.set_nights(self.nights)
        QtWidgets.QMessageBox.information(self, 'Apple Health import', f'{len(data["sleep"]):,} sleep records, {len(data["hr"]):,} heart rate samples, {len(data["spo2"]):,} SpO2 samples read.\nMatched to {n} of {len(self.nights)} nights.')
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
    w = MainWindow(); w.show()
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]): w.load(sys.argv[1])
    sys.exit(app.exec())
