"""Start here: a home screen with numbered, colour coded step cards and live status."""
from __future__ import annotations
import os
from PySide6 import QtCore, QtWidgets, QtGui
from .branding import logo_pixmap

STEPS = [
    ('1', '#2a78d6', 'Get your data in', 'Put the machine\'s SD card in the PC (built-in slot or a USB card reader) and open it. No card yet? Load the sample data to look around.', 'Open SD card…', 'open'),
    ('2', '#1baf7a', 'Read the Synopsis', 'A plain English report for any date range, and, once Claude is connected, Claude\'s own reading of the same data beside it.', 'Go to Synopsis', 'synopsis'),
    ('3', '#6250d6', 'See the picture', 'The 3D Landscape shows a week at a glance; the Night tab shows every breath. Drag to rotate, hover for values.', 'Go to 3D Landscape', 'landscape'),
    ('4', '#eb6834', 'Connect Claude', 'Save an API key from console.anthropic.com and Claude writes a synopsis of your data by itself each time it loads, and answers questions (a few cents each).', 'Set up Ask Claude', 'ask'),
    ('5', '#e34948', 'Add an oximeter', 'A Wellue O2Ring or similar records SpO2 all night. Import its CSV and the oxygen side of the picture fills in.', 'Import oximeter CSV…', 'oximeter'),
    ('6', '#eda100', 'Add Apple Health', 'Export from the Health app on the iPhone and import here for sleep stages, heart rate and Watch SpO2 next to the CPAP data.', 'Import Apple Health…', 'apple'),
    ('7', '#0f8f8a', 'Record your equipment', 'Enter your machine and mask (type, brand, model, size) and when parts were last replaced. SleepScope reads how you use them and lists options worth raising with your doctor or supplier.', 'Go to Equipment', 'equipment'),
]


class StepCard(QtWidgets.QFrame):
    clicked = QtCore.Signal(str)
    def __init__(self, num, colour, title, body, button, action):
        super().__init__(); self.action = action; self.colour = colour
        self.setObjectName('card'); self.setStyleSheet(f"""
            QFrame#card {{ background: white; border: 1px solid #e6e5e2; border-top: 6px solid {colour}; border-radius: 10px; }}
            QLabel {{ background: transparent; border: none; }}
            QPushButton#go {{ background: {colour}; color: white; border: none; border-radius: 6px; padding: 7px 14px; font-weight: 600; }}
            QPushButton#go:hover {{ background: {QtGui.QColor(colour).darker(115).name()}; }}
        """)
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(16, 12, 16, 14); lay.setSpacing(8)
        top = QtWidgets.QHBoxLayout(); lay.addLayout(top)
        badge = QtWidgets.QLabel(num); badge.setFixedSize(34, 34); badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setStyleSheet(f'background:{colour}; color:white; border-radius:17px; font-size:16px; font-weight:700;'); top.addWidget(badge)
        t = QtWidgets.QLabel(title); t.setStyleSheet('font-size:15px; font-weight:700; color:#0b0b0b'); top.addWidget(t, 1)
        self.status = QtWidgets.QLabel(''); self.status.setStyleSheet('color:#52514e; font-size:11px'); top.addWidget(self.status)
        b = QtWidgets.QLabel(body); b.setWordWrap(True); b.setStyleSheet('color:#3a3936; font-size:12px'); b.setMinimumHeight(54); lay.addWidget(b, 1)
        btn = QtWidgets.QPushButton(button); btn.setObjectName('go'); btn.setCursor(QtCore.Qt.PointingHandCursor); btn.clicked.connect(lambda: self.clicked.emit(self.action))
        row = QtWidgets.QHBoxLayout(); row.addWidget(btn); row.addStretch(); lay.addLayout(row)
    def set_done(self, done, text_done='Done', text_todo='Not yet'):
        self.status.setText(('✔ ' + text_done) if done else text_todo)
        self.status.setStyleSheet(f"color:{'#008300' if done else '#8a8985'}; font-size:11px; font-weight:{600 if done else 400}")


class HomeView(QtWidgets.QScrollArea):
    action = QtCore.Signal(str)
    def __init__(self):
        super().__init__(); self.setWidgetResizable(True); self.setFrameShape(QtWidgets.QFrame.NoFrame)
        w = QtWidgets.QWidget(); w.setStyleSheet('background:#f6f5f2'); self.setWidget(w)
        lay = QtWidgets.QVBoxLayout(w); lay.setContentsMargins(24, 20, 24, 24); lay.setSpacing(16)
        banner = QtWidgets.QFrame(); banner.setStyleSheet('QFrame { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4f91, stop:1 #2a78d6); border-radius: 12px; } QLabel { color: white; background: transparent; }')
        bl = QtWidgets.QVBoxLayout(banner); bl.setContentsMargins(24, 18, 24, 18)
        hrow = QtWidgets.QHBoxLayout(); bl.addLayout(hrow)
        mark = QtWidgets.QLabel(); mark.setPixmap(logo_pixmap(48, on_dark=True)); hrow.addWidget(mark)
        h = QtWidgets.QLabel('SleepScope'); h.setStyleSheet('font-size:26px; font-weight:800'); hrow.addWidget(h); hrow.addStretch()
        sub = QtWidgets.QLabel('See what your CPAP is doing every night: what the machine scored, what the airflow shows, where the mask leaked, and what it all means. Seven steps, in order. Steps 1 and 2 are enough to start; the rest add more of the picture.')
        sub.setWordWrap(True); sub.setStyleSheet('font-size:13px'); bl.addWidget(sub)
        self.summary = QtWidgets.QLabel(''); self.summary.setStyleSheet('font-size:12px; color:#dbe7f7'); bl.addWidget(self.summary)
        lay.addWidget(banner)
        grid = QtWidgets.QGridLayout(); grid.setSpacing(14); lay.addLayout(grid)
        self.cards = {}
        for i, (num, col, title, body, button, action) in enumerate(STEPS):
            c = StepCard(num, col, title, body, button, action); c.clicked.connect(self.action.emit); grid.addWidget(c, i // 3, i % 3); self.cards[action] = c
        foot = QtWidgets.QLabel('Full written instructions, including setting up the card reader and the Claude API key, are on the <b>How to use</b> tab. SleepScope is not a medical device; it reads the data so you can ask better questions.')
        foot.setWordWrap(True); foot.setStyleSheet('color:#52514e; font-size:12px; background:transparent'); lay.addWidget(foot); lay.addStretch()

    def update_status(self, nights, api_key, oximetry, apple, equipment=False):
        n = len(nights or [])
        self.cards['open'].set_done(n > 0, f'{n} nights loaded', 'No data loaded')
        self.cards['synopsis'].set_done(n > 0, 'Ready to read', 'Needs data')
        self.cards['landscape'].set_done(n > 0, 'Ready', 'Needs data')
        self.cards['ask'].set_done(bool(api_key), 'API key saved', 'No API key yet')
        self.cards['oximeter'].set_done(oximetry, 'Oximetry present', 'Optional')
        self.cards['apple'].set_done(apple, 'Watch data present', 'Optional')
        self.cards['equipment'].set_done(equipment, 'Recorded', 'Recommended')
        if n:
            hrs = sum(x.hours for x in nights); ahi = sum(x.stats.get('OA', 0) + x.stats.get('CA', 0) + x.stats.get('H', 0) + x.stats.get('UA', 0) for x in nights) / hrs if hrs else 0
            self.summary.setText(f'Loaded: {n} nights, {hrs:.1f} hours, machine AHI {ahi:.1f}. Last night {nights[-1].label}: {nights[-1].hours:.1f} h, AHI {nights[-1].stats.get("AHI", 0):.1f}.')
        else:
            self.summary.setText('Nothing loaded yet. Start with step 1.')
