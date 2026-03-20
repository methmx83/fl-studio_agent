import unittest

from fl_studio_agent_mcp.ollama_agent import _extract_json, _to_tool_calls


class OllamaMcpAgentTests(unittest.TestCase):
    def test_extract_json_reads_wrapped_json_block(self) -> None:
        obj = _extract_json('prefix {"final":"ok"} suffix')
        self.assertEqual(obj, {"final": "ok"})

    def test_to_tool_calls_returns_empty_when_model_finishes(self) -> None:
        self.assertEqual(_to_tool_calls({"final": "done"}), [])

    def test_to_tool_calls_parses_multiple_calls(self) -> None:
        calls = _to_tool_calls(
            {
                "tool_calls": [
                    {"tool": "fl_launch", "args": {}},
                    {"tool": "fl_set_tempo", "args": {"bpm": 94}},
                ]
            }
        )
        self.assertEqual(calls[0].tool, "fl_launch")
        self.assertEqual(calls[1].args, {"bpm": 94})


if __name__ == "__main__":
    unittest.main()
