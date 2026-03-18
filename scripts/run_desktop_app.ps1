$ErrorActionPreference = "Stop"

param(
  [string]$MidiIn = "fl-agent 0",
  [string]$MidiOut = "fl-agent 1",
  [string]$FlPath = "C:\\Program Files\\Image-Line\\FL Studio 2025\\FL64.exe"
)

& "$PSScriptRoot\\..\\.venv\\Scripts\\python.exe" -m pip show PySide6 *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing UI dependencies (PySide6)..." -ForegroundColor Yellow
  & "$PSScriptRoot\\..\\.venv\\Scripts\\python.exe" -m pip install -e "$PSScriptRoot\\..\\.[ui]"
}

& "$PSScriptRoot\\..\\.venv\\Scripts\\python.exe" -m fl_agent_desktop.main --midi-in $MidiIn --midi-out $MidiOut --fl-path $FlPath

