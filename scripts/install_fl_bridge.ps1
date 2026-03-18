$ErrorActionPreference = "Stop"

$src = Join-Path $PSScriptRoot "..\\fl_bridge\\device_fl_studio_agent.py"
$dstDir = Join-Path $env:USERPROFILE "Documents\\Image-Line\\FL Studio\\Settings\\Hardware"
$dst = Join-Path $dstDir "device_fl_studio_agent.py"

if (!(Test-Path $src)) {
  throw "Source not found: $src"
}

New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
Copy-Item -Force $src $dst

Write-Host "Installed bridge script to: $dst"
Write-Host "In FL Studio: Options -> MIDI settings -> set Controller type to 'FL Studio Agent (MCP Bridge)' for your loopMIDI port."

