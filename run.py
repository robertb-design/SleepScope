import sys, os
if '--selftest' in sys.argv:
    # used by the build: the frozen exe must import everything it needs before a release is published
    out = os.path.join(os.path.dirname(sys.executable), 'selftest.txt')
    try:
        import numpy, scipy.signal, pyedflib, pyqtgraph
        from PySide6 import QtWidgets
        import sleepscope.ui_main, sleepscope.scoring, sleepscope.apple_health
        numpy.linalg.inv(numpy.eye(3)); scipy.signal.butter(2, 0.1)
        open(out, 'w').write(f'ok numpy {numpy.__version__}\n'); sys.exit(0)
    except Exception:
        import traceback; open(out, 'w').write(traceback.format_exc()); sys.exit(3)
from sleepscope.ui_main import main
main()
