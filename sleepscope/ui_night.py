"""Night viewer: stacked, time-linked panels over the raw signals with machine and app events overlaid."""
from __future__ import annotations
import datetime as dt
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets, QtGui
from .theme import C, EVENT_COLORS, style_plot

PANELS = [  # key, title, units, y range or None
    ('flow', 'Flow', 'L/min', None),
    ('press', 'Pressure (set, mask, EPR)', 'cmH2O', (0, 21)),
    ('leak', 'Leak', 'L/min', (0, 60)),
    ('flowlim', 'Flow limitation (machine) and snore', 'index', (0, 1.05)),
    ('vent', 'Ventilation vs 2 min baseline (app)', 'ratio', (0, 2.5)),
    ('rr', 'Respiratory rate', 'bpm', (0, 35)),
    ('tv', 'Tidal volume', 'mL', (0, 1200)),
    ('mv', 'Minute ventilation', 'L/min', (0, 20)),
    ('spo2', 'SpO2', '%', (80, 100)),
    ('pulse', 'Pulse', 'bpm', (40, 120)),
    ('apple_stage', 'Apple Watch sleep stage', '', (-0.5, 4.5)),
    ('apple_hr', 'Apple Watch heart rate and SpO2', 'bpm / %', (40, 110)),
]


class TimeAxis(pg.AxisItem):
    def __init__(self, t0: dt.datetime, *a, **k):
        super().__init__(*a, **k); self.t0 = t0
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            t = self.t0 + dt.timedelta(seconds=float(v))
            out.append(t.strftime('%H:%M:%S') if spacing < 60 else t.strftime('%H:%M'))
        return out


class NightView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.night = None; self.t0 = None; self.plots = {}; self.curves = {}; self.regions = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(4)
        bar = QtWidgets.QHBoxLayout(); lay.addLayout(bar)
        self.title = QtWidgets.QLabel('No night selected'); self.title.setStyleSheet('font-weight:600; font-size:13px')
        bar.addWidget(self.title); bar.addStretch()
        for lab, secs in [('30 s', 30), ('2 min', 120), ('10 min', 600), ('1 h', 3600), ('Night', None)]:
            b = QtWidgets.QPushButton(lab); b.setFixedWidth(56); b.clicked.connect(lambda _, s=secs: self.zoom_to(s)); bar.addWidget(b)
        self.prev_btn = QtWidgets.QPushButton('◀ event'); self.next_btn = QtWidgets.QPushButton('event ▶')
        self.prev_btn.clicked.connect(lambda: self.step_event(-1)); self.next_btn.clicked.connect(lambda: self.step_event(1))
        bar.addWidget(self.prev_btn); bar.addWidget(self.next_btn)
        self.show_machine = QtWidgets.QCheckBox('Machine events'); self.show_machine.setChecked(True)
        self.show_app = QtWidgets.QCheckBox('App events'); self.show_app.setChecked(True)
        self.show_breaths = QtWidgets.QCheckBox('Breath marks'); self.show_breaths.setChecked(False)
        for cb in (self.show_machine, self.show_app, self.show_breaths):
            cb.toggled.connect(self.redraw_events); bar.addWidget(cb)
        self.panel_menu = QtWidgets.QToolButton(); self.panel_menu.setText('Panels ▾'); self.panel_menu.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        m = QtWidgets.QMenu(self.panel_menu); self.panel_actions = {}
        for key, title, _, _ in PANELS:
            a = m.addAction(title); a.setCheckable(True); a.setChecked(key in ('flow', 'press', 'leak', 'flowlim', 'vent', 'tv', 'apple_stage', 'apple_hr'))
            a.toggled.connect(self.update_visibility); self.panel_actions[key] = a
        self.panel_menu.setMenu(m); bar.addWidget(self.panel_menu)

        # overview strip (whole night) with region selector
        self.ov = pg.PlotWidget(axisItems={'bottom': TimeAxis(dt.datetime(2000, 1, 1), orientation='bottom')}); self.ov.setFixedHeight(70); style_plot(self.ov.getPlotItem()); self.ov.hideAxis('left')
        self.ov.setMouseEnabled(x=False, y=False); self.ov.hideButtons()
        self.region = pg.LinearRegionItem(brush=pg.mkBrush(42, 120, 214, 40), pen=pg.mkPen(C['blue'], width=1))
        self.region.sigRegionChanged.connect(self._region_moved); self.ov.addItem(self.region)
        lay.addWidget(self.ov)

        self.gl = pg.GraphicsLayoutWidget(); self.gl.setBackground('w'); lay.addWidget(self.gl, 1)
        self.gl.ci.layout.setSpacing(2)
        self.label = QtWidgets.QLabel(''); self.label.setStyleSheet('color:#52514e; font-size:11px'); lay.addWidget(self.label)
        self._building = False; self.event_list = []; self.event_idx = -1
        self._build_panels(dt.datetime(2000, 1, 1))

    # ------------------------------------------------------------------ building
    def _build_panels(self, t0):
        self.gl.clear(); self.plots = {}; self.curves = {}
        first = None
        for key, title, unit, yr in PANELS:
            p = self.gl.addPlot(axisItems={'bottom': TimeAxis(t0, orientation='bottom')}); self.gl.nextRow()
            style_plot(p); p.setLabel('left', unit); p.setTitle(title, size='9pt', color='#0b0b0b')
            p.titleLabel.item.setFont(QtGui.QFont('Segoe UI', 9, QtGui.QFont.DemiBold))
            p.setDownsampling(auto=True, mode='peak'); p.setClipToView(True); p.setMouseEnabled(y=False)
            if yr: p.setYRange(*yr, padding=0)
            if first is None: first = p
            else: p.setXLink(first)
            p.scene().sigMouseMoved.connect(self._mouse_moved)
            self.plots[key] = p
        first.sigXRangeChanged.connect(self._xrange_changed)
        self.update_visibility()

    def update_visibility(self):
        for key, p in self.plots.items():
            vis = self.panel_actions[key].isChecked()
            if key in ('spo2', 'pulse') and self.night is not None and not any(s.has_oximetry for s in self.night.sessions):
                vis = False
            if key.startswith('apple') and (self.night is None or not getattr(self.night, 'apple', None)):
                vis = False
            p.setVisible(vis)

    # ------------------------------------------------------------------ data
    def set_night(self, night):
        self.night = night
        if night is None: return
        self.t0 = night.sessions[0].start
        self._build_panels(self.t0)
        self.ov.setAxisItems({'bottom': TimeAxis(self.t0, orientation='bottom')}); style_plot(self.ov.getPlotItem())
        self.title.setText(f"{night.date.strftime('%A %B %d, %Y')}   {night.hours:.2f} h in {len(night.sessions)} session(s)")
        total_end = (night.sessions[-1].end - self.t0).total_seconds()
        pen = {k: pg.mkPen(c, width=1) for k, c in dict(flow=C['blue'], press=C['blue'], mask=C['aqua'], epr=C['grey'], leak=C['orange'],
                                                      flowlim=C['violet'], snore=C['magenta'], vent=C['aqua'], rr=C['blue'], tv=C['aqua'], mv=C['green'],
                                                      spo2=C['red'], pulse=C['orange']).items()}
        self.ov.clear(); self.ov.addItem(self.region)
        for s in night.sessions:
            off = (s.start - self.t0).total_seconds()
            if s.flow is not None:
                t = off + np.arange(len(s.flow)) / s.fs
                self.plots['flow'].plot(t, s.flow * 60, pen=pen['flow'])
            t2 = off + 2 * np.arange(len(s.ch.get('Press', [])))
            if 'Press' in s.ch:
                self.plots['press'].plot(t2, s.ch['Press'], pen=pen['press'])
                self.ov.plot(t2, s.ch['Press'], pen=pg.mkPen(C['blue'], width=1))
            if 'MaskPress' in s.ch: self.plots['press'].plot(t2, s.ch['MaskPress'], pen=pen['mask'])
            if 'EprPress' in s.ch: self.plots['press'].plot(t2, s.ch['EprPress'], pen=pen['epr'])
            if 'Leak' in s.ch:
                self.plots['leak'].plot(t2, s.ch['Leak'] * 60, pen=pen['leak'])
                self.plots['leak'].addLine(y=24, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine, width=1))
            if 'FlowLim' in s.ch: self.plots['flowlim'].plot(t2, s.ch['FlowLim'], pen=pen['flowlim'])
            if 'Snore' in s.ch: self.plots['flowlim'].plot(t2, s.ch['Snore'], pen=pen['snore'])
            vr = getattr(s, 'vent_ratio', None)
            if vr is not None:
                self.plots['vent'].plot(off + np.arange(len(vr)), vr, pen=pen['vent'])
                for y, c in ((0.7, C['orange']), (0.25, C['red'])):
                    self.plots['vent'].addLine(y=y, pen=pg.mkPen(c, style=QtCore.Qt.DashLine, width=1))
            if 'RespRate' in s.ch: self.plots['rr'].plot(t2, s.ch['RespRate'], pen=pen['rr'])
            if 'TidVol' in s.ch: self.plots['tv'].plot(t2, s.ch['TidVol'] * 1000, pen=pen['tv'])
            if 'MinVent' in s.ch: self.plots['mv'].plot(t2, s.ch['MinVent'], pen=pen['mv'])
            if s.has_oximetry:
                t1 = off + np.arange(len(s.spo2))
                sp = np.where(s.spo2 > 0, s.spo2, np.nan); pu = np.where(s.pulse > 0, s.pulse, np.nan)
                self.plots['spo2'].plot(t1, sp, pen=pen['spo2'], connect='finite')
                self.plots['spo2'].addLine(y=90, pen=pg.mkPen(C['red'], style=QtCore.Qt.DashLine, width=1))
                self.plots['pulse'].plot(t1, pu, pen=pen['pulse'], connect='finite')
        ap = getattr(night, 'apple', None)
        if ap:
            order = {'Awake': 4, 'REM': 3, 'Core': 2, 'Asleep': 2, 'Deep': 1, 'InBed': 0}
            cols = {'Awake': C['orange'], 'REM': C['violet'], 'Core': C['blue'], 'Asleep': C['blue'], 'Deep': C['aqua'], 'InBed': C['grey']}
            p = self.plots['apple_stage']
            for st, en, stage in ap['stages']:
                a = (st - self.t0).total_seconds(); b = (en - self.t0).total_seconds(); y = order.get(stage, 2)
                bar = pg.BarGraphItem(x0=[a], x1=[b], y0=[y - 0.4], y1=[y + 0.4], brush=pg.mkBrush(cols.get(stage, C['grey'])), pen=pg.mkPen(None)); p.addItem(bar)
            p.getAxis('left').setTicks([[(0, 'In bed'), (1, 'Deep'), (2, 'Core'), (3, 'REM'), (4, 'Awake')]])
            if ap['hr']:
                t = np.array([(x - self.t0).total_seconds() for x, _ in ap['hr']]); v = np.array([v for _, v in ap['hr']])
                self.plots['apple_hr'].plot(t, v, pen=pg.mkPen(C['red'], width=1), symbol='o', symbolSize=3, symbolBrush=C['red'], symbolPen=None)
            if ap['spo2']:
                t = np.array([(x - self.t0).total_seconds() for x, _ in ap['spo2']]); v = np.array([v for _, v in ap['spo2']])
                self.plots['apple_hr'].plot(t, v, pen=None, symbol='s', symbolSize=6, symbolBrush=C['blue'], symbolPen=None)
        self.update_visibility()
        self.ov.setXRange(0, total_end, padding=0)
        self.event_list = sorted([(s, e) for s in night.sessions for e in (s.machine_events + s.app_events)], key=lambda x: x[1].start)
        self.event_idx = -1
        self.redraw_events()
        self._building = True
        self.region.setRegion((0, total_end)); self.plots['flow'].setXRange(0, total_end, padding=0)
        self._building = False

    def redraw_events(self):
        for r in self.regions:
            for p in self.plots.values():
                try: p.removeItem(r)
                except Exception: pass
        self.regions = []
        if self.night is None: return
        for s in self.night.sessions:
            evs = []
            if self.show_machine.isChecked(): evs += [(e, 'machine') for e in s.machine_events]
            if self.show_app.isChecked(): evs += [(e, 'app') for e in s.app_events]
            for e, src in evs:
                a = (e.start - self.t0).total_seconds(); b = a + max(e.duration, 2.0)
                col = QtGui.QColor(EVENT_COLORS.get(e.label.split(' (')[0], C['grey']))
                col.setAlpha(70 if src == 'machine' else 45)
                targets = ['flow', 'vent'] if e.label in ('Hypopnea', 'Apnea (unflagged by machine)') or 'Apnea' in e.label else \
                          ['leak'] if e.label == 'Large Leak' else ['flowlim', 'flow'] if e.label == 'Flow Limitation Run' else \
                          ['vent'] if e.label == 'Periodic Breathing' else ['flow']
                for key in targets:
                    p = self.plots[key]
                    if src == 'machine':
                        r = pg.LinearRegionItem((a, b), movable=False, brush=pg.mkBrush(col), pen=pg.mkPen(col.darker(130), width=1))
                    else:   # app events drawn as a band along the top of the panel
                        r = pg.LinearRegionItem((a, b), movable=False, brush=pg.mkBrush(col), pen=pg.mkPen(None))
                        r.setZValue(-5)
                    r.setToolTip(f"{e.label} [{src}]\n{e.start.strftime('%H:%M:%S')}  {e.duration:.0f} s\n{e.detail}")
                    p.addItem(r); self.regions.append(r)
            if self.show_breaths.isChecked() and s.breaths:
                off = (s.start - self.t0).total_seconds()
                sc = pg.ScatterPlotItem(x=off + s.breaths['t0'], y=np.zeros(len(s.breaths['t0'])), size=4, brush=pg.mkBrush(C['grey']), pen=None)
                self.plots['flow'].addItem(sc); self.regions.append(sc)

    # ------------------------------------------------------------------ navigation
    def zoom_to(self, secs, center=None):
        if self.night is None: return
        total = (self.night.sessions[-1].end - self.t0).total_seconds()
        if secs is None:
            self.plots['flow'].setXRange(0, total, padding=0); return
        lo, hi = self.plots['flow'].viewRange()[0]
        c = center if center is not None else (lo + hi) / 2
        a = max(0, c - secs / 2); b = min(total, a + secs); a = max(0, b - secs)
        self.plots['flow'].setXRange(a, b, padding=0)

    def goto_event(self, e, window=120):
        c = (e.start - self.t0).total_seconds() + e.duration / 2
        self.zoom_to(max(window, e.duration + 60), center=c)
        for i, (_, ev) in enumerate(self.event_list):
            if ev is e: self.event_idx = i

    def step_event(self, d):
        if not self.event_list: return
        self.event_idx = (self.event_idx + d) % len(self.event_list)
        s, e = self.event_list[self.event_idx]; self.goto_event(e)
        self.label.setText(f"Event {self.event_idx + 1}/{len(self.event_list)}: {e.label} [{e.source}] {e.start.strftime('%H:%M:%S')} {e.duration:.0f} s  {e.detail}")

    def _xrange_changed(self, _, rng):
        if self._building: return
        self._building = True; self.region.setRegion(rng); self._building = False

    def _region_moved(self):
        if self._building: return
        self._building = True; self.plots['flow'].setXRange(*self.region.getRegion(), padding=0); self._building = False

    def _mouse_moved(self, pos):
        if self.night is None: return
        p = self.plots['flow']
        if not p.sceneBoundingRect().contains(pos) and not any(pp.sceneBoundingRect().contains(pos) for pp in self.plots.values()): return
        x = p.vb.mapSceneToView(pos).x()
        t = self.t0 + dt.timedelta(seconds=float(x))
        parts = [t.strftime('%H:%M:%S')]
        for s in self.night.sessions:
            off = (s.start - self.t0).total_seconds()
            if off <= x <= off + s.duration:
                i2 = int((x - off) / 2)
                def g(k, sc=1, f='{:.1f}'):
                    a = s.ch.get(k)
                    return f.format(a[min(i2, len(a) - 1)] * sc) if a is not None and len(a) else ''
                parts += [f"P {g('Press')} / mask {g('MaskPress')} cmH2O", f"leak {g('Leak', 60, '{:.0f}')} L/min", f"FL {g('FlowLim', 1, '{:.2f}')}",
                          f"RR {g('RespRate', 1, '{:.0f}')}", f"Vt {g('TidVol', 1000, '{:.0f}')} mL", f"MV {g('MinVent', 1, '{:.1f}')}"]
                if s.flow is not None:
                    i = int((x - off) * s.fs); parts.append(f"flow {s.flow[min(i, len(s.flow) - 1)] * 60:.1f} L/min")
                if s.has_oximetry:
                    i1 = min(int(x - off), len(s.spo2) - 1); parts.append(f"SpO2 {s.spo2[i1]:.0f}%  pulse {s.pulse[i1]:.0f}")
                break
        self.label.setText('    '.join(parts))
