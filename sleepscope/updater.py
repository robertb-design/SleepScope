"""Automatic update: on every start the app asks GitHub for the newest release and, when there is a newer one,
installs it without asking.

Uses the public releases API (no account, no key). Nothing is sent but the request itself. SleepScope-Setup.exe is
downloaded to the temp folder (progress shown, Cancel skips it for this session) and run silently; the installer
closes this copy, installs over it (settings, key and saved answers are kept) and starts the new version.
Falls back to asking when the copy is portable (no uninstaller beside the exe, so the installer would put a second
copy elsewhere) or when two automatic attempts at the same version have not taken.
"""
from __future__ import annotations
import json, os, re, sys, tempfile, subprocess, urllib.request
from PySide6 import QtCore, QtWidgets

REPO = 'robertb-design/SleepScope'
API = f'https://api.github.com/repos/{REPO}/releases/latest'
LATEST = f'https://github.com/{REPO}/releases/latest'          # redirects to .../releases/tag/vX.Y.Z, no rate limit
UA = {'User-Agent': 'SleepScope-updater', 'Accept': 'application/vnd.github+json'}
TIMEOUT = 25


def log(msg):
    """update_log.txt beside the exe (or the source folder): every check, download and failure, with the exact error."""
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        import datetime
        with open(os.path.join(base, 'update_log.txt'), 'a', encoding='utf-8') as f:
            f.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n')
    except Exception:
        pass


def parse_version(v):
    """'v1.0.43' or '1.0.43' -> (1, 0, 43); anything else -> None."""
    m = re.match(r'^v?(\d+)\.(\d+)\.(\d+)$', (v or '').strip())
    return tuple(int(x) for x in m.groups()) if m else None


def installer_url(ver):
    return f'https://github.com/{REPO}/releases/download/v{ver}/SleepScope-Setup.exe'


def _powershell(script, timeout):
    """Run PowerShell with Windows' own networking (system proxy, PAC scripts, company certificates). Windows only."""
    flags = 0x08000000 if sys.platform == 'win32' else 0            # CREATE_NO_WINDOW
    pre = '[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = "SilentlyContinue"; '
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', pre + script],
                       capture_output=True, text=True, timeout=timeout, creationflags=flags)
    if r.returncode != 0: raise IOError('PowerShell: ' + (r.stderr or r.stdout).strip()[:300])
    return r.stdout.strip()


def _tag_from_url(u):
    m = re.search(r'/releases/tag/(v?[\d.]+)', u or '')
    return m.group(1).lstrip('v') if m else None


def latest_release(timeout=TIMEOUT):
    """Return (version_text, installer_url, page_url) of the newest release.
    Tries, in order: the releases page redirect (github.com, no rate limit), the releases API, then Windows networking
    through PowerShell. Raises with every route's error when all fail."""
    errors = []
    try:                                                                  # 1. github.com/.../releases/latest -> tag
        with urllib.request.urlopen(urllib.request.Request(LATEST, headers={'User-Agent': UA['User-Agent']}), timeout=timeout) as r:
            ver = _tag_from_url(r.geturl())
        if ver: return ver, installer_url(ver), LATEST
        errors.append('releases page: no version in ' + LATEST)
    except Exception as e: errors.append(f'releases page: {e}')
    try:                                                                  # 2. API
        with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=timeout) as r:
            j = json.load(r)
        ver = j.get('tag_name', '').lstrip('v')
        url = next((a['browser_download_url'] for a in j.get('assets', []) if a.get('name') == 'SleepScope-Setup.exe'), None)
        if ver: return ver, url or installer_url(ver), j.get('html_url', LATEST)
    except Exception as e: errors.append(f'API: {e}')
    if sys.platform == 'win32':                                           # 3. Windows networking
        try:
            out = _powershell(f'(Invoke-WebRequest -UseBasicParsing -Uri "{LATEST}" -MaximumRedirection 5).BaseResponse.ResponseUri.AbsoluteUri', timeout + 15)
            ver = _tag_from_url(out)
            if ver: return ver, installer_url(ver), LATEST
            errors.append('Windows: no version in ' + out[:120])
        except Exception as e: errors.append(f'Windows: {e}')
    raise IOError(' | '.join(errors))


class CheckWorker(QtCore.QThread):
    result = QtCore.Signal(object)          # (version, url, page) or Exception
    def run(self):
        try: res = latest_release(); log(f'check ok: newest is {res[0]}'); self.result.emit(res)
        except Exception as e: log(f'check failed: {e}'); self.result.emit(e)


class DownloadWorker(QtCore.QThread):
    progress = QtCore.Signal(int, int)
    done = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    def __init__(self, url, version):
        super().__init__(); self.url, self.version = url, version
    def run(self):
        path = os.path.join(tempfile.gettempdir(), f'SleepScope-Setup-{self.version}.exe'); part = path + '.part'
        try:
            with urllib.request.urlopen(urllib.request.Request(self.url, headers={'User-Agent': UA['User-Agent']}), timeout=TIMEOUT) as r, open(part, 'wb') as f:
                total = int(r.headers.get('Content-Length') or 0); got = 0
                while True:
                    b = r.read(1 << 16)
                    if not b: break
                    f.write(b); got += len(b); self.progress.emit(got, total)
            if total and got != total: raise IOError(f'download incomplete ({got} of {total} bytes)')
            os.replace(part, path); log(f'downloaded {self.version} ({got} bytes)'); self.done.emit(path); return
        except Exception as e:
            first = str(e); log(f'download failed: {first}')
        if sys.platform == 'win32':
            try:
                self.progress.emit(0, 0)
                _powershell(f'Invoke-WebRequest -UseBasicParsing -Uri "{self.url}" -OutFile "{part}"', 600)
                if os.path.getsize(part) < 1_000_000: raise IOError(f'file too small ({os.path.getsize(part)} bytes)')
                os.replace(part, path); log(f'downloaded {self.version} through Windows'); self.done.emit(path); return
            except Exception as e:
                log(f'Windows download failed: {e}'); first += f' | Windows: {e}'
        self.failed.emit(first)


class Updater(QtCore.QObject):
    """Owned by the main window. check(quiet=True) runs at start; quiet means say nothing when up to date or offline."""
    def __init__(self, window, settings):
        super().__init__(window); self.w, self.settings = window, settings; self.worker = None; self.quiet = True

    def installed(self):
        """True for a copy put there by the installer (Inno Setup leaves unins000.exe beside the exe)."""
        return getattr(sys, 'frozen', False) and os.path.exists(os.path.join(os.path.dirname(sys.executable), 'unins000.exe'))

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
            if not self.quiet:
                QtWidgets.QMessageBox.warning(self.w, 'Updates', f'Could not reach GitHub to check for updates.\n\n{res}\n\n'
                                              f'The details are in update_log.txt in the SleepScope folder. The installer is also at {LATEST}')
            else:
                self.w.statusBar().showMessage('Update check could not reach GitHub; trying again in a minute. Details in update_log.txt.', 10000)
                if not getattr(self, '_retried', False): self._retried = True; QtCore.QTimer.singleShot(60000, lambda: self.check(quiet=True))
            return
        ver, url, page = res; cur = self.current()
        new, have = parse_version(ver), parse_version(cur)
        if not new or not have or new <= have:
            if not self.quiet: QtWidgets.QMessageBox.information(self.w, 'Updates', f'You have the newest version, {cur}.')
            else: self.w.statusBar().showMessage(f'SleepScope {cur} is the newest version.', 6000)
            return
        if not url:
            if not self.quiet: import webbrowser; webbrowser.open(page)
            return
        if self.installed():
            tries = int(self.settings.value('auto_update_tries', 0) or 0) if self.settings.value('auto_update_ver', '') == ver else 0
            if tries < 2 or not self.quiet:
                self.settings.setValue('auto_update_ver', ver); self.settings.setValue('auto_update_tries', tries + 1)
                self._download(url, ver); return
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
        dlg = QtWidgets.QProgressDialog(f'Updating to SleepScope {ver}. It reopens by itself when done.', 'Cancel', 0, 100, self.w)
        dlg.setWindowTitle('Update'); dlg.setWindowModality(QtCore.Qt.WindowModal); dlg.setMinimumDuration(0); dlg.setValue(0)
        self.dl = DownloadWorker(url, ver)
        self.dl.progress.connect(lambda got, tot: dlg.setValue(int(100 * got / tot)) if tot else dlg.setRange(0, 0))
        self.dl.failed.connect(lambda msg: (dlg.close(), self.w.statusBar().showMessage(f'Update to {ver} failed ({msg}); it is tried again next start.', 15000) if self.quiet
                                            else QtWidgets.QMessageBox.warning(self.w, 'Update', f'The download failed: {msg}\n\nDetails in update_log.txt. Get it from {LATEST}')))
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
