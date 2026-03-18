# FL Studio Agent (MCP)

MCP server + FL Studio MIDI Scripting bridge for controlling FL Studio 2025.x on Windows via a loopMIDI port.

## What this does (MVP)

- `ping`: round-trip test MCP -> SysEx -> FL -> SysEx -> MCP
- `set_tempo`: set FL Studio tempo in BPM
- `create_drum_loop`: program a simple 4/4 step-sequencer drum loop (Kick/Snare/Hat) on the first channels

## Requirements

- Windows 11
- FL Studio **25.2.5**
- loopMIDI installed, port name: `fl-agent`
- Python 3.11+ on the machine running the MCP server

## Install the FL bridge script

1. Copy the device script into your FL user scripts folder:

   - Destination: `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\`
   - File: `device_fl_studio_agent.py` (from `fl_bridge\device_fl_studio_agent.py`)

   Or run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\install_fl_bridge.ps1
   ```

2. In FL Studio:
   - Open `Options -> MIDI settings`
   - Enable the input device for your loopMIDI port `fl-agent`
   - Set **Controller type** to `FL Studio Agent (MCP Bridge)`
   - Set the **Output** port number to the same value as the **Input** port number (two-way communication)
   - Enable the output device for `fl-agent` as well (same port number)
   - Open `View -> Script output` to see bridge logs

## Run the MCP server

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -U pip
.\.venv\Scripts\python -m pip install -e .
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --midi-port "fl-agent"
```

## Notes

- This project uses SysEx messages and a small custom protocol. Payloads are Base64-encoded so they stay 7-bit clean.
- The bridge is intentionally restrictive: it only exposes specific operations (no arbitrary `exec`).

