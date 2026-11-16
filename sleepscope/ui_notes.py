"""Notes tab: browse and search everything saved from the Ask Claude tab (questions and Claude's answers)."""
from __future__ import annotations
import os, re, glob, json, datetime as dt
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


class MyNotesView(QtWidgets.QWidget):
    """My notes tab: the user's own notes, one or more per night. Synopsis, Ask Claude and the Night view read them.
    A note marked as a change (new mask, new pressure, a medicine) gets a before and after comparison in the Synopsis."""
    changed = QtCore.Signal()

    def __init__(self):
        super().__init__(); from . import notes as nm; self.nm = nm; self.folder = None; self.nights = []; self.cur_id = None
        nm.CURRENT = nm.merge(self._settings_notes())
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        intro = QtWidgets.QLabel('Write what the numbers cannot know: a new mask, a pressure change, a cold, alcohol, a late night, a night the mask '
                                 'could not be worn, how you felt in the morning. The Synopsis lists them and Ask Claude reads them with every question. '
                                 'Tick <b>This is a change</b> for something that holds from that night on; the Synopsis then compares the nights before and after it. '
                                 'Saved on this PC and in Sleep notes.json in your Sleepscope folder, which also carries them to the phone.')
        intro.setWordWrap(True); intro.setStyleSheet('color:#52514e'); lay.addWidget(intro)
        split = QtWidgets.QSplitter(); lay.addWidget(split, 1)
        self.list = QtWidgets.QTreeWidget(); self.list.setHeaderLabels(['Night', 'Change', 'Note']); self.list.setRootIsDecorated(False)
        self.list.itemSelectionChanged.connect(self._pick); split.addWidget(self.list)
        ed = QtWidgets.QWidget(); el = QtWidgets.QVBoxLayout(ed); split.addWidget(ed); split.setSizes([700, 500])
        row = QtWidgets.QHBoxLayout(); el.addLayout(row)
        row.addWidget(QtWidgets.QLabel('Night of')); self.date = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addDays(-1)); self.date.setCalendarPopup(True); self.date.setDisplayFormat('ddd MM/dd/yyyy'); row.addWidget(self.date)
        self.change = QtWidgets.QCheckBox('This is a change (from this night on)'); row.addWidget(self.change); row.addStretch(1)
        self.text = QtWidgets.QPlainTextEdit(); self.text.setPlaceholderText('For example: First night with the ResMed AirTouch N30i. Or: Head cold, mouth breathing, took the mask off at 3.'); el.addWidget(self.text, 1)
        b = QtWidgets.QHBoxLayout(); el.addLayout(b)
        for t, f in (('New note', self._new), ('Save', self._save), ('Delete', self._delete)):
            w = QtWidgets.QPushButton(t); w.clicked.connect(f); b.addWidget(w)
        b.addStretch(1); self.status = QtWidgets.QLabel(''); self.status.setStyleSheet('color:#52514e'); el.addWidget(self.status)
        self._fill()

    def _settings_notes(self):
        try: return json.loads(SETTINGS.value('sleep_notes', '[]') or '[]')
        except Exception: return []

    def set_folder(self, folder):
        """Merge in Sleep notes.json (and any 'Sleep notes*.json' copies the phone saved) from the Sleepscope folder, then write the result back."""
        self.folder = folder if folder and os.path.isdir(folder) else None
        if not self.folder: return
        extra = []
        for p in glob.glob(os.path.join(self.folder, 'Sleep notes*.json')):
            try:
                with open(p, encoding='utf-8') as f: j = json.load(f)
                extra.append(j.get('notes', []) if isinstance(j, dict) else j)
            except Exception: pass
        before = json.dumps(self.nm.CURRENT); self.nm.CURRENT = self.nm.merge(self.nm.CURRENT, *extra)
        self._persist()
        if json.dumps(self.nm.CURRENT) != before: self._fill(); self.changed.emit()

    def set_night(self, date):
        """Selecting a night elsewhere sets the date for a new note (unless a note is open)."""
        if self.cur_id is None and date: self.date.setDate(QtCore.QDate(date.year, date.month, date.day))

    def _persist(self):
        SETTINGS.setValue('sleep_notes', json.dumps(self.nm.CURRENT))
        if self.folder:
            try: self.nm.save_file(self.folder, self.nm.CURRENT)
            except OSError as e: self.status.setText(f'Could not write Sleep notes.json: {e}')

    def _fill(self):
        self.list.blockSignals(True); self.list.clear()
        for n in reversed(self.nm.live(self.nm.CURRENT)):
            it = QtWidgets.QTreeWidgetItem([self.nm.label(n['date']), 'yes' if n.get('change') else '', ' '.join(n['text'].split())])
            it.setData(0, QtCore.Qt.UserRole, n['id']); it.setToolTip(2, n['text']); self.list.addTopLevelItem(it)
        self.list.resizeColumnToContents(0); self.list.resizeColumnToContents(1); self.list.blockSignals(False)
        k = len(self.nm.live(self.nm.CURRENT)); self.status.setText(f'{k} note{"s" if k != 1 else ""}.' + ('' if self.folder else ' No Sleepscope folder found, so they stay on this PC.'))

    def _pick(self):
        its = self.list.selectedItems()
        if not its: return
        nid = its[0].data(0, QtCore.Qt.UserRole); n = next((x for x in self.nm.CURRENT if x['id'] == nid), None)
        if not n: return
        self.cur_id = nid; d = dt.date.fromisoformat(n['date']); self.date.setDate(QtCore.QDate(d.year, d.month, d.day))
        self.change.setChecked(bool(n.get('change'))); self.text.setPlainText(n['text'])

    def _new(self):
        self.cur_id = None; self.list.clearSelection(); self.text.clear(); self.change.setChecked(False); self.text.setFocus()

    def _save(self):
        t = self.text.toPlainText().strip()
        if not t: self.status.setText('Write something first.'); return
        d = self.date.date().toPython().isoformat()
        if self.cur_id:
            for n in self.nm.CURRENT:
                if n['id'] == self.cur_id: n.update(date=d, text=t, change=self.change.isChecked(), updated=self.nm.now_ms(), deleted=False)
        else:
            n = self.nm.new(d, t, self.change.isChecked()); self.nm.CURRENT.append(n); self.cur_id = n['id']
        self.nm.CURRENT = self.nm.merge(self.nm.CURRENT); self._persist(); self._fill(); self.status.setText('Saved. The Synopsis and Ask Claude use it now.'); self.changed.emit()

    def _delete(self):
        if not self.cur_id: return
        for n in self.nm.CURRENT:
            if n['id'] == self.cur_id: n.update(deleted=True, updated=self.nm.now_ms())
        self._persist(); self._new(); self._fill(); self.changed.emit()
