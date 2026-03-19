# name=FL Studio Agent (MCP Bridge)
#
# Minimal SysEx RPC bridge for FL Studio MIDI Controller Scripting.
# Install to: %USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\device_fl_studio_agent.py

import base64
import json
import os
import time

import channels
import device
import mixer
import patterns


MANUFACTURER_ID = 0x7D  # non-commercial
SIG = b"FLA"
VERSION = 1

TYPE_REQ = 1
TYPE_RES = 2
TYPE_ERR = 3

# simple chunk reassembly by request id
_chunks = {}  # req_id -> { "count": int, "parts": dict[int, bytes], "ts": float }

_IPC_DIR = None
_IPC_READY_PRINTED = False
_IPC_WRITE_TESTED = False
_LAST_IDLE_ERR_MS = {}
_IDLE_ERR_THROTTLE_MS = 2000
_LOG_FILE = None
_LOG_MAX_BYTES = 512 * 1024
_LOG_BACKUPS = 3


def _now_ms() -> int:
    return int(time.time() * 1000)


def _log_file_path() -> str:
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE
    base = _ipc_dir()
    logs = os.path.join(base, "logs")
    try:
        os.makedirs(logs, exist_ok=True)
    except Exception:
        pass
    _LOG_FILE = os.path.join(logs, "bridge.log")
    return _LOG_FILE


def _rotate_log_if_needed(path: str) -> None:
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) < _LOG_MAX_BYTES:
            return
        for idx in range(_LOG_BACKUPS - 1, 0, -1):
            src = path + "." + str(idx)
            dst = path + "." + str(idx + 1)
            if os.path.exists(src):
                try:
                    os.replace(src, dst)
                except Exception:
                    pass
        try:
            os.replace(path, path + ".1")
        except Exception:
            pass
    except Exception:
        pass


def _append_log_line(message: str) -> None:
    try:
        path = _log_file_path()
        _rotate_log_if_needed(path)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "ab") as f:
            f.write((ts + " " + message + "\n").encode("utf-8", "replace"))
    except Exception:
        pass


def _log(*parts) -> None:
    msg = " ".join(str(p) for p in parts)
    print(msg)
    _append_log_line(msg)


def _log_idle_error(tag: str, err: Exception) -> None:
    now = _now_ms()
    last = _LAST_IDLE_ERR_MS.get(tag, 0)
    if now - last >= _IDLE_ERR_THROTTLE_MS:
        _log("[fl-agent] idle error (" + tag + "):", err)
        _LAST_IDLE_ERR_MS[tag] = now


def _sysex_strip(envelope: bytes) -> bytes:
    # FlMidiMsg.sysex includes 0xF0 ... 0xF7
    if not envelope:
        return b""
    if envelope[0] == 0xF0:
        envelope = envelope[1:]
    if envelope and envelope[-1] == 0xF7:
        envelope = envelope[:-1]
    return envelope


def _sysex_wrap(data: bytes) -> bytes:
    return bytes([0xF0]) + data + bytes([0xF7])


def _encode_packet(msg_type: int, req_id: int, chunk_index: int, chunk_count: int, payload_b64: bytes) -> bytes:
    header = bytes(
        [
            MANUFACTURER_ID,
            SIG[0],
            SIG[1],
            SIG[2],
            VERSION,
            msg_type,
            (req_id >> 8) & 0x7F,
            req_id & 0x7F,
            chunk_index & 0x7F,
            chunk_count & 0x7F,
        ]
    )
    return _sysex_wrap(header + payload_b64)


def _send(msg_type: int, req_id: int, obj) -> None:
    payload_json = json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii", "strict")
    payload_b64 = base64.b64encode(payload_json)  # ASCII, 7-bit safe

    max_payload = 180  # conservative to avoid overflow issues
    chunks = [payload_b64[i : i + max_payload] for i in range(0, len(payload_b64), max_payload)]
    chunk_count = len(chunks) if chunks else 1

    if not chunks:
        chunks = [b""]

    for idx, part in enumerate(chunks):
        packet = _encode_packet(msg_type, req_id, idx, chunk_count, part)
        device.midiOutSysex(packet)


def _cleanup_chunks() -> None:
    # prevent unbounded growth if client disconnects mid-request
    cutoff = time.time() - 10.0
    dead = []
    for rid, info in _chunks.items():
        if info.get("ts", 0) < cutoff:
            dead.append(rid)
    for rid in dead:
        del _chunks[rid]

def _ipc_dir() -> str:
    global _IPC_DIR
    if _IPC_DIR is not None:
        return _IPC_DIR

    # Prefer the user's TEMP. If unavailable, fall back to a deterministic path.
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if not tmp:
        tmp = r"C:\Temp"
    base = os.path.join(tmp, "fl_studio_agent_ipc")
    inbox = os.path.join(base, "in")
    outbox = os.path.join(base, "out")
    try:
        os.makedirs(inbox, exist_ok=True)
        os.makedirs(outbox, exist_ok=True)
    except Exception:
        # directory creation might fail under some permission flags; keep path anyway
        pass
    _IPC_DIR = base
    return base


def _process_ipc_once() -> None:
    base = _ipc_dir()
    inbox = os.path.join(base, "in")
    outbox = os.path.join(base, "out")
    try:
        names = os.listdir(inbox)
    except Exception:
        return

    # process a single request per idle tick to keep OnIdle fast
    req_name = None
    for n in names:
        if n.startswith("req_") and n.endswith(".json"):
            req_name = n
            break
    if req_name is None:
        return

    req_path = os.path.join(inbox, req_name)
    try:
        with open(req_path, "rb") as f:
            req = json.loads(f.read().decode("utf-8", "strict"))
    except Exception as e:
        try:
            os.remove(req_path)
        except Exception:
            pass
        return

    try:
        os.remove(req_path)
    except Exception:
        pass

    req_id = int(req.get("id", 0))
    try:
        res = _parse_and_dispatch({"op": req.get("op"), "args": req.get("args") or {}})
    except TypeError as e:
        res = {"ok": False, "error": str(e)}
    except Exception as e:
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    try:
        with open(os.path.join(outbox, f"res_{req_id}.json"), "wb") as f:
            f.write(json.dumps(res, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except Exception:
        pass


def _try_transport_method(action: str) -> dict:
    # Keep imports local; these modules only exist in FL's Python runtime.
    try:
        import transport  # type: ignore
    except Exception:
        transport = None

    method_names = {
        "play": ("start", "play"),
        "stop": ("stop",),
        "record": ("record", "recordToggle", "toggleRecord"),
    }
    for name in method_names.get(action, ()):
        if transport is not None and hasattr(transport, name):
            fn = getattr(transport, name)
            try:
                fn()
            except TypeError:
                fn(1)
            return {"method": "transport." + name}
    return {}


def _try_global_transport(action: str) -> dict:
    try:
        import midi  # type: ignore
        import transport  # type: ignore
    except Exception:
        return {}

    if not hasattr(transport, "globalTransport"):
        return {}

    constant_candidates = {
        "play": ("FPT_Play",),
        "stop": ("FPT_Stop",),
        "record": ("FPT_Record", "FPT_RecordOnOff"),
        "panic": ("FPT_F12", "FPT_Panic", "FPT_StopAllSound"),
    }
    for cname in constant_candidates.get(action, ()):
        if hasattr(midi, cname):
            cmd = getattr(midi, cname)
            try:
                transport.globalTransport(cmd, 1)
            except TypeError:
                transport.globalTransport(cmd, 1, 0)
            return {"method": "transport.globalTransport", "command": cname}
    return {}


def _transport_action(action: str) -> dict:
    action = str(action or "").strip().lower()
    if action not in ("play", "stop", "record", "panic"):
        raise ValueError("Invalid transport action: " + action)

    info = _try_transport_method(action)
    if info:
        return info

    info = _try_global_transport(action)
    if info:
        return info

    raise RuntimeError("No supported FL transport API path found for action=" + action)


def _parse_and_dispatch(req) -> dict:
    op = req.get("op")
    args = req.get("args") or {}

    def _set_tempo_bpm(bpm: float) -> None:
        # FL returns tempo as BPM*1000. setCurrentTempo behavior varies across versions/builds,
        # so try a few safe call patterns.
        last_err = None
        for value, as_int in (
            (bpm, 0),
            (int(round(bpm * 1000.0)), 0),
            (int(round(bpm * 1000.0)), 1),
        ):
            try:
                mixer.setCurrentTempo(value, as_int)
                return
            except Exception as e:
                last_err = e
        if last_err is not None:
            raise last_err

    if op == "ping":
        return {"ok": True, "result": {"pong": True, "ts_ms": _now_ms()}}

    if op == "get_tempo":
        # FL returns tempo as BPM * 1000 (e.g. 130000 == 130.000 BPM)
        return {"ok": True, "result": {"bpm": float(mixer.getCurrentTempo()) / 1000.0}}

    if op == "get_pattern_info":
        try:
            pat = int(patterns.patternNumber())
        except Exception:
            pat = 1
        try:
            length_beats = int(patterns.getPatternLength(pat))
        except Exception:
            length_beats = None
        return {"ok": True, "result": {"pattern": pat, "length_beats": length_beats}}

    if op == "set_tempo":
        bpm = float(args.get("bpm"))
        _set_tempo_bpm(bpm)
        return {"ok": True, "result": {"bpm": float(mixer.getCurrentTempo()) / 1000.0}}

    if op == "transport_control":
        action = str(args.get("action", "")).strip().lower()
        detail = _transport_action(action)
        return {"ok": True, "result": {"action": action, **detail}}

    if op == "panic":
        stop_result = None
        panic_result = None
        errors = []
        try:
            stop_result = _transport_action("stop")
        except Exception as e:
            errors.append("stop:" + str(e))
        try:
            panic_result = _transport_action("panic")
        except Exception as e:
            errors.append("panic:" + str(e))
        if stop_result is None and panic_result is None:
            raise RuntimeError("panic failed: " + "; ".join(errors))
        return {
            "ok": True,
            "result": {
                "action": "panic",
                "stop": stop_result,
                "panic": panic_result,
                "warnings": errors,
            },
        }

    if op == "create_drum_loop":
        bpm = float(args.get("bpm", 94.0))
        kick = int(args.get("kick_channel", 0))
        snare = int(args.get("snare_channel", 1))
        hat = int(args.get("hat_channel", 2))
        steps = int(args.get("steps", 16))

        _set_tempo_bpm(bpm)

        # clear + set steps
        for ch in (kick, snare, hat):
            for s in range(steps):
                channels.setGridBit(ch, s, False)

        # 4-on-the-floor kick
        for s in range(0, steps, 4):
            channels.setGridBit(kick, s, True)

        # backbeat snare on 2 and 4 (assuming 16 steps = 1 bar, 4 steps per beat)
        if steps >= 16:
            channels.setGridBit(snare, 4, True)
            channels.setGridBit(snare, 12, True)

        # 8th hats
        for s in range(0, steps, 2):
            channels.setGridBit(hat, s, True)

        return {
            "ok": True,
            "result": {
                "bpm": float(mixer.getCurrentTempo()) / 1000.0,
                "kick_channel": kick,
                "snare_channel": snare,
                "hat_channel": hat,
                "steps": steps,
            },
        }

    if op == "set_stepseq":
        bpm = args.get("bpm", None)
        if bpm is not None:
            _set_tempo_bpm(float(bpm))

        steps_per_bar = int(args.get("steps_per_bar", 16))
        bars = int(args.get("bars", 1))
        total_steps = int(args.get("total_steps", steps_per_bar * bars))
        # 1-indexed pattern number. Default to the currently active pattern.
        pat_num = args.get("pat_num", None)
        if pat_num is None:
            try:
                pat_num = patterns.patternNumber()
            except Exception:
                pat_num = 1
        pat_num = int(pat_num)

        try:
            pattern_len_beats = int(patterns.getPatternLength(pat_num))
        except Exception:
            pattern_len_beats = 4
        if pattern_len_beats < 1:
            pattern_len_beats = 1
        # setStepParameterByIndex appears to be limited to the pattern length.
        max_param_steps = pattern_len_beats * 4
        bass_mode = str(args.get("bass_mode", "step")).strip().lower()
        if bass_mode not in ("step", "step_pitch", "piano_roll"):
            bass_mode = "step"
        warnings = []
        if bass_mode == "piano_roll":
            # FL MIDI device API does not expose a stable direct piano-roll note-write callback.
            # Fallback to step pitch parameters for now.
            warnings.append("bass_mode=piano_roll is not directly supported by this API; used step_pitch fallback")
            bass_mode = "step_pitch"

        tracks = args.get("tracks") or []
        # track: { "channel": int, "on_steps": [int], "velocities": { "step": int } }
        for tr in tracks:
            ch = int(tr.get("channel"))
            # clear
            for s in range(total_steps):
                channels.setGridBit(ch, s, False)

        for tr in tracks:
            ch = int(tr.get("channel"))
            on_steps = tr.get("on_steps") or []
            for s in on_steps:
                channels.setGridBit(ch, int(s), True)

            velocities = tr.get("velocities") or {}
            # Step parameter type 1 is velocity (0..127).
            failed = False
            for k, v in velocities.items():
                step = int(k)
                if step < 0 or step >= max_param_steps:
                    continue
                vel = int(v)
                if vel < 0:
                    vel = 0
                if vel > 127:
                    vel = 127
                try:
                    channels.setStepParameterByIndex(ch, pat_num, step, 1, vel, False)
                except Exception:
                    # Some projects/patterns expose a smaller step-param range; don't fail the whole request.
                    failed = True
                    break

            if bass_mode == "step_pitch":
                pitches = tr.get("pitches") or {}
                for k, v in pitches.items():
                    step = int(k)
                    if step < 0 or step >= max_param_steps:
                        continue
                    pitch = int(v)
                    if pitch < 0:
                        pitch = 0
                    if pitch > 127:
                        pitch = 127
                    try:
                        # pPitch = 0 (see FL MIDI scripting docs step parameters table).
                        channels.setStepParameterByIndex(ch, pat_num, step, 0, pitch, False)
                    except Exception:
                        failed = True
                        break
            if failed:
                warnings.append("some step parameters could not be applied for channel " + str(ch))

        return {
            "ok": True,
            "result": {
                "bpm": float(mixer.getCurrentTempo()) / 1000.0,
                "steps_per_bar": steps_per_bar,
                "bars": bars,
                "total_steps": total_steps,
                "pat_num": pat_num,
                "pattern_len_beats": pattern_len_beats,
                "max_param_steps": max_param_steps,
                "bass_mode": bass_mode,
                "warnings": warnings,
                "tracks": [{"channel": int(t.get("channel"))} for t in tracks],
            },
        }

    return {"ok": False, "error": f"Unknown op: {op}"}


def OnInit():
    _log("[fl-agent] initialized")
    try:
        # helps some setups keep output routing active; safe to call if available
        port_num = device.getPortNumber()
        _log("[fl-agent] input port:", port_num)
    except Exception as e:
        _log("[fl-agent] getPortNumber failed:", e)

    # IPC debug (some setups restrict file IO; this makes it visible in Script Output)
    try:
        base = _ipc_dir()
        inbox = os.path.join(base, "in")
        outbox = os.path.join(base, "out")
        _log("[fl-agent] ipc base:", base)
        _log("[fl-agent] ipc inbox exists:", os.path.isdir(inbox))
        _log("[fl-agent] ipc outbox exists:", os.path.isdir(outbox))
        _log("[fl-agent] log file:", _log_file_path())
    except Exception as e:
        _log("[fl-agent] ipc init failed:", e)


def OnIdle():
    global _IPC_READY_PRINTED, _IPC_WRITE_TESTED
    try:
        _cleanup_chunks()
    except Exception as e:
        _log_idle_error("cleanup_chunks", e)

    try:
        _process_ipc_once()
    except Exception as e:
        _log_idle_error("process_ipc", e)

    # One-time file IO probe so we can see whether FL allows reading/writing.
    if not _IPC_WRITE_TESTED:
        _IPC_WRITE_TESTED = True
        try:
            base = _ipc_dir()
            test_path = os.path.join(base, "fl_agent_ipc_test.txt")
            with open(test_path, "wb") as f:
                f.write(b"ok")
            _log("[fl-agent] ipc write test: OK ->", test_path)
        except Exception as e:
            _log("[fl-agent] ipc write test: FAILED:", e)


def OnSysEx(msg):
    try:
        raw = _sysex_strip(msg.sysex)
        if len(raw) < 10:
            return

        if raw[0] != MANUFACTURER_ID or raw[1:4] != SIG or raw[4] != VERSION:
            return

        msg_type = raw[5]
        if msg_type != TYPE_REQ:
            return  # ignore non-requests (prevents loops on same port)

        req_id = ((raw[6] & 0x7F) << 8) | (raw[7] & 0x7F)
        chunk_index = raw[8] & 0x7F
        chunk_count = raw[9] & 0x7F
        payload_part = raw[10:]

        info = _chunks.get(req_id)
        if info is None:
            info = {"count": chunk_count, "parts": {}, "ts": time.time()}
            _chunks[req_id] = info

        info["parts"][chunk_index] = payload_part
        info["ts"] = time.time()

        if len(info["parts"]) < info["count"]:
            return

        ordered = b"".join(info["parts"][i] for i in range(info["count"]))
        del _chunks[req_id]

        payload_json = base64.b64decode(ordered or b"{}", validate=False)
        req = json.loads(payload_json.decode("ascii", "strict"))

        try:
            res = _parse_and_dispatch(req)
            _send(TYPE_RES, req_id, res)
        except TypeError as e:
            # FL uses TypeError("Operation unsafe at current time") for permission issues
            _append_log_line("[fl-agent] request TypeError req_id=" + str(req_id) + " err=" + str(e))
            _send(TYPE_ERR, req_id, {"ok": False, "error": str(e)})
        except Exception as e:
            _append_log_line("[fl-agent] request Exception req_id=" + str(req_id) + " err=" + str(type(e).__name__) + ": " + str(e))
            _send(TYPE_ERR, req_id, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    except Exception as e:
        _append_log_line("[fl-agent] OnSysEx outer Exception err=" + str(type(e).__name__) + ": " + str(e))
        try:
            _send(TYPE_ERR, 0, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
