from __future__ import annotations

from typing import Any


def coerce_timeout(value: Any, *, default: float = 2.0) -> float:
    try:
        timeout = float(value)
    except Exception:
        return default
    if timeout <= 0:
        return default
    return timeout


def safe_rpc(client: Any, op: str, args: dict | None = None, *, timeout_s: float = 2.0) -> dict[str, Any]:
    try:
        return client.rpc(op, args, timeout_s=timeout_s).payload
    except TimeoutError:
        return {
            "ok": False,
            "error": f"Timeout after {timeout_s:.2f}s waiting for FL Studio response to '{op}'.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"RPC '{op}' failed: {exc.__class__.__name__}: {exc}"}
