# Next Steps (Tomorrow)

This repo already works end-to-end on the test system:

- FL Studio bridge (MIDI controller script) is loaded
- SysEx RPC works via loopMIDI
- Desktop app can parse text via Ollama and program drums (and simple bass rhythm) into the step sequencer

## Quick start (test system)

1. Start loopMIDI and ensure the port exists:
   - `fl-agent`

2. If Python can't see the MIDI ports, restart the Windows MIDI service (Admin PowerShell):
   - `Stop-Service midisrv -Force`
   - `Start-Service midisrv`

3. Start FL Studio and assign the controller script:
   - `Options -> MIDI settings`
   - Input device: `fl-agent` enabled
   - Controller type: `FL Studio Agent (MCP Bridge)`

4. Run the desktop app:
   - `D:\Coding\Projekte\fl-studio_agent\scripts\run_desktop_app.ps1`

5. Enable Ollama mode (optional):
   - Check `Use Ollama`
   - Model: `gemma3:4b`
   - URL: `http://localhost:11434/api/chat`

Example prompt:
- `Öffne FL Studio und erstelle einen 4/4 Drumloop in 94 BPM (hiphop)`

## Template channel mapping

Local config (not committed):
- `fl_agent_config.json`

Current mapping (1-based as musicians count channels):
- Kick = 1
- Clap = 2
- HiHat = 3
- Snare = 4
- Bass = 5

The app/server converts to 0-based internally.

## What to build next

### 1) Make the desktop UI “musician-friendly”

- Show current config mapping in UI (Kick/Clap/Hat/Snare/Bass).
- Add UI controls for BPM, bars, style dropdown.
- Add “Stop / Panic” (future: transport stop + clear pattern).

### 2) Make the “bass” musical (not only rhythm)

Right now bass is only step-triggered. Next upgrade:
- Ask for `key` and `scale` (or detect from prompt).
- Add a simple bassline generator (root/5th patterns).
- If feasible with FL API: write actual notes to Piano Roll / channel (otherwise keep step-seq rhythm).

### 3) OpenClaw / GPT-5.3 integration (main workstation)

When you’re ready, provide:
- the OpenClaw repo/docs link
- how you want to run MCP (stdio vs http)

Then we can add a connector so GPT-5.3 can drive the same MCP tools.
