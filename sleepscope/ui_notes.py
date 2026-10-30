"""Notes tab: browse and search everything saved from the Ask Claude tab (questions and Claude's answers)."""
from __future__ import annotations
import os, re, glob, datetime as dt
from PySide6 import QtCore, QtWidgets, QtGui

SETTINGS = QtCore.QSettings('SleepScope', 'SleepScope')


class NotesView(QtWidgets.QWidget):
    continue_requested = QtCore.Signal(list)   # list of {'role','content'} to load into the Ask tab

    def __init__(self):
        super().__init__(); self.card_root = None; self.files = []
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        bar = QtWidgets.QHBoxLayout(); lay.addLayout(bar)
        bar.addWidget(QtWidgets.QLabel('Search')); self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText('word or phrase, searches questions and answers')
        self.search.textChanged.connect(self.refresh); bar.addWidget(self.search, 2)
        rf = QtWidgets.QPushButton('Refresh'); rf.clicked.connect(self.refresh); bar.addWidget(rf)
        op = QtWidgets.QPushButton('Open folder'); op.clicked.connect(self.open_folder); bar.addWidget(op)
        self.cont = QtWidgets.QPushButton('Continue in Ask Claude'); self.cont.setToolTip('Load this file\'s questions and answers into the Ask Claude tab so you can keep going'); self.cont.clicked.connect(self._continue); bar.addWidget(self.cont)
        dl = QtWidgets.QPushButton('Delete file'); dl.clicked.connect(self._delete); bar.addWidget(dl)
        split = QtWidgets.QSplitter(); lay.addWidget(split, 1)
        self.list = QtWidgets.QTreeWidget(); self.list.setHeaderLabels(['File', 'Where', 'Entries', 'Modified']); self.list.setRootIsDecorated(False)
        self.list.itemSelectionChanged.connect(self._show); split.addWidget(self.list)
        self.view = QtWidgets.QTextBrowser(); self.view.setOpenExternalLinks(True); self.view.setStyleSheet('font-size:13px; padding:8px'); split.addWidget(self.view)
        split.setSizes([420, 1000])
        self.status = QtWidgets.QLabel(''); self.status.setStyleSheet('color:#52514e'); lay.addWidget(self.status)

    # folders: the configured notes folder plus SleepScope_Notes on the card when present
    def folders(self):
        out = []
        f = SETTINGS.value('ask_folder', os.path.join(os.path.expanduser('~'), 'Documents', 'SleepScope'))
        if f: out.append(('PC', f))
        if self.card_root:
            c = os.path.join(self.card_root, 'SleepScope_Notes')
            if os.path.isdir(c) and os.path.abspath(c) != os.path.abspath(f): out.append(('SD card', c))
        return out

    def set_card_root(self, root):
        self.card_root = root; self.refresh()

    def open_folder(self):
        for _, f in self.folders():
            if os.path.isdir(f): QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(f)); return

    def refresh(self):
        self.list.clear(); self.files = []
        q = self.search.text().strip().lower()
        for where, folder in self.folders():
            for p in sorted(glob.glob(os.path.join(folder, '*.md')) + glob.glob(os.path.join(folder, '*.txt')) + glob.glob(os.path.join(folder, '*.html')), key=os.path.getmtime, reverse=True):
                try: text = open(p, 'r', encoding='utf-8', errors='ignore').read()
                except Exception: continue
                if q and q not in text.lower(): continue
                entries = len(re.findall(r'\*\*Question:\*\*', text)) or text.count('<b style')
                it = QtWidgets.QTreeWidgetItem([os.path.basename(p), where, str(entries), dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')])
                it.setData(0, QtCore.Qt.UserRole, p); self.list.addTopLevelItem(it); self.files.append(p)
        for c in range(4): self.list.resizeColumnToContents(c)
        n = len(self.files)
        self.status.setText(f'{n} file{"s" if n != 1 else ""}' + (f' containing "{self.search.text().strip()}"' if q else '') + '  in ' + '; '.join(f for _, f in self.folders()))
        if n: self.list.setCurrentItem(self.list.topLevelItem(0))
        else: self.view.setHtml('<p>No saved answers yet. Answers from the Ask Claude tab are saved automatically when "Save every answer" is ticked.</p>')

    def _current_path(self):
        it = self.list.currentItem(); return it.data(0, QtCore.Qt.UserRole) if it else None

    def _show(self):
        p = self._current_path()
        if not p: return
        text = open(p, 'r', encoding='utf-8', errors='ignore').read()
        if p.lower().endswith('.html'): self.view.setHtml(text)
        else: self.view.setMarkdown(text)
        q = self.search.text().strip()
        if q:   # highlight first match
            cur = self.view.document().find(q)
            if not cur.isNull(): self.view.setTextCursor(cur)

    def _parse_pairs(self, text):
        pairs = []
        for m in re.finditer(r'\*\*Question:\*\*\s*(.*?)\n+\*\*Answer:\*\*\s*\n+(.*?)(?=\n---|\Z)', text, re.S):
            pairs.append({'role': 'user', 'content': m.group(1).strip()}); pairs.append({'role': 'assistant', 'content': m.group(2).strip()})
        return pairs

    def _continue(self):
        p = self._current_path()
        if not p or p.lower().endswith('.html'): return
        pairs = self._parse_pairs(open(p, 'r', encoding='utf-8', errors='ignore').read())
        if pairs: self.continue_requested.emit(pairs)
        else: self.status.setText('No question and answer pairs found in that file.')

    def _delete(self):
        p = self._current_path()
        if not p: return
        if QtWidgets.QMessageBox.question(self, 'Delete', f'Delete {os.path.basename(p)}? This cannot be undone.') == QtWidgets.QMessageBox.Yes:
            try: os.remove(p)
            except Exception as e: self.status.setText(str(e)); return
            self.refresh()
