from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from typing import Any, Callable

from fl_studio_agent_mcp.midi_transport import MidiBridgeClient
from fl_studio_agent_mcp.ollama_agent import run_ollama_mcp_agent_sync
from fl_studio_agent_mcp.patterns import normalize_key_scale, on_steps, render_with_bassline
from fl_studio_agent_mcp.server import _default_fl_path

from .pattern_preview import pattern_preview_lines
from .parse import parse_command
from .ollama import plan_with_ollama
from .stepseq_readback import format_stepseq_snapshot
from .ui_state import (
    DEFAULT_CHANNEL_MAP,
    PRESET_SETTINGS,
    STYLE_OPTIONS,
    mapping_label_text,
    resolved_loop_settings,
)


def _require_pyside() -> Any:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            "PySide6 is required for the desktop UI.\n"
            "Install it with:\n"
            "  .\\.venv\\Scripts\\python -m pip install -e .[ui]\n"
        ) from e
    return QtCore, QtGui, QtWidgets


def _make_runner(QtCore: Any) -> Any:
    class _Runner(QtCore.QObject):  # type: ignore
        finished = QtCore.Signal(object, object)  # result, error

        def __init__(self) -> None:
            super().__init__()
            self._pool = ThreadPoolExecutor(max_workers=1)

        def run(self, fn: Callable[[], Any], cb: Callable[[Any, Exception | None], None] | None = None) -> None:
            if cb is not None:
                def _slot(res, err):
                    try:
                        self.finished.disconnect(_slot)
                    except Exception:
                        pass
                    cb(res, err)

                # queued to UI thread because `self` lives there
                self.finished.connect(_slot)

            fut = self._pool.submit(fn)

            def done(_f):
                try:
                    res = _f.result()
                    self.finished.emit(res, None)
                except Exception as e:  # noqa: BLE001
                    self.finished.emit(None, e)

            fut.add_done_callback(done)

    return _Runner()


def main(argv: list[str] | None = None) -> int:
    QtCore, QtGui, QtWidgets = _require_pyside()

    parser = argparse.ArgumentParser(description="FL Studio Agent Desktop UI")
    parser.add_argument("--midi-in", default="fl-agent 0")
    parser.add_argument("--midi-out", default="fl-agent 1")
    parser.add_argument("--fl-path", default=_default_fl_path())
    parser.add_argument("--config", default="fl_agent_config.json", help="Optional JSON config for channel mapping")
    args = parser.parse_args(argv)

    app = QtWidgets.QApplication([])
    app.setApplicationName("FL Studio Agent")

    runner = _make_runner(QtCore)
    client: MidiBridgeClient | None = None

    win = QtWidgets.QMainWindow()
    win.setWindowTitle("FL Studio Agent")
    central = QtWidgets.QWidget()
    win.setCentralWidget(central)

    layout = QtWidgets.QVBoxLayout(central)

    # Connection row
    conn = QtWidgets.QHBoxLayout()
    layout.addLayout(conn)

    midi_in = QtWidgets.QLineEdit(args.midi_in)
    midi_in.setPlaceholderText("MIDI In (e.g. fl-agent 0)")
    midi_out = QtWidgets.QLineEdit(args.midi_out)
    midi_out.setPlaceholderText("MIDI Out (e.g. fl-agent 1)")
    fl_path = QtWidgets.QLineEdit(args.fl_path)
    fl_path.setPlaceholderText(r"C:\Program Files\Image-Line\FL Studio 2025\FL64.exe")

    btn_connect = QtWidgets.QPushButton("Connect")
    btn_ping = QtWidgets.QPushButton("Ping")
    btn_launch = QtWidgets.QPushButton("Launch FL")

    conn.addWidget(QtWidgets.QLabel("In:"))
    conn.addWidget(midi_in, 1)
    conn.addWidget(QtWidgets.QLabel("Out:"))
    conn.addWidget(midi_out, 1)
    conn.addWidget(QtWidgets.QLabel("FL64.exe:"))
    conn.addWidget(fl_path, 2)
    conn.addWidget(btn_connect)
    conn.addWidget(btn_ping)
    conn.addWidget(btn_launch)

    cfg_row = QtWidgets.QHBoxLayout()
    layout.addLayout(cfg_row)
    cfg_path = QtWidgets.QLineEdit(args.config)
    cfg_path.setPlaceholderText("fl_agent_config.json")
    btn_cfg = QtWidgets.QPushButton("Reload config")
    cfg_row.addWidget(QtWidgets.QLabel("Config:"))
    cfg_row.addWidget(cfg_path, 1)
    cfg_row.addWidget(btn_cfg)

    performance = QtWidgets.QHBoxLayout()
    layout.addLayout(performance)
    bpm_input = QtWidgets.QDoubleSpinBox()
    bpm_input.setRange(40.0, 240.0)
    bpm_input.setDecimals(1)
    bpm_input.setSingleStep(1.0)
    bpm_input.setValue(94.0)
    bars_input = QtWidgets.QSpinBox()
    bars_input.setRange(1, 16)
    bars_input.setValue(1)
    pattern_input = QtWidgets.QSpinBox()
    pattern_input.setRange(1, 999)
    pattern_input.setValue(1)
    style_input = QtWidgets.QComboBox()
    style_input.addItems(list(STYLE_OPTIONS))
    key_input = QtWidgets.QLineEdit("C")
    key_input.setMaximumWidth(60)
    key_input.setToolTip("Bass key (e.g. C, D#, F#)")
    scale_input = QtWidgets.QComboBox()
    scale_input.addItems(["minor", "major"])
    bass_mode_input = QtWidgets.QComboBox()
    bass_mode_input.addItems(["step", "step_pitch", "piano_roll"])
    bass_mode_input.setCurrentText("step_pitch")
    btn_create = QtWidgets.QPushButton("Create Loop")
    btn_play = QtWidgets.QPushButton("Play")
    btn_stop = QtWidgets.QPushButton("Stop")
    btn_record = QtWidgets.QPushButton("Record")
    btn_panic = QtWidgets.QPushButton("Stop / Panic")
    btn_panic.setToolTip("Best effort: transport stop + panic.")
    performance.addWidget(QtWidgets.QLabel("BPM:"))
    performance.addWidget(bpm_input)
    performance.addWidget(QtWidgets.QLabel("Bars:"))
    performance.addWidget(bars_input)
    performance.addWidget(QtWidgets.QLabel("Pattern:"))
    performance.addWidget(pattern_input)
    performance.addWidget(QtWidgets.QLabel("Style:"))
    performance.addWidget(style_input, 1)
    performance.addWidget(QtWidgets.QLabel("Key:"))
    performance.addWidget(key_input)
    performance.addWidget(QtWidgets.QLabel("Scale:"))
    performance.addWidget(scale_input)
    performance.addWidget(QtWidgets.QLabel("Bass Mode:"))
    performance.addWidget(bass_mode_input)
    performance.addWidget(btn_create)
    performance.addWidget(btn_play)
    performance.addWidget(btn_stop)
    performance.addWidget(btn_record)
    performance.addWidget(btn_panic)

    preview_box = QtWidgets.QGroupBox("Pattern Preview")
    preview_layout = QtWidgets.QVBoxLayout(preview_box)
    preview = QtWidgets.QPlainTextEdit()
    preview.setReadOnly(True)
    preview.setMaximumBlockCount(16)
    preview.setMinimumHeight(130)
    preview_layout.addWidget(preview)
    layout.addWidget(preview_box)

    readback_box = QtWidgets.QGroupBox("FL Read-Back")
    readback_layout = QtWidgets.QVBoxLayout(readback_box)
    readback_toolbar = QtWidgets.QHBoxLayout()
    readback_status = QtWidgets.QLabel("No FL read-back yet")
    btn_readback = QtWidgets.QPushButton("Read Back")
    readback_toolbar.addWidget(readback_status, 1)
    readback_toolbar.addWidget(btn_readback)
    readback = QtWidgets.QPlainTextEdit()
    readback.setReadOnly(True)
    readback.setMaximumBlockCount(64)
    readback.setMinimumHeight(170)
    readback_layout.addLayout(readback_toolbar)
    readback_layout.addWidget(readback)
    layout.addWidget(readback_box)

    mapping_box = QtWidgets.QGroupBox("Template Mapping")
    mapping_layout = QtWidgets.QFormLayout(mapping_box)
    mapping_status = QtWidgets.QLabel("Config not loaded")
    mapping_labels = {
        "kick": QtWidgets.QLabel("-"),
        "clap": QtWidgets.QLabel("-"),
        "hat": QtWidgets.QLabel("-"),
        "snare": QtWidgets.QLabel("-"),
        "bass": QtWidgets.QLabel("-"),
    }
    mapping_layout.addRow("Status:", mapping_status)
    for key, label in mapping_labels.items():
        mapping_layout.addRow(f"{key.title()}:", label)
    layout.addWidget(mapping_box)

    # Presets row
    presets = QtWidgets.QHBoxLayout()
    layout.addLayout(presets)
    btn_rock = QtWidgets.QPushButton("Rock 94 BPM")
    btn_house = QtWidgets.QPushButton("House 128 BPM")
    btn_hiphop = QtWidgets.QPushButton("HipHop 92 BPM")
    btn_trap = QtWidgets.QPushButton("Trap 140 BPM")
    presets.addWidget(btn_rock)
    presets.addWidget(btn_house)
    presets.addWidget(btn_hiphop)
    presets.addWidget(btn_trap)

    # Log + input
    log = QtWidgets.QPlainTextEdit()
    log.setReadOnly(True)
    layout.addWidget(log, 1)

    llm_row = QtWidgets.QHBoxLayout()
    layout.addLayout(llm_row)
    chk_llm = QtWidgets.QCheckBox("Use Ollama")
    ollama_model = QtWidgets.QLineEdit("gemma3:4b")
    ollama_model.setPlaceholderText("Ollama model (e.g. gemma3:4b)")
    ollama_url = QtWidgets.QLineEdit("http://localhost:11434/api/chat")
    ollama_url.setPlaceholderText("Ollama URL (http://localhost:11434/api/chat)")
    llm_row.addWidget(chk_llm)
    llm_row.addWidget(QtWidgets.QLabel("Model:"))
    llm_row.addWidget(ollama_model, 1)
    llm_row.addWidget(QtWidgets.QLabel("URL:"))
    llm_row.addWidget(ollama_url, 2)

    input_row = QtWidgets.QHBoxLayout()
    layout.addLayout(input_row)
    inp = QtWidgets.QLineEdit()
    inp.setPlaceholderText('Type: "Open FL Studio and create a 4/4 drumloop at 94 BPM (rock)"')
    btn_preview_prompt = QtWidgets.QPushButton("Preview Prompt")
    btn_send = QtWidgets.QPushButton("Send")
    input_row.addWidget(inp, 1)
    input_row.addWidget(btn_preview_prompt)
    input_row.addWidget(btn_send)

    def write_line(s: str) -> None:
        log.appendPlainText(s)

    def is_unknown_op_payload(payload: Any, op_name: str) -> bool:
        if not isinstance(payload, dict):
            return False
        err = payload.get("error")
        if not isinstance(err, str):
            return False
        return ("Unknown op: " + op_name) in err

    def log_bridge_update_hint(op_name: str) -> None:
        write_line(
            "[hint] FL bridge is outdated (missing "
            + op_name
            + "). Run .\\scripts\\install_fl_bridge.ps1 and restart FL Studio."
        )

    channel_map: dict[str, int] = dict(DEFAULT_CHANNEL_MAP)
    one_based_cfg = False

    def reset_channel_map() -> None:
        nonlocal channel_map, one_based_cfg
        channel_map = dict(DEFAULT_CHANNEL_MAP)
        one_based_cfg = False

    def update_mapping_panel(status: str) -> None:
        mapping_status.setText(status)
        for name, label in mapping_labels.items():
            label.setText(mapping_label_text(name, channel_map, one_based_cfg))

    def load_config() -> None:
        nonlocal channel_map, one_based_cfg
        p = cfg_path.text().strip()
        if not p:
            reset_channel_map()
            write_line("[ui] config: (empty)")
            update_mapping_panel("Defaults (no config path)")
            return
        if not os.path.exists(p):
            reset_channel_map()
            write_line(f"[ui] config not found: {p}")
            update_mapping_panel(f"Defaults (config not found: {p})")
            return
        try:
            with open(p, "rb") as f:
                obj = json.loads(f.read().decode("utf-8", "strict"))
            tmpl = (obj.get("template") or {}) if isinstance(obj, dict) else {}
            one_based_cfg = bool(tmpl.get("one_based", False)) if isinstance(tmpl, dict) else False
            ch = (tmpl.get("channels") or {}) if isinstance(tmpl, dict) else {}
            if isinstance(ch, dict):
                channel_map = {k: int(v) for k, v in ch.items() if v is not None}
            write_line(f"[ui] config loaded: one_based={one_based_cfg} channels={channel_map}")
            basis = "1-based config" if one_based_cfg else "0-based config"
            update_mapping_panel(f"Loaded {p} ({basis})")
        except Exception as e:  # noqa: BLE001
            reset_channel_map()
            write_line(f"[error] config load: {e}")
            update_mapping_panel(f"Defaults (config error: {e})")

    def ch(name: str, default: int) -> int:
        v = int(channel_map.get(name, default))
        if one_based_cfg:
            v -= 1
        return max(0, v)

    def current_loop_settings() -> tuple[float, str, int]:
        return float(bpm_input.value()), style_input.currentText(), int(bars_input.value())

    def current_tonal_settings() -> tuple[str, str]:
        key = key_input.text().strip() or "C"
        scale = scale_input.currentText().strip() or "minor"
        return normalize_key_scale(key, scale)

    def current_bass_mode() -> str:
        mode = bass_mode_input.currentText().strip().lower()
        if mode not in ("step", "step_pitch", "piano_roll"):
            mode = "step_pitch"
        return mode

    def current_mcp_command() -> list[str]:
        cmd = [
            sys.executable,
            "-m",
            "fl_studio_agent_mcp.server",
            "--backend",
            "midi",
            "--midi-in",
            midi_in.text().strip(),
            "--midi-out",
            midi_out.text().strip(),
            "--fl-path",
            fl_path.text().strip(),
        ]
        config_value = cfg_path.text().strip()
        if config_value:
            cmd.extend(["--config", config_value])
        return cmd

    def set_loop_settings(bpm: float, style: str, bars: int) -> None:
        bpm_input.setValue(float(bpm))
        idx = style_input.findText(style)
        if idx >= 0:
            style_input.setCurrentIndex(idx)
        bars_input.setValue(int(bars))

    def set_tonal_settings(key: str | None, scale: str | None) -> None:
        norm_key, norm_scale = normalize_key_scale(key, scale)
        key_input.setText(norm_key)
        scale_idx = scale_input.findText(norm_scale)
        if scale_idx >= 0:
            scale_input.setCurrentIndex(scale_idx)

    def update_pattern_preview() -> None:
        bpm, style, bars = current_loop_settings()
        key, scale = current_tonal_settings()
        try:
            lines = pattern_preview_lines(style, bars=bars, key=key, scale=scale)
        except Exception as e:  # noqa: BLE001
            preview.setPlainText(f"Preview unavailable: {e}")
            return
        lines.insert(0, f"BPM: {bpm:g}")
        preview.setPlainText("\n".join(lines))

    def readback_track_specs() -> list[dict[str, Any]]:
        tracks: list[dict[str, Any]] = [
            {"name": "kick", "channel": ch("kick", 0)},
            {"name": "snare", "channel": ch("snare", 1)},
            {"name": "hat", "channel": ch("hat", 2)},
        ]
        if "clap" in channel_map:
            tracks.append({"name": "clap", "channel": ch("clap", 3)})
        if "bass" in channel_map:
            tracks.append({"name": "bass", "channel": ch("bass", 4)})
        return tracks

    def set_readback_sections(*sections: tuple[str, dict[str, Any] | None]) -> None:
        chunks = ["\n".join(format_stepseq_snapshot(title, payload)) for title, payload in sections]
        readback.setPlainText("\n\n".join(chunk for chunk in chunks if chunk.strip()))
        readback_status.setText("Updated")

    def ensure_client() -> MidiBridgeClient:
        nonlocal client
        if client is None:
            client = MidiBridgeClient(midi_in.text().strip(), midi_out.text().strip())
        return client

    def do_connect() -> None:
        nonlocal client
        if client is not None:
            client.close()
            client = None
        ensure_client()
        write_line(f"[ui] connected: in={midi_in.text().strip()} out={midi_out.text().strip()}")
        load_config()

    def do_ping() -> None:
        def work():
            c = ensure_client()
            return c.rpc("ping", timeout_s=2.0).payload

        def cb(res, err):
            if err:
                write_line(f"[error] ping: {err}")
            else:
                write_line(f"[ok] ping: {res}")

        runner.run(work, cb)

    def do_launch() -> None:
        exe = fl_path.text().strip()
        if not os.path.exists(exe):
            write_line(f"[error] FL exe not found: {exe}")
            return
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        write_line("[ui] launched FL Studio")

    def do_readback(*, title: str = "Current FL Pattern") -> None:
        total_steps = 16 * int(bars_input.value())
        pattern_index = int(pattern_input.value())

        def work():
            c = ensure_client()
            return c.rpc(
                "get_stepseq",
                {
                    "tracks": readback_track_specs(),
                    "total_steps": total_steps,
                    "include_step_params": True,
                    "pattern_index": pattern_index,
                },
                timeout_s=4.0,
            ).payload

        def cb(res, err):
            if err:
                readback_status.setText("Read-back failed")
                write_line(f"[error] read-back: {err}")
                return
            set_readback_sections((title, res if isinstance(res, dict) else None))
            if isinstance(res, dict) and not bool(res.get("ok", False)):
                write_line(f"[error] read-back: {res}")
                if is_unknown_op_payload(res, "get_stepseq"):
                    log_bridge_update_hint("get_stepseq")
                return
            track_count = len(res.get("result", {}).get("tracks", [])) if isinstance(res, dict) else 0
            write_line(f"[ok] read-back: {track_count} track(s)")

        readback_status.setText("Reading...")
        runner.run(work, cb)

    def do_drumloop(
        bpm: float,
        style: str,
        bars: int = 1,
        *,
        key: str | None = None,
        scale: str | None = None,
        bass_mode: str | None = None,
        pattern_index: int | None = None,
    ) -> None:
        norm_key, norm_scale = normalize_key_scale(key, scale)
        mode = (bass_mode or current_bass_mode()).strip().lower()
        if mode not in ("step", "step_pitch", "piano_roll"):
            mode = "step_pitch"
        pat_num = max(1, int(pattern_index if pattern_index is not None else pattern_input.value()))

        def work():
            c = ensure_client()
            # If FL was just launched, the controller script can take a moment to start responding.
            for _ in range(40):  # ~20s
                try:
                    c.rpc("ping", timeout_s=0.5)
                    break
                except Exception:
                    import time

                    time.sleep(0.5)

            total_steps = 16 * bars
            pat = render_with_bassline(style, total_steps=total_steps, steps_per_bar=16, key=norm_key, scale=norm_scale)
            tracks = [
                {"channel": ch("kick", 0), "on_steps": on_steps(pat.kick)},
                {"channel": ch("snare", 1), "on_steps": on_steps(pat.snare)},
                {"channel": ch("hat", 2), "on_steps": on_steps(pat.hat)},
            ]
            if pat.clap is not None and "clap" in channel_map:
                tracks.append({"channel": ch("clap", 3), "on_steps": on_steps(pat.clap)})
            if pat.bass is not None and "bass" in channel_map:
                bass_track: dict[str, Any] = {"channel": ch("bass", 4), "on_steps": on_steps(pat.bass)}
                if mode in ("step_pitch", "piano_roll") and pat.bass_notes:
                    bass_track["pitches"] = {str(ev.step): int(ev.midi) for ev in pat.bass_notes}
                tracks.append(bass_track)

            readback_tracks = readback_track_specs()
            before_payload = None
            try:
                before_payload = c.rpc(
                    "get_stepseq",
                    {
                        "tracks": readback_tracks,
                        "total_steps": total_steps,
                        "include_step_params": True,
                        "pattern_index": pat_num,
                    },
                    timeout_s=4.0,
                ).payload
            except Exception as e:  # noqa: BLE001
                before_payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}

            rpc_payload = c.rpc(
                "set_stepseq",
                {
                    "bpm": bpm,
                    "steps_per_bar": 16,
                    "bars": bars,
                    "total_steps": total_steps,
                    "bass_mode": mode,
                    "pattern_index": pat_num,
                    "tracks": tracks,
                },
                timeout_s=6.0,
            ).payload
            after_payload = None
            try:
                after_payload = c.rpc(
                    "get_stepseq",
                    {
                        "tracks": readback_tracks,
                        "total_steps": total_steps,
                        "include_step_params": True,
                        "pattern_index": pat_num,
                    },
                    timeout_s=4.0,
                ).payload
            except Exception as e:  # noqa: BLE001
                after_payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            bassline = [{"step": ev.step, "degree": ev.degree, "note": ev.note} for ev in (pat.bass_notes or [])]
            return {
                "rpc": rpc_payload,
                "before": before_payload,
                "after": after_payload,
                "bassline": {"key": norm_key, "scale": norm_scale, "mode": mode, "events": bassline},
            }

        def cb(res, err):
            if err:
                write_line(f"[error] drumloop: {err}")
            else:
                rpc_payload = res.get("rpc", {}) if isinstance(res, dict) else {}
                if isinstance(rpc_payload, dict) and not bool(rpc_payload.get("ok", False)):
                    write_line(f"[error] drumloop ({style}, {bpm} bpm, {bars} bar): {rpc_payload}")
                    set_readback_sections(
                        ("Before write", res.get("before") if isinstance(res, dict) else None),
                        ("After write", res.get("after") if isinstance(res, dict) else None),
                    )
                    if is_unknown_op_payload(rpc_payload, "set_stepseq"):
                        log_bridge_update_hint("set_stepseq")
                    return
                set_readback_sections(
                    ("Before write", res.get("before") if isinstance(res, dict) else None),
                    ("After write", res.get("after") if isinstance(res, dict) else None),
                )
                bassline = (res.get("bassline", {}) if isinstance(res, dict) else {})
                ev = bassline.get("events", []) if isinstance(bassline, dict) else []
                mode_out = bassline.get("mode", mode) if isinstance(bassline, dict) else mode
                preview_notes = ", ".join(f"{x['step']}:{x['note']}({x['degree']})" for x in ev[:6]) if ev else "-"
                write_line(
                    f"[ok] drumloop (pattern {pat_num}, {style}, {bpm} bpm, {bars} bar, {norm_key} {norm_scale}, {mode_out}): {rpc_payload} | bass: {preview_notes}"
                )

        runner.run(work, cb)

    def on_create_loop() -> None:
        bpm, style, bars = current_loop_settings()
        key, scale = current_tonal_settings()
        do_drumloop(
            bpm=bpm,
            style=style,
            bars=bars,
            key=key,
            scale=scale,
            bass_mode=current_bass_mode(),
            pattern_index=int(pattern_input.value()),
        )

    def do_transport(action: str, *, timeout_s: float = 1.5) -> None:
        action = action.strip().lower()

        def work():
            c = ensure_client()
            return c.rpc("transport_control", {"action": action}, timeout_s=timeout_s).payload

        def cb(res, err):
            if err:
                write_line(f"[error] transport {action}: {err}")
                return
            if isinstance(res, dict) and not bool(res.get("ok", False)):
                write_line(f"[error] transport {action}: {res}")
                if is_unknown_op_payload(res, "transport_control"):
                    log_bridge_update_hint("transport_control")
                return
            write_line(f"[ok] transport {action}: {res}")

        runner.run(work, cb)

    def on_panic() -> None:
        def work():
            c = ensure_client()
            out: dict[str, Any] = {"ok": False, "result": {}}
            errors: list[str] = []
            try:
                out["result"]["stop"] = c.rpc("transport_control", {"action": "stop"}, timeout_s=0.8).payload
            except Exception as e:  # noqa: BLE001
                errors.append(f"stop={e}")
            try:
                out["result"]["panic"] = c.rpc("panic", timeout_s=0.8).payload
            except Exception as e:  # noqa: BLE001
                errors.append(f"panic={e}")
            stop_payload = out["result"].get("stop")
            panic_payload = out["result"].get("panic")
            stop_ok = isinstance(stop_payload, dict) and bool(stop_payload.get("ok", False))
            panic_ok = isinstance(panic_payload, dict) and bool(panic_payload.get("ok", False))
            out["ok"] = bool(stop_ok or panic_ok)
            out["errors"] = errors
            return out

        def cb(res, err):
            if err:
                write_line(f"[error] panic: {err}")
                return
            if not isinstance(res, dict) or not res.get("ok", False):
                write_line(f"[error] panic failed: {res}")
                return
            stop_payload = res.get("result", {}).get("stop")
            panic_payload = res.get("result", {}).get("panic")
            stop_ok = isinstance(stop_payload, dict) and bool(stop_payload.get("ok", False))
            panic_ok = isinstance(panic_payload, dict) and bool(panic_payload.get("ok", False))
            if not stop_ok and not panic_ok:
                write_line(f"[error] panic failed: {res}")
                if is_unknown_op_payload(stop_payload, "transport_control") or is_unknown_op_payload(panic_payload, "panic"):
                    log_bridge_update_hint("transport_control/panic")
                return
            if res.get("errors"):
                write_line(f"[warn] panic partial: {res}")
            else:
                write_line(f"[ok] panic: {res}")

        runner.run(work, cb)

    def trigger_preset(style_name: str) -> None:
        bpm, style, bars = PRESET_SETTINGS[style_name]
        set_loop_settings(bpm, style, bars)
        on_create_loop()

    def preview_plan(
        *,
        launch: bool,
        create: bool,
        bpm: float | None,
        style: str | None,
        bars: int | None,
        key: str | None,
        scale: str | None,
        label: str,
    ) -> None:
        write_line(
            f"[preview:{label}] launch={launch} create_drumloop={create} bpm={bpm} style={style} bars={bars} key={key} scale={scale}"
        )
        if not create:
            return
        target_bpm, target_style, target_bars = resolved_loop_settings(current_loop_settings(), bpm, style, bars)
        target_key, target_scale = normalize_key_scale(key, scale)
        set_loop_settings(target_bpm, target_style, target_bars)
        set_tonal_settings(target_key, target_scale)
        update_pattern_preview()

    def on_send() -> None:
        text = inp.text().strip()
        if not text:
            return
        inp.clear()
        write_line(f"> {text}")

        def apply_plan(
            launch: bool,
            create: bool,
            bpm: float | None,
            style: str | None,
            bars: int | None,
            key: str | None,
            scale: str | None,
            label: str,
        ) -> None:
            write_line(
                f"[plan:{label}] launch={launch} create_drumloop={create} bpm={bpm} style={style} bars={bars} key={key} scale={scale}"
            )
            if launch:
                do_launch()
            if create:
                target_bpm, target_style, target_bars = resolved_loop_settings(current_loop_settings(), bpm, style, bars)
                target_key, target_scale = normalize_key_scale(key, scale)
                set_loop_settings(target_bpm, target_style, target_bars)
                set_tonal_settings(target_key, target_scale)
                do_drumloop(
                    bpm=target_bpm,
                    style=target_style,
                    bars=target_bars,
                    key=target_key,
                    scale=target_scale,
                    bass_mode=current_bass_mode(),
                    pattern_index=int(pattern_input.value()),
                )

        if chk_llm.isChecked():
            write_line("[ui] ollama agent running...")
            btn_send.setEnabled(False)

            def handle_finished(res, err):
                btn_send.setEnabled(True)
                if err:
                    write_line(f"[error] ollama: {err}")
                    return
                if not isinstance(res, dict):
                    write_line(f"[error] ollama invalid result: {res!r}")
                    return
                tool_results = res.get("tool_results", [])
                for entry in tool_results:
                    if not isinstance(entry, dict):
                        continue
                    tool_name = str(entry.get("tool", "?"))
                    tool_args = entry.get("args", {})
                    tool_result = entry.get("result", {})
                    write_line(f"[ollama-tool] {tool_name} args={tool_args} result={tool_result}")
                final_text = str(res.get("final_text", "") or "").strip()
                if final_text:
                    write_line(f"[ollama-final] {final_text}")
                if any(
                    isinstance(entry, dict) and str(entry.get("tool")) in ("fl_create_drum_loop", "fl_create_4_4_drumloop", "fl_get_stepseq")
                    for entry in tool_results
                ):
                    do_readback(title="Current FL Pattern")

            def work():
                return run_ollama_mcp_agent_sync(
                    model=ollama_model.text().strip(),
                    ollama_url=ollama_url.text().strip(),
                    mcp_command=current_mcp_command(),
                    user_request=text,
                )

            runner.run(work, handle_finished)
            return

        cmd = parse_command(text)
        write_line(f"[parsed] {asdict(cmd)}")
        apply_plan(cmd.launch, cmd.create_drumloop, cmd.bpm, cmd.style, cmd.bars, cmd.key, cmd.scale, "regex")

    def on_preview_prompt() -> None:
        text = inp.text().strip()
        if not text:
            return
        write_line(f"[preview-request] {text}")
        if chk_llm.isChecked():
            write_line("[ui] ollama preview planning...")
            btn_preview_prompt.setEnabled(False)

            def handle_finished(res, err):
                btn_preview_prompt.setEnabled(True)
                if err:
                    write_line(f"[error] ollama preview: {err}")
                    cmd = parse_command(text)
                    write_line(f"[preview:fallback] {asdict(cmd)}")
                    preview_plan(
                        launch=cmd.launch,
                        create=cmd.create_drumloop,
                        bpm=cmd.bpm,
                        style=cmd.style,
                        bars=cmd.bars,
                        key=cmd.key,
                        scale=cmd.scale,
                        label="fallback",
                    )
                else:
                    write_line(f"[preview:ollama] {asdict(res)}")
                    preview_plan(
                        launch=res.launch,
                        create=res.create_drumloop,
                        bpm=res.bpm,
                        style=res.style,
                        bars=res.bars,
                        key=res.key,
                        scale=res.scale,
                        label="ollama",
                    )

            def work():
                return plan_with_ollama(text, model=ollama_model.text().strip(), url=ollama_url.text().strip())

            runner.run(work, handle_finished)
            return

        cmd = parse_command(text)
        write_line(f"[preview:parsed] {asdict(cmd)}")
        preview_plan(
            launch=cmd.launch,
            create=cmd.create_drumloop,
            bpm=cmd.bpm,
            style=cmd.style,
            bars=cmd.bars,
            key=cmd.key,
            scale=cmd.scale,
            label="regex",
        )

    btn_connect.clicked.connect(do_connect)
    btn_ping.clicked.connect(do_ping)
    btn_launch.clicked.connect(do_launch)
    btn_create.clicked.connect(on_create_loop)
    btn_play.clicked.connect(lambda: do_transport("play"))
    btn_stop.clicked.connect(lambda: do_transport("stop"))
    btn_record.clicked.connect(lambda: do_transport("record"))
    btn_panic.clicked.connect(on_panic)
    btn_readback.clicked.connect(lambda: do_readback())
    btn_preview_prompt.clicked.connect(on_preview_prompt)
    btn_send.clicked.connect(on_send)
    inp.returnPressed.connect(on_send)
    btn_cfg.clicked.connect(load_config)
    bpm_input.valueChanged.connect(lambda _value: update_pattern_preview())
    bars_input.valueChanged.connect(lambda _value: update_pattern_preview())
    pattern_input.valueChanged.connect(lambda _value: do_readback(title="Current FL Pattern"))
    style_input.currentIndexChanged.connect(lambda _index: update_pattern_preview())
    key_input.editingFinished.connect(update_pattern_preview)
    scale_input.currentIndexChanged.connect(lambda _index: update_pattern_preview())
    bass_mode_input.currentIndexChanged.connect(lambda _index: update_pattern_preview())

    btn_rock.clicked.connect(partial(trigger_preset, "rock"))
    btn_house.clicked.connect(partial(trigger_preset, "house"))
    btn_hiphop.clicked.connect(partial(trigger_preset, "hiphop"))
    btn_trap.clicked.connect(partial(trigger_preset, "trap"))

    update_mapping_panel("Defaults (0-based internal mapping)")
    update_pattern_preview()
    if os.path.exists(cfg_path.text().strip()):
        load_config()

    win.resize(1200, 700)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
