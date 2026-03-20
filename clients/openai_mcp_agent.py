from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def _tool_summary(tools: list[Any]) -> str:
    lines = []
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description or ''}".rstrip())
        if tool.inputSchema:
            lines.append(f"  inputSchema: {json.dumps(tool.inputSchema, ensure_ascii=True)}")
    return "\n".join(lines)


def _openai_function_tools(tools: list[Any]) -> list[dict[str, Any]]:
    out = []
    for tool in tools:
        schema = tool.inputSchema if isinstance(tool.inputSchema, dict) else {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            }
        )
    return out


def _normalize_tools(tools: Any) -> list[Any]:
    if isinstance(tools, (list, tuple)):
        return list(tools)
    if hasattr(tools, "tools"):
        value = getattr(tools, "tools")
        if isinstance(value, list):
            return value
    raise TypeError(f"Unsupported tools payload: {type(tools).__name__}")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "model_dump"):
        try:
            dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        except TypeError:
            dumped = value.model_dump()
        return _jsonable(dumped)
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return repr(value)


def _responses_create(
    *,
    api_key: str,
    base_url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", "strict")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = e.reason or ""
        raise RuntimeError(f"OpenAI HTTP error: {e.code} {detail}".strip()) from e
    except OSError as e:
        raise RuntimeError(f"Failed to connect to OpenAI at {base_url!r}") from e
    return json.loads(body)


def _response_id(response: dict[str, Any]) -> str | None:
    value = response.get("id")
    return str(value) if value else None


def _extract_function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "function_call":
            continue
        raw_args = item.get("arguments") or "{}"
        if isinstance(raw_args, str):
            args = json.loads(raw_args)
        elif isinstance(raw_args, dict):
            args = raw_args
        else:
            args = {}
        out.append(
            {
                "name": str(item.get("name") or ""),
                "arguments": args,
                "call_id": str(item.get("call_id") or ""),
            }
        )
    return out


def _response_output_text(response: dict[str, Any]) -> str:
    value = response.get("output_text")
    if isinstance(value, str) and value.strip():
        return value

    parts: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for chunk in item.get("content", []) or []:
            if not isinstance(chunk, dict):
                continue
            if chunk.get("type") == "output_text" and isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
            elif chunk.get("type") == "text" and isinstance(chunk.get("text"), str):
                parts.append(chunk["text"])
    return "\n".join(part for part in parts if part.strip())


async def run_agent(
    *,
    model: str,
    openai_base_url: str,
    api_key: str,
    mcp_command: list[str],
    user_request: str,
    max_tool_rounds: int,
) -> int:
    server_params = StdioServerParameters(command=mcp_command[0], args=mcp_command[1:], env=os.environ.copy())
    system = (
        "You are an assistant that controls FL Studio via MCP tools.\n"
        "Use the minimum safe tool calls needed to satisfy the user.\n"
        "If the user asks to open FL Studio and create a drumloop, call fl_launch then fl_create_4_4_drumloop.\n"
        "Avoid redundant reads after successful writes unless verification helps.\n"
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = _normalize_tools(await session.list_tools())
            response = _responses_create(
                api_key=api_key,
                base_url=openai_base_url,
                payload={
                    "model": model,
                    "input": [
                        {"role": "system", "content": [{"type": "input_text", "text": system}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user_request}]},
                    ],
                    "tools": _openai_function_tools(mcp_tools),
                },
            )

            tool_results: list[dict[str, Any]] = []
            rounds = 0
            while rounds < max(1, int(max_tool_rounds)):
                calls = _extract_function_calls(response)
                if not calls:
                    break
                rounds += 1
                outputs = []
                for call in calls:
                    result = await session.call_tool(call["name"], call["arguments"])
                    payload = result[1] if isinstance(result, tuple) and len(result) > 1 else result
                    payload = _jsonable(payload)
                    tool_results.append({"tool": call["name"], "args": call["arguments"], "result": payload})
                    outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call["call_id"],
                            "output": json.dumps(payload, ensure_ascii=False),
                        }
                    )

                prev_id = _response_id(response)
                payload: dict[str, Any] = {
                    "model": model,
                    "input": outputs,
                    "tools": _openai_function_tools(mcp_tools),
                }
                if prev_id:
                    payload["previous_response_id"] = prev_id
                response = _responses_create(api_key=api_key, base_url=openai_base_url, payload=payload)

            final_payload = {
                "model": model,
                "tool_results": tool_results,
                "final_text": _response_output_text(response),
                "response_id": _response_id(response),
            }
            print(json.dumps(final_payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenAI GPT-5.x -> MCP agent for FL Studio")
    parser.add_argument("--model", default="gpt-5.4", help="OpenAI model name (default: gpt-5.4)")
    parser.add_argument(
        "--openai-base-url",
        default="https://api.openai.com/v1",
        help="OpenAI API base URL (default: https://api.openai.com/v1)",
    )
    parser.add_argument(
        "--mcp-cmd",
        default=None,
        help="Command to run the MCP server (default: current python -m fl_studio_agent_mcp.server --backend midi --midi-in ... --midi-out ...)",
    )
    parser.add_argument("--midi-in", default="fl-agent 0", help="MIDI input port for the MCP server")
    parser.add_argument("--midi-out", default="fl-agent 1", help="MIDI output port for the MCP server")
    parser.add_argument("--max-tool-rounds", type=int, default=8, help="Safety cap for repeated model/tool rounds")
    parser.add_argument("request", nargs="+", help="Natural-language request")
    args = parser.parse_args(argv)

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        print("Missing OPENAI_API_KEY.")
        return 2

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
            openai_base_url=args.openai_base_url,
            api_key=api_key,
            mcp_command=mcp_command,
            user_request=user_request,
            max_tool_rounds=args.max_tool_rounds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
