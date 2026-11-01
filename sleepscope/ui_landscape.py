"""3D landscape of nights.

Each night is a strip of terrain running left to right through the night. Height is how freely you were breathing:
  openness = min(ventilation ratio, 1) x (1 - 0.7 x flow limitation)        1.0 = full easy breaths, 0 = airway closed
Nights are stacked front to back (oldest at the back). Colour follows height: green plateau, yellow dips, red craters.
Grey floor = no mask on. Blue water = large leak (over 24 L/min), the mask letting therapy escape.
Pillars mark machine-scored events: red obstructive apnea, violet central apnea, orange hypopnea.
Thin white line above each strip = set pressure.
"""
from __future__ import annotations
import datetime as dt
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from .theme import C

try:
    import pyqtgraph.opengl as gl
    HAVE_GL = True
except Exception:  # PyOpenGL missing
    HAVE_GL = False

BIN_S = 120          # 2 minute bins
T_START = 19.0       # clock hours, evening
T_END = 9.0 + 24     # next morning
NBIN = int((T_END - T_START) * 3600 / BIN_S)
NIGHT_GAP = 1.6      # spacing between strips (in bin units scaled below)
Z_SCALE = 6.0


def _hex(c, a=1.0):
    q = QtGui.QColor(c); return (q.redF(), q.greenF(), q.blueF(), a)


def terrain_colour(z):
    """z in [0,1] -> colour. Green at 1, yellow at 0.6, red at 0.2 and below."""
    g = np.array(_hex(C['aqua'])); y = np.array(_hex(C['yellow'])); r = np.array(_hex(C['red']))
    out = np.zeros(z.shape + (4,))
    hi = z >= 0.6; lo = ~hi
    t = np.clip((z[hi] - 0.6) / 0.4, 0, 1)[:, None]; out[hi] = y * (1 - t) + g * t
    t = np.clip((z[lo] - 0.2) / 0.4, 0, 1)[:, None]; out[lo] = r * (1 - t) + y * t
    return out


def night_grids(night):
    """Return (openness[NBIN], leak[NBIN], press[NBIN], mask_on[NBIN]) for one night, NaN where no data."""
    op = np.full(NBIN, np.nan); lk = np.full(NBIN, np.nan); pr = np.full(NBIN, np.nan)
    base = dt.datetime.combine(night.date, dt.time(0)) + dt.timedelta(hours=T_START)
    for s in night.sessions:
        vr = getattr(s, 'vent_ratio', None); fl = s.ch.get('FlowLim'); leak = s.ch.get('Leak'); press = s.ch.get('Press')
        n2 = len(fl) if fl is not None else 0
        for i2 in range(0, n2, BIN_S // 2):
            t = s.start + dt.timedelta(seconds=2 * i2)
            b = int((t - base).total_seconds() // BIN_S)
            if not 0 <= b < NBIN: continue
            j = min(i2 + BIN_S // 2, n2)
            f = float(np.nanmean(fl[i2:j])) if fl is not None else 0.0
            if vr is not None:
                a1 = 2 * i2; a2 = min(2 * j, len(vr)); v = float(np.nanmean(np.minimum(vr[a1:a2], 1.0))) if a2 > a1 else 1.0
            else:
                v = 1.0
            op[b] = v * (1 - 0.7 * f)
            if leak is not None: lk[b] = float(np.nanmean(leak[i2:j])) * 60
            if press is not None: pr[b] = float(np.nanmean(press[i2:j]))
    return op, lk, pr


class LandscapeView(QtWidgets.QWidget):
    def __init__(self):
        super().__init__(); self.nights = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 4)
        bar = QtWidgets.QHBoxLayout(); lay.addLayout(bar)
        self.caption = QtWidgets.QLabel(''); self.caption.setStyleSheet('font-weight:600'); bar.addWidget(self.caption); bar.addStretch()
        self.str_data = None
        self.highlight = QtWidgets.QLabel(''); self.highlight.setWordWrap(True); self.highlight.setTextFormat(QtCore.Qt.RichText)
        self.highlight.setStyleSheet('background:#fff4d6; border:1px solid #eda100; border-left:6px solid #eda100; border-radius:8px; padding:8px 12px; font-size:13px; color:#0b0b0b')
        lay.addWidget(self.highlight)
        for lab, fn in (('Overview', self.view_overview), ('Fly along', self.view_along), ('Top down', self.view_top), ('Side', self.view_side)):
            b = QtWidgets.QPushButton(lab); b.clicked.connect(fn); bar.addWidget(b)
        self.mode = QtWidgets.QComboBox(); self.mode.addItems(['Synopsis range', 'Selected night', 'Last 30 nights']); self.mode.setToolTip('Which nights to draw')
        self.mode.currentIndexChanged.connect(lambda _: self.rebuild()); bar.addWidget(self.mode)
        self.range = None; self.selected = None
        if not HAVE_GL:
            lay.addWidget(QtWidgets.QLabel('3D view needs the PyOpenGL package. Close the app and run SleepScope.bat again (it installs missing packages), or run install.bat.'))
            return
        self.gl = gl.GLViewWidget(); self.gl.setBackgroundColor('#fcfcfb')
        mid = QtWidgets.QHBoxLayout(); mid.setSpacing(6); lay.addLayout(mid, 1); mid.addWidget(self.gl, 1); mid.addWidget(LandscapeKey(), 0, QtCore.Qt.AlignTop)
        self.gl.setToolTip('Click any pillar, pool or patch of terrain for a plain language explanation. Drag to rotate, wheel to zoom.')
        self.gl.installEventFilter(self); self._press_pos = None
        self.popup = QtWidgets.QLabel(self.gl); self.popup.setWordWrap(True); self.popup.setTextFormat(QtCore.Qt.RichText); self.popup.setVisible(False)
        self.popup.setStyleSheet('background:#ffffff; border:1px solid #2a78d6; border-left:6px solid #2a78d6; border-radius:8px; padding:10px 12px; font-size:12.5px; color:#0b0b0b'); self.popup.setFixedWidth(360)
        self.popup.mousePressEvent = lambda ev: self.popup.setVisible(False)
        self.items = []

    def set_nights(self, nights):
        self.nights = nights; self.rebuild()
    def set_range(self, a, b):
        self.range = (a, b)
        if self.mode.currentIndex() == 1: self.mode.blockSignals(True); self.mode.setCurrentIndex(0); self.mode.blockSignals(False)
        if self.nights: self.rebuild()
    def set_selected(self, night):
        self.selected = night
        if night is not None: self.mode.blockSignals(True); self.mode.setCurrentIndex(1); self.mode.blockSignals(False)
        if self.nights: self.rebuild()

    def rebuild(self):
        if not HAVE_GL or not self.nights: return
        for it in self.items:
            try: self.gl.removeItem(it)
            except Exception: pass
        self.items = []; self.pick_pts = []   # (x, y, z, kind, ctx)
        m = self.mode.currentIndex()
        if m == 1 and self.selected is not None: nights = [self.selected]
        elif m == 0 and self.range: nights = [n for n in self.nights if self.range[0] <= n.date <= self.range[1]] or self.nights[-14:]
        else: nights = self.nights[-30:]
        nights = nights[::-1]      # newest first = front (y = 0)
        N = len(nights); W = NBIN
        xs = np.arange(W, dtype=float) * 0.25                   # 2 min bin = 0.25 units  (12 h = 105 units)
        ys = np.arange(N, dtype=float) * 7.0                    # strip spacing
        strip_w = 5.0
        # per night: terrain as a narrow surface (3 rows: front edge, centre, back edge) so strips read as ribbons with gaps
        for k, nt in enumerate(nights):
            op, lk, pr = night_grids(nt); y0 = ys[k]
            base_dt = dt.datetime.combine(nt.date, dt.time(0)) + dt.timedelta(hours=T_START)
            for i in range(0, W, 2):
                tm = (base_dt + dt.timedelta(seconds=i * BIN_S)).strftime('%H:%M')
                if np.isnan(op[i]): self.pick_pts.append((xs[i], y0, -0.15 * Z_SCALE, 'floor', dict(night=nt.label, time=tm)))
                else:
                    opi = float(np.clip(op[i], 0, 1)); lki = float(lk[i]) if not np.isnan(lk[i]) else 0.0; pri = float(pr[i]) if not np.isnan(pr[i]) else None
                    self.pick_pts.append((xs[i], y0, opi * Z_SCALE, 'terrain', dict(night=nt.label, time=tm, openness=opi, fl=round(max(0.0, 1 - opi), 2), leak=lki, press=pri)))
                    if lki > 24: self.pick_pts.append((xs[i], y0, 0.55 * Z_SCALE, 'water', dict(night=nt.label, time=tm, leak=lki)))
                    if pri is not None: self.pick_pts.append((xs[i], y0, Z_SCALE * (1.15 + (pri - 4) / 12), 'pressure', dict(night=nt.label, time=tm, press=pri)))
            z = np.where(np.isnan(op), -0.15, np.clip(op, 0, 1)) * Z_SCALE
            col = terrain_colour(np.where(np.isnan(op), 0.0, np.clip(op, 0, 1)))
            col[np.isnan(op)] = _hex('#c9c8c3')                 # floor grey for mask off
            # smooth the height a touch so it reads as terrain, not bars
            zz = np.convolve(z, np.ones(5) / 5, 'same'); zz[:2] = z[:2]; zz[-2:] = z[-2:]
            Z = np.vstack([zz, zz, zz]).T                         # (W, 3)
            Cc = np.stack([col, col, col], axis=1)                # (W, 3, 4)
            yy = np.array([ys[k] - strip_w / 2, ys[k], ys[k] + strip_w / 2])
            surf = gl.GLSurfacePlotItem(x=xs, y=yy, z=Z, colors=Cc, shader='shaded', smooth=True, glOptions='opaque')
            self.gl.addItem(surf); self.items.append(surf)
            # water pools only over the bins in large leak (separate small surfaces so nothing shows elsewhere)
            wet = np.where(np.nan_to_num(lk, nan=0) > 24)[0]
            if len(wet):
                runs = np.split(wet, np.where(np.diff(wet) > 1)[0] + 1)
                for r in runs:
                    a, b = max(r[0] - 1, 0), min(r[-1] + 2, W)
                    if b - a < 2: continue
                    zw = np.full(b - a, 0.55 * Z_SCALE); Zw = np.vstack([zw, zw, zw]).T
                    Cw = np.zeros((b - a, 3, 4)); Cw[:] = _hex(C['blue'], 0.6)
                    water = gl.GLSurfacePlotItem(x=xs[a:b], y=yy, z=Zw, colors=Cw, shader='shaded', smooth=True, glOptions='translucent')
                    self.gl.addItem(water); self.items.append(water)
            # pressure line, scaled: 4 cmH2O -> 1.1*Z, 16 -> 2.2*Z above
            ok = ~np.isnan(pr)
            if ok.any():
                zp = Z_SCALE * (1.15 + (np.where(ok, pr, 4) - 4) / 12 * 1.0)
                pts = np.column_stack([xs[ok], np.full(ok.sum(), ys[k]), zp[ok]])
                line = gl.GLLinePlotItem(pos=pts, color=(1, 1, 1, 0.95), width=2, antialias=True, mode='line_strip', glOptions='opaque')
                self.gl.addItem(line); self.items.append(line)
                # thin grey post at start and end of each session so the pressure line visibly floats above the strip
            # event pillars
            base = dt.datetime.combine(nt.date, dt.time(0)) + dt.timedelta(hours=T_START)
            for s in nt.sessions:
                for e in s.machine_events:
                    colr = {'Obstructive Apnea': C['red'], 'Central Apnea': C['violet'], 'Hypopnea': C['orange']}.get(e.label)
                    if not colr: continue
                    b = (e.start - base).total_seconds() / BIN_S
                    if not 0 <= b < W: continue
                    x = b * 0.25; z0 = zz[int(b)]
                    h = Z_SCALE * (0.9 if 'Apnea' in e.label else 0.6)
                    seg = np.array([[x, ys[k], max(z0, 0)], [x, ys[k], max(z0, 0) + h]])
                    bi = int(b); self.pick_pts.append((x, ys[k], max(z0, 0) + h, 'event', dict(night=nt.label, time=e.start.strftime('%H:%M'), label=e.label, dur=e.duration, press=float(pr[bi]) if not np.isnan(pr[bi]) else None, leak=float(lk[bi]) if not np.isnan(lk[bi]) else None, at_ceiling=(not np.isnan(pr[bi]) and nt.stats.get('mode') == 'AutoSet' and pr[bi] >= nt.stats.get('press_max', 99) - 0.1))))
                    self.pick_pts.append((x, ys[k], max(z0, 0) + h / 2, 'event', self.pick_pts[-1][4]))
                    pil = gl.GLLinePlotItem(pos=seg, color=_hex(colr), width=4, antialias=True, mode='lines', glOptions='opaque')
                    self.gl.addItem(pil); self.items.append(pil)
                    cap = gl.GLScatterPlotItem(pos=seg[1:2], color=_hex(colr), size=9, pxMode=True, glOptions='opaque')
                    self.gl.addItem(cap); self.items.append(cap)
            # Apple Watch: sleep stage ribbon behind the strip, heart rate line, SpO2 dips
            ap = getattr(nt, 'apple', None)
            if ap:
                stage_col = {'Deep': _hex('#0f6e4f'), 'Core': _hex(C['blue']), 'Asleep': _hex(C['blue']), 'REM': _hex(C['violet']), 'Awake': _hex(C['orange']), 'InBed': _hex('#d9d8d3')}
                stage_of = np.full(W, '', dtype=object)
                for st, en, stage in sorted(ap['stages'], key=lambda r: {'InBed': 0}.get(r[2], 1)):   # InBed first so stages overwrite it
                    b0 = int((st - base).total_seconds() // BIN_S); b1 = int(np.ceil((en - base).total_seconds() / BIN_S))
                    for bb in range(max(b0, 0), min(b1, W)): stage_of[bb] = stage
                has = stage_of != ''
                if has.any():
                    zr = np.where(has, 0.25 * Z_SCALE, -0.15 * Z_SCALE); Zr = np.vstack([zr, zr, zr]).T
                    Cr = np.zeros((W, 3, 4))
                    for bb in range(W): Cr[bb, :] = stage_col.get(stage_of[bb], _hex('#c9c8c3')) if has[bb] else _hex('#c9c8c3', 0.0)
                    yr = np.array([ys[k] - strip_w / 2 - 1.9, ys[k] - strip_w / 2 - 1.1, ys[k] - strip_w / 2 - 0.3])
                    for i in range(0, W, 2):
                        if has[i]: self.pick_pts.append((xs[i], y0 - strip_w / 2 - 1.1, 0.25 * Z_SCALE, 'stage', dict(night=nt.label, time=(base_dt + dt.timedelta(seconds=i * BIN_S)).strftime('%H:%M'), stage=str(stage_of[i]))))
                    rib = gl.GLSurfacePlotItem(x=xs, y=yr, z=Zr, colors=Cr, shader='shaded', smooth=True, glOptions='translucent')
                    self.gl.addItem(rib); self.items.append(rib)
                if ap.get('hr'):
                    th = np.array([(t - base).total_seconds() / BIN_S * 0.25 for t, _ in ap['hr']]); vh = np.array([v for _, v in ap['hr']])
                    ok = (th >= 0) & (th <= xs[-1])
                    if ok.sum() > 2:
                        zh = Z_SCALE * (1.6 + (vh[ok] - 40) / 80)       # 40 bpm at 1.6 Z, 120 bpm at 2.6 Z
                        vsm = np.convolve(vh[ok], np.ones(5) / 5, 'same'); zh = Z_SCALE * (1.6 + (vsm - 40) / 80)
                        pts = np.column_stack([th[ok], np.full(ok.sum(), ys[k] - strip_w / 2 - 1.1), zh])
                        hrl = gl.GLLinePlotItem(pos=pts, color=_hex(C['red'], 0.9), width=1.5, antialias=True, mode='line_strip', glOptions='opaque')
                        self.gl.addItem(hrl); self.items.append(hrl)
                if ap.get('spo2'):
                    ts_ = np.array([(t - base).total_seconds() / BIN_S * 0.25 for t, _ in ap['spo2']]); vs = np.array([v for _, v in ap['spo2']])
                    ok = (ts_ >= 0) & (ts_ <= xs[-1])
                    if ok.any():
                        low = vs[ok] < 90
                        pts = np.column_stack([ts_[ok], np.full(ok.sum(), ys[k] - strip_w / 2 - 1.1), np.full(ok.sum(), 0.3 * Z_SCALE)])
                        cols = np.array([_hex(C['red']) if l else _hex('#ffffff', 0.9) for l in low])
                        sp = gl.GLScatterPlotItem(pos=pts, color=cols, size=6 + 4 * low.astype(float).max() if False else 6, pxMode=True, glOptions='translucent')
                        self.gl.addItem(sp); self.items.append(sp)
            # night label at the left end of the strip
            if N <= 14 or k % max(1, int(np.ceil(N / 14))) == 0:
                lab = gl.GLTextItem(pos=(-14, ys[k], 0.5), text=nt.label if N <= 10 else nt.label.split(' ')[-1], color=QtGui.QColor(C['text']), font=QtGui.QFont('Segoe UI', 9))
                self.gl.addItem(lab); self.items.append(lab)
        # clock labels along the front
        for hh in range(int(T_START), int(T_END) + 1, 2):
            x = (hh - T_START) * 3600 / BIN_S * 0.25
            t = gl.GLTextItem(pos=(x, -6, 0), text=f'{hh % 24:02d}:00', color=QtGui.QColor(C['text2']), font=QtGui.QFont('Segoe UI', 8))
            self.gl.addItem(t); self.items.append(t)
        # floor grid
        grid = gl.GLGridItem(); grid.setSize(xs[-1] + 10, ys[-1] + 14, 1); grid.setSpacing(7.5, 7, 1); grid.translate(xs[-1] / 2, ys[-1] / 2, -0.2)
        grid.setColor((200, 200, 195, 90)); self.gl.addItem(grid); self.items.append(grid)
        self.center = QtGui.QVector3D(xs[-1] / 2, ys[-1] / 2, 0)
        self.extent = max(xs[-1], ys[-1] + 10)
        self.caption.setText((f'{nights[0].date.strftime("%A %B %d")}' if N == 1 else f'{N} nights, {nights[-1].label} to {nights[0].label}') + '. Evening on the left, morning on the right, newest strip at the front.')
        from . import scoring as _sc
        self.highlight.setText('<b>SETTINGS</b> &nbsp; ' + _sc.settings_text(_sc.settings_summary(nights, self.str_data)))
        self.view_overview()

    # ------------------------------------------------------------------ picking
    def eventFilter(self, obj, ev):
        if obj is getattr(self, 'gl', None):
            if ev.type() == QtCore.QEvent.MouseButtonPress: self._press_pos = ev.position() if hasattr(ev, 'position') else ev.pos()
            elif ev.type() == QtCore.QEvent.MouseButtonRelease and self._press_pos is not None:
                p = ev.position() if hasattr(ev, 'position') else ev.pos()
                if (p - self._press_pos).manhattanLength() < 4: self._pick(p)
                self._press_pos = None
        return super().eventFilter(obj, ev)
    def _pick(self, pos):
        if not getattr(self, 'pick_pts', None): return
        from . import explain as _ex
        w, h = self.gl.width(), self.gl.height(); dpr = self.gl.devicePixelRatioF()
        vp = self.gl.getViewport(); mvp = self.gl.projectionMatrix(vp, vp) * self.gl.viewMatrix()
        pts = np.array([[x, y, z] for x, y, z, _, _ in self.pick_pts], dtype=float)
        best = None; bestd = 1e9
        for i, (x, y, z) in enumerate(pts):
            v = mvp.map(QtGui.QVector4D(x, y, z, 1.0))
            if v.w() <= 0: continue
            sx = (v.x() / v.w() * 0.5 + 0.5) * w; sy = (1 - (v.y() / v.w() * 0.5 + 0.5)) * h
            d = (sx - pos.x()) ** 2 + (sy - pos.y()) ** 2
            kind = self.pick_pts[i][3]; d *= {'event': 0.5, 'water': 0.8, 'pressure': 1.2, 'stage': 1.0, 'terrain': 1.0, 'floor': 1.0}[kind]   # favour pillars when close
            if d < bestd: bestd = d; best = i
        if best is None or bestd > 30 ** 2: self.popup.setVisible(False); return
        x, y, z, kind, ctx = self.pick_pts[best]
        self.popup.setText(_ex.point(kind, **ctx) + "<br><span style='color:#8a8985;font-size:11px'>click to close</span>")
        self.popup.adjustSize(); px = int(min(max(8, pos.x() + 14), w - self.popup.width() - 8)); py = int(min(max(8, pos.y() - self.popup.height() - 10), h - self.popup.height() - 8))
        self.popup.move(px, py); self.popup.setVisible(True); self.popup.raise_()
    def view_overview(self):
        if HAVE_GL: self.gl.setCameraPosition(pos=self.center, distance=self.extent * 1.25, elevation=32, azimuth=-110)
    def view_along(self):
        if HAVE_GL: self.gl.setCameraPosition(pos=self.center, distance=self.extent * 0.9, elevation=14, azimuth=-170)
    def view_top(self):
        if HAVE_GL: self.gl.setCameraPosition(pos=self.center, distance=self.extent * 1.3, elevation=89, azimuth=-90)
    def view_side(self):
        if HAVE_GL: self.gl.setCameraPosition(pos=self.center, distance=self.extent * 1.1, elevation=8, azimuth=-90)


class LandscapeKey(QtWidgets.QWidget):
    """Illustrated key drawn beside the 3D view: a cartoon night strip with every element labelled."""
    def __init__(self):
        super().__init__(); self.setFixedWidth(300); self.setMinimumHeight(620)
    def paintEvent(self, ev):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor('#fcfcfb'))
        font = QtGui.QFont('Segoe UI', 9); bold = QtGui.QFont('Segoe UI', 10, QtGui.QFont.DemiBold); p.setFont(bold); p.setPen(QtGui.QColor(C['text']))
        p.drawText(12, 22, 'How to read one night')
        # cartoon strip
        x0, x1, base = 16, 284, 150
        prof = [(0, 0.0), (0.22, 0.0), (0.22, 0.85), (0.34, 0.9), (0.40, 0.55), (0.46, 0.9), (0.52, 0.88), (0.56, 0.1), (0.60, 0.9), (0.72, 0.85), (0.78, 0.6), (0.84, 0.9), (0.86, 0.0), (1.0, 0.0)]
        H = 70
        def X(t): return x0 + t * (x1 - x0)
        def Z(h): return base - h * H
        # floor
        p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor('#c9c8c3')); p.drawRect(QtCore.QRectF(x0, base - 6, x1 - x0, 10))
        # terrain polygon with gradient fill by height: draw as vertical slices
        pts = [(X(t), h) for t, h in prof]
        for i in range(len(pts) - 1):
            (xa, ha), (xb, hb) = pts[i], pts[i + 1]
            n = max(1, int(xb - xa))
            for k in range(n):
                t0_, t1_ = k / n, (k + 1) / n
                h0, h1 = ha + (hb - ha) * t0_, ha + (hb - ha) * t1_
                hm = (h0 + h1) / 2
                if hm <= 0.02: continue
                col = terrain_colour(np.array([hm]))[0]
                p.setBrush(QtGui.QColor.fromRgbF(*col[:3])); p.setPen(QtCore.Qt.NoPen)
                poly = QtGui.QPolygonF([QtCore.QPointF(xa + (xb - xa) * t0_, base), QtCore.QPointF(xa + (xb - xa) * t0_, Z(h0)), QtCore.QPointF(xa + (xb - xa) * t1_, Z(h1)), QtCore.QPointF(xa + (xb - xa) * t1_, base)])
                p.drawPolygon(poly)
        # water pool over the yellow dip
        p.setBrush(QtGui.QColor(42, 120, 214, 150)); p.drawRect(QtCore.QRectF(X(0.74), Z(0.62), X(0.82) - X(0.74), 8))
        # pillars
        for t, c in ((0.40, C['orange']), (0.56, C['red']), (0.64, C['violet'])):
            p.setPen(QtGui.QPen(QtGui.QColor(c), 3)); p.drawLine(QtCore.QPointF(X(t), Z(0.9)), QtCore.QPointF(X(t), Z(1.35)))
            p.setBrush(QtGui.QColor(c)); p.setPen(QtCore.Qt.NoPen); p.drawEllipse(QtCore.QPointF(X(t), Z(1.35)), 4, 4)
        # pressure line
        p.setPen(QtGui.QPen(QtGui.QColor('#ffffff'), 2)); p.drawLine(QtCore.QPointF(X(0.22), Z(1.1)), QtCore.QPointF(X(0.86), Z(1.1)))
        p.setPen(QtGui.QPen(QtGui.QColor('#9a9994'), 1)); p.drawLine(QtCore.QPointF(X(0.22), Z(1.1)), QtCore.QPointF(X(0.86), Z(1.1)))
        # stage ribbon in front
        rib_y = base + 14
        for a, b, c in ((0.12, 0.3, C['blue']), (0.3, 0.42, '#0f6e4f'), (0.42, 0.6, C['blue']), (0.6, 0.72, C['violet']), (0.72, 0.76, C['orange']), (0.76, 0.92, C['blue'])):
            p.setBrush(QtGui.QColor(c)); p.setPen(QtCore.Qt.NoPen); p.drawRect(QtCore.QRectF(X(a), rib_y, X(b) - X(a), 8))
        p.setBrush(QtGui.QColor('#d9d8d3')); p.drawRect(QtCore.QRectF(X(0.06), rib_y, X(0.12) - X(0.06), 8)); p.drawRect(QtCore.QRectF(X(0.92), rib_y, X(0.97) - X(0.92), 8))
        # HR line
        p.setPen(QtGui.QPen(QtGui.QColor(C['red']), 1.5)); path = QtGui.QPainterPath(QtCore.QPointF(X(0.12), rib_y - 3))
        for i in range(1, 30): path.lineTo(QtCore.QPointF(X(0.12 + 0.8 * i / 29), rib_y - 3 - 2 * ((i % 3) - 1))); p.drawPath(path)
        # spo2 dots
        for t in (0.2, 0.35, 0.5, 0.65, 0.8):
            p.setBrush(QtGui.QColor(C['red']) if t == 0.65 else QtGui.QColor('#ffffff')); p.setPen(QtGui.QPen(QtGui.QColor('#8a8985'), 0.8)); p.drawEllipse(QtCore.QPointF(X(t), rib_y + 4), 3, 3)
        p.setFont(font); p.setPen(QtGui.QColor(C['text2']))
        p.drawText(x0, base + 36, 'evening'); p.drawText(x1 - 44, base + 36, 'morning')
        # legend rows
        rows = [
            (('swatch', C['aqua']), 'High green: breathing freely'),
            (('swatch', C['yellow']), 'Yellow dip: airway narrowing'),
            (('swatch', C['red']), 'Red crater: airflow stopped'),
            (('swatch', '#c9c8c3'), 'Grey floor: mask off'),
            (('swatch', 'rgba'), 'Blue pool: mask leaking (>24 L/min)'),
            (('pillar', C['red']), 'Red pillar: obstructive apnea'),
            (('pillar', C['violet']), 'Violet pillar: central apnea'),
            (('pillar', C['orange']), 'Orange pillar: hypopnea'),
            (('line', '#9a9994'), 'White line: pressure delivered'),
            (('ribbon', None), 'Ribbon: Watch sleep stages'),
            (('swatch', '#0f6e4f'), '   deep'), (('swatch', C['blue']), '   core'), (('swatch', C['violet']), '   REM'), (('swatch', C['orange']), '   awake'), (('swatch', '#d9d8d3'), '   in bed, not asleep'),
            (('line', C['red']), 'Red line: Watch heart rate'),
            (('dot', None), 'Dots: Watch SpO2 (red = under 90%)'),
        ]
        y = base + 58
        for (kind, c), label in rows:
            if kind == 'swatch':
                p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(42, 120, 214, 150) if c == 'rgba' else QtGui.QColor(c)); p.drawRect(QtCore.QRectF(16, y - 9, 14, 11))
            elif kind == 'pillar':
                p.setPen(QtGui.QPen(QtGui.QColor(c), 3)); p.drawLine(QtCore.QPointF(23, y + 2), QtCore.QPointF(23, y - 9)); p.setBrush(QtGui.QColor(c)); p.setPen(QtCore.Qt.NoPen); p.drawEllipse(QtCore.QPointF(23, y - 9), 3, 3)
            elif kind == 'line':
                p.setPen(QtGui.QPen(QtGui.QColor(c), 2)); p.drawLine(QtCore.QPointF(16, y - 3), QtCore.QPointF(30, y - 3))
            elif kind == 'ribbon':
                for i, cc in enumerate((C['blue'], '#0f6e4f', C['violet'], C['orange'])):
                    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(cc)); p.drawRect(QtCore.QRectF(16 + i * 3.5, y - 8, 3.5, 8))
            elif kind == 'dot':
                p.setBrush(QtGui.QColor('#ffffff')); p.setPen(QtGui.QPen(QtGui.QColor('#8a8985'), 0.8)); p.drawEllipse(QtCore.QPointF(19, y - 3), 3, 3)
                p.setBrush(QtGui.QColor(C['red'])); p.drawEllipse(QtCore.QPointF(27, y - 3), 3, 3)
            p.setPen(QtGui.QColor(C['text'])); p.drawText(38, y, label); y += 19
        p.setPen(QtGui.QColor(C['text2'])); p.setFont(QtGui.QFont('Segoe UI', 8))
        p.drawText(QtCore.QRectF(12, y + 2, 276, 60), QtCore.Qt.TextWordWrap, 'A good night is a long flat green strip, no pillars, no water, ribbon fully covered by the strip. Drag to rotate, wheel to zoom.')
        p.end()
