from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import mido

from .protocol import TYPE_ERR, TYPE_RES, TYPE_REQ, decode_payload, encode_packets, try_parse_packet


@dataclass(frozen=True)
class RpcResult:
    ok: bool
    payload: dict
    raw_type: int


class MidiBridgeClient:
    def __init__(self, port_name: str, *, debug: bool = False):
        self._port_name = port_name
        self._debug = debug
        self._req_id = 1
        self._lock = threading.Lock()
        self._inbox: "queue.Queue[tuple[int, dict, int]]" = queue.Queue()
        self._closed = False

        try:
            self._in = mido.open_input(port_name)
        except Exception as e:  # noqa: BLE001
            available_in = mido.get_input_names()
            available_out = mido.get_output_names()
            raise RuntimeError(
                "Failed to open MIDI input port. "
                f"Requested={port_name!r}. Available inputs={available_in!r}. Available outputs={available_out!r}. "
                "If your loopMIDI port isn't listed, the Python MIDI backend can't see it on this system."
            ) from e

        try:
            self._out = mido.open_output(port_name)
        except Exception as e:  # noqa: BLE001
            available_in = mido.get_input_names()
            available_out = mido.get_output_names()
            raise RuntimeError(
                "Failed to open MIDI output port. "
                f"Requested={port_name!r}. Available inputs={available_in!r}. Available outputs={available_out!r}."
            ) from e

        self._thread = threading.Thread(target=self._reader, name="fl-agent-midi-reader", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True
        try:
            self._in.close()
        finally:
            self._out.close()

    def _reader(self) -> None:
        buffers: dict[int, dict] = {}
        last_seen: dict[int, float] = {}

        for msg in self._in:
            if self._closed:
                return

            if msg.type != "sysex":
                continue

            envelope = bytes([0xF0] + list(msg.data) + [0xF7])
            packet = try_parse_packet(envelope)
            if packet is None:
                continue

            # Ignore our own requests if the port loops back
            if packet.msg_type == TYPE_REQ:
                continue

            buf = buffers.get(packet.req_id)
            if buf is None:
                buf = {"count": packet.chunk_count, "parts": {}}
                buffers[packet.req_id] = buf

            buf["parts"][packet.chunk_index] = packet.payload_b64_part
            last_seen[packet.req_id] = time.time()

            if len(buf["parts"]) < buf["count"]:
                self._cleanup(buffers, last_seen)
                continue

            parts = [buf["parts"][i] for i in range(buf["count"])]
            payload = decode_payload(parts)
            buffers.pop(packet.req_id, None)
            last_seen.pop(packet.req_id, None)
            self._inbox.put((packet.req_id, payload, packet.msg_type))

    @staticmethod
    def _cleanup(buffers: dict, last_seen: dict[int, float]) -> None:
        cutoff = time.time() - 10.0
        stale = [rid for rid, ts in last_seen.items() if ts < cutoff]
        for rid in stale:
            buffers.pop(rid, None)
            last_seen.pop(rid, None)

    def rpc(self, op: str, args: dict | None = None, *, timeout_s: float = 2.0) -> RpcResult:
        with self._lock:
            req_id = self._req_id & 0x3FFF
            self._req_id += 1

        request = {"op": op, "args": args or {}}
        packets = encode_packets(TYPE_REQ, req_id, request)
        for pkt in packets:
            # mido wants sysex data without 0xF0/0xF7
            data = list(pkt[1:-1])
            self._out.send(mido.Message("sysex", data=data))

        deadline = time.time() + timeout_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(f"Timeout waiting for response to {op} (req_id={req_id})")
            try:
                rid, payload, msg_type = self._inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            if rid != req_id:
                continue
            return RpcResult(ok=(msg_type == TYPE_RES and bool(payload.get("ok", False))), payload=payload, raw_type=msg_type)
