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
    # moon
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor('#ffd166'))
    cx, cy, rr = r.left() + s * 0.70, r.top() + s * 0.30, s * 0.13
    p.drawEllipse(QtCore.QPointF(cx, cy), rr, rr)
    p.setBrush(grad); p.drawEllipse(QtCore.QPointF(cx + rr * 0.55, cy - rr * 0.35), rr * 0.9, rr * 0.9)
    # breathing wave
    path = QtGui.QPainterPath()
    n = 60; x0, x1 = r.left() + s * 0.14, r.right() - s * 0.14; ym = r.top() + s * 0.66; amp = s * 0.14
    for i in range(n + 1):
        t = i / n; x = x0 + (x1 - x0) * t
        env = 0.35 + 0.65 * math.sin(math.pi * t) ** 0.8
        y = ym - amp * env * math.sin(t * math.pi * 4.0)
        if i == 0: path.moveTo(x, y)
        else: path.lineTo(x, y)
    p.setPen(QtGui.QPen(QtGui.QColor('white'), max(1.5, s * 0.07), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)); p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(path)


def logo_pixmap(size=64, on_dark=False):
    pm = QtGui.QPixmap(size, size); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); paint_logo(p, QtCore.QRectF(1, 1, size - 2, size - 2), on_dark); p.end(); return pm


def app_icon():
    ic = QtGui.QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256): ic.addPixmap(logo_pixmap(s))
    return ic


class LogoWidget(QtWidgets.QWidget):
    """Logo mark plus wordmark, for the toolbar (dark background)."""
    def __init__(self, size=30, wordmark=True):
        super().__init__(); self.size_ = size; self.wordmark = wordmark
        self.setFixedSize(size + (118 if wordmark else 0) + 8, size + 4)
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
        mark = QtWidgets.QLabel(); mark.setPixmap(logo_pixmap(34, on_dark=True)); lay.addWidget(mark)
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
