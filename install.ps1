$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$log = Join-Path $root 'install_log.txt'
Start-Transcript -Path $log -Force | Out-Null
Write-Host "===== SleepScope setup =====  $(Get-Date)"
Write-Host "Folder: $root"

function Find-Python {
    # returns path to a real python.exe (3.9+), ignoring the Microsoft Store stub
    $cands = @()
    try { $p = & py -3 -c "import sys;print(sys.executable)" 2>$null; if ($p) { $cands += $p.Trim() } } catch {}
    foreach ($c in (Get-Command python -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })) { $cands += $c }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    $cands += Get-ChildItem "C:\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    $cands += Get-ChildItem "C:\Program Files\Python3*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName }
    foreach ($c in $cands | Select-Object -Unique) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        if ($c -like '*WindowsApps*') { Write-Host "Skipping Microsoft Store stub: $c"; continue }
        try {
            $v = & $c -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            if ($v -and [version]$v -ge [version]'3.9') { Write-Host "Found Python $v at $c"; return $c }
        } catch {}
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "Python not found. Downloading Python 3.12 from python.org (about 25 MB)..."
    $url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    $exe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
    } catch {
        Write-Host "Download failed: $_"
        Write-Host "Install Python 3.12 manually from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then run install.bat again."
        Stop-Transcript | Out-Null; Read-Host 'Press Enter to close'; exit 1
    }
    Write-Host "Installing Python (silent, current user only)..."
    $p = Start-Process -FilePath $exe -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_launcher=1','Include_test=0' -Wait -PassThru
    Write-Host "Installer exit code: $($p.ExitCode)"
    $py = Find-Python
    if (-not $py) {
        Write-Host "Python still not found after install. Open a new window and run install.bat again; if it still fails, send install_log.txt."
        Stop-Transcript | Out-Null; Read-Host 'Press Enter to close'; exit 1
    }
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Write-Host "Creating private environment (.venv)..."
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed (exit $LASTEXITCODE)"; Stop-Transcript | Out-Null; Read-Host 'Press Enter to close'; exit 1 }
}
$vpy = Join-Path $root '.venv\Scripts\python.exe'
Write-Host "Installing packages (first run downloads about 150 MB, give it a few minutes)..."
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "Package install failed (exit $LASTEXITCODE). Check your internet connection and run again."; Stop-Transcript | Out-Null; Read-Host 'Press Enter to close'; exit 1 }

Write-Host "Checking the installation..."
& $vpy -c "import PySide6, pyqtgraph, pyedflib, scipy, numpy; print('Libraries OK: PySide6', PySide6.__version__)"
if ($LASTEXITCODE -ne 0) { Write-Host "Import check failed."; Stop-Transcript | Out-Null; Read-Host 'Press Enter to close'; exit 1 }

try {
    $ws = New-Object -ComObject WScript.Shell
    $s = $ws.CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'SleepScope.lnk'))
    $s.TargetPath = Join-Path $root 'SleepScope.bat'; $s.WorkingDirectory = $root
    $s.IconLocation = Join-Path $root 'sleepscope\icon.ico'; $s.Save()
    Write-Host "Desktop shortcut created."
} catch { Write-Host "Shortcut not created: $_" }

Write-Host ""
Write-Host "SUCCESS. Double-click SleepScope.bat or the desktop shortcut to start."
Stop-Transcript | Out-Null
Read-Host 'Press Enter to close'
