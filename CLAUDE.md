# SleepScope: project brief for Claude

Read this first. It is the working memory of the project: what exists, how it fits together, the rules the
owners have set, and what is still open. Keep it current when you change something structural.

## What SleepScope is
A free tool that reads a ResMed AirSense 10/11 SD card (and optionally a Wellue O2Ring oximeter and Apple Watch
data) and explains the therapy in plain language. It is a reading of the data, not a medical device.
Owner: Robert Barmore (GitHub robertb-design). MIT license. Contributors: Robert, Ryan Barmore.

Two programs share the same scoring rules and must stay in step (parity is a hard rule):
- **Windows desktop app**: Python 3.12+, PySide6, pyqtgraph (incl. OpenGL 3D), pyedflib, numpy, scipy.
  Folder `sleepscope/`, entry `run.py` / `python -m sleepscope`.
- **Phone web app (PWA)**: plain JavaScript, Plotly, JSZip, in `docs/`. Served by GitHub Pages at
  https://robertb-design.github.io/SleepScope/ . Works offline via `docs/sw.js`.

## Releases (automatic)
- Every push to `main` runs `.github/workflows/build.yml` on Windows: stamps `sleepscope/version.py`
  (version 1.0.<run number>, build date), builds the exe with PyInstaller (`SleepScope.spec`), builds the
  installer with Inno Setup (`installer.iss`), and publishes a GitHub Release with
  `SleepScope-Setup.exe` (per user install, desktop icon, Installed apps entry) and a portable zip.
- Every push also runs `pages.yml`, which looks up the build.yml run number for the same commit, stamps
  `docs/version.js` with the same 1.0.N, and deploys the phone app. Both apps show the version in their header.
- Both apps check for a new version every time they open. Desktop: `updater.py` asks the GitHub releases API on start
  (and from the Check for updates button) and, for an installed copy, updates without asking (Cancel on the progress bar skips
  it for that session; after two attempts at the same version that did not take, or for the portable copy, it falls back to
  Install now / Later / Skip), downloads SleepScope-Setup.exe and runs it
  with /SILENT /CLOSEAPPLICATIONS; the installer restarts the app (`Check: WizardSilent`). Phone: the service worker
  is registered with updateViaCache none, checked on every open and on return to the front, and the page reloads
  once when a new worker takes over; sw.js fetches with cache no-cache.
- When you change phone files, bump the cache name in `docs/sw.js` (`sleepscope-vNN`) or phones keep the old copy.
- Latest installer: https://github.com/robertb-design/SleepScope/releases/latest

## Map of the code
Desktop (`sleepscope/`):
- `loader.py`: EDF reading, sessions and nights (noon to noon), STR.edf daily settings, summary-only nights for
  dates the card missed (`summary_nights`), oximeter import (CSV from ViHealth or O2 Insight Pro, and raw
  O2 Insight Pro files), companion file discovery (`find_companion_files`).
- `scoring.py`: breath detection, ventilation ratio, app events (apnea, hypopnea, flow limitation runs,
  large leak, periodic breathing), `annotate_events` (leak exclusion, ring confirmation of hypopneas),
  `desat_events` and ODI, `night_stats`, `STAT_COLUMNS`, settings text, `oximetry_report` (timeline for Claude).
- `apple_health.py`: Health export reader (regex stream; zip, unzipped folder or export.xml), `attach` (per night
  `night.apple`: stages, Breathing Disturbances, mask coverage of Watch sleep), `watch_fields` (the `w_*` columns), `to_sync`.
  Exports in the companion folders are found automatically (`find_companion_files`), newest wins.
- `synopsis.py`: rule based plain English synopsis for a date range.
- `explain.py`: plain language for every chart (`overview`, `night`), one line captions
  (`OVERVIEW_CAPTIONS`, `NIGHT_CAPTIONS`), column help (`COLUMN_HELP`), click explanations in 3D (`point`).
- `ui_main.py`: main window, toolbar, load worker, phone copy worker (writes `SleepScope card.zip` to the
  Dropbox Sleepscope folder), tables, tabs. `ui_night.py` (per night panels), `ui_landscape.py` (3D),
  `ui_ask.py` (Ask Claude, Anthropic Messages API; `QUICK_QUESTIONS` one click questions and `context_summary`,
  the "What Claude sees" box, mirrored by `QUICK` and `refreshAskContext` in app.js; the phone has its own Ask range, default 30 nights), `ui_notes.py`, `ui_home.py`, `ui_help.py` (How to use),
  `ui_update.py` (Update tab: the morning routine, Sunday Watch step highlighted; same text as the phone's `p-update` page),
  `branding.py` (logo, banners, About box), `updater.py` (update check and install), `theme.py`, `apple_health.py`, `sample_data.py`.

Phone (`docs/`): `engine.js` (port of loader + scoring + synopsis), `explain.js` (port of explain.py),
`app.js` (UI, file intake, IndexedDB persistence, Plotly charts, 3D, Claude), `apple.js` (Health import),
`index.html`, `sw.js`, `version.js`, `vendor/` (plotly, jszip).

## Data formats (verified on real cards and files)
- ResMed DATALOG/yyyymmdd: `*_BRP.edf` flow and pressure 25 Hz; `*_PLD.edf` 2 s channels (Leak in L/s,
  TidVol in L, FlowLim 0 to 1, Press, EprPress, MaskPress, RespRate, MinVent, Snore); `*_SA2.edf` oximetry
  (-1 when none); `*_EVE.edf` / `*_CSL.edf` EDF+ annotations stamped at the event END (onset = stamp minus
  duration). STR.edf: one record per day starting at noon; MaskOn/MaskOff carry several samples per day
  (minutes from the record start); Leak values in L/s.
- The AirSense needs FAT32. Cards formatted exFAT are re-initialised by the machine.
- Wellue O2Ring S CSV (ViHealth): `Time,Oxygen Level,Pulse Rate,Motion,O2 Reminder,PR Reminder`,
  time `22:35:18 Nov 06 2026`, `--` for no reading.
- Wellue O2Ring S CSV (O2 Insight Pro): `Time,SpO2(%),Pulse Rate(bpm),Motion,...`, time quoted
  `"10:35:18PM Nov 6, 2026"`, 255 / 65535 for no reading.
- O2 Insight Pro raw file: name yyyymmddHHMMSS (no extension, the start time), 10 byte header starting
  01 03, then 3 bytes per second (SpO2, pulse, motion; 255 = no reading), then a 48 byte footer. Verified
  second by second against ViHealth CSVs on two nights.
- Apple Health export: `export.zip` holding `apple_health_export/export.xml` (one `<Record>` per line, local times
  `2026-11-02 23:45:51 -0500`). Used types: SleepAnalysis (AsleepCore/Deep/REM, Awake, InBed; several sources, the one
  with most stage detail wins), HeartRate, OxygenSaturation (fraction), RespiratoryRate, HeartRateVariabilitySDNN, and
  `HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances` (one record per Watch night, spanning the sleep, value is a
  per hour rate although the unit says count). Verified on Robert's Ultra 2 export.
- About me: kept in `About me.txt` in the user's Sleepscope folder (their Dropbox, never the repo). The desktop takes it
  when its own field is empty or still holds the last copy it took, writes edits back, and packs it as `about.txt` in
  `SleepScope card.zip`; the phone takes `about.txt` by the same rule.
- Watch data reaches the phone as `health.json` inside `SleepScope card.zip` (desktop `apple_health.to_sync`, phone
  `AH.fromSync`), trimmed to the card's nights.

## Scoring rules that matter
- AHI (machine) comes from the machine. The app's own recount is shown beside it, never instead of it.
- App hypopneas count only when the ring confirms them (3 point SpO2 drop from the 2 min pre-event median,
  or a pulse rise of 6 bpm or more within 15 s). Without ring data they are counted and marked flow only.
- App events whose midpoint is inside a large leak run (over 24 L/min for 60 s or more) are listed but not counted.
- ODI: dips of 3 points below the median of the previous 2 min, lasting 10 s or more, per hour of oximetry,
  excluding dips within 10 s of ring motion 30 or more.
- Pressure setting column: STR.edf when present, otherwise the trace with each session's ramp (45 min) skipped,
  labelled "(trace)".
- Watch columns: `w_bd` Breathing Disturbances (shown beside the machine AHI, never instead of it), `w_cover` share of
  Watch asleep minutes overlapping machine sessions, `w_asleep`, `w_deeprem`, `w_hrv`, `w_rr`. Nights with only
  daytime Watch samples get no Watch data.
- Validation: the app detector reproduced 17 of 19 and 21 of 22 machine apneas on the two real cards tested.

## House rules (from Robert)
- Plain, clinical, tight language. No dashes in prose anywhere (use commas or restructure).
- Every chart and table gets a plain one line explanation and "what to do" guidance where it fits.
- Separate verified facts from inference; say "probable" or "guessing" when that is what it is.
- No personal health data, API keys or account details in the repository. The About me box and API key live
  in each user's own settings (QSettings on Windows, browser storage on the phone).
- Desktop and phone stay in step: a scoring or wording change lands in both.
- Ask Claude in the app uses the user's own Anthropic API key (console.anthropic.com). Default model
  `claude-sonnet-5-5`, budget 8000 tokens with one retry at 24000 if the reply came back empty.

## How to test before pushing
- Desktop, no screen: `QT_QPA_PLATFORM=offscreen python -c "..."` loading a card folder and calling
  `MainWindow.load(path)`; 3D needs `xvfb-run` with `LIBGL_ALWAYS_SOFTWARE=1 QT_QPA_PLATFORM=xcb`.
- Phone: `python -m http.server 8765` inside `docs/`, then Playwright with the iPhone 14 Pro profile; load a zip
  through `#filein` and check `nights`, `SS.nightStats`, and that there are no page errors.
- `Load sample data` in the desktop app writes a synthetic card (`sample_data.py`) for quick checks.

## Open ideas (not built yet)
- Connect Dropbox on the phone (Dropbox app key, PKCE) so the phone loads the latest zip without a file pick.
- One page doctor report export (week summary in the format a physician expects).
- Merge an archive folder with the live card so history and new nights load together.
- Apple Health: the full export route is built and automatic. The Shortcut route remains but is fiddly.
