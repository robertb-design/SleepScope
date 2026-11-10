"""Update tab: the morning routine for bringing last night's data in. Same steps as the phone's Update page (docs/index.html, p-update)."""
import datetime
from PySide6 import QtWidgets

STYLE = """<style> h1{color:#1baf7a} h2{color:#2a78d6; margin-top:18px} .box{background:#eef4fc; border-left:5px solid #2a78d6; padding:8px 12px; margin:8px 0}
.today{background:#fff4d6; border-left:5px solid #eda100; padding:8px 12px; margin:8px 0} li{margin:4px 0} </style>"""

STEPS = [
    ('Ring', 'Every morning',
     'Plug the ring into the PC, open <b>O2 Insight Pro</b>, click <b>Download</b>. '
     'Or from the phone: <b>ViHealth</b>, open last night, <b>Share</b>, <b>CSV</b>, save to the <b>Dropbox \\ Sleepscope</b> folder.'),
    ('Watch', 'Sundays',
     'iPhone <b>Health</b> app, tap your profile picture, <b>Export All Health Data</b>, '
     'save <b>export.zip</b> to the <b>Dropbox \\ Sleepscope</b> folder, replacing the old one.'),
    ('PC', 'Every morning',
     'Card in, open <b>SleepScope</b>, click <b>Open SD card</b> and pick the card drive (for example <b>F:</b>). '
     'This also writes <b>SleepScope card.zip</b> to Dropbox for the phone. Then put the card back in the AirSense.'),
    ('Phone', 'Every morning',
     'Open <b>SleepScope</b>, tap <b>Choose zip or files</b>, then <b>Dropbox \\ Sleepscope \\ SleepScope card.zip</b>.'),
]
TONIGHT = 'Tonight: wear the Watch to bed, ring on, card in the machine.'


def update_html(today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    sunday = today.weekday() == 6
    out = [STYLE, '<h1>Good morning. Bring last night in.</h1>',
           '<p>Four steps, in order. The ring and Watch files land in Dropbox first so the PC finds them when the card is opened.</p>']
    if sunday:
        out.append('<div class="today"><b>Today is Sunday:</b> do the Watch export (step 2) as well.</div>')
    out.append('<ol>')
    for name, when, text in STEPS:
        skip = when == 'Sundays' and not sunday
        style = ' style="color:#8a8985"' if skip else ''
        note = ' (not today)' if skip else ''
        out.append(f'<li{style}><b>{name}</b> <i>({when}{note})</i><br>{text}</li>')
    out.append('</ol>')
    out.append(f'<div class="box"><b>{TONIGHT}</b></div>')
    out.append('<p style="color:#8a8985">The card must go back in the machine before bed or tonight is not recorded. '
               'The phone keeps the last zip it loaded, so step 4 is only needed when you want the new nights there.</p>')
    return ''.join(out)


class UpdateView(QtWidgets.QTextBrowser):
    def __init__(self):
        super().__init__(); self.setOpenExternalLinks(True); self.setStyleSheet('font-size:13px; padding:12px'); self.refresh()

    def refresh(self):
        self.setHtml(update_html())
