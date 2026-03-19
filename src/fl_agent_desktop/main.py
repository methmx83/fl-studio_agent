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
from fl_studio_agent_mcp.patterns import on_steps, render
from fl_studio_agent_mcp.server import _default_fl_path

from .pattern_preview import pattern_preview_lines
from .parse import parse_command
from .ollama import plan_with_ollama
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
    style_input = QtWidgets.QComboBox()
    style_input.addItems(list(STYLE_OPTIONS))
    btn_create = QtWidgets.QPushButton("Create Loop")
    btn_panic = QtWidgets.QPushButton("Stop / Panic")
    btn_panic.setEnabled(False)
    btn_panic.setToolTip("Reserved for a future transport-stop + clear-pattern action.")
    performance.addWidget(QtWidgets.QLabel("BPM:"))
    performance.addWidget(bpm_input)
    performance.addWidget(QtWidgets.QLabel("Bars:"))
    performance.addWidget(bars_input)
    performance.addWidget(QtWidgets.QLabel("Style:"))
    performance.addWidget(style_input, 1)
    performance.addWidget(btn_create)
    performance.addWidget(btn_panic)

    preview_box = QtWidgets.QGroupBox("Pattern Preview")
    preview_layout = QtWidgets.QVBoxLayout(preview_box)
    preview = QtWidgets.QPlainTextEdit()
    preview.setReadOnly(True)
    preview.setMaximumBlockCount(16)
    preview.setMinimumHeight(130)
    preview_layout.addWidget(preview)
    layout.addWidget(preview_box)

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

    def set_loop_settings(bpm: float, style: str, bars: int) -> None:
        bpm_input.setValue(float(bpm))
        idx = style_input.findText(style)
        if idx >= 0:
            style_input.setCurrentIndex(idx)
        bars_input.setValue(int(bars))

    def update_pattern_preview() -> None:
        bpm, style, bars = current_loop_settings()
        try:
            lines = pattern_preview_lines(style, bars=bars)
        except Exception as e:  # noqa: BLE001
            preview.setPlainText(f"Preview unavailable: {e}")
            return
        lines.insert(0, f"BPM: {bpm:g}")
        preview.setPlainText("\n".join(lines))

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

    def do_drumloop(bpm: float, style: str, bars: int = 1) -> None:
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
            pat = render(style, total_steps=total_steps, steps_per_bar=16)
            tracks = [
                {"channel": ch("kick", 0), "on_steps": on_steps(pat.kick)},
                {"channel": ch("snare", 1), "on_steps": on_steps(pat.snare)},
                {"channel": ch("hat", 2), "on_steps": on_steps(pat.hat)},
            ]
            if pat.clap is not None and "clap" in channel_map:
                tracks.append({"channel": ch("clap", 3), "on_steps": on_steps(pat.clap)})
            if pat.bass is not None and "bass" in channel_map:
                tracks.append({"channel": ch("bass", 4), "on_steps": on_steps(pat.bass)})

            return c.rpc(
                "set_stepseq",
                {
                    "bpm": bpm,
                    "steps_per_bar": 16,
                    "bars": bars,
                    "total_steps": total_steps,
                    "tracks": tracks,
                },
                timeout_s=6.0,
            ).payload

        def cb(res, err):
            if err:
                write_line(f"[error] drumloop: {err}")
            else:
                write_line(f"[ok] drumloop ({style}, {bpm} bpm, {bars} bar): {res}")

        runner.run(work, cb)

    def on_create_loop() -> None:
        bpm, style, bars = current_loop_settings()
        do_drumloop(bpm=bpm, style=style, bars=bars)

    def on_panic() -> None:
        write_line("[ui] Stop / Panic is reserved for a future transport-stop + clear-pattern action.")

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
        label: str,
    ) -> None:
        write_line(f"[preview:{label}] launch={launch} create_drumloop={create} bpm={bpm} style={style} bars={bars}")
        if not create:
            return
        target_bpm, target_style, target_bars = resolved_loop_settings(current_loop_settings(), bpm, style, bars)
        set_loop_settings(target_bpm, target_style, target_bars)
        update_pattern_preview()

    def on_send() -> None:
        text = inp.text().strip()
        if not text:
            return
        inp.clear()
        write_line(f"> {text}")

        def apply_plan(launch: bool, create: bool, bpm: float | None, style: str | None, bars: int | None, label: str) -> None:
            write_line(f"[plan:{label}] launch={launch} create_drumloop={create} bpm={bpm} style={style} bars={bars}")
            if launch:
                do_launch()
            if create:
                target_bpm, target_style, target_bars = resolved_loop_settings(current_loop_settings(), bpm, style, bars)
                set_loop_settings(target_bpm, target_style, target_bars)
                do_drumloop(bpm=target_bpm, style=target_style, bars=target_bars)

        if chk_llm.isChecked():
            write_line("[ui] ollama planning...")
            btn_send.setEnabled(False)

            def handle_finished(res, err):
                btn_send.setEnabled(True)
                if err:
                    write_line(f"[error] ollama: {err}")
                    cmd = parse_command(text)
                    write_line(f"[parsed:fallback] {asdict(cmd)}")
                    apply_plan(cmd.launch, cmd.create_drumloop, cmd.bpm, cmd.style, cmd.bars, "fallback")
                else:
                    write_line(f"[ollama] {asdict(res)}")
                    apply_plan(res.launch, res.create_drumloop, res.bpm, res.style, res.bars, "ollama")

            def work():
                return plan_with_ollama(text, model=ollama_model.text().strip(), url=ollama_url.text().strip())

            runner.run(work, handle_finished)
            return

        cmd = parse_command(text)
        write_line(f"[parsed] {asdict(cmd)}")
        apply_plan(cmd.launch, cmd.create_drumloop, cmd.bpm, cmd.style, cmd.bars, "regex")

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
            label="regex",
        )

    btn_connect.clicked.connect(do_connect)
    btn_ping.clicked.connect(do_ping)
    btn_launch.clicked.connect(do_launch)
    btn_create.clicked.connect(on_create_loop)
    btn_panic.clicked.connect(on_panic)
    btn_preview_prompt.clicked.connect(on_preview_prompt)
    btn_send.clicked.connect(on_send)
    inp.returnPressed.connect(on_send)
    btn_cfg.clicked.connect(load_config)
    bpm_input.valueChanged.connect(lambda _value: update_pattern_preview())
    bars_input.valueChanged.connect(lambda _value: update_pattern_preview())
    style_input.currentIndexChanged.connect(lambda _index: update_pattern_preview())

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
