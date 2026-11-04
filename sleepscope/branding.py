"""SleepScope logo and page chrome, drawn in code so it scales and matches the app palette."""
from __future__ import annotations
import math
from PySide6 import QtCore, QtWidgets, QtGui

BLUE_DARK, BLUE = '#1d4f91', '#2a78d6'
PAGE_BG = '#f6f5f2'


def paint_logo(p: QtGui.QPainter, rect: QtCore.QRectF, on_dark=False):
    """Rounded square with a night-blue gradient, a crescent moon and a breathing wave."""
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    r = rect; s = r.width()
    grad = QtGui.QLinearGradient(r.topLeft(), r.bottomRight()); grad.setColorAt(0, QtGui.QColor('#153b6e')); grad.setColorAt(1, QtGui.QColor(BLUE))
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 90 if on_dark else 0), max(1, s * 0.03))); p.setBrush(grad)
    p.drawRoundedRect(r, s * 0.22, s * 0.22)
    # the V with two wings: 1.5 cycles of a sine, amplitude shaped by |sin| so the centre dip is deep and the wings taper
    path = QtGui.QPainterPath()
    n = 80; x0, x1 = r.left() + s * 0.07, r.right() - s * 0.07; ym = r.top() + s * 0.50; amp = s * 0.27
    for i in range(n + 1):
        t = i / n; x = x0 + (x1 - x0) * t
        y = ym - amp * math.sin(t * math.pi * 3) * (0.3 + 0.7 * abs(math.sin(t * math.pi)))
        if i == 0: path.moveTo(x, y)
        else: path.lineTo(x, y)
    p.setPen(QtGui.QPen(QtGui.QColor('white'), max(1.5, s * 0.055), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)); p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(path)


def logo_pixmap(size=64, on_dark=False):
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); paint_logo(p, QtCore.QRectF(1, 1, size - 2, size - 2), on_dark); p.end(); return pm


def app_icon():
    ic = QtGui.QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256): ic.addPixmap(logo_pixmap(s))
    return ic


def version_text():
    from . import version as _v
    import datetime as _dt
    v = _v.VERSION; d = _v.BUILD_DATE
    if v == 'source':
        return 'Running from source', _dt.date.today().strftime('%B %d, %Y')
    try: d = _dt.date.fromisoformat(d).strftime('%B %d, %Y')
    except Exception: pass
    return f'Version {v}', d


def show_about(parent=None):
    """About box: version, date issued, copyright. Opened from any logo."""
    ver, issued = version_text()
    dlg = QtWidgets.QDialog(parent); dlg.setWindowTitle('About SleepScope'); dlg.setFixedWidth(440)
    dlg.setStyleSheet('QDialog { background: white; } QLabel { color: #0b0b0b; }')
    lay = QtWidgets.QVBoxLayout(dlg); lay.setContentsMargins(24, 22, 24, 18); lay.setSpacing(6)
    top = QtWidgets.QHBoxLayout(); top.setSpacing(14)
    mark = QtWidgets.QLabel(); mark.setPixmap(logo_pixmap(56, on_dark=False)); top.addWidget(mark, 0, QtCore.Qt.AlignTop)
    col = QtWidgets.QVBoxLayout(); col.setSpacing(2)
    t = QtWidgets.QLabel('SleepScope'); t.setStyleSheet('font-size: 22px; font-weight: 800'); col.addWidget(t)
    col.addWidget(QtWidgets.QLabel('CPAP data, read in plain language.'))
    top.addLayout(col, 1); lay.addLayout(top)
    lay.addSpacing(8)
    for k, v in ((ver, ''), ('Issued', issued), ('Copyright', f'\u00a9 {_year()} Robert Barmore. All rights reserved.'), ('License', 'MIT License; source and releases at github.com/robertb-design/SleepScope')):
        row = QtWidgets.QLabel(f'<b>{k}</b>' + (f'&nbsp;&nbsp;{v}' if v else '')); row.setWordWrap(True); row.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse); lay.addWidget(row)
    note = QtWidgets.QLabel('SleepScope is a reading of the data, not a medical device. Decisions about therapy belong with you and your prescriber.')
    note.setWordWrap(True); note.setStyleSheet('color:#52514e; font-size: 11px; margin-top: 8px'); lay.addWidget(note)
    btn = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok); btn.accepted.connect(dlg.accept); lay.addWidget(btn)
    dlg.exec()


def _year():
    import datetime as _dt
    return max(2026, _dt.date.today().year)


class LogoWidget(QtWidgets.QWidget):
    """Logo mark plus wordmark, for the toolbar (dark background). Click opens About."""
    def __init__(self, size=30, wordmark=True):
        super().__init__(); self.size_ = size; self.wordmark = wordmark
        self.setFixedSize(size + (118 if wordmark else 0) + 8, size + 4)
        self.setCursor(QtCore.Qt.PointingHandCursor); self.setToolTip('About SleepScope')
    def mousePressEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton: show_about(self.window())
    def paintEvent(self, ev):
        p = QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing)
        paint_logo(p, QtCore.QRectF(2, 2, self.size_, self.size_), on_dark=True)
        if self.wordmark:
            p.setPen(QtGui.QColor('white')); f = QtGui.QFont('Segoe UI', 13, QtGui.QFont.Bold); p.setFont(f)
            p.drawText(QtCore.QRectF(self.size_ + 10, 0, 120, self.height()), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, 'SleepScope')
        p.end()


class PageBanner(QtWidgets.QFrame):
    def __init__(self, title, subtitle, colour):
        super().__init__(); self.setFixedHeight(58)
        c2 = QtGui.QColor(colour).darker(135).name()
        self.setStyleSheet(f'QFrame {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c2}, stop:1 {colour}); border-radius: 10px; }} QLabel {{ color: white; background: transparent; }}')
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(14, 6, 14, 6); lay.setSpacing(12)
        mark = QtWidgets.QLabel(); mark.setPixmap(logo_pixmap(34, on_dark=True)); mark.setCursor(QtCore.Qt.PointingHandCursor); mark.setToolTip('About SleepScope')
        mark.mousePressEvent = lambda ev, w=self: show_about(w.window()); lay.addWidget(mark)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(0); lay.addLayout(col, 1)
        t = QtWidgets.QLabel(title); t.setStyleSheet('font-size:17px; font-weight:800'); col.addWidget(t)
        s = QtWidgets.QLabel(subtitle); s.setStyleSheet('font-size:11px; color:#e8eefb'); s.setWordWrap(True); col.addWidget(s)
        self.right = QtWidgets.QLabel(''); self.right.setStyleSheet('font-size:11px; color:#e8eefb'); self.right.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter); lay.addWidget(self.right)


class Page(QtWidgets.QWidget):
    """Banner on top, content in a white rounded card below, page-coloured background: the Start page look."""
    def __init__(self, inner: QtWidgets.QWidget, title, subtitle, colour):
        super().__init__(); self.inner = inner
        self.setStyleSheet(f'Page {{ background: {PAGE_BG}; }}'); self.setAutoFillBackground(True)
        pal = self.palette(); pal.setColor(QtGui.QPalette.Window, QtGui.QColor(PAGE_BG)); self.setPalette(pal)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(12, 10, 12, 12); lay.setSpacing(10)
        self.banner = PageBanner(title, subtitle, colour); lay.addWidget(self.banner)
        card = QtWidgets.QFrame(); card.setObjectName('pagecard'); card.setStyleSheet('QFrame#pagecard { background: white; border: 1px solid #e6e5e2; border-radius: 10px; }')
        cl = QtWidgets.QVBoxLayout(card); cl.setContentsMargins(6, 6, 6, 6); cl.addWidget(inner); lay.addWidget(card, 1)
