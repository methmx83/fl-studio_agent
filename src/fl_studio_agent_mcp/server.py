from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from .file_transport import FileBridgeClient
from .midi_transport import MidiBridgeClient
from .patterns import on_steps, render
from .rpc_utils import coerce_timeout, safe_rpc


def _default_fl_path() -> str:
    return r"C:\Program Files\Image-Line\FL Studio 2025\FL64.exe"


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8", "strict"))
    except FileNotFoundError:
        return {}


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
    config_path: str | None = None,
    rpc_timeout_s: float | None = None,
) -> FastMCP:
    mcp = FastMCP("fl-studio-agent")
    client = _create_client(backend, midi_port=midi_port, midi_in=midi_in, midi_out=midi_out, ipc_dir=ipc_dir)
    fl_exe = fl_path or _default_fl_path()
    cfg = _load_config(config_path)
    template_cfg = (cfg.get("template") or {}) if isinstance(cfg, dict) else {}
    chan_cfg = (template_cfg.get("channels") or {}) if isinstance(template_cfg, dict) else {}
    one_based = bool(template_cfg.get("one_based", False)) if isinstance(template_cfg, dict) else False
    rpc_cfg = (cfg.get("rpc") or {}) if isinstance(cfg, dict) else {}
    default_timeout_s = coerce_timeout(rpc_timeout_s, default=coerce_timeout(rpc_cfg.get("timeout_s"), default=2.0))

    def _ch(name: str, default: int) -> int:
        v = chan_cfg.get(name, default)
        try:
            n = int(v)
        except Exception:
            n = int(default)
        if one_based:
            n -= 1
        return max(0, n)

    @mcp.tool()
    def fl_ping() -> dict[str, Any]:
        """Round-trip test to the FL Studio bridge."""
        return safe_rpc(client, "ping", timeout_s=default_timeout_s)

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
        return safe_rpc(client, "get_tempo", timeout_s=default_timeout_s)

    @mcp.tool()
    def fl_set_tempo(bpm: float) -> dict[str, Any]:
        """Set FL Studio tempo in BPM."""
        return safe_rpc(client, "set_tempo", {"bpm": bpm}, timeout_s=default_timeout_s)

    @mcp.tool()
    def fl_create_drum_loop(
        bpm: float = 94.0,
        kick_channel: int = 0,
        snare_channel: int = 1,
        hat_channel: int = 2,
        steps: int = 16,
    ) -> dict[str, Any]:
        """Program a simple 4/4 drum loop via step sequencer grid bits."""
        return safe_rpc(
            client,
            "create_drum_loop",
            {
                "bpm": bpm,
                "kick_channel": kick_channel,
                "snare_channel": snare_channel,
                "hat_channel": hat_channel,
                "steps": steps,
            },
            timeout_s=default_timeout_s,
        )

    @mcp.tool()
    def fl_create_4_4_drumloop(
        bpm: float = 94.0,
        style: str = "rock",
        bars: int = 1,
        steps_per_bar: int = 16,
        kick_channel: int | None = None,
        snare_channel: int | None = None,
        hat_channel: int | None = None,
        clap_channel: int | None = None,
        bass_channel: int | None = None,
        include_bass: bool = True,
        use_velocities: bool = False,
        humanize: int = 6,
    ) -> dict[str, Any]:
        """
        High-level beat tool: create a 4/4 drumloop at `bpm` using a named `style`.

        Uses a template channel mapping (if `--config` is provided) and programs the step sequencer.
        """
        if bars < 1:
            bars = 1
        if bars > 8:
            bars = 8
        if steps_per_bar not in (16,):
            return {"ok": False, "error": "Only steps_per_bar=16 is supported for now."}

        kick = int(kick_channel) if kick_channel is not None else _ch("kick", 0)
        snare = int(snare_channel) if snare_channel is not None else _ch("snare", 1)
        hat = int(hat_channel) if hat_channel is not None else _ch("hat", 2)
        clap = clap_channel if clap_channel is not None else (chan_cfg.get("clap", None))
        if clap is not None:
            clap = int(clap)
            if one_based:
                clap -= 1
            if clap < 0:
                clap = None
        bass = bass_channel if bass_channel is not None else (chan_cfg.get("bass", None))
        if bass is not None:
            bass = int(bass)
            if one_based:
                bass -= 1
            if bass < 0:
                bass = None

        total_steps = steps_per_bar * bars
        pat = render(style, total_steps=total_steps, steps_per_bar=steps_per_bar)

        def vel_map(on: list[int], *, base: int, accent_every: int | None = None) -> dict[str, int]:
            # Keep deterministic (no RNG) but provide small accents.
            velocities: dict[str, int] = {}
            for i, step in enumerate(on):
                v = base
                if accent_every and (step % accent_every == 0):
                    v = min(127, base + humanize)
                velocities[str(step)] = v
            return velocities

        tracks: list[dict[str, Any]] = [
            {"channel": kick, "on_steps": on_steps(pat.kick)},
            {"channel": snare, "on_steps": on_steps(pat.snare)},
            {"channel": hat, "on_steps": on_steps(pat.hat)},
        ]
        if clap is not None and pat.clap:
            tracks.append({"channel": int(clap), "on_steps": on_steps(pat.clap)})
        if include_bass and bass is not None and pat.bass:
            tracks.append({"channel": int(bass), "on_steps": on_steps(pat.bass)})

        if use_velocities:
            # Velocity support can be limited depending on the project's pattern length; keep it opt-in.
            tracks[0]["velocities"] = vel_map(tracks[0]["on_steps"], base=110, accent_every=4)
            tracks[1]["velocities"] = vel_map(tracks[1]["on_steps"], base=115, accent_every=8)
            tracks[2]["velocities"] = vel_map(tracks[2]["on_steps"], base=85, accent_every=2)
            if clap is not None and pat.clap:
                tracks[-1]["velocities"] = vel_map(tracks[-1]["on_steps"], base=108, accent_every=8)

        return safe_rpc(
            client,
            "set_stepseq",
            {"bpm": bpm, "steps_per_bar": steps_per_bar, "bars": bars, "total_steps": total_steps, "tracks": tracks},
            timeout_s=default_timeout_s,
        )

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
    parser.add_argument("--config", default=None, help="Optional JSON config (see fl_agent_config.example.json)")
    parser.add_argument(
        "--rpc-timeout",
        type=float,
        default=None,
        help="RPC timeout in seconds for FL bridge calls (overrides config rpc.timeout_s).",
    )
    args = parser.parse_args(argv)

    # Allow config to provide default MIDI port names.
    cfg = _load_config(args.config)
    if isinstance(cfg, dict):
        midi_cfg = cfg.get("midi") or {}
        if args.midi_in is None and isinstance(midi_cfg, dict) and midi_cfg.get("in"):
            args.midi_in = str(midi_cfg.get("in"))
        if args.midi_out is None and isinstance(midi_cfg, dict) and midi_cfg.get("out"):
            args.midi_out = str(midi_cfg.get("out"))

    app = create_app(
        args.midi_port,
        midi_in=args.midi_in,
        midi_out=args.midi_out,
        fl_path=args.fl_path,
        backend=args.backend,
        ipc_dir=args.ipc_dir,
        config_path=args.config,
        rpc_timeout_s=args.rpc_timeout,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
