from PySide6 import QtWidgets

HELP = """
<style> h1{color:#1d4f91} h2{color:#2a78d6; margin-top:22px} .box{background:#eef4fc; border-left:5px solid #2a78d6; padding:8px 12px; margin:8px 0} td{vertical-align:top; padding:4px 8px} </style>
<h1>Setting up the whole system, step by step</h1>
<p>Follow these in order. Steps 1 to 4 get you reading your own data. Steps 5 to 8 add Claude, the oximeter, Apple Watch and your equipment. Each step says exactly what to click.</p>

<h2>What you need</h2>
<table>
<tr><td><b>Required</b></td><td>A ResMed AirSense 10 or 11 (AutoSet, Elite or CPAP) with its SD card. A Windows 10 or 11 PC. A way to read the card: most laptops have an SD slot; if yours does not, any USB SD card reader (about $10) works. The card is a normal full-size SD card.</td></tr>
<tr><td><b>Optional</b></td><td>A recording pulse oximeter (Wellue O2Ring or similar). An Apple Watch with the iPhone Health app. An Anthropic API key for the Ask Claude tab.</td></tr>
</table>

<h2>Step 1. Install SleepScope</h2>
<ol>
<li>Download <b>SleepScope-Windows-x64.zip</b> from the releases page (github.com/robertb-design/sleepscope/releases).</li>
<li>Right-click the zip, <b>Extract All</b>, and choose a permanent folder such as <b>C:\\SleepScope</b>. Do not run it from inside the zip.</li>
<li>Double-click <b>SleepScope.exe</b>. The first time, Windows SmartScreen shows "Windows protected your PC" because the file is not code-signed. Click <b>More info</b>, then <b>Run anyway</b>. This happens once.</li>
<li>Optional: right-click SleepScope.exe, Send to, Desktop (create shortcut).</li>
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
<li><b>3D Landscape</b>: the week as terrain. Height is how freely you breathed; red pillars are events; blue pools are leak; grey is mask off. The key on the right explains each colour. Drag to rotate, wheel to zoom.</li>
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
<li>In SleepScope click <b>Import oximeter CSV…</b> and pick the file. Readings are matched to nights by time.</li>
<li>Look at the Synopsis oxygen section, the SpO2 and pulse panels in the Night tab, and the SpO2 columns in Statistics.</li>
</ol>

<h2>Step 7. Add Apple Health (optional)</h2>
<ol>
<li>On the iPhone open the <b>Health</b> app, tap your profile picture (top right), scroll down and tap <b>Export All Health Data</b>, then <b>Export</b>. It takes a minute and produces <b>export.zip</b>.</li>
<li>Send export.zip to the PC (AirDrop to a Mac then to the PC, email, or save to iCloud Drive and open it on the PC).</li>
<li>In SleepScope click <b>Import Apple Health export…</b> and pick export.zip. The file can be several hundred MB; the import takes a minute or two.</li>
<li>Sleep stages, heart rate, HRV and Watch SpO2 now appear in the Night tab, on the 3D Landscape (the ribbon in front of each strip) and in the Synopsis. Re-import after each new export; it is not remembered between launches.</li>
</ol>

<h2>Step 8. Record your equipment</h2>
<ol>
<li>Open the <b>Equipment</b> tab. Pick your mask type, then brand, model and size (start typing a model to search the list, or type any model). The machine model fills in from the card.</li>
<li>Enter when you last replaced the cushion, frame, headgear, tubing, filter and water chamber. <b>Today</b> fills in today's date. Click <b>Save equipment</b>.</li>
<li>The right side shows what the data says about how you use the mask, and options worth raising with your doctor or equipment supplier, each with the pattern behind it.</li>
<li>When you change masks, set <b>New mask started on</b> to the first night with the new one before saving. The tab then compares the nights before and after.</li>
</ol>

<h2>Step 9. Routine</h2>
<ol>
<li>Each morning (or each week): card out, into the PC, click <b>Reload</b> (or Open SD card if it is a different folder), read the Synopsis, card back in the machine.</li>
<li>Before an appointment, click <b>Doctor visit PDF…</b> on the Synopsis tab and print it or bring it on your phone.</li>
<li>Copy the whole card to a folder on the PC every month or so (for example Documents\\CPAP\\2026-10). Cards fail and get reformatted; the copy is your history.</li>
<li>When a new SleepScope version is released, download the zip again and extract it over the same folder; your settings, key and saved answers are kept.</li>
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
