from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .file_transport import FileBridgeClient
from .midi_transport import MidiBridgeClient


def _default_fl_path() -> str:
    return r"C:\Program Files\Image-Line\FL Studio 2025\FL64.exe"


def _pick_port(base: str, names: list[str]) -> str | None:
    # Prefer prefix matches, then substring matches.
    base_l = base.lower()
    for n in names:
        if n.lower().startswith(base_l):
            return n
    for n in names:
        if base_l in n.lower():
            return n
    return None


def _create_client(
    backend: str,
    *,
    midi_port: str,
    midi_in: str | None,
    midi_out: str | None,
    ipc_dir: str | None,
) -> Any:
    if backend == "file":
        return FileBridgeClient(ipc_dir)
    if backend == "midi":
        if midi_in and midi_out:
            return MidiBridgeClient(midi_in, midi_out)
        if midi_in and not midi_out:
            return MidiBridgeClient(midi_in, midi_in)
        # auto-pick from base
        import mido

        chosen_in = _pick_port(midi_port, mido.get_input_names())
        chosen_out = _pick_port(midi_port, mido.get_output_names())
        if not chosen_in or not chosen_out:
            raise RuntimeError(
                f"Could not auto-pick MIDI ports for base {midi_port!r}. "
                f"Inputs={mido.get_input_names()!r} Outputs={mido.get_output_names()!r}"
            )
        return MidiBridgeClient(chosen_in, chosen_out)
    if backend == "auto":
        try:
            return _create_client("midi", midi_port=midi_port, midi_in=midi_in, midi_out=midi_out, ipc_dir=ipc_dir)
        except Exception:
            return FileBridgeClient(ipc_dir)
    raise ValueError(f"Unknown backend: {backend!r}")


def create_app(
    midi_port: str,
    *,
    midi_in: str | None = None,
    midi_out: str | None = None,
    fl_path: str | None = None,
    backend: str = "auto",
    ipc_dir: str | None = None,
) -> FastMCP:
    mcp = FastMCP("fl-studio-agent")
    client = _create_client(backend, midi_port=midi_port, midi_in=midi_in, midi_out=midi_out, ipc_dir=ipc_dir)
    fl_exe = fl_path or _default_fl_path()

    @mcp.tool()
    def fl_ping() -> dict[str, Any]:
        """Round-trip test to the FL Studio bridge."""
        res = client.rpc("ping", timeout_s=2.0)
        return res.payload

    @mcp.tool()
    def fl_launch() -> dict[str, Any]:
        """Launch FL Studio if it's not already running."""
        if not os.path.exists(fl_exe):
            return {"ok": False, "error": f"FL Studio exe not found: {fl_exe}"}
        subprocess.Popen([fl_exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "result": {"launched": True, "path": fl_exe}}

    @mcp.tool()
    def fl_get_tempo() -> dict[str, Any]:
        """Get current FL Studio tempo."""
        res = client.rpc("get_tempo", timeout_s=2.0)
        return res.payload

    @mcp.tool()
    def fl_set_tempo(bpm: float) -> dict[str, Any]:
        """Set FL Studio tempo in BPM."""
        res = client.rpc("set_tempo", {"bpm": bpm}, timeout_s=2.0)
        return res.payload

    @mcp.tool()
    def fl_create_drum_loop(
        bpm: float = 94.0,
        kick_channel: int = 0,
        snare_channel: int = 1,
        hat_channel: int = 2,
        steps: int = 16,
    ) -> dict[str, Any]:
        """Program a simple 4/4 drum loop via step sequencer grid bits."""
        res = client.rpc(
            "create_drum_loop",
            {
                "bpm": bpm,
                "kick_channel": kick_channel,
                "snare_channel": snare_channel,
                "hat_channel": hat_channel,
                "steps": steps,
            },
            timeout_s=3.0,
        )
        return res.payload

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FL Studio Agent MCP server")
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "midi", "file"],
        help="Bridge backend: midi (SysEx), file (TEMP polling), or auto (try midi then file).",
    )
    parser.add_argument(
        "--midi-port",
        default="fl-agent",
        help="Base MIDI port name to auto-pick input/output (e.g. fl-agent).",
    )
    parser.add_argument("--midi-in", default=None, help="Explicit MIDI input port name (overrides --midi-port)")
    parser.add_argument("--midi-out", default=None, help="Explicit MIDI output port name (overrides --midi-port)")
    parser.add_argument("--ipc-dir", default=None, help="IPC base dir for file backend (default: TEMP\\fl_studio_agent_ipc)")
    parser.add_argument("--fl-path", default=_default_fl_path(), help="Path to FL64.exe")
    args = parser.parse_args(argv)

    app = create_app(
        args.midi_port,
        midi_in=args.midi_in,
        midi_out=args.midi_out,
        fl_path=args.fl_path,
        backend=args.backend,
        ipc_dir=args.ipc_dir,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
