from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RpcResult:
    ok: bool
    payload: dict
    raw_type: int


TYPE_RES = 2
TYPE_ERR = 3


class FileBridgeClient:
    def __init__(self, ipc_dir: str | None = None):
        base = ipc_dir or os.path.join(tempfile.gettempdir(), "fl_studio_agent_ipc")
        self._base = base
        self._inbox = os.path.join(base, "in")
        self._outbox = os.path.join(base, "out")
        os.makedirs(self._inbox, exist_ok=True)
        os.makedirs(self._outbox, exist_ok=True)
        self._req_id = 1

    def close(self) -> None:
        return

    def rpc(self, op: str, args: dict | None = None, *, timeout_s: float = 2.0) -> RpcResult:
        req_id = self._req_id
        self._req_id += 1

        req = {"id": req_id, "op": op, "args": args or {}}
        req_path = os.path.join(self._inbox, f"req_{req_id}.json")
        tmp_path = req_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(json.dumps(req, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        os.replace(tmp_path, req_path)

        res_path = os.path.join(self._outbox, f"res_{req_id}.json")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if os.path.exists(res_path):
                try:
                    with open(res_path, "rb") as f:
                        payload = json.loads(f.read().decode("utf-8", "strict"))
                finally:
                    try:
                        os.remove(res_path)
                    except Exception:
                        pass
                ok = bool(payload.get("ok", False))
                return RpcResult(ok=ok, payload=payload, raw_type=TYPE_RES if ok else TYPE_ERR)
            time.sleep(0.02)

        raise TimeoutError(f"Timeout waiting for response to {op} (req_id={req_id}) via file IPC at {self._base!r}")

