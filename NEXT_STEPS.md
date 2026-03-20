# Next Steps (v0.2 focus)

This repo already works end-to-end on the current test setup:

- FL Studio bridge script is loaded and reachable via loopMIDI.
- SysEx RPC works through MCP server <-> FL bridge round-trips.
- Desktop app supports prompt preview, BPM/bars/style controls, pattern preview, and optional Ollama parsing.
- Template channel mapping via `fl_agent_config.json` is already integrated.

## Quick start (test system)

1. Start loopMIDI and ensure these ports are available:
   - `fl-agent` (single-port setup), or
   - `fl-agent 0` + `fl-agent 1` (recommended split in/out setup)
2. If Python cannot see virtual ports, restart Windows MIDI service (Admin PowerShell):
   - `Stop-Service midisrv -Force`
   - `Start-Service midisrv`
3. Start FL Studio and assign the controller script:
   - `Options -> MIDI settings`
   - Enable input device for `fl-agent*`
   - Controller type: `FL Studio Agent (MCP Bridge)`
   - Enable output for the same loopMIDI pair/port
4. Run desktop app:
   - `D:\Coding\Projekte\fl-studio_agent\scripts\run_desktop_app.ps1`
5. Optional Ollama mode:
   - `Use Ollama` enabled
   - Model: `gemma3:4b`
   - URL: `http://localhost:11434/api/chat`

Example prompt:
- `Oeffne FL Studio und erstelle einen 4/4 Drumloop in 94 BPM (hiphop)`

## Local mapping reference

Local config (not committed):
- `fl_agent_config.json`

Typical 1-based template mapping:
- Kick = 1
- Clap = 2
- HiHat = 3
- Snare = 4
- Bass = 5

Note: app/server converts to 0-based indices internally.

## Priority plan (next implementation)

For broader backlog items, keep `TODO.md` as source of truth. This list is the practical build order.

### 1) Stabilize runtime and errors

- Status: done on 2026-03-19.
- Done: configurable RPC timeouts via CLI (`--rpc-timeout`, `--rpc-timeout-loop`) and structured server error payloads (`error` + `error_detail`).
- Done: FL bridge `OnIdle` now guards chunk cleanup and IPC processing with throttled error logging.
- Done: MIDI client now attempts reconnect on stream interruption and send failures.
- Done: optional rotating file logs added for MCP server and FL bridge troubleshooting.

### 2) Transport and safety controls

- Status: done on 2026-03-19 (pending runtime verification in FL Studio).
- Done: MCP tools added for transport (`fl_transport`, `fl_play`, `fl_stop`, `fl_record`) plus `fl_panic`.
- Done: desktop UI now has `Play`, `Stop`, `Record`, and wired `Stop / Panic`.
- Done: panic path is best-effort and resilient to delayed/missing RPC responses (short timeouts + partial-success handling).

### 3) Musical bass upgrade

- Status: done on 2026-03-19.
- Done: parse/Ollama plan now support `key` + `scale` with fallback defaults.
- Done: deterministic bassline planner added (root/5th/octave rotation per style) with note-event preview.
- Done: optional bass mode (`step`, `step_pitch`, `piano_roll`) added.
- Done: `piano_roll` is evaluated and currently falls back to `step_pitch` in bridge due API limitations; fallback is returned as warning.

### 4) Pattern read-back and multi-pattern workflow

- Status: done on 2026-03-20.
- Done: bridge/server method added to read current step pattern state, including active step indices plus optional velocity/pitch read-back.
- Done: desktop UI now surfaces read-back and shows before/after snapshots around loop writes, plus manual refresh.
- Done: `pattern_index` support added for loop write/read flows so non-active FL patterns can be targeted explicitly.

### 5) OpenClaw / GPT-5.x connector

- Status: done on 2026-03-20.
- Done: integration baseline documented in `docs/OPENCLAW_GPT5_CONNECTOR.md`, including OpenClaw repo/docs reference, `stdio` recommendation for local MCP transport, and local `OPENAI_API_KEY` adapter process model.
- Done: local OpenAI / GPT-5.x adapter added (`clients/openai_mcp_agent.py` + `scripts/run_openai_agent.ps1`) using the same MCP tool surface via `stdio`.
