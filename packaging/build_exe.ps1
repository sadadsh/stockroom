# Build the portable Stockroom.exe on Windows (M9e). Run from anywhere:
#   powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
#
# Prereqs on the BUILD machine: git + uv (https://astral.sh/uv). PyInstaller is pulled on the
# fly via `uv run --with`. Output: dist\Stockroom.exe (a portable, single-file launcher).
$ErrorActionPreference = "Stop"
$repo = Resolve-Path "$PSScriptRoot\.."
Push-Location $repo
try {
    Write-Host "Building the Stockroom launcher exe with PyInstaller..."
    uv run --with pyinstaller pyinstaller `
        packaging\stockroom.spec `
        --noconfirm --clean `
        --distpath dist `
        --workpath build\pyinstaller
    Write-Host "Done: $repo\dist\Stockroom.exe"
}
finally {
    Pop-Location
}
