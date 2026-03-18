$ErrorActionPreference = "Stop"

$src = Join-Path $PSScriptRoot "..\\fl_bridge\\device_fl_studio_agent.py"
$dstDir = Join-Path $env:USERPROFILE "Documents\\Image-Line\\FL Studio\\Settings\\Hardware"
$deviceFolder = Join-Path $dstDir "device_fl_studio_agent"
$dst = Join-Path $deviceFolder "device_fl_studio_agent.py"
$iniPath = Join-Path $dstDir "device_fl_studio_agent.ini"

if (!(Test-Path $src)) {
  throw "Source not found: $src"
}

New-Item -ItemType Directory -Force -Path $deviceFolder | Out-Null
Copy-Item -Force $src $dst

if (!(Test-Path $iniPath)) {
  @"
[Ini]
Version=1
"@ | Set-Content -Encoding Ascii $iniPath
}

# Remove legacy flat-file install to reduce confusion
$legacy = Join-Path $dstDir "device_fl_studio_agent.py"
if (Test-Path $legacy) {
  Remove-Item -Force $legacy
}

Write-Host "Installed bridge script to: $dst"
Write-Host "Installed INI to: $iniPath"
Write-Host "In FL Studio: Options -> MIDI settings -> set Controller type to 'FL Studio Agent (MCP Bridge)' for your loopMIDI port."

