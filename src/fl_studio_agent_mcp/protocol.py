from __future__ import annotations

import base64
import json
from dataclasses import dataclass


MANUFACTURER_ID = 0x7D  # non-commercial
SIG = b"FLA"
VERSION = 1

TYPE_REQ = 1
TYPE_RES = 2
TYPE_ERR = 3


@dataclass(frozen=True)
class Packet:
    msg_type: int
    req_id: int
    chunk_index: int
    chunk_count: int
    payload_b64_part: bytes


def encode_packets(msg_type: int, req_id: int, obj: object, *, max_payload: int = 180) -> list[bytes]:
    payload_json = json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("ascii", "strict")
    payload_b64 = base64.b64encode(payload_json)

    chunks = [payload_b64[i : i + max_payload] for i in range(0, len(payload_b64), max_payload)] or [b""]
    chunk_count = len(chunks)

    out: list[bytes] = []
    for idx, part in enumerate(chunks):
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
                idx & 0x7F,
                chunk_count & 0x7F,
            ]
        )
        out.append(bytes([0xF0]) + header + part + bytes([0xF7]))
    return out


def try_parse_packet(sysex_envelope: bytes) -> Packet | None:
    if not sysex_envelope:
        return None
    if sysex_envelope[0] != 0xF0 or sysex_envelope[-1] != 0xF7:
        return None

    data = sysex_envelope[1:-1]
    if len(data) < 10:
        return None
    if data[0] != MANUFACTURER_ID or data[1:4] != SIG or data[4] != VERSION:
        return None

    msg_type = data[5]
    req_id = ((data[6] & 0x7F) << 8) | (data[7] & 0x7F)
    chunk_index = data[8] & 0x7F
    chunk_count = data[9] & 0x7F
    payload_part = data[10:]

    return Packet(
        msg_type=msg_type,
        req_id=req_id,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        payload_b64_part=payload_part,
    )


def decode_payload(parts: list[bytes]) -> dict:
    joined = b"".join(parts)
    payload_json = base64.b64decode(joined or b"{}", validate=False)
    return json.loads(payload_json.decode("ascii", "strict"))

