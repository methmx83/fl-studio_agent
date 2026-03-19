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

The canonical dependency definitions live in `pyproject.toml`. For users who prefer
plain requirements files, the repo also includes `requirements.txt` and
`requirements-ui.txt`.

## Install the FL bridge script

1. Copy the device script into your FL user scripts folder (FL expects a folder + INI entry):

   - Destination: `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\`
   - Folder: `device_fl_studio_agent\`
   - File: `device_fl_studio_agent\device_fl_studio_agent.py` (from `fl_bridge\device_fl_studio_agent.py`)
   - INI: `device_fl_studio_agent.ini` (minimal content: `[Ini]` + `Version=1`)

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

Alternative install (without editable mode):

```powershell
.\.venv\Scripts\python -m pip install -r .\requirements.txt
```

### Recommended on your system (separate in/out names)

```powershell
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --backend midi --midi-in "fl-agent 0" --midi-out "fl-agent 1"
```

### Channel mapping (templates)

Create `fl_agent_config.json` by copying `fl_agent_config.example.json`, then run:

```powershell
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --backend midi --midi-in "fl-agent 0" --midi-out "fl-agent 1" --config .\fl_agent_config.json
```

This lets the high-level tool `fl_create_4_4_drumloop` target your template's kick/snare/hat channels without hardcoding indices.

The config supports `template.one_based=true` if you prefer writing channels as 1..N (the app/server will subtract 1 internally).
You can also set `rpc.timeout_s` in the same config to control how long MCP waits for FL bridge responses before returning an error payload.

CLI override:

```powershell
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --backend midi --midi-in "fl-agent 0" --midi-out "fl-agent 1" --rpc-timeout 3.5
```

## Ollama agent (optional)

If you want a simple natural-language CLI that uses an Ollama model to decide which MCP tools to call:

1. Start Ollama and ensure your model is available (example model: `llama3.2`).
2. Run:

```powershell
.\scripts\run_ollama_agent.ps1 -Model llama3.2 -Request "Open FL Studio and create a 4/4 drumloop at 94 BPM"
```

This spawns the MCP server via stdio, asks Ollama for tool calls, and prints the tool results as JSON.

## Desktop app (optional)

Minimal Windows desktop UI (chat + preset buttons) that talks to the MIDI bridge directly.
It also exposes direct controls for BPM, bars, and style, plus a read-only
template-channel mapping panel loaded from `fl_agent_config.json`, and a live
pattern preview so you can see the generated step grid before sending it. Use
`Preview Prompt` to parse a text command into the controls without triggering FL.

Install deps:

```powershell
.\.venv\Scripts\python -m pip install -e .[ui]
```

Alternative install (without editable mode):

```powershell
.\.venv\Scripts\python -m pip install -r .\requirements-ui.txt
```

Run:

```powershell
.\scripts\run_desktop_app.ps1
```

### LLM mode (Ollama)

The desktop app can optionally use an Ollama model to turn text into a small execution plan. Enable `Use Ollama` and set:

- Model: `gemma3:4b` (works on small GPUs)
- URL: `http://localhost:11434/api/chat`

If Ollama fails, the app falls back to a deterministic regex parser.

### File-IPC fallback (if MIDI ports are not visible to Python)

If the system's MIDI stack doesn't expose your virtual port to the Python backend, you can use the file backend:

```powershell
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --backend file
```

This uses `%TEMP%\fl_studio_agent_ipc\in` for requests and `%TEMP%\fl_studio_agent_ipc\out` for responses. The FL bridge processes one request per `OnIdle` tick.

## Roadmap / Backlog

- `NEXT_STEPS.md` tracks the short-term build plan.
- `TODO.md` collects the broader backlog for stability, features, and repo hygiene.
- `CHANGELOG.md` tracks the current MVP milestone.

## Notes

- This project uses SysEx messages and a small custom protocol. Payloads are Base64-encoded so they stay 7-bit clean.
- The bridge is intentionally restrictive: it only exposes specific operations (no arbitrary `exec`).
- On some FL installs, Python file I/O may be restricted; if the bridge logs `ipc write test: FAILED`, use the MIDI backend instead.

## Troubleshooting MIDI ports

If the MCP server can't open the loopMIDI port and errors with something like `OSError: no ports available`, run:

```powershell
.\.venv\Scripts\python -c "import mido; print('inputs', mido.get_input_names()); print('outputs', mido.get_output_names())"
```

You should see your `fl-agent` port in **both** lists. If you don't, the Python MIDI backend can't see that virtual port on this system (often a driver / MIDI stack mismatch). In that case:

- Confirm `fl-agent` is created in loopMIDI and visible to other WinMM apps.
- If needed, create a second loopMIDI port and use a two-port setup (future update will support separate in/out names).

If your system exposes different names for input and output (e.g. `fl-agent 0` vs `fl-agent 1`), pin them explicitly:

```powershell
.\.venv\Scripts\python -m fl_studio_agent_mcp.server --backend midi --midi-in "fl-agent 0" --midi-out "fl-agent 1"
```

### Windows MIDI Service + dynamic ports (March 2026)

Windows 11 has a known issue where dynamically created ports (loopMIDI / teVirtualMIDI) are not visible unless created before the Windows MIDI service starts. A workaround is to restart the `midisrv` service after the port is created (requires Administrator). See Microsoft's known-issues post for details.
