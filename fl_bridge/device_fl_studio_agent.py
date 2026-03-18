# name=FL Studio Agent (MCP Bridge)
#
# Minimal SysEx RPC bridge for FL Studio MIDI Controller Scripting.
# Install to: %USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\device_fl_studio_agent.py

import base64
import json
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


def OnIdle():
    _cleanup_chunks()


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

