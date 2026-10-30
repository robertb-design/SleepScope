@echo off
rem Builds a shareable Windows package: dist\SleepScope\SleepScope.exe plus SleepScope-Windows-x64.zip next to this file.
rem Run install.bat first. Takes 3 to 6 minutes. The zip is about 150 MB.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run install.bat first. & pause & exit /b 1)
echo Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install --quiet pyinstaller
echo Building (this takes a few minutes)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean SleepScope.spec
if errorlevel 1 (echo Build failed. & pause & exit /b 1)
copy /y README.md dist\SleepScope\README.md >nul
echo Zipping...
if exist SleepScope-Windows-x64.zip del SleepScope-Windows-x64.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\SleepScope\*' -DestinationPath 'SleepScope-Windows-x64.zip' -CompressionLevel Optimal"
echo.
echo Done. Share SleepScope-Windows-x64.zip. Recipients unzip it anywhere and double-click SleepScope.exe. No Python needed.
pause
