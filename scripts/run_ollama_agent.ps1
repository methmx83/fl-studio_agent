$ErrorActionPreference = "Stop"

param(
  [string]$Model = "llama3.2",
  [string]$MidiIn = "fl-agent 0",
  [string]$MidiOut = "fl-agent 1",
  [Parameter(Mandatory=$true)][string]$Request
)

& "$PSScriptRoot\\..\\.venv\\Scripts\\python.exe" "$PSScriptRoot\\..\\clients\\ollama_mcp_agent.py" `
  --model $Model `
  --midi-in $MidiIn `
  --midi-out $MidiOut `
  $Request

