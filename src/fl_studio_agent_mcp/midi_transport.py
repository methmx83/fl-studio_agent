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
    def __init__(self, midi_in: str, midi_out: str | None = None, *, debug: bool = False):
        self._midi_in = midi_in
        self._midi_out = midi_out or midi_in
        self._debug = debug
        self._req_id = 1
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._inbox: "queue.Queue[tuple[int, dict, int]]" = queue.Queue()
        self._closed = False
        self._reconnect_wait_s = 0.75
        self._reconnect_max_wait_s = 12.0

        self._in = None
        self._out = None
        self._open_ports()

        self._thread = threading.Thread(target=self._reader, name="fl-agent-midi-reader", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._closed = True
        with self._io_lock:
            self._close_ports()

    def _close_ports(self) -> None:
        try:
            if self._in is not None:
                self._in.close()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._in = None
        try:
            if self._out is not None:
                self._out.close()
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._out = None

    def _open_ports(self) -> None:
        try:
            midi_in = mido.open_input(self._midi_in)
        except Exception as e:  # noqa: BLE001
            available_in = mido.get_input_names()
            available_out = mido.get_output_names()
            raise RuntimeError(
                "Failed to open MIDI input port. "
                f"Requested={self._midi_in!r}. Available inputs={available_in!r}. Available outputs={available_out!r}. "
                "If your loopMIDI port isn't listed, the Python MIDI backend can't see it on this system."
            ) from e

        try:
            midi_out = mido.open_output(self._midi_out)
        except Exception as e:  # noqa: BLE001
            try:
                midi_in.close()
            except Exception:  # noqa: BLE001
                pass
            available_in = mido.get_input_names()
            available_out = mido.get_output_names()
            raise RuntimeError(
                "Failed to open MIDI output port. "
                f"Requested={self._midi_out!r}. Available inputs={available_in!r}. Available outputs={available_out!r}."
            ) from e

        self._in = midi_in
        self._out = midi_out

    def _reconnect(self, reason: str) -> None:
        deadline = time.time() + self._reconnect_max_wait_s
        last_error: Exception | None = None

        while not self._closed and time.time() < deadline:
            try:
                self._open_ports()
                if self._debug:
                    print(f"[fl-agent-midi] reconnected ({reason}) in={self._midi_in!r} out={self._midi_out!r}")
                return
            except Exception as e:  # noqa: BLE001
                last_error = e
                time.sleep(self._reconnect_wait_s)

        raise RuntimeError(
            f"MIDI reconnect failed after {self._reconnect_max_wait_s:.1f}s ({reason})"
            + (f": {last_error}" if last_error else "")
        )

    def _reader(self) -> None:
        buffers: dict[int, dict] = {}
        last_seen: dict[int, float] = {}

        while not self._closed:
            with self._io_lock:
                midi_in = self._in
            if midi_in is None:
                time.sleep(0.05)
                continue

            try:
                for msg in midi_in:
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

                if self._closed:
                    return
            except Exception:  # noqa: BLE001
                pass

            with self._io_lock:
                if self._closed:
                    return
                self._close_ports()
                self._reconnect("reader stream interrupted")

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
        sent = False
        for attempt in range(2):
            try:
                with self._io_lock:
                    if self._out is None:
                        raise RuntimeError("MIDI output port is not available")
                    for pkt in packets:
                        # mido wants sysex data without 0xF0/0xF7
                        data = list(pkt[1:-1])
                        self._out.send(mido.Message("sysex", data=data))
                sent = True
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 1:
                    raise RuntimeError(f"Failed to send MIDI request {op} (req_id={req_id}): {e}") from e
                with self._io_lock:
                    self._close_ports()
                    self._reconnect(f"send failed for {op}: {type(e).__name__}")

        if not sent:
            raise RuntimeError(f"Failed to send MIDI request {op} (req_id={req_id})")

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
