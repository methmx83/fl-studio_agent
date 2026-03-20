import asyncio
import json
import tempfile
import unittest
from pathlib import Path

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


class ServerStepseqToolTests(unittest.TestCase):
    def test_fl_get_stepseq_uses_template_mapping_by_default(self) -> None:
        fake_client = _FakeClient({"ok": True, "result": {"tracks": []}})
        original_create_client = server._create_client
        try:
            server._create_client = lambda *args, **kwargs: fake_client
            with tempfile.TemporaryDirectory() as tmp:
                config_path = Path(tmp) / "fl_agent_config.json"
                config_path.write_text(
                    json.dumps(
                        {
                            "template": {
                                "one_based": True,
                                "channels": {"kick": 1, "snare": 2, "hat": 3, "clap": 4, "bass": 5},
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                app = server.create_app("fl-agent", backend="file", ipc_dir=tmp, config_path=str(config_path))
                asyncio.run(app.call_tool("fl_get_stepseq", {}))
        finally:
            server._create_client = original_create_client

        self.assertEqual(fake_client.calls[0][0], "get_stepseq")
        self.assertEqual(
            fake_client.calls[0][1]["tracks"],
            [
                {"name": "kick", "channel": 0},
                {"name": "snare", "channel": 1},
                {"name": "hat", "channel": 2},
                {"name": "clap", "channel": 3},
                {"name": "bass", "channel": 4},
            ],
        )

    def test_fl_get_stepseq_passes_explicit_channels_and_total_steps(self) -> None:
        fake_client = _FakeClient({"ok": True, "result": {"tracks": []}})
        original_create_client = server._create_client
        try:
            server._create_client = lambda *args, **kwargs: fake_client
            app = server.create_app("fl-agent", backend="file", ipc_dir=".")
            asyncio.run(
                app.call_tool(
                    "fl_get_stepseq",
                    {"channels": [7, 9], "total_steps": 32, "include_step_params": False},
                )
            )
        finally:
            server._create_client = original_create_client

        self.assertEqual(fake_client.calls[0][1], {"tracks": [{"channel": 7}, {"channel": 9}], "include_step_params": False, "total_steps": 32})


if __name__ == "__main__":
    unittest.main()
