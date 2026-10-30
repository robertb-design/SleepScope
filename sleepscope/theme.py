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
        QMainWindow, QDialog { background: #f6f5f2; }
        QToolBar { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1d4f91, stop:1 #2a78d6); border: none; padding: 4px 8px; spacing: 6px; }
        QToolBar QToolButton { color: white; background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.25); border-radius: 6px; padding: 5px 10px; font-weight: 600; }
        QToolBar QToolButton:hover { background: rgba(255,255,255,0.28); }
        QToolBar::separator { background: rgba(255,255,255,0.3); width: 1px; margin: 4px 6px; }
        QTabWidget::pane { border: 1px solid #e6e5e2; border-radius: 8px; background: #f6f5f2; top: -1px; }
        QTabBar::tab { background: #e9e8e4; color: #3a3936; padding: 7px 14px; margin-right: 3px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
        QTabBar::tab:selected { background: #f6f5f2; color: #1d4f91; font-weight: 700; border: 1px solid #e6e5e2; border-bottom: 2px solid #f6f5f2; }
        QTabBar::tab:hover:!selected { background: #f0efec; }
        QTableView { gridline-color: #e6e5e2; selection-background-color: #d6e6fa; selection-color: #0b0b0b; background: white; alternate-background-color: #fafaf8; border: none; }
        QHeaderView::section { background: #eef4fc; color: #1d4f91; padding: 4px 6px; border: 0; border-bottom: 1px solid #d6e6fa; font-weight: 700; }
        QPushButton { background: white; border: 1px solid #c9c8c3; border-radius: 6px; padding: 4px 10px; }
        QPushButton:hover { background: #eef4fc; border-color: #2a78d6; }
        QPushButton:default { background: #2a78d6; color: white; border-color: #2a78d6; font-weight: 600; }
        QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #c9c8c3; border-radius: 5px; padding: 3px 6px; }
        QLineEdit:focus, QPlainTextEdit:focus { border-color: #2a78d6; }
        QProgressBar { border: 1px solid #c9c8c3; border-radius: 5px; text-align: center; background: white; } QProgressBar::chunk { background: #1baf7a; border-radius: 4px; }
        QStatusBar { background: #eceae6; color: #3a3936; }
        QTextBrowser { background: white; border: none; }
        QCheckBox { spacing: 6px; }
    """)


def style_plot(p):
    p.showGrid(x=True, y=True, alpha=0.15)
    for ax in ('left', 'bottom'):
        a = p.getAxis(ax); a.setPen(pg.mkPen(C['grid'])); a.setTextPen(pg.mkPen(C['text2']))
    p.getViewBox().setBackgroundColor('w')
