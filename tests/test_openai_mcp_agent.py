import unittest

from clients.openai_mcp_agent import _extract_function_calls, _openai_function_tools, _response_output_text


class _FakeTool:
    def __init__(self, name, description, input_schema):
        self.name = name
        self.description = description
        self.inputSchema = input_schema


class OpenAIMcpAgentTests(unittest.TestCase):
    def test_openai_function_tools_uses_mcp_schema(self) -> None:
        tools = _openai_function_tools([_FakeTool("fl_ping", "Ping FL", {"type": "object", "properties": {}})])
        self.assertEqual(
            tools,
            [
                {
                    "type": "function",
                    "name": "fl_ping",
                    "description": "Ping FL",
                    "parameters": {"type": "object", "properties": {}},
                }
            ],
        )

    def test_extract_function_calls_parses_arguments_json(self) -> None:
        calls = _extract_function_calls(
            {
                "output": [
                    {
                        "type": "function_call",
                        "name": "fl_set_tempo",
                        "arguments": "{\"bpm\": 128}",
                        "call_id": "call_123",
                    }
                ]
            }
        )
        self.assertEqual(calls, [{"name": "fl_set_tempo", "arguments": {"bpm": 128}, "call_id": "call_123"}])

    def test_response_output_text_falls_back_to_message_content(self) -> None:
        text = _response_output_text(
            {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "Done."},
                            {"type": "output_text", "text": "Loop created."},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(text, "Done.\nLoop created.")


if __name__ == "__main__":
    unittest.main()
