param(
    [Parameter(Mandatory)]
    [string]$RepositoryRoot,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$launcher = Join-Path $root 'scripts\Start-Stockroom-Development.ps1'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
    throw "The selected checkout has no development launcher: $launcher"
}
$programs = [Environment]::GetFolderPath('Programs')
$shortcutPath = Join-Path $programs 'Stockroom Development.lnk'
if ($Remove) {
    Remove-Item -LiteralPath $shortcutPath -Force -ErrorAction SilentlyContinue
    Write-Host "Removed: $shortcutPath"
    exit 0
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$escapedLauncher = $launcher.Replace('"', '""')
$escapedRoot = $root.Replace('"', '""')
$shortcut.Arguments = (
    "-NoProfile -ExecutionPolicy Bypass -File `"$escapedLauncher`" " +
    "-RepositoryRoot `"$escapedRoot`""
)
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Run this Stockroom checkout with isolated hot reload.'
$icon = Join-Path $root 'app\frontend\public\favicon.ico'
if (Test-Path -LiteralPath $icon -PathType Leaf) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()
Write-Host "Installed: $shortcutPath"
