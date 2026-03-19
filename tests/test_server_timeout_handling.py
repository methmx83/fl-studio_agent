import unittest

from fl_studio_agent_mcp.rpc_utils import coerce_timeout, safe_rpc


class _OkClient:
    def rpc(self, op, args=None, timeout_s=2.0):  # noqa: ANN001
        class _Res:
            payload = {"ok": True, "result": {"op": op, "args": args or {}, "timeout_s": timeout_s}}

        return _Res()


class _TimeoutClient:
    def rpc(self, op, args=None, timeout_s=2.0):  # noqa: ANN001
        raise TimeoutError(op)


class _CrashClient:
    def rpc(self, op, args=None, timeout_s=2.0):  # noqa: ANN001
        raise RuntimeError("bridge down")


class CoerceTimeoutTests(unittest.TestCase):
    def test_returns_default_for_invalid_values(self) -> None:
        self.assertEqual(coerce_timeout("x", default=2.0), 2.0)
        self.assertEqual(coerce_timeout(0, default=2.0), 2.0)
        self.assertEqual(coerce_timeout(-1, default=2.0), 2.0)

    def test_accepts_positive_numbers(self) -> None:
        self.assertEqual(coerce_timeout(3, default=2.0), 3.0)
        self.assertEqual(coerce_timeout("1.5", default=2.0), 1.5)


class SafeRpcTests(unittest.TestCase):
    def test_returns_payload_on_success(self) -> None:
        payload = safe_rpc(_OkClient(), "ping", timeout_s=1.25)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["result"]["op"], "ping")
        self.assertEqual(payload["result"]["timeout_s"], 1.25)

    def test_returns_structured_timeout_error(self) -> None:
        payload = safe_rpc(_TimeoutClient(), "set_tempo", timeout_s=2.5)
        self.assertFalse(payload["ok"])
        self.assertIn("Timeout after 2.50s", payload["error"])
        self.assertIn("set_tempo", payload["error"])

    def test_returns_structured_exception_error(self) -> None:
        payload = safe_rpc(_CrashClient(), "get_tempo", timeout_s=2.0)
        self.assertFalse(payload["ok"])
        self.assertIn("RPC 'get_tempo' failed", payload["error"])
        self.assertIn("RuntimeError", payload["error"])


if __name__ == "__main__":
    unittest.main()
