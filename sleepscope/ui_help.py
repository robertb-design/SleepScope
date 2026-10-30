from PySide6 import QtWidgets

HELP = """
<h1>How to use SleepScope</h1>
<p>SleepScope reads the SD card from a ResMed AirSense 10 or 11 and shows you what happened every night: how long the mask was on, where the airway
narrowed or closed, how the machine responded, whether the mask leaked, and, with an oximeter or Apple Watch, what it did to your oxygen and heart rate.
Nothing leaves this PC unless you use the Ask Claude tab.</p>

<h2>0. Try it first</h2>
<p>Click <b>Load sample data</b> on the toolbar. It generates seven nights of made-up data for an imaginary patient in the machine's own file format, so every tab has something to show. Nothing about a real person is in it. When you are ready, open your own card.</p>

<h2>1. Load the card</h2>
<ol>
<li>Take the SD card out of the machine (the slot on the side; the machine keeps working without it) and put it in the PC.</li>
<li>Click <b>Open SD card…</b> and pick the drive letter (for example <b>F:\\</b>). Picking the card root rather than the DATALOG folder also loads the machine's settings file.</li>
<li>Wait for the progress bar. The app re-scores every night from the raw airflow, about a second per night.</li>
<li>Put the card back in the machine before bed. The app remembers the folder and reopens it next time.</li>
</ol>
<p>Tip: copy the whole card to a folder on the PC (for example <b>Documents\\CPAP\\2026-10</b>) now and then. Cards fill, fail and get reformatted; the copy is your history.</p>

<h2>2. Read the tabs, in the order a new user should</h2>
<table cellpadding="4">
<tr><td><b>Synopsis</b></td><td>Start here. Pick a date range and read the plain English report. It says whether the apnea is controlled, how much of your sleep is treated, whether leak or flow limitation is costing you, and what to raise with the prescriber. Enter your diagnostic AHI from the sleep study to see the percent reduction.</td></tr>
<tr><td><b>3D Landscape</b></td><td>The same week as a picture. Each strip is a night; height is how freely you breathed; red pillars are events; blue pools are leak; grey is mask off. The key on the right explains every colour. Drag to rotate.</td></tr>
<tr><td><b>Overview</b></td><td>Trend charts across nights: usage, AHI, event mix, pressure band, leak, flow limitation, breathing. Click a bar to open that night.</td></tr>
<tr><td><b>Night</b></td><td>The detail for one night: airflow at 25 samples a second, pressure, leak, flow limitation, the app's ventilation trace, breathing rate and volume, and oximeter or Watch panels when present. Use the zoom buttons or drag the strip at the top. The <b>◀ event / event ▶</b> buttons step through every event. Hover for values. <b>Panels</b> chooses what to show.</td></tr>
<tr><td><b>Events</b></td><td>Every event the machine scored and every one the app found, with pressure and leak at that moment. Double-click to see it in the Night tab.</td></tr>
<tr><td><b>Breaths</b></td><td>Breath-by-breath mechanics for the night, and a chart of events against the pressure they happened at.</td></tr>
<tr><td><b>Statistics</b></td><td>Every number for every night in one table. Export to CSV for the doctor or a spreadsheet.</td></tr>
<tr><td><b>Ask Claude</b></td><td>Ask questions about your results in plain language. Needs an API key (below). Answers are saved automatically and reappear when you reopen the app.</td></tr>
<tr><td><b>Saved answers</b></td><td>Browse and search everything Ask Claude has answered.</td></tr>
<tr><td><b>Device and settings</b></td><td>Machine model and serial, and the machine's own daily summary and settings when the card root was opened.</td></tr>
<tr><td><b>Methods</b></td><td>Exactly how every number is computed and how far to trust it.</td></tr>
</table>

<h2>3. The numbers that matter, in plain words</h2>
<ul>
<li><b>Hours.</b> The benefit tracks hours per night more than anything else. Four hours on 70% of nights is the insurer's floor; six or more is where people feel the difference.</li>
<li><b>AHI</b> (events per hour). Under 5 is controlled, under 2 is excellent. The machine's AHI counts only what it is sure of; the app's "AHI app" counts every 30% dip in airflow and is always higher. Read the app number as a ceiling.</li>
<li><b>Leak.</b> The 95th percentile should stay under 24 L/min. Above that the machine cannot hold pressure and therapy is escaping.</li>
<li><b>Flow limitation.</b> Airway narrowing short of an event. Does not count in AHI but fragments sleep. If you wake unrefreshed with a low AHI, look here.</li>
<li><b>Central apneas.</b> A few after a sigh or arousal are normal. Many, or more than half the events, is a question for the sleep doctor.</li>
<li><b>SpO2 and ODI</b> (needs an oximeter). Whether the events are dropping your oxygen. ODI under 5 and almost no time under 90% is the goal.</li>
</ul>

<h2>4. Add an oximeter</h2>
<p>A Wellue O2Ring or similar records SpO2 and pulse all night. Export its CSV from the phone app or PC software, then <b>Import oximeter CSV…</b>. Readings are matched to nights by time. The Synopsis oxygen section, the Night tab panels and the statistics fill in.</p>

<h2>5. Add Apple Health (Apple Watch)</h2>
<p>On the iPhone: Health app, profile picture top right, <b>Export All Health Data</b>. Send the export.zip to the PC (AirDrop, email, iCloud Drive), then <b>Import Apple Health export…</b>. Sleep stages, heart rate, HRV, respiratory rate and Watch SpO2 appear in the Night tab, the 3D landscape and the Synopsis. The file can be large; the import takes a minute or two. It is not remembered between launches yet, so re-import after reopening.</p>

<h2>6. Set up Ask Claude</h2>
<ol>
<li>Go to <a href="https://console.anthropic.com/">console.anthropic.com</a>, sign in, open <b>API Keys</b>, create a key (starts with sk-ant-).</li>
<li>Add a few dollars of credit under Billing. Each question with a month of data costs a few cents.</li>
<li>Paste the key into the API key box on the Ask Claude tab. Press <b>Test connection</b>; it should list the models available to the key.</li>
<li>Ask. Ctrl+Enter sends. Answers are saved to Documents\\SleepScope and shown again next time.</li>
</ol>

<h2>7. Updating</h2>
<p>Unzip a new version over the SleepScope folder and start it with <b>SleepScope.bat</b>. Anything new it needs installs itself. Your settings, key and saved answers are kept.</p>

<h2>8. If something goes wrong</h2>
<ul>
<li>Installer trouble: <b>install_log.txt</b> in the SleepScope folder says what failed.</li>
<li>The app closes or shows an error: <b>app_log.txt</b> has the details.</li>
<li>Ask Claude problems: <b>ask_log.txt</b> records every request and error; <b>Test connection</b> isolates key and network problems.</li>
<li>Empty 3D tab: the PC's graphics driver does not provide OpenGL; everything else still works.</li>
</ul>
<p><i>SleepScope is a reading of the data, not a medical device. Use it to understand what the machine is doing and to bring better questions to whoever manages your prescription.</i></p>
"""


class HelpView(QtWidgets.QTextBrowser):
    def __init__(self):
        super().__init__(); self.setOpenExternalLinks(True); self.setHtml(HELP)
        self.setStyleSheet('font-size:13px; padding:12px')
