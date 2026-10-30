# SleepScope

Desktop analysis for ResMed AirSense 10 / 11 SD card data. Reads the raw EDF files, re-scores events from the 25 Hz flow
signal, and shows the machine's scoring next to its own.

## Try it without a card
**Load sample data** on the toolbar generates seven nights for an imaginary patient in ResMed's file format (synthetic, no real person).

## Install (Windows)
1. Unzip this folder somewhere permanent (for example `C:\SleepScope`).
2. Double-click `install.bat`. It installs Python from python.org if missing, sets up a private environment, checks it, and puts a shortcut on the desktop. It writes `install_log.txt` next to itself; if anything fails, that file says why.
3. Double-click `SleepScope.bat` (or the shortcut). Click **Open SD card…** and pick the card root (the drive letter, e.g. `F:\`)
   or its `DATALOG` folder. The last folder reopens automatically next time.

## Sharing with others (no Python needed on their PC)
Run `build_exe.bat` once (after install.bat). It packages Python, the libraries and the app into `dist\SleepScope\SleepScope.exe` and zips
that folder as `SleepScope-Windows-x64.zip` (about 150 MB). Send the zip; recipients unzip it anywhere and double-click `SleepScope.exe`.
Windows SmartScreen will warn the first time because the exe is not code-signed: click "More info", then "Run anyway".
Ready-made downloads: https://github.com/robertb-design/sleepscope/releases (built automatically by GitHub on every update).

## Tabs
- **Start here** a home screen with six numbered, colour coded step cards (get data in, read the synopsis, see the picture, connect Claude, add an oximeter, add Apple Health) that show what is done and open the right place.
- **How to use** the full step by step setup: what you need (card reader), installing, getting the card into the PC, opening it, reading results, Claude API key, oximeter, Apple Health, routine, the numbers in plain words, troubleshooting.
- **Overview** usage, AHI (machine vs app), event mix, pressure band, leak, flow limitation, breathing, SpO2 when present. Click a bar to open the night.
- **Night** stacked panels, all time linked: flow (25 Hz), pressure (set, mask, EPR), leak, flow limitation and snore, ventilation ratio,
  RR, tidal volume, minute ventilation, SpO2 and pulse. Drag the top strip or use the zoom buttons. Mouse wheel zooms, drag pans.
  Machine events are solid bands, app events are lighter bands. Hover shows every channel value at the cursor. Panels menu picks what to show.
- **Events** every machine and app event for the night with pressure, mask pressure, leak and flow limitation at onset. Double click to jump to it.
- **Breaths** histograms of Ti, Te, I:E, PIF, PIF/PEF, tidal volume, plateau ratio, breath rate; events plotted against the pressure they happened at.
- **Statistics** the full per-night table (export to CSV).
- **Device and settings** identification, and the STR.edf daily summary (settings, machine AHI, leak percentiles) when the card root is opened.
- **Methods** what each number means and how far to trust it.

## 3D Landscape
One strip of terrain per night, evening on the left, newest at the front. Height is how freely you breathed (green plateau good, red craters are
closed airway), grey is mask off, blue pools are large leak, pillars are the machine's events, the white line is pressure. Drag to rotate, wheel to zoom,
preset views on the buttons. Meant for reading a week at a glance without the vocabulary.
With Apple Health imported, a flat ribbon in front of each strip shows the Watch's sleep stages (deep, core, REM, awake, in bed) across the whole
night, a red line above it is heart rate, and dots are Watch SpO2 readings (red when under 90%). Ribbon over grey floor is sleep with the mask off.

## Synopsis
Pick a date range (or Last 7 / 14 / 30 / All) and the tab writes a plain English report: usage, event control, event mix, central apnea and periodic
breathing checks, settings changes and how AHI and flow limitation behaved under each, leak, breathing mechanics, oxygen (when an oximeter is attached),
Apple Watch sleep (when imported), and a short "what this means" list. Enter your diagnostic AHI from the sleep study to get the percent reduction.
Copy or save as HTML to send to the prescriber.

## Ask Claude
A chat panel that sends your question plus the synopsis, statistics table and event list for a date range to the Claude API and shows the answer.
Needs an API key from console.anthropic.com (billed per use, separate from a claude.ai subscription; a question with a month of context is a few cents).
The key is stored on this PC only. Nothing leaves the PC until you press Send. The model name is editable for when newer models ship.
Every answer is appended to a dated Markdown file (`claude_answers_YYYY-MM-DD.md`) in the folder shown on the second row, by default
`Documents\SleepScope`. Browse to change it, or **Use SD card** to keep the notes in a `SleepScope_Notes` folder on the card.
**Save conversation…** writes the whole exchange as Markdown, text or HTML.
When the app starts, the most recent saved conversation is shown in the window, ready to continue; the **Earlier** dropdown brings any saved
conversation back into the same window.

## Saved answers
Lists every file the Ask Claude tab has written (PC folder and, when present, SleepScope_Notes on the card), newest first, and shows the
questions and Claude's answers. Search filters by any word. **Continue in Ask Claude** reloads a file's exchange into the chat so you can keep going.

## Apple Health
On the iPhone: Health app, profile picture (top right), Export All Health Data. AirDrop or email the export.zip to the PC, then
**Import Apple Health export…**. The file can be several hundred MB; the import streams it and takes a minute or two.
The O2Ring's ViHealth app can sync its readings to Apple Health, so once the ring is in use the Watch SpO2 and ring SpO2 both appear.
Writing CPAP data into Apple Health is not possible from a Windows app; that direction needs an iOS app.

## Oximeter
Import a Wellue O2Ring / Checkme CSV export with **Import oximeter CSV…**. Readings are matched to sessions by timestamp and
SpO2, pulse, ODI, min SpO2 and time under 90% are added to every view.

## Notes
- ResMed stamps the END of each event in the EVE file. SleepScope subtracts the duration so markers sit on the pause.
- App hypopneas are flow only (30% reduction for 10 s) and over-count relative to a lab score that needs a desaturation or arousal.
- Not a medical device.
