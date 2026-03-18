from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any, Callable

from fl_studio_agent_mcp.midi_transport import MidiBridgeClient
from fl_studio_agent_mcp.patterns import on_steps, render
from fl_studio_agent_mcp.server import _default_fl_path

from .parse import parse_command
from .ollama import plan_with_ollama


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
    btn_send = QtWidgets.QPushButton("Send")
    input_row.addWidget(inp, 1)
    input_row.addWidget(btn_send)

    def write_line(s: str) -> None:
        log.appendPlainText(s)

    channel_map: dict[str, int] = {"kick": 0, "snare": 1, "hat": 2, "clap": 3}
    one_based_cfg = False

    def load_config() -> None:
        nonlocal channel_map, one_based_cfg
        p = cfg_path.text().strip()
        if not p:
            write_line("[ui] config: (empty)")
            return
        if not os.path.exists(p):
            write_line(f"[ui] config not found: {p}")
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
        except Exception as e:  # noqa: BLE001
            write_line(f"[error] config load: {e}")

    def ch(name: str, default: int) -> int:
        v = int(channel_map.get(name, default))
        if one_based_cfg:
            v -= 1
        return max(0, v)

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
                do_drumloop(bpm=bpm or 94.0, style=style or "rock", bars=bars or 1)

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

    btn_connect.clicked.connect(do_connect)
    btn_ping.clicked.connect(do_ping)
    btn_launch.clicked.connect(do_launch)
    btn_send.clicked.connect(on_send)
    inp.returnPressed.connect(on_send)
    btn_cfg.clicked.connect(load_config)

    btn_rock.clicked.connect(lambda: do_drumloop(94.0, "rock", 1))
    btn_house.clicked.connect(lambda: do_drumloop(128.0, "house", 1))
    btn_hiphop.clicked.connect(lambda: do_drumloop(92.0, "hiphop", 1))
    btn_trap.clicked.connect(lambda: do_drumloop(140.0, "trap", 1))

    win.resize(1200, 700)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
