[CmdletBinding()]
param(
    [string]$Version = "1.0.0.0",
    [string]$OutputRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

throw @"
Standalone bootstrap executables are no longer supported. Build the native,
immutable MSIX package instead:

  .\packaging\Build-Windows-Package.ps1 -Mode Fixture -Version $Version

Production packaging requires the explicit signing and TUF trust inputs described
in packaging\README.md. This wrapper deliberately does not download Git, uv,
Node, WebView2, browsers, or mutable source.
"@
