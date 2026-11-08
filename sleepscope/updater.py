"""Update check: on every start the app asks GitHub for the newest release and offers to install it.

Uses the public releases API (no account, no key). Nothing is sent but the request itself. When the user accepts,
SleepScope-Setup.exe is downloaded to the temp folder and run silently; the installer closes this copy, installs
over it (settings, key and saved answers are kept) and starts the new version.
"""
from __future__ import annotations
import json, os, re, sys, tempfile, subprocess, urllib.request
from PySide6 import QtCore, QtWidgets

REPO = 'robertb-design/SleepScope'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
UA = {'User-Agent': 'SleepScope-updater', 'Accept': 'application/vnd.github+json'}


def parse_version(v):
    """'v1.0.43' or '1.0.43' -> (1, 0, 43); anything else -> None."""
    m = re.match(r'^v?(\d+)\.(\d+)\.(\d+)$', (v or '').strip())
    return tuple(int(x) for x in m.groups()) if m else None


def latest_release(timeout=8):
    """Return (version_text, installer_url, page_url) of the newest release."""
    with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=timeout) as r:
        j = json.load(r)
    url = next((a['browser_download_url'] for a in j.get('assets', []) if a.get('name') == 'SleepScope-Setup.exe'), None)
    return j.get('tag_name', '').lstrip('v'), url, j.get('html_url', f'https://github.com/{REPO}/releases/latest')


class CheckWorker(QtCore.QThread):
    result = QtCore.Signal(object)          # (version, url, page) or Exception
    def run(self):
        try: self.result.emit(latest_release())
        except Exception as e: self.result.emit(e)


class DownloadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    def __init__(self, url, version):
        super().__init__(); self.url, self.version = url, version
    def run(self):
        try:
            path = os.path.join(tempfile.gettempdir(), f'SleepScope-Setup-{self.version}.exe'); part = path + '.part'
            with urllib.request.urlopen(urllib.request.Request(self.url, headers={'User-Agent': UA['User-Agent']}), timeout=30) as r, open(part, 'wb') as f:
                total = int(r.headers.get('Content-Length') or 0); got = 0
                while True:
                    b = r.read(1 << 16)
                    if not b: break
                    f.write(b); got += len(b); self.progress.emit(got, total)
            if total and got != total: raise IOError(f'download incomplete ({got} of {total} bytes)')
            os.replace(part, path); self.done.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class Updater(QtCore.QObject):
    """Owned by the main window. check(quiet=True) runs at start; quiet means say nothing when up to date or offline."""
    def __init__(self, window, settings):
        super().__init__(window); self.w, self.settings = window, settings; self.worker = None; self.quiet = True

    def current(self):
        from . import version as _v
        return _v.VERSION

    def check(self, quiet=True):
        cur = self.current()
        if cur == 'source':
            if not quiet: QtWidgets.QMessageBox.information(self.w, 'Updates', 'Running from source; updates come from git, not the installer.')
            return
        if self.worker is not None and self.worker.isRunning(): return
        self.quiet = quiet
        self.worker = CheckWorker(); self.worker.result.connect(self._result); self.worker.start()

    def _result(self, res):
        if isinstance(res, Exception):
            if not self.quiet: QtWidgets.QMessageBox.warning(self.w, 'Updates', f'Could not reach GitHub to check for updates.\n\n{res}')
            return
        ver, url, page = res; cur = self.current()
        new, have = parse_version(ver), parse_version(cur)
        if not new or not have or new <= have:
            if not self.quiet: QtWidgets.QMessageBox.information(self.w, 'Updates', f'You have the newest version, {cur}.')
            else: self.w.statusBar().showMessage(f'SleepScope {cur} is the newest version.', 6000)
            return
        if self.quiet and self.settings.value('skip_version', '') == ver: return
        box = QtWidgets.QMessageBox(self.w); box.setWindowTitle('Update available'); box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(f'SleepScope {ver} is available. You have {cur}.')
        box.setInformativeText('Install now? SleepScope closes, installs the new version over this one and opens again. '
                               'Your settings, API key and saved answers are kept.')
        b_now = box.addButton('Install now', QtWidgets.QMessageBox.AcceptRole); b_later = box.addButton('Later', QtWidgets.QMessageBox.RejectRole)
        b_skip = box.addButton('Skip this version', QtWidgets.QMessageBox.DestructiveRole); box.setDefaultButton(b_now)
        box.exec()
        if box.clickedButton() is b_skip: self.settings.setValue('skip_version', ver); return
        if box.clickedButton() is not b_now: return
        if not url:
            import webbrowser; webbrowser.open(page); return
        self._download(url, ver)

    def _download(self, url, ver):
        dlg = QtWidgets.QProgressDialog(f'Downloading SleepScope {ver}…', 'Cancel', 0, 100, self.w)
        dlg.setWindowTitle('Update'); dlg.setWindowModality(QtCore.Qt.WindowModal); dlg.setMinimumDuration(0); dlg.setValue(0)
        self.dl = DownloadWorker(url, ver)
        self.dl.progress.connect(lambda got, tot: dlg.setValue(int(100 * got / tot)) if tot else None)
        self.dl.failed.connect(lambda msg: (dlg.close(), QtWidgets.QMessageBox.warning(self.w, 'Update', f'The download failed: {msg}\n\nGet it from {API.replace("api.github.com/repos", "github.com")}')))
        self.dl.done.connect(lambda path: (dlg.close(), self._install(path)))
        dlg.canceled.connect(self.dl.terminate)
        self.dl.start()

    def _install(self, path):
        try:
            flags = 0x00000008 | 0x00000200 if sys.platform == 'win32' else 0      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([path, '/SILENT', '/CLOSEAPPLICATIONS', '/NORESTART'], creationflags=flags, close_fds=True)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self.w, 'Update', f'Could not start the installer: {e}\n\nIt is saved at {path}; run it by hand.'); return
        QtWidgets.QApplication.quit()
