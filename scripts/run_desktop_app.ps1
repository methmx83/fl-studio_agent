param(
  [string]$MidiIn = "fl-agent 0"
  ,
  [string]$MidiOut = "fl-agent 1"
  ,
  [string]$FlPath = "C:\\Program Files\\Image-Line\\FL Studio 2025\\FL64.exe"
  ,
  [string]$Config = "fl_agent_config.json"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$py = Join-Path $repoRoot ".venv\\Scripts\\python.exe"

Push-Location $repoRoot
try {
  $oldPref = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  & $py -c "import PySide6" 1>$null 2>$null
  $ErrorActionPreference = $oldPref
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing UI dependencies (PySide6)..." -ForegroundColor Yellow
    & $py -m pip install -e ".[ui]"
  }

  & $py -m fl_agent_desktop.main --midi-in $MidiIn --midi-out $MidiOut --fl-path $FlPath --config $Config
}
finally {
  Pop-Location
}
