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


def _now_ms() -> int:
    return int(time.time() * 1000)


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


def _parse_and_dispatch(req) -> dict:
    op = req.get("op")
    args = req.get("args") or {}

    if op == "ping":
        return {"ok": True, "result": {"pong": True, "ts_ms": _now_ms()}}

    if op == "get_tempo":
        return {"ok": True, "result": {"bpm": float(mixer.getCurrentTempo())}}

    if op == "set_tempo":
        bpm = float(args.get("bpm"))
        # API docs indicate mixer.setCurrentTempo exists (not stubbed everywhere)
        mixer.setCurrentTempo(bpm, 0)
        return {"ok": True, "result": {"bpm": float(mixer.getCurrentTempo())}}

    if op == "create_drum_loop":
        bpm = float(args.get("bpm", 94.0))
        kick = int(args.get("kick_channel", 0))
        snare = int(args.get("snare_channel", 1))
        hat = int(args.get("hat_channel", 2))
        steps = int(args.get("steps", 16))

        mixer.setCurrentTempo(bpm, 0)

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
                "bpm": float(mixer.getCurrentTempo()),
                "kick_channel": kick,
                "snare_channel": snare,
                "hat_channel": hat,
                "steps": steps,
            },
        }

    return {"ok": False, "error": f"Unknown op: {op}"}


def OnInit():
    print("[fl-agent] initialized")
    try:
        # helps some setups keep output routing active; safe to call if available
        port_num = device.getPortNumber()
        print("[fl-agent] input port:", port_num)
    except Exception as e:
        print("[fl-agent] getPortNumber failed:", e)

    # IPC debug (some setups restrict file IO; this makes it visible in Script Output)
    try:
        base = _ipc_dir()
        inbox = os.path.join(base, "in")
        outbox = os.path.join(base, "out")
        print("[fl-agent] ipc base:", base)
        print("[fl-agent] ipc inbox exists:", os.path.isdir(inbox))
        print("[fl-agent] ipc outbox exists:", os.path.isdir(outbox))
    except Exception as e:
        print("[fl-agent] ipc init failed:", e)


def OnIdle():
    global _IPC_READY_PRINTED, _IPC_WRITE_TESTED
    _cleanup_chunks()
    _process_ipc_once()

    # One-time file IO probe so we can see whether FL allows reading/writing.
    if not _IPC_WRITE_TESTED:
        _IPC_WRITE_TESTED = True
        try:
            base = _ipc_dir()
            test_path = os.path.join(base, "fl_agent_ipc_test.txt")
            with open(test_path, "wb") as f:
                f.write(b"ok")
            print("[fl-agent] ipc write test: OK ->", test_path)
        except Exception as e:
            print("[fl-agent] ipc write test: FAILED:", e)


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
            _send(TYPE_ERR, req_id, {"ok": False, "error": str(e)})
        except Exception as e:
            _send(TYPE_ERR, req_id, {"ok": False, "error": f"{type(e).__name__}: {e}"})
    except Exception as e:
        try:
            _send(TYPE_ERR, 0, {"ok": False, "error": f"{type(e).__name__}: {e}"})
        except Exception:
            pass
