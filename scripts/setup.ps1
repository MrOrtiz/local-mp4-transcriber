$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64 from python.org, including Tcl/Tk and the py launcher.' }
}
& .venv/Scripts/python.exe -c "import sys,struct,tkinter; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 x64 required'"
if ($LASTEXITCODE -ne 0) { throw 'Python/Tk check failed.' }
& .venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency install failed.' }
& .venv/Scripts/python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check failed.' }
& .venv/Scripts/python.exe -m course_transcriber --diagnostics
if ($LASTEXITCODE -ne 0) { throw 'Diagnostics failed.' }
