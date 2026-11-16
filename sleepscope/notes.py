"""My notes: dated notes and context the user writes (mask change, congestion, alcohol, late night, a new medicine).

Each note is {id, date 'YYYY-MM-DD' (the night it belongs to, noon to noon like every night), text, change (bool),
updated (ms since 1970), deleted (bool)}. A note marked as a change starts a before and after comparison in the
Synopsis. Notes are read by the Synopsis, Ask Claude and the Night view.

Stored in QSettings ('sleep_notes') and in 'Sleep notes.json' in the Sleepscope folder; packed into SleepScope card.zip
as notes.json so the phone gets them. Merge keeps the newest edit of each id; deletes are kept as tombstones so they
spread too. Mirrored in docs/engine.js (SS.notes*). Pure Python here, no Qt, so the scoring side can use it.
"""
from __future__ import annotations
import json, os, time, uuid, datetime as dt
import numpy as np

FILE_NAME = 'Sleep notes.json'
CURRENT: list = []          # set by the UI; read by synopsis and the Claude context


def now_ms():
    return int(time.time() * 1000)


def new(date, text, change=False):
    return {'id': uuid.uuid4().hex[:12], 'date': str(date), 'text': text.strip(), 'change': bool(change), 'updated': now_ms(), 'deleted': False}


def merge(*lists):
    """Union by id, newest 'updated' wins. Returns the list sorted by date then time written."""
    by = {}
    for lst in lists:
        for n in lst or []:
            if not isinstance(n, dict) or not n.get('id') or not n.get('date'): continue
            o = by.get(n['id'])
            if o is None or (n.get('updated') or 0) > (o.get('updated') or 0): by[n['id']] = dict(n)
    return sorted(by.values(), key=lambda n: (n['date'], n.get('updated') or 0))


def live(notes):
    return [n for n in notes or [] if not n.get('deleted') and (n.get('text') or '').strip()]


def load_file(folder):
    try:
        with open(os.path.join(folder, FILE_NAME), encoding='utf-8') as f: j = json.load(f)
        return j.get('notes', []) if isinstance(j, dict) else j
    except Exception:
        return []


def save_file(folder, notes):
    p = os.path.join(folder, FILE_NAME); tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump({'notes': notes}, f, indent=1)
    os.replace(tmp, p)


def _d(s):
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


def for_range(notes, start, end):
    a, b = _d(start), _d(end)
    return [n for n in live(notes) if a <= _d(n['date']) <= b]


def for_night(notes, date):
    d = _d(date); return [n for n in live(notes) if _d(n['date']) == d]


def label(d):
    d = _d(d); return f"{d:%a} {d.month}/{d.day:02d}"


METRICS = [('hours', 'hours used', 1, False), ('AHI', 'machine AHI', 1, True), ('leak_95', 'leak 95th percentile L/min', 1, True),
           ('ODI', 'ODI', 1, True), ('spo2_mean', 'mean SpO2 %', 1, False), ('w_bd', 'Watch Breathing Disturbances', 1, True)]
WINDOW = 14


def compare(notes, nights, end):
    """For each change note on or before 'end': treated nights before it against nights from it on (up to 14 each side,
    nights after the change stop at 'end'). Returns a list of {note, before, after, rows:[(name, before, after)]}."""
    e = _d(end); out = []
    treated = [n for n in nights if not getattr(n, 'no_mask', False) and not getattr(n, 'summary_only', False)]
    for c in [n for n in live(notes) if n.get('change') and _d(n['date']) <= e]:
        d = _d(c['date'])
        bef = [n for n in treated if n.date < d][-WINDOW:]; aft = [n for n in treated if d <= n.date <= e][:WINDOW]
        rows = []
        for k, name, dp, _ in METRICS:
            def m(ns):
                v = [n.stats.get(k) for n in ns]; v = [x for x in v if isinstance(x, (int, float)) and np.isfinite(x)]
                return float(np.mean(v)) if v else np.nan
            a, b = m(bef), m(aft)
            if np.isfinite(a) and np.isfinite(b): rows.append((name, round(a, dp), round(b, dp)))
        out.append({'note': c, 'before': len(bef), 'after': len(aft), 'rows': rows})
    return out


def synopsis_html(notes, nights, start, end):
    """The Synopsis section: notes in range, then before and after for each change. '' when there are none."""
    inr = for_range(notes, start, end); cmp_ = [c for c in compare(notes, nights, end) if c['after'] or _d(c['note']['date']) >= _d(start)]
    if not inr and not cmp_: return ''
    H = ['<h3>Your notes</h3>']
    if inr: H.append('<ul>' + ''.join(f"<li><b>{label(n['date'])}</b>{' (change)' if n.get('change') else ''}: {_esc(n['text'])}</li>" for n in inr) + '</ul>')
    for c in cmp_:
        n = c['note']; head = f"<b>Since {label(n['date'])}</b> ({_esc(n['text'])}): "
        if not c['after']: H.append(f'<p>{head}no treated nights after the change yet.</p>'); continue
        if not c['before'] or not c['rows']: H.append(f"<p>{head}{c['after']} treated night{'s' if c['after'] != 1 else ''} since, nothing before it to compare with.</p>"); continue
        rows = '; '.join(f'{name} {b} against {a} before' for name, a, b in c['rows'])
        H.append(f"<p>{head}{c['after']} treated night{'s' if c['after'] != 1 else ''} after against {c['before']} before. {rows}.")
        H.append(' Too few nights after the change to judge; give it a week.</p>' if c['after'] < 5 else ' Enough nights to read a trend, though one setting or mask change can be masked by a cold, alcohol or a short night, so check the notes above.</p>')
    return '\n'.join(H)


def context_text(notes, nights, start, end):
    """Plain text for Claude: every note in range, every change before it, and the before and after numbers."""
    inr = for_range(notes, start, end); a = _d(start)
    earlier = [n for n in live(notes) if n.get('change') and _d(n['date']) < a]
    if not inr and not earlier: return ''
    lines = [f"{label(n['date'])}{' [change]' if n.get('change') else ''}: {' '.join(n['text'].split())}" for n in earlier + inr]
    for c in compare(notes, nights, end):
        if c['before'] and c['after'] and c['rows']:
            lines.append(f"Before and after {label(c['note']['date'])} ({c['before']} nights before, {c['after']} after): "
                         + '; '.join(f'{name} {x} then {y}' for name, x, y in c['rows']))
    return '\n'.join(lines)


def _esc(t):
    return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
