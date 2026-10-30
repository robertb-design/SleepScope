@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo SleepScope is not installed yet. Run install.bat first.
  echo If you already ran it, open install_log.txt in this folder to see what went wrong.
  pause
  exit /b 1
)
rem Install any packages added by an update (quick when nothing is missing)
".venv\Scripts\python.exe" -c "import PySide6, pyqtgraph, pyedflib, scipy, numpy, OpenGL" >nul 2>&1
if errorlevel 1 (
  echo An update added new components. Installing them, this takes a minute...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" -m sleepscope %* > app_log.txt 2>&1
if errorlevel 1 (
  echo SleepScope stopped with an error. Details:
  type app_log.txt
  pause
)
