# PyInstaller spec for SleepScope (one-folder build)
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files
datas, binaries, hidden = [], [], []
d, b, h = collect_all('pyedflib'); datas += d; binaries += b; hidden += h
datas += collect_data_files('pyqtgraph', excludes=['**/examples/**', '**/jupyter/**'])
hidden += collect_submodules('pyqtgraph', filter=lambda n: not n.startswith(('pyqtgraph.examples', 'pyqtgraph.jupyter', 'pyqtgraph.canvas', 'pyqtgraph.flowchart')))
hidden += collect_submodules('OpenGL') + ['OpenGL.platform.win32', 'OpenGL.platform.glx', 'OpenGL.arrays.numpymodule', 'OpenGL.arrays.ctypesarrays', 'OpenGL.arrays.lists', 'OpenGL.arrays.numbers', 'OpenGL.arrays.strings',
           'scipy.signal', 'scipy.special._cdflib', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtSvg', 'PySide6.QtXml', 'PySide6.QtPrintSupport']
datas += [('sleepscope/icon.ico', 'sleepscope'), ('README.md', '.')]
a = Analysis(['run.py'], pathex=['.'], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'PyQt5', 'PyQt6', 'IPython', 'pandas', 'PIL'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SleepScope', debug=False, console=False, icon='sleepscope/icon.ico')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SleepScope')
