import pyqtgraph as pg
from PySide6 import QtGui

C = dict(blue='#2a78d6', orange='#eb6834', aqua='#1baf7a', yellow='#eda100', magenta='#e87ba4', green='#008300',
         violet='#6250d6', red='#e34948', grey='#8a8985', text='#0b0b0b', text2='#52514e', grid='#e6e5e2')

EVENT_COLORS = {
    'Obstructive Apnea': C['red'], 'Central Apnea': C['violet'], 'Unclassified Apnea': C['grey'], 'Hypopnea': C['orange'],
    'Arousal': C['yellow'], 'RERA': C['yellow'], 'Apnea': C['red'], 'Flow Limitation Run': C['violet'], 'Large Leak': C['orange'],
    'Periodic Breathing': C['magenta'], 'Cheyne-Stokes': C['magenta'],
}


def apply(app):
    pg.setConfigOptions(antialias=False, background='w', foreground=C['text2'], useOpenGL=False)
    app.setStyle('Fusion')
    pal = app.palette()
    pal.setColor(QtGui.QPalette.Window, QtGui.QColor('#fcfcfb')); pal.setColor(QtGui.QPalette.Base, QtGui.QColor('#ffffff'))
    pal.setColor(QtGui.QPalette.WindowText, QtGui.QColor(C['text'])); pal.setColor(QtGui.QPalette.Text, QtGui.QColor(C['text']))
    pal.setColor(QtGui.QPalette.Highlight, QtGui.QColor(C['blue'])); pal.setColor(QtGui.QPalette.Button, QtGui.QColor('#f3f2ef'))
    app.setPalette(pal)
    app.setStyleSheet("""
        QWidget { font-family: 'Segoe UI', Arial; font-size: 12px; }
        QTableView { gridline-color: #e6e5e2; selection-background-color: #d6e6fa; selection-color: #0b0b0b; }
        QHeaderView::section { background: #f3f2ef; padding: 3px 6px; border: 0; border-bottom: 1px solid #e6e5e2; font-weight: 600; }
        QTabBar::tab { padding: 6px 14px; } QTabBar::tab:selected { font-weight: 600; }
        QPushButton { padding: 3px 8px; }
    """)


def style_plot(p):
    p.showGrid(x=True, y=True, alpha=0.15)
    for ax in ('left', 'bottom'):
        a = p.getAxis(ax); a.setPen(pg.mkPen(C['grid'])); a.setTextPen(pg.mkPen(C['text2']))
    p.getViewBox().setBackgroundColor('w')
