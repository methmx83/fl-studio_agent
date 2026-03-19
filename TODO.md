# FL Studio Agent — Todo Liste

## 🔧 Code-Qualität & Stabilität

### Fehlertoleranz im Bridge-Script

- `try/except` um `OnIdle`-Logik wrappen.
- Reconnect-Logik einbauen, wenn der MIDI-Port kurz verschwindet.

### Timeout-Handling im MCP-Server

- Konfigurierbares Timeout ergänzen, wenn FL keine SysEx-Antwort schickt.
- Sauberes Error-Return statt hängendem Tool-Call sicherstellen.

### Config-Validierung beim Start

- JSON-Schema für `fl_agent_config.json` definieren.
- Verständliche Fehlermeldungen bei Tippfehlern oder fehlendem Key ausgeben.

### File-Logging hinzufügen

- Rotating file logger zusätzlich zur FL-Script-Output-Konsole einbauen.
- Besonders nützlich, wenn die Desktop-App läuft und FL im Hintergrund ist.

## 🎛️ Features (nach Priorität)

### Transport-Controls

- Play / Stop / Record über MCP-Tool steuerbar machen.
- Ermöglicht echte „Starte den Loop“-Workflows.

### Pattern Read-Back

- Aktuelles Step-Sequencer-Pattern auslesen und zurückgeben.
- Agent kann prüfen, was drin ist, bevor er überschreibt.
- Live-Preview in der Desktop-UI aktualisierbar machen.

### Mixer-Control

- Volume und Pan pro Kanal setzen (`mixer.setTrackVolume` etc.).
- Grundlage für Live-Tweaking über den Agent.

### Playlist / Song-Position

- Aktuelle Position in Bars lesen und setzen.
- Befehle wie „springe zu Bar 9“ oder „loope Bars 1–4“ ermöglichen.

### Multi-Pattern-Support

- `pattern_index`-Parameter zu Drum-Loop-Tools hinzufügen.
- Mehrere Patterns befüllen und zwischen ihnen wechseln.

### Preset-System für Prompts

- `prompts.json` analog zur `fl_agent_config.json`.
- Vordefinierte Templates wie „Hiphop Boom-Bap“ oder „Techno 4-on-the-floor“ ergänzen.
- In der Desktop-UI als Dropdown anbieten.

## 📁 Repo-Hygiene

### GitHub Topics setzen

- `fl-studio`
- `midi`
- `mcp`
- `music-production`
- `python`

### `CHANGELOG.md` anlegen

- Aktuelle Features als `v0.1` / MVP dokumentieren.

### Dependencies klarer kommunizieren

- Im README explizit erwähnen, dass `pyproject.toml` die Deps enthält.
- Optional `requirements.txt` für User ergänzen, die kein `pip install -e .` kennen.
