# Changelog

## v0.1.0 - MVP

### Added

- MCP server for FL Studio control over SysEx / MIDI bridge.
- FL Studio bridge script for controller-side message handling.
- Drum-loop creation flow with basic style rendering.
- Optional desktop UI with BPM / bars / style controls, prompt preview, and pattern preview.
- Optional Ollama-assisted planning path for the desktop app and CLI agent.
- Template channel mapping via `fl_agent_config.json`.

### Notes

- The canonical dependency definitions live in `pyproject.toml`.
- Convenience install files are available as `requirements.txt` and `requirements-ui.txt`.
