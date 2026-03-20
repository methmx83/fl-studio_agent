import asyncio
import unittest

import fl_studio_agent_mcp.server as server


class _FakeRpcResult:
    def __init__(self, payload):
        self.payload = payload
        self.raw_type = 2


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def rpc(self, op, args=None, *, timeout_s):
        self.calls.append((op, args, timeout_s))
        return _FakeRpcResult(self.response)


class ServerPatternIndexToolTests(unittest.TestCase):
    def test_fl_create_drum_loop_passes_pattern_index(self) -> None:
        fake_client = _FakeClient({"ok": True, "result": {}})
        original_create_client = server._create_client
        try:
            server._create_client = lambda *args, **kwargs: fake_client
            app = server.create_app("fl-agent", backend="file", ipc_dir=".")
            asyncio.run(app.call_tool("fl_create_drum_loop", {"steps": 16, "pattern_index": 9}))
        finally:
            server._create_client = original_create_client

        self.assertEqual(fake_client.calls[0][0], "create_drum_loop")
        self.assertEqual(fake_client.calls[0][1]["pattern_index"], 9)

    def test_fl_create_4_4_drumloop_passes_pattern_index(self) -> None:
        fake_client = _FakeClient({"ok": True, "result": {}})
        original_create_client = server._create_client
        try:
            server._create_client = lambda *args, **kwargs: fake_client
            app = server.create_app("fl-agent", backend="file", ipc_dir=".")
            asyncio.run(app.call_tool("fl_create_4_4_drumloop", {"pattern_index": 11}))
        finally:
            server._create_client = original_create_client

        self.assertEqual(fake_client.calls[0][0], "set_stepseq")
        self.assertEqual(fake_client.calls[0][1]["pattern_index"], 11)

    def test_fl_get_stepseq_passes_pattern_index(self) -> None:
        fake_client = _FakeClient({"ok": True, "result": {"tracks": []}})
        original_create_client = server._create_client
        try:
            server._create_client = lambda *args, **kwargs: fake_client
            app = server.create_app("fl-agent", backend="file", ipc_dir=".")
            asyncio.run(app.call_tool("fl_get_stepseq", {"pattern_index": 5}))
        finally:
            server._create_client = original_create_client

        self.assertEqual(fake_client.calls[0][0], "get_stepseq")
        self.assertEqual(fake_client.calls[0][1]["pattern_index"], 5)


if __name__ == "__main__":
    unittest.main()
