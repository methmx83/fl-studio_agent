from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict[str, Any]


def _ollama_chat(model: str, messages: list[dict[str, Any]], *, url: str) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.1},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "strict")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP error: {e.code} {e.reason}") from e
    except OSError as e:
        raise RuntimeError(f"Failed to connect to Ollama at {url!r}. Is Ollama running?") from e

    obj = json.loads(body)
    return (obj.get("message") or {}).get("content") or ""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    # Try to extract the first JSON object block.
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")
    return json.loads(m.group(0))


def _to_tool_calls(obj: dict[str, Any]) -> list[ToolCall]:
    if "tool_calls" in obj:
        out: list[ToolCall] = []
        for tc in obj["tool_calls"]:
            out.append(ToolCall(tool=str(tc["tool"]), args=dict(tc.get("args") or {})))
        return out
    if "tool" in obj:
        return [ToolCall(tool=str(obj["tool"]), args=dict(obj.get("args") or {}))]
    raise ValueError("JSON must contain `tool` or `tool_calls`.")


def _tool_summary(tools: list[Any]) -> str:
    lines = []
    for t in tools:
        lines.append(f"- {t.name}: {t.description or ''}".rstrip())
        if t.inputSchema:
            lines.append(f"  inputSchema: {json.dumps(t.inputSchema, ensure_ascii=True)}")
    return "\n".join(lines)


async def run_agent(
    *,
    model: str,
    ollama_url: str,
    mcp_command: list[str],
    user_request: str,
) -> int:
    server_params = StdioServerParameters(command=mcp_command[0], args=mcp_command[1:], env=os.environ.copy())

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            system = (
                "You are an assistant that controls FL Studio via MCP tools.\n"
                "Return ONLY JSON. No prose.\n"
                "Pick the minimal tool calls to satisfy the user.\n"
                "If the user asks to open FL Studio and create a drumloop, call fl_launch then fl_create_4_4_drumloop.\n"
                "Available tools:\n"
                f"{_tool_summary(tools)}\n"
                "\n"
                "Output format:\n"
                "{ \"tool_calls\": [ {\"tool\": \"name\", \"args\": {..}}, ... ] }\n"
            )

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_request},
            ]
            content = _ollama_chat(model, messages, url=ollama_url)
            obj = _extract_json(content)
            calls = _to_tool_calls(obj)

            for call in calls:
                result = await session.call_tool(call.tool, call.args)
                # Print the structured result; most UIs can parse JSON.
                print(json.dumps({"tool": call.tool, "args": call.args, "result": result[1]}, ensure_ascii=False, indent=2))

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ollama -> MCP agent for FL Studio")
    parser.add_argument("--model", default="llama3.2", help="Ollama model name (e.g. llama3.2)")
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434/api/chat",
        help="Ollama chat endpoint URL",
    )
    parser.add_argument(
        "--mcp-cmd",
        default=None,
        help="Command to run the MCP server (default: current python -m fl_studio_agent_mcp.server --backend midi --midi-in ... --midi-out ...)",
    )
    parser.add_argument("--midi-in", default="fl-agent 0", help="MIDI input port for the MCP server")
    parser.add_argument("--midi-out", default="fl-agent 1", help="MIDI output port for the MCP server")
    parser.add_argument("request", nargs="+", help="Natural-language request")
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip()
    if not user_request:
        print("Empty request.")
        return 2

    if args.mcp_cmd:
        mcp_command = args.mcp_cmd.split(" ")
    else:
        mcp_command = [
            sys.executable,
            "-m",
            "fl_studio_agent_mcp.server",
            "--backend",
            "midi",
            "--midi-in",
            args.midi_in,
            "--midi-out",
            args.midi_out,
        ]

    return asyncio.run(
        run_agent(
            model=args.model,
            ollama_url=args.ollama_url,
            mcp_command=mcp_command,
            user_request=user_request,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

