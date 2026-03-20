$ErrorActionPreference = "Stop"

param(
  [string]$Model = "gpt-5.4",
  [string]$MidiIn = "fl-agent 0",
  [string]$MidiOut = "fl-agent 1",
  [string]$OpenAIBaseUrl = "https://api.openai.com/v1",
  [Parameter(Mandatory=$true)][string]$Request
)

& "$PSScriptRoot\\..\\.venv\\Scripts\\python.exe" "$PSScriptRoot\\..\\clients\\openai_mcp_agent.py" `
  --model $Model `
  --midi-in $MidiIn `
  --midi-out $MidiOut `
  --openai-base-url $OpenAIBaseUrl `
  $Request
