"""Ask Claude tab: chat with the Claude API about the loaded data.

Uses the Messages API directly over HTTPS (no SDK, no extra packages). The API key is entered once and stored in the
app settings on this PC (Windows registry, HKCU\\Software\\SleepScope). Each question is sent with a context block built
from the selected date range: the synopsis text, the per-night statistics table, settings runs, and the event list.
Nothing is sent until you press Send.
"""
from __future__ import annotations
import json, datetime as dt, urllib.request, urllib.error, html, re, os, glob
import numpy as np
from PySide6 import QtCore, QtWidgets, QtGui
from . import scoring, synopsis

API_URL = 'https://api.anthropic.com/v1/messages'
DEFAULT_MODEL = 'claude-sonnet-5-5'
C_ERR = '#e34948'
SETTINGS = QtCore.QSettings('SleepScope', 'SleepScope')

SYSTEM = """You are a sleep-therapy data analyst helping a CPAP user understand their own ResMed AirSense data.
Give plain, direct, well-reasoned answers with no filler. If the user has written an About me note, use it to pitch the answer.
You have the app's computed results for the selected date range in the CONTEXT block. Use those numbers; do not invent data.
When a question needs something not in the context, say so and name what would answer it (an oximeter, STR.edf, a longer range, the prescriber).
Be clear about what is established physiology versus your inference. Pressure settings are prescribed: discuss trade-offs and what to raise
with the prescriber rather than instructing changes. Never use dashes in prose; use commas or restructure. Keep answers tight.
"""


def build_context(nights, start, end, diag_ahi=None):
    sel = [n for n in nights if start <= n.date <= end]
    if not sel: return 'No nights in range.'
    syn = re.sub(r'<[^>]+>', '', synopsis.generate(sel, start, end, diag_ahi))
    syn = html.unescape(re.sub(r'\n{3,}', '\n\n', syn))
    cols = [(k, h) for k, h, _ in scoring.STAT_COLUMNS]
    table = ['\t'.join(h for _, h in cols)]
    for n in sel:
        table.append('\t'.join(scoring.fmt(k, n.stats.get(k)) for k, _ in cols))
    evs = []
    for n in sel:
        for s in n.sessions:
            for e in sorted(s.machine_events + s.app_events, key=lambda e: e.start):
                if e.label in ('Flow Limitation Run',) and 'RERA' not in e.detail: continue
                i2 = max(0, int((e.start - s.start).total_seconds() / 2)); pr = s.ch.get('Press'); lk = s.ch.get('Leak')
                ptxt = f"P={pr[min(i2, len(pr) - 1)]:.1f}" if pr is not None and len(pr) else 'P=?'
                ltxt = f"leak={lk[min(i2, len(lk) - 1)] * 60:.0f}" if lk is not None and len(lk) else 'leak=?'
                evs.append(f"{n.label} {e.start:%H:%M:%S} {e.label} [{e.source}] {e.duration:.0f}s {ptxt} {ltxt} {e.detail}")
    if len(evs) > 400: evs = evs[:400] + [f'... {len(evs) - 400} more events omitted']
    total, hit = scoring.validation_summary(sel)
    return (f"CONTEXT\nDate range: {start} to {end}. Nights with data: {len(sel)}.\n\n=== App synopsis (rule based) ===\n{syn}\n\n"
            f"=== Per night statistics (tab separated; P = set pressure cmH2O, leak L/min, app = SleepScope's own flow scoring, machine = ResMed scoring) ===\n"
            + '\n'.join(table) + "\n\n=== Events (flow limitation runs listed only when RERA-like) ===\n" + '\n'.join(evs)
            + "\n\n=== Method notes ===\nResMed stamps event end; app subtracts duration. App hypopnea = 30% flow drop >= 10 s without desaturation check (over-counts). "
              f"On this card the app's detector reproduced {hit} of {total} machine-scored apneas. Obstructive vs central comes only from the machine. No SpO2 unless an oximeter is listed above.")


class AskWorker(QtCore.QThread):
    done = QtCore.Signal(str); failed = QtCore.Signal(str)
    def __init__(self, key, model, system, messages):
        super().__init__(); self.key, self.model, self.system, self.messages = key, model, system, messages
    def run(self):
        hdr = {'content-type': 'application/json', 'x-api-key': self.key, 'anthropic-version': '2023-06-01'}
        if self.messages is None:      # connection test: list models
            req = urllib.request.Request('https://api.anthropic.com/v1/models', headers=hdr)
        else:
            body = json.dumps({'model': self.model, 'max_tokens': 2000, 'system': self.system, 'messages': self.messages}).encode()
            req = urllib.request.Request(API_URL, data=body, headers=hdr)
        t0 = dt.datetime.now()
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read()
            _log(f'{req.full_url} -> {len(raw)} bytes in {(dt.datetime.now() - t0).total_seconds():.1f} s')
            j = json.loads(raw)
            if self.messages is None:
                ids = [m.get('id') for m in j.get('data', [])]
                self.done.emit('Connection OK. Models available to this key: ' + ', '.join(ids))
                return
            text = ''.join(b.get('text', '') for b in j.get('content', []) if b.get('type') == 'text')
            if not text.strip():
                _log('EMPTY ANSWER, raw response: ' + raw.decode('utf-8', 'ignore')[:2000])
                self.failed.emit('The API returned no text. Stop reason: ' + str(j.get('stop_reason')) + '. Raw response is in ask_log.txt.')
                return
            self.done.emit(text)
        except urllib.error.HTTPError as e:
            try: msg = json.loads(e.read()).get('error', {}).get('message', str(e))
            except Exception: msg = str(e)
            _log(f'HTTP {e.code}: {msg}'); self.failed.emit(f'API error {e.code}: {msg}')
        except Exception as e:
            _log(f'EXCEPTION: {e!r}'); self.failed.emit(f'{type(e).__name__}: {e}')


def _log(msg):
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ask_log.txt'), 'a', encoding='utf-8') as f:
            f.write(f'{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n')
    except Exception:
        pass


class AskView(QtWidgets.QWidget):
    answer_saved = QtCore.Signal()
    def __init__(self):
        super().__init__(); self.nights = []; self.history = []; self.worker = None
        lay = QtWidgets.QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        top = QtWidgets.QHBoxLayout(); lay.addLayout(top)
        top.addWidget(QtWidgets.QLabel('API key'))
        self.key = QtWidgets.QLineEdit(SETTINGS.value('api_key', '')); self.key.setEchoMode(QtWidgets.QLineEdit.Password); self.key.setPlaceholderText('sk-ant-...')
        self.key.editingFinished.connect(lambda: SETTINGS.setValue('api_key', self.key.text().strip())); top.addWidget(self.key, 2)
        top.addWidget(QtWidgets.QLabel('Model')); self.model = QtWidgets.QLineEdit(SETTINGS.value('model', DEFAULT_MODEL)); self.model.setFixedWidth(180)
        self.model.editingFinished.connect(lambda: SETTINGS.setValue('model', self.model.text().strip())); top.addWidget(self.model)
        top.addWidget(QtWidgets.QLabel('Range')); self.d0 = QtWidgets.QDateEdit(calendarPopup=True); self.d0.setDisplayFormat('MMM d, yyyy'); top.addWidget(self.d0)
        top.addWidget(QtWidgets.QLabel('to')); self.d1 = QtWidgets.QDateEdit(calendarPopup=True); self.d1.setDisplayFormat('MMM d, yyyy'); top.addWidget(self.d1)
        tst = QtWidgets.QPushButton('Test connection'); tst.setToolTip('Checks the key and the network without sending any data'); tst.clicked.connect(self.test_connection); top.addWidget(tst)
        clr = QtWidgets.QPushButton('New conversation'); clr.clicked.connect(self.clear); top.addWidget(clr)
        row2 = QtWidgets.QHBoxLayout(); lay.addLayout(row2)
        self.autosave = QtWidgets.QCheckBox('Save every answer to'); self.autosave.setChecked(SETTINGS.value('ask_autosave', 'true') == 'true')
        self.autosave.toggled.connect(lambda v: SETTINGS.setValue('ask_autosave', 'true' if v else 'false')); row2.addWidget(self.autosave)
        default_dir = os.path.join(os.path.expanduser('~'), 'Documents', 'SleepScope')
        self.folder = QtWidgets.QLineEdit(SETTINGS.value('ask_folder', default_dir)); self.folder.editingFinished.connect(lambda: SETTINGS.setValue('ask_folder', self.folder.text().strip())); row2.addWidget(self.folder, 2)
        b = QtWidgets.QPushButton('Browse…'); b.clicked.connect(self.pick_folder); row2.addWidget(b)
        self.card_btn = QtWidgets.QPushButton('Use SD card'); self.card_btn.setToolTip('Save into a SleepScope_Notes folder on the card. The machine ignores folders it does not know, but keep the card clean if ResMed support ever asks for it.')
        self.card_btn.clicked.connect(self.use_card); row2.addWidget(self.card_btn)
        sv = QtWidgets.QPushButton('Save conversation…'); sv.clicked.connect(self.save_conversation); row2.addWidget(sv)
        row3 = QtWidgets.QHBoxLayout(); lay.addLayout(row3)
        row3.addWidget(QtWidgets.QLabel('About me (optional, sent with each question, stored on this PC only)'))
        self.about = QtWidgets.QLineEdit(SETTINGS.value('about_me', '')); self.about.setPlaceholderText('e.g. 71, engineer, diagnosed 2024, diagnostic AHI 35, want direct answers')
        self.about.editingFinished.connect(lambda: SETTINGS.setValue('about_me', self.about.text().strip())); row3.addWidget(self.about, 1)
        row2.addWidget(QtWidgets.QLabel('Earlier:')); self.earlier = QtWidgets.QComboBox(); self.earlier.setMinimumWidth(260)
        self.earlier.activated.connect(self._pick_earlier); row2.addWidget(self.earlier)
        op = QtWidgets.QPushButton('Open folder'); op.clicked.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self._ensure_folder() or '.'))); row2.addWidget(op)
        self.card_root = None
        self.view = QtWidgets.QTextBrowser(); self.view.setOpenExternalLinks(True); self.view.setStyleSheet('font-size:13px; padding:6px'); lay.addWidget(self.view, 1)
        bottom = QtWidgets.QHBoxLayout(); lay.addLayout(bottom)
        self.input = QtWidgets.QPlainTextEdit(); self.input.setFixedHeight(70); self.input.setPlaceholderText('Ask about the results in the selected range. Ctrl+Enter to send.')
        self.input.installEventFilter(self); bottom.addWidget(self.input, 1)
        self.send = QtWidgets.QPushButton('Send'); self.send.setFixedWidth(90); self.send.clicked.connect(self.ask); bottom.addWidget(self.send)
        self.status = QtWidgets.QLabel(''); self.status.setStyleSheet('color:#52514e'); lay.addWidget(self.status)
        self.timer = QtCore.QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self._tick); self._t0 = None
        self.intro()

    def intro(self):
        self.view.setHtml("""<p><b>Ask Claude about your data.</b> Each question goes to the Claude API together with the synopsis, the per-night statistics and the event list for the selected range,
        so the answer is grounded in your numbers.</p>
        <p>You need an API key: create one at <a href='https://console.anthropic.com/'>console.anthropic.com</a> (API keys). It is billed per use, separately from a claude.ai subscription;
        a question with a month of context costs a few cents. The key is saved on this PC only. Nothing is sent until you press Send.</p>
        <p>Suggested questions: <i>What should I change first?</i> &nbsp; <i>Is the leak on 10/28 the mask or my mouth?</i> &nbsp; <i>Do the central apneas worry you?</i> &nbsp;
        <i>Write a summary I can give my sleep doctor.</i> &nbsp; <i>Compare the nights under different settings.</i></p>""")

    def set_nights(self, nights):
        self.nights = nights
        if not nights: return
        self.d0.setDate(QtCore.QDate(max(nights[0].date, nights[-1].date - dt.timedelta(days=29)))); self.d1.setDate(QtCore.QDate(nights[-1].date))

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QtCore.QEvent.KeyPress and ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and ev.modifiers() & QtCore.Qt.ControlModifier:
            self.ask(); return True
        return super().eventFilter(obj, ev)

    def clear(self):
        self.history = []; self._resume = None; self.intro(); self.status.setText('')

    def _append(self, who, text):
        body = html.escape(text).replace('\n', '<br>')
        color = '#2a78d6' if who == 'You' else '#0b0b0b'
        self.view.append(f"<p style='margin-top:10px'><b style='color:{color}'>{who}</b><br>{body}</p>")
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def ask(self):
        q = self.input.toPlainText().strip()
        if not q or (self.worker and self.worker.isRunning()): return
        key = self.key.text().strip()
        if not key:
            self.status.setText('Enter an API key first.'); return
        if not self.nights:
            self.status.setText('Load an SD card first.'); return
        a, b = self.d0.date().toPython(), self.d1.date().toPython()
        if a > b: a, b = b, a
        diag = float(SETTINGS.value('diag_ahi', 0)) or None
        ctx = build_context(self.nights, a, b, diag)
        if not self.history:
            resumed = getattr(self, '_resume', None)
            if resumed:
                first = resumed[0]['content']
                self.history = [{'role': 'user', 'content': ctx + '\n\nQUESTION: ' + first}] + resumed[1:]
                self._resume = None
                self.history.append({'role': 'user', 'content': q})
            else:
                self.history.append({'role': 'user', 'content': ctx + '\n\nQUESTION: ' + q})
        else:
            self.history.append({'role': 'user', 'content': q})
        self._append('You', q); self.input.clear()
        _log(f'ask: model={self.model.text().strip()} context_chars={len(ctx)} history={len(self.history)}')
        self._start_worker(list(self.history), f'Sending to {self.model.text().strip()} with {len(ctx) // 4:,} tokens of context...')

    # ------------------------------------------------------------------ saving
    def _ensure_folder(self):
        d = self.folder.text().strip()
        if not d: return None
        try: os.makedirs(d, exist_ok=True); return d
        except Exception as e: self.status.setText(f'Cannot create folder {d}: {e}'); return None
    def pick_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Folder for saved answers', self.folder.text())
        if d: self.folder.setText(d); SETTINGS.setValue('ask_folder', d)
    def set_card_root(self, root):
        self.card_root = root; self.card_btn.setEnabled(bool(root)); self.autoload_latest()
    def use_card(self):
        if self.card_root:
            d = os.path.join(self.card_root, 'SleepScope_Notes'); self.folder.setText(d); SETTINGS.setValue('ask_folder', d); self._ensure_folder()
    def _note_files(self):
        out = []
        for d in {self.folder.text().strip(), os.path.join(self.card_root, 'SleepScope_Notes') if self.card_root else ''}:
            if d and os.path.isdir(d): out += glob.glob(os.path.join(d, '*.md'))
        return sorted(set(out), key=os.path.getmtime, reverse=True)
    def refresh_earlier(self):
        self.earlier.blockSignals(True); self.earlier.clear(); self.earlier.addItem('pick a saved conversation to show it here', '')
        for p in self._note_files():
            self.earlier.addItem(f"{os.path.basename(p)}  ({dt.datetime.fromtimestamp(os.path.getmtime(p)):%b %d %H:%M})", p)
        self.earlier.blockSignals(False)
    def _pick_earlier(self, i):
        p = self.earlier.itemData(i)
        if p: self.load_file(p)
    @staticmethod
    def parse_pairs(text):
        pairs = []
        for m in re.finditer(r'\*\*Question:\*\*\s*(.*?)\n+\*\*Answer:\*\*\s*\n+(.*?)(?=\n---|\Z)', text, re.S):
            pairs.append({'role': 'user', 'content': m.group(1).strip()}); pairs.append({'role': 'assistant', 'content': m.group(2).strip()})
        return pairs
    def load_file(self, path):
        try: pairs = self.parse_pairs(open(path, 'r', encoding='utf-8', errors='ignore').read())
        except Exception as e: self.status.setText(str(e)); return
        if pairs: self.load_history(pairs); self.status.setText(f'Showing {os.path.basename(path)}: {len(pairs) // 2} question(s). Ask a follow-up to continue it, or New conversation to start fresh.')
        else: self.status.setText('No questions and answers found in that file.')
    def autoload_latest(self):
        files = self._note_files()
        if files and not self.history and getattr(self, '_resume', None) is None: self.load_file(files[0])
        self.refresh_earlier()
    def _range_text(self):
        return f"{self.d0.date().toPython()} to {self.d1.date().toPython()}"
    def _log_pair(self, q, a):
        d = self._ensure_folder()
        if not d: return
        path = os.path.join(d, f"claude_answers_{dt.date.today():%Y-%m-%d}.md")
        new = not os.path.exists(path)
        with open(path, 'a', encoding='utf-8') as f:
            if new: f.write(f"# SleepScope, questions to Claude, {dt.date.today():%B %d, %Y}\n\n")
            f.write(f"## {dt.datetime.now():%H:%M}  (data range {self._range_text()}, model {self.model.text().strip()})\n\n**Question:** {q}\n\n**Answer:**\n\n{a}\n\n---\n\n")
        self.status.setText(f'Saved to {path}'); self.answer_saved.emit(); self.refresh_earlier()
    def save_conversation(self):
        if not self.history: self.status.setText('Nothing to save yet.'); return
        d = self._ensure_folder() or ''
        default = os.path.join(d, f"claude_conversation_{dt.datetime.now():%Y-%m-%d_%H%M}.md")
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save conversation', default, 'Markdown (*.md);;Text (*.txt);;HTML (*.html)')
        if not p: return
        if p.lower().endswith('.html'):
            open(p, 'w', encoding='utf-8').write('<html><body style="font-family:Segoe UI,Arial;max-width:800px;margin:auto">' + self.view.toHtml() + '</body></html>')
        else:
            lines = [f"# SleepScope conversation with Claude, {dt.datetime.now():%B %d, %Y %H:%M}", f"Data range {self._range_text()}, model {self.model.text().strip()}", '']
            for m in self.history:
                c = m['content']
                if m['role'] == 'user' and c.startswith('CONTEXT'): c = c.split('QUESTION: ', 1)[-1]
                lines += [f"**{'Question' if m['role'] == 'user' else 'Answer'}:** {c}" if m['role'] == 'user' else f"**Answer:**\n\n{c}", '', '---', '']
            open(p, 'w', encoding='utf-8').write('\n'.join(lines))
        self.status.setText('Saved ' + p)

    def load_history(self, pairs):
        """Resume a saved conversation. The data context is re-attached to the first question on the next send."""
        self.history = []; self.view.clear(); self._resume = list(pairs)
        self.view.append("<p style='color:#52514e'><i>Earlier conversation loaded. Your next question continues it with the current data range attached.</i></p>")
        for m in pairs: self._append('You' if m['role'] == 'user' else 'Claude', m['content'])
        self.status.setText(f'Loaded {len(pairs) // 2} earlier question(s). Your next question continues this conversation with the current data range attached.')

    def _tick(self):
        if self._t0: self.status.setText(f'Waiting for Claude... {int((dt.datetime.now() - self._t0).total_seconds())} s  (a long answer can take 30 to 60 s)')
    def _start_worker(self, messages, msg):
        self._t0 = dt.datetime.now(); self.timer.start(); self.send.setEnabled(False); self.status.setText(msg)
        sysmsg = SYSTEM + (f'\nAbout the user, in their words: {self.about.text().strip()}\n' if self.about.text().strip() else '')
        self.worker = AskWorker(self.key.text().strip(), self.model.text().strip() or DEFAULT_MODEL, sysmsg, messages)
        self.worker.done.connect(self._answer); self.worker.failed.connect(self._fail); self.worker.start()
    def test_connection(self):
        if not self.key.text().strip(): self.status.setText('Enter an API key first.'); return
        if self.worker and self.worker.isRunning(): return
        self._test = True; self._start_worker(None, 'Testing key and connection...')

    def _answer(self, text):
        self.timer.stop(); self._t0 = None
        if getattr(self, '_test', False):
            self._test = False; self._append('Connection test', text); self.send.setEnabled(True); self.status.setText(''); return
        self.history.append({'role': 'assistant', 'content': text}); self._append('Claude', text); self.send.setEnabled(True); self.status.setText('')
        if self.autosave.isChecked():
            q = self.history[-2]['content']; q = q.split('QUESTION: ', 1)[-1] if q.startswith('CONTEXT') else q
            self._log_pair(q, text)
    def _fail(self, msg):
        self.timer.stop(); self._t0 = None
        if getattr(self, '_test', False): self._test = False
        elif self.history and self.history[-1]['role'] == 'user': self.history.pop()
        self.view.append(f"<p style='margin-top:10px'><b style='color:{C_ERR}'>Error</b><br>{html.escape(msg)}</p>"); self.send.setEnabled(True); self.status.setText('Not answered. See the error above; details also in ask_log.txt in the SleepScope folder.')
