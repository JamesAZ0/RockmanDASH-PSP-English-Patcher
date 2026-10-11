# Build the packaged patcher on Windows: the same steps as .github/workflows/release.yml.
#   powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1     ->  dist\RockmanDASH-PSP-English-Patcher.exe
# Needs, installed beforehand:
#   Python 3.10 to 3.14 (python.org installer, includes Tk). Not 3.15 yet: pyeboot has no Windows package for it.
#   With several versions installed, put 3.14 first for this window before running the script:
#     $env:Path = (Split-Path (py -3.14 -c "import sys; print(sys.executable)")) + ";" + $env:Path
#   CMake and Visual Studio Build Tools with "Desktop development with C++"   (compiles src\atracdenc)
#   plus the individual component "C++ ATL for latest build tools (x86 & x64)": without it the compile stops at
#   "Cannot open include file: 'atlbase.h'". It must be the ATL for the compiler in use, not an older toolset's (v141).
# Python packages go into a virtual environment in build\venv.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
foreach ($p in 'python', 'cmake') {
    if (-not (Get-Command $p -ErrorAction SilentlyContinue)) { throw "missing: $p (see the top of this script)" }
}

python -m venv build\venv
& build\venv\Scripts\python.exe -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE) { throw 'pip failed' }
$py = "$root\build\venv\Scripts\python.exe"

$tag = & $py -c "import sys; sys.path.insert(0, 'tools'); import exttools; print(exttools.platform_tag())"
Write-Host "platform: $tag"
& $py -c "import sys; sys.path.insert(0, 'tools'); import exttools; print(exttools.build_atracdenc())"
if ($LASTEXITCODE) { throw 'compiling atracdenc failed' }

& $py -m PyInstaller --noconfirm packaging\patcher.spec
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
Write-Host "`ndone: $(Get-ChildItem dist\RockmanDASH-PSP-English-Patcher* | Select-Object -Expand FullName)"
