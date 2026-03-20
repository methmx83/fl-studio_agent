from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from logging.handlers import RotatingFileHandler
from typing import Any

from mcp.server.fastmcp import FastMCP

from .file_transport import FileBridgeClient
from .midi_transport import MidiBridgeClient
from .patterns import normalize_key_scale, on_steps, render_with_bassline

LOG = logging.getLogger("fl_studio_agent_mcp.server")


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


def _setup_logging(log_file: str | None, level: str, max_bytes: int, backups: int) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    LOG.setLevel(log_level)
    LOG.handlers.clear()
    LOG.propagate = False

    # Keep console output light while enabling persistent diagnostics.
    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(log_level)
    stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(stream)

    path = log_file
    if not path:
        base = os.path.join(tempfile.gettempdir(), "fl_studio_agent_logs")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, "server.log")
    else:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    file_handler = RotatingFileHandler(
        path,
        maxBytes=max(1024, int(max_bytes)),
        backupCount=max(1, int(backups)),
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(file_handler)
    LOG.info("server logging enabled file=%s level=%s", path, level.upper())


def _error_result(
    code: str,
    message: str,
    *,
    operation: str | None = None,
    timeout_s: float | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if operation is not None:
        detail["operation"] = operation
    if timeout_s is not None:
        detail["timeout_s"] = timeout_s
    if details:
        detail.update(details)
    # Keep a plain string at error for existing clients while adding structured metadata.
    return {"ok": False, "error": message, "error_detail": detail}


def _rpc_call(client: Any, op: str, args: dict[str, Any] | None = None, *, timeout_s: float) -> dict[str, Any]:
    try:
        res = client.rpc(op, args, timeout_s=timeout_s)
    except TimeoutError as e:
        LOG.warning("rpc timeout op=%s timeout_s=%.3f error=%s", op, timeout_s, e)
        return _error_result("RPC_TIMEOUT", str(e), operation=op, timeout_s=timeout_s)
    except Exception as e:  # noqa: BLE001
        LOG.exception("rpc transport failure op=%s", op)
        return _error_result("RPC_TRANSPORT", f"{type(e).__name__}: {e}", operation=op)

    payload = res.payload if isinstance(res.payload, dict) else {}
    if bool(payload.get("ok", False)):
        return payload

    remote_error = payload.get("error")
    if isinstance(remote_error, dict):
        msg = str(remote_error.get("message") or "FL bridge returned an error.")
        LOG.warning("rpc remote error op=%s message=%s", op, msg)
        return _error_result(
            "RPC_REMOTE",
            msg,
            operation=op,
            details={"remote_error": remote_error, "raw_type": res.raw_type},
        )
    if isinstance(remote_error, str) and remote_error.strip():
        LOG.warning("rpc remote error op=%s message=%s", op, remote_error)
        return _error_result("RPC_REMOTE", remote_error, operation=op, details={"raw_type": res.raw_type})

    LOG.warning("rpc invalid response op=%s payload=%r raw_type=%s", op, payload, getattr(res, "raw_type", None))
    return _error_result(
        "RPC_INVALID_RESPONSE",
        "FL bridge returned an invalid error payload.",
        operation=op,
        details={"payload": payload, "raw_type": res.raw_type},
    )


def _coerce_optional_channel(chan_cfg: dict[str, Any], name: str, *, one_based: bool) -> int | None:
    if name not in chan_cfg:
        return None
    try:
        value = int(chan_cfg.get(name))
    except Exception:
        return None
    if one_based:
        value -= 1
    if value < 0:
        return None
    return value


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
    rpc_timeout: float = 2.0,
    rpc_timeout_loop: float = 4.0,
) -> FastMCP:
    mcp = FastMCP("fl-studio-agent")
    client = _create_client(backend, midi_port=midi_port, midi_in=midi_in, midi_out=midi_out, ipc_dir=ipc_dir)
    fl_exe = fl_path or _default_fl_path()
    cfg = _load_config(config_path)
    template_cfg = (cfg.get("template") or {}) if isinstance(cfg, dict) else {}
    chan_cfg = (template_cfg.get("channels") or {}) if isinstance(template_cfg, dict) else {}
    one_based = bool(template_cfg.get("one_based", False)) if isinstance(template_cfg, dict) else False

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
        return _rpc_call(client, "ping", timeout_s=rpc_timeout)

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
        return _rpc_call(client, "get_tempo", timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_set_tempo(bpm: float) -> dict[str, Any]:
        """Set FL Studio tempo in BPM."""
        return _rpc_call(client, "set_tempo", {"bpm": bpm}, timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_transport(action: str) -> dict[str, Any]:
        """Control FL transport. Supported actions: play, stop, record."""
        action_norm = str(action).strip().lower()
        if action_norm not in ("play", "stop", "record"):
            return _error_result(
                "INVALID_ARGUMENT",
                "action must be one of: play, stop, record",
                operation="transport_control",
                details={"action": action},
            )
        return _rpc_call(client, "transport_control", {"action": action_norm}, timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_play() -> dict[str, Any]:
        """Start playback."""
        return _rpc_call(client, "transport_control", {"action": "play"}, timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_stop() -> dict[str, Any]:
        """Stop playback."""
        return _rpc_call(client, "transport_control", {"action": "stop"}, timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_record() -> dict[str, Any]:
        """Toggle/arm recording (depends on FL runtime support)."""
        return _rpc_call(client, "transport_control", {"action": "record"}, timeout_s=rpc_timeout)

    @mcp.tool()
    def fl_panic() -> dict[str, Any]:
        """Best effort stop + all-notes-off style panic."""
        return _rpc_call(client, "panic", timeout_s=max(0.75, rpc_timeout))

    @mcp.tool()
    def fl_create_drum_loop(
        bpm: float = 94.0,
        kick_channel: int = 0,
        snare_channel: int = 1,
        hat_channel: int = 2,
        steps: int = 16,
        pattern_index: int | None = None,
    ) -> dict[str, Any]:
        """Program a simple 4/4 drum loop via step sequencer grid bits."""
        args = {
            "bpm": bpm,
            "kick_channel": kick_channel,
            "snare_channel": snare_channel,
            "hat_channel": hat_channel,
            "steps": steps,
        }
        if pattern_index is not None:
            args["pattern_index"] = max(1, int(pattern_index))
        return _rpc_call(client, "create_drum_loop", args, timeout_s=max(rpc_timeout, 3.0))

    @mcp.tool()
    def fl_create_4_4_drumloop(
        bpm: float = 94.0,
        style: str = "rock",
        bars: int = 1,
        steps_per_bar: int = 16,
        key: str = "C",
        scale: str = "minor",
        bass_mode: str = "step_pitch",
        kick_channel: int | None = None,
        snare_channel: int | None = None,
        hat_channel: int | None = None,
        clap_channel: int | None = None,
        bass_channel: int | None = None,
        include_bass: bool = True,
        use_velocities: bool = False,
        humanize: int = 6,
        pattern_index: int | None = None,
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
        clap = int(clap_channel) if clap_channel is not None else _coerce_optional_channel(chan_cfg, "clap", one_based=one_based)
        bass = int(bass_channel) if bass_channel is not None else _coerce_optional_channel(chan_cfg, "bass", one_based=one_based)

        total_steps = steps_per_bar * bars
        norm_key, norm_scale = normalize_key_scale(key, scale)
        bass_mode_norm = str(bass_mode or "step_pitch").strip().lower()
        if bass_mode_norm not in ("step", "step_pitch", "piano_roll"):
            return _error_result(
                "INVALID_ARGUMENT",
                "bass_mode must be one of: step, step_pitch, piano_roll",
                operation="fl_create_4_4_drumloop",
                details={"bass_mode": bass_mode},
            )
        pat = render_with_bassline(style, total_steps=total_steps, steps_per_bar=steps_per_bar, key=norm_key, scale=norm_scale)

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
            bass_track: dict[str, Any] = {"channel": int(bass), "on_steps": on_steps(pat.bass)}
            if bass_mode_norm in ("step_pitch", "piano_roll") and pat.bass_notes:
                bass_track["pitches"] = {str(ev.step): int(ev.midi) for ev in pat.bass_notes}
            tracks.append(bass_track)

        if use_velocities:
            # Velocity support can be limited depending on the project's pattern length; keep it opt-in.
            tracks[0]["velocities"] = vel_map(tracks[0]["on_steps"], base=110, accent_every=4)
            tracks[1]["velocities"] = vel_map(tracks[1]["on_steps"], base=115, accent_every=8)
            tracks[2]["velocities"] = vel_map(tracks[2]["on_steps"], base=85, accent_every=2)
            if clap is not None and pat.clap:
                tracks[-1]["velocities"] = vel_map(tracks[-1]["on_steps"], base=108, accent_every=8)

        out = _rpc_call(
            client,
            "set_stepseq",
            {
                "bpm": bpm,
                "steps_per_bar": steps_per_bar,
                "bars": bars,
                "total_steps": total_steps,
                "bass_mode": bass_mode_norm,
                "tracks": tracks,
                "pattern_index": max(1, int(pattern_index)) if pattern_index is not None else None,
            },
            timeout_s=max(rpc_timeout_loop, rpc_timeout),
        )
        if bool(out.get("ok", False)):
            bassline = []
            if pat.bass_notes:
                bassline = [{"step": ev.step, "degree": ev.degree, "note": ev.note, "midi": ev.midi} for ev in pat.bass_notes]
            result = out.get("result")
            if isinstance(result, dict):
                result["bassline"] = {"key": norm_key, "scale": norm_scale, "mode": bass_mode_norm, "events": bassline}
        return out

    @mcp.tool()
    def fl_get_stepseq(
        channels: list[int] | None = None,
        total_steps: int | None = None,
        include_step_params: bool = True,
        pattern_index: int | None = None,
    ) -> dict[str, Any]:
        """Read the current step sequencer pattern state for configured or explicit channels."""
        if total_steps is not None:
            try:
                total_steps = int(total_steps)
            except Exception:
                return _error_result(
                    "INVALID_ARGUMENT",
                    "total_steps must be an integer >= 1",
                    operation="get_stepseq",
                    details={"total_steps": total_steps},
                )
            if total_steps < 1:
                return _error_result(
                    "INVALID_ARGUMENT",
                    "total_steps must be an integer >= 1",
                    operation="get_stepseq",
                    details={"total_steps": total_steps},
                )

        tracks: list[dict[str, Any]] = []
        if channels is not None:
            try:
                tracks = [{"channel": int(ch)} for ch in channels]
            except Exception:
                return _error_result(
                    "INVALID_ARGUMENT",
                    "channels must be a list of integers",
                    operation="get_stepseq",
                    details={"channels": channels},
                )
        else:
            tracks.extend(
                [
                    {"name": "kick", "channel": _ch("kick", 0)},
                    {"name": "snare", "channel": _ch("snare", 1)},
                    {"name": "hat", "channel": _ch("hat", 2)},
                ]
            )
            clap = _coerce_optional_channel(chan_cfg, "clap", one_based=one_based)
            bass = _coerce_optional_channel(chan_cfg, "bass", one_based=one_based)
            if clap is not None:
                tracks.append({"name": "clap", "channel": clap})
            if bass is not None:
                tracks.append({"name": "bass", "channel": bass})

        args: dict[str, Any] = {"tracks": tracks, "include_step_params": bool(include_step_params)}
        if total_steps is not None:
            args["total_steps"] = total_steps
        if pattern_index is not None:
            args["pattern_index"] = max(1, int(pattern_index))
        return _rpc_call(client, "get_stepseq", args, timeout_s=max(rpc_timeout_loop, rpc_timeout))

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
    parser.add_argument("--rpc-timeout", type=float, default=2.0, help="Default RPC timeout in seconds.")
    parser.add_argument("--rpc-timeout-loop", type=float, default=4.0, help="Loop/programming RPC timeout in seconds.")
    parser.add_argument("--log-file", default=None, help="Optional server log file path.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Server log level.")
    parser.add_argument("--log-max-bytes", type=int, default=1_048_576, help="Max bytes per log file before rotation.")
    parser.add_argument("--log-backups", type=int, default=3, help="Number of rotated server log files to keep.")
    args = parser.parse_args(argv)

    _setup_logging(args.log_file, args.log_level, args.log_max_bytes, args.log_backups)
    LOG.info(
        "starting server backend=%s midi_in=%r midi_out=%r midi_port=%r",
        args.backend,
        args.midi_in,
        args.midi_out,
        args.midi_port,
    )

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
        rpc_timeout=max(0.1, float(args.rpc_timeout)),
        rpc_timeout_loop=max(0.1, float(args.rpc_timeout_loop)),
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
