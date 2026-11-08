from PySide6 import QtWidgets

HELP = """
<style> h1{color:#1d4f91} h2{color:#2a78d6; margin-top:22px} .box{background:#eef4fc; border-left:5px solid #2a78d6; padding:8px 12px; margin:8px 0} td{vertical-align:top; padding:4px 8px} </style>
<h1>Setting up the whole system, step by step</h1>
<p>Follow these in order. Steps 1 to 4 get you reading your own data. Steps 5 to 7 add the oximeter, Apple Watch and Claude. Each step says exactly what to click.</p>

<h2>What you need</h2>
<table>
<tr><td><b>Required</b></td><td>A ResMed AirSense 10 or 11 (AutoSet, Elite or CPAP) with its SD card. A Windows 10 or 11 PC. A way to read the card: most laptops have an SD slot; if yours does not, any USB SD card reader (about $10) works. The card is a normal full-size SD card.</td></tr>
<tr><td><b>Optional</b></td><td>A recording pulse oximeter (Wellue O2Ring or similar). An Apple Watch with the iPhone Health app. An Anthropic API key for the Ask Claude tab.</td></tr>
</table>

<h2>Step 1. Install SleepScope</h2>
<ol>
<li>Download <b>SleepScope-Setup.exe</b> from github.com/robertb-design/SleepScope/releases/latest.</li>
<li>Double-click it. The first time, Windows SmartScreen shows "Windows protected your PC" because the file is not code-signed. Click <b>More info</b>, then <b>Run anyway</b>. This happens once.</li>
<li>Click through the installer, leaving <b>Create a desktop shortcut</b> ticked. It installs for your user only, so no administrator password is needed, and it appears in Settings, Apps, Installed apps like any other program.</li>
<li>Start SleepScope from the desktop shortcut or the Start menu.</li>
<li>Prefer no installer? <b>SleepScope-Windows-x64.zip</b> on the same page is the portable version: extract it to a permanent folder and double-click SleepScope.exe.</li>
</ol>
<div class="box">Running from source instead (the folder with SleepScope.bat): double-click <b>install.bat</b> once, then <b>SleepScope.bat</b> to start.</div>

<h2>Step 2. Get the card into the PC</h2>
<ol>
<li>Turn the machine's display on and wait until it is idle (not running therapy).</li>
<li>Open the SD card door on the side of the machine and press the card in gently; it springs out. The machine keeps working without it.</li>
<li>Put the card in the PC's slot or the USB reader. Windows shows it as a drive letter, usually D:, E: or F:. If a window pops up asking what to do with the drive, close it.</li>
<li>Leave the card write-protect switch (small slider on the side of the card) in the unlocked position; the machine needs to write to it later.</li>
</ol>
<div class="box"><b>Put the card back before bed.</b> The machine records therapy data only when the card is in. The card holds about a year of detailed data; the app reads everything on it each time.</div>

<h2>Step 3. Open the card in SleepScope</h2>
<ol>
<li>Click <b>Open SD card…</b> on the toolbar (top left).</li>
<li>In the folder picker, click the card's drive letter (for example <b>F:\\</b>) and click <b>Select Folder</b>. Pick the drive itself, not the DATALOG folder inside it, so the machine's settings file is read too.</li>
<li>Watch the progress bar at the bottom right. The app re-scores every night from the raw airflow; expect a second or two per night.</li>
<li>When it finishes, the <b>Synopsis</b> tab opens. The night list on the left shows every night found. The app remembers the folder and reopens it next time.</li>
</ol>
<div class="box">No card handy? Click <b>Load sample data</b> to generate seven nights for an imaginary patient and try every tab. Click <b>Close data</b> to clear it again.</div>

<h2>Step 4. Read your results</h2>
<ol>
<li><b>Synopsis</b>: pick a date range (Last 7, Last 14, Last 30 or All) and read. It covers hours used, event control, event mix, settings changes, leak, flow limitation, breathing, oxygen and what to raise with the prescriber. Type your diagnostic AHI from the sleep study into the box to see the percent reduction. <b>Save HTML</b> or <b>Copy</b> to hand it to the doctor.</li>
<li><b>3D Landscape</b>: the week as terrain. Height is how freely you breathed; red pillars are events; blue pools are leak; grey is mask off. The key on the right explains each colour. Click any pillar, pool or patch of ground and a box explains it in plain language. Drag to rotate, wheel to zoom.</li>
<li><b>Night</b>: click a night on the left. Use <b>◀ event / event ▶</b> to jump between events, the zoom buttons for 30 s to a whole night, and hover for every value at the cursor.</li>
<li><b>Statistics</b>: every number for every night; <b>Export statistics CSV</b> for a spreadsheet.</li>
</ol>

<h2>Step 5. Connect Claude (Ask Claude tab)</h2>
<ol>
<li>In a browser go to <b>console.anthropic.com</b> and sign in or create an account. This is the developer console, separate from a claude.ai chat subscription.</li>
<li>Open <b>Billing</b> (left menu) and add credit, $5 is plenty to start. Each question with a month of data attached costs a few cents.</li>
<li>Open <b>API Keys</b>, click <b>Create Key</b>, give it any name, and copy the key. It starts with <b>sk-ant-</b> and is shown only once; if you lose it, create another.</li>
<li>In SleepScope, open the <b>Ask Claude</b> tab and paste the key into the <b>API key</b> box (top left). It is saved on this PC only.</li>
<li>Click <b>Test connection</b>. You should see "Connection OK" and a list of models. If you see "invalid x-api-key" the paste was incomplete; if "credit balance", go back to Billing.</li>
<li>Optional: fill in <b>About me</b> (third row) with a line about yourself, for example age, when you were diagnosed, your diagnostic AHI, and how you like answers. It is sent with each question so answers fit you.</li>
<li>As soon as the key is saved, the <b>Synopsis</b> tab fills its right hand pane with Claude's own reading of your data, and does so again whenever new data loads (switch off with the "Automatic when data loads" box if you prefer to press <b>Ask Claude now</b> yourself). The same data is never sent twice.</li>
<li>Type a question and press <b>Send</b> (or Ctrl+Enter). Answers appear in the window and are saved to Documents\\SleepScope. They are shown again next time you open the app, and the <b>Earlier</b> list brings back any saved conversation.</li>
</ol>

<h2>Step 6. Add an oximeter (optional)</h2>
<ol>
<li>Wear the ring every night with the CPAP. Charge it during the day.</li>
<li>In the ring's phone app (ViHealth for Wellue), open the night, choose export or share, and pick <b>CSV</b>. Send the file to the PC (email it to yourself, AirDrop, or the app's PC software).</li>
<li>Save the CSV into a folder SleepScope watches: the SD card itself, your Dropbox or OneDrive folder, Downloads, or any folder you choose with <b>Companion folder…</b> on the toolbar. Every time a card is loaded, SleepScope finds the ring files there on its own and attaches them by time; the status bar at the bottom reports how many. <b>Import oximeter CSV…</b> is still there for a file somewhere else.</li>
<li><b>O2 Insight Pro (ring by USB cable).</b> In O2 Insight Pro set the data folder (File, Settings) to Dropbox\\R Barmore\\Sleepscope\\O2 or any folder beside your card. After you click Download there, SleepScope reads the ring's own files directly on the next Open SD card or Reload; no CSV export needed.</li>
<li><b>Phone copy.</b> Each time a card is opened, SleepScope saves <b>SleepScope card.zip</b> (the last 45 nights) in Dropbox\\SleepScope, or the folder chosen under <b>Phone copy…</b> on the toolbar. The iPhone app opens that file from Dropbox, so the phone never needs to read the SD card. It also carries the ring CSVs it found, so the phone gets everything in one file. If you already have a folder named Sleepscope in Dropbox (including inside your own folder in a team Dropbox), that is the one it uses.</li>
<li>Look at the Synopsis oxygen section, the SpO2 and pulse panels in the Night tab, and the SpO2 columns in Statistics.</li>
</ol>

<h2>Step 7. Add Apple Watch sleep (optional)</h2>
<ol>
<li>Wear the Watch to bed with Sleep tracking on (Watch app, Sleep). Breathing Disturbances fill in on their own on a Series 9, Ultra 2 or later.</li>
<li>On the iPhone open the <b>Health</b> app, tap your profile picture (top right), scroll down and tap <b>Export All Health Data</b>, then <b>Export</b>. Save <b>export.zip</b> to <b>Dropbox, Sleepscope</b>. Unzipped is fine too; SleepScope reads either.</li>
<li>That is all. Every Open SD card or Reload finds the newest export in the Sleepscope folder, matches it to each night, and packs the Watch nights into SleepScope card.zip so the phone shows them too. <b>Import Apple Health…</b> still works for a file kept somewhere else.</li>
<li>What you get: <b>Watch BD</b> (Breathing Disturbances per hour) beside the machine AHI, <b>Mask on % of sleep</b> (how much of the Watch's sleep happened with the mask on, minute by minute), Watch asleep hours, deep plus REM minutes, HRV and breathing rate. They show in the Statistics table, the Night tab, the 3D ribbon and the Synopsis.</li>
<li>How to read it: the Watch measures wrist motion, not airflow, so its Breathing Disturbances will not match the machine AHI exactly. Use it as a trend, and as the only check on nights the mask comes off. Mask on % below 90 means untreated sleep; that is the first thing to fix.</li>
<li>Export again every week or two; each export replaces the last.</li>
</ol>

<h2>Step 8. Routine</h2>
<ol>
<li>Each morning (or each week): card out, into the PC, click <b>Reload</b> (or Open SD card if it is a different folder), read the Synopsis, card back in the machine.</li>
<li>Copy the whole card to a folder on the PC every month or so (for example Documents\\CPAP\\2026-10). Cards fail and get reformatted; the copy is your history.</li>
<li>Updates: each time SleepScope opens it checks for a newer version and, if there is one, installs it by itself: a progress bar shows for a few seconds, then it closes, updates and opens again, keeping your settings, key and saved answers. Press <b>Cancel</b> on the progress bar to skip it until the next start. <b>Check for updates</b> in the toolbar does the same on demand. The portable zip version asks instead, since it is not installed. The phone app updates itself when opened.</li>
</ol>

<h2>The numbers that matter, in plain words</h2>
<ul>
<li><b>Hours.</b> The benefit tracks hours per night more than anything else. Four hours on 70% of nights is the insurer's floor; six or more is where people feel the difference.</li>
<li><b>AHI</b> (events per hour). Under 5 is the normal range; 5 to 15 mild, 15 to 30 moderate, over 30 severe. The machine's AHI counts only what it is sure of; the app's "AHI app" counts every 30% dip in airflow and is always higher. Read the app number as a ceiling.</li>
<li><b>Leak.</b> The 95th percentile should stay under 24 L/min. Above that the machine cannot hold pressure and therapy is escaping.</li>
<li><b>Flow limitation.</b> Airway narrowing short of an event. Does not count in AHI but fragments sleep. If you wake unrefreshed with a low AHI, look here.</li>
<li><b>Central apneas.</b> A few after a sigh or arousal are normal. Many, or more than half the events, is a question for the sleep doctor.</li>
<li><b>SpO2 and ODI</b> (needs an oximeter). Whether the events are dropping your oxygen. ODI under 5 and almost no time under 90% is the goal.</li>
</ul>

<h2>If something goes wrong</h2>
<ul>
<li>The card does not appear in Windows: try another slot or reader; check the card is fully seated; a card the machine formatted is FAT32 and readable by any PC.</li>
<li>"No sessions found": you picked a folder with no DATALOG inside, or the card has only tonight's partial data. Pick the drive letter itself.</li>
<li>Installer trouble (source version): <b>install_log.txt</b> in the SleepScope folder says what failed.</li>
<li>The app closes or shows an error: <b>app_log.txt</b> has the details.</li>
<li>Ask Claude problems: <b>Test connection</b> isolates key and network problems; <b>ask_log.txt</b> records every request.</li>
<li>Empty 3D tab: the PC's graphics driver does not provide OpenGL; everything else still works.</li>
</ul>
<p><i>SleepScope is a reading of the data, not a medical device. Use it to understand what the machine is doing and to bring better questions to whoever manages your prescription.</i></p>
"""


class HelpView(QtWidgets.QTextBrowser):
    def __init__(self):
        super().__init__(); self.setOpenExternalLinks(True); self.setHtml(HELP)
        self.setStyleSheet('font-size:13px; padding:12px')
