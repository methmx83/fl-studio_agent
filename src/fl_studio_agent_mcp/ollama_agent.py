from __future__ import annotations

import asyncio
import json
import os
import re
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
    text = (text or "").strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in model output.")
    return json.loads(m.group(0))


def _to_tool_calls(obj: dict[str, Any]) -> list[ToolCall]:
    raw_calls = obj.get("tool_calls")
    if raw_calls is None:
        return []
    out: list[ToolCall] = []
    for tc in raw_calls:
        out.append(ToolCall(tool=str(tc["tool"]), args=dict(tc.get("args") or {})))
    return out


def _tool_summary(tools: list[Any]) -> str:
    lines = []
    for tool in tools:
        lines.append(f"- {tool.name}: {tool.description or ''}".rstrip())
        if tool.inputSchema:
            lines.append(f"  inputSchema: {json.dumps(tool.inputSchema, ensure_ascii=True)}")
    return "\n".join(lines)


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


async def run_ollama_mcp_agent(
    *,
    model: str,
    ollama_url: str,
    mcp_command: list[str],
    user_request: str,
    max_tool_rounds: int = 8,
) -> dict[str, Any]:
    server_params = StdioServerParameters(command=mcp_command[0], args=mcp_command[1:], env=os.environ.copy())
    system = (
        "You are an assistant that controls FL Studio via MCP tools.\n"
        "Return ONLY JSON. No prose outside JSON.\n"
        "Each reply must be exactly one of these shapes:\n"
        '{{ "tool_calls": [ {{"tool": "name", "args": {{...}}}}, ... ] }}\n'
        '{{ "final": "short result for the user" }}\n'
        "Use tools when runtime state matters. Do not invent tools or arguments.\n"
        "If the user asks to open FL Studio and create a drumloop, typically call fl_launch then fl_create_4_4_drumloop.\n"
        "Available tools:\n"
        "{tool_summary}\n"
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = _normalize_tools(await session.list_tools())
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system.format(tool_summary=_tool_summary(tools))},
                {"role": "user", "content": user_request},
            ]
            executed: list[dict[str, Any]] = []
            last_obj: dict[str, Any] | None = None

            for _round in range(max(1, int(max_tool_rounds))):
                content = _ollama_chat(model, messages, url=ollama_url)
                obj = _extract_json(content)
                last_obj = obj
                messages.append({"role": "assistant", "content": json.dumps(obj, ensure_ascii=False)})

                calls = _to_tool_calls(obj)
                if calls:
                    round_results = []
                    for call in calls:
                        result = await session.call_tool(call.tool, call.args)
                        payload = result[1] if isinstance(result, tuple) and len(result) > 1 else result
                        payload = _jsonable(payload)
                        record = {"tool": call.tool, "args": call.args, "result": payload}
                        executed.append(record)
                        round_results.append(record)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Tool results:\n"
                                + json.dumps(round_results, ensure_ascii=False, indent=2)
                                + "\nReturn ONLY JSON. If more actions are needed, emit tool_calls. Otherwise emit final."
                            ),
                        }
                    )
                    continue

                final = obj.get("final")
                if isinstance(final, str) and final.strip():
                    return {"tool_results": executed, "final_text": final.strip(), "raw": obj}

                raise ValueError("Model reply did not contain `tool_calls` or `final`.")

    return {"tool_results": executed, "final_text": "", "raw": last_obj or {}}


def run_ollama_mcp_agent_sync(
    *,
    model: str,
    ollama_url: str,
    mcp_command: list[str],
    user_request: str,
    max_tool_rounds: int = 8,
) -> dict[str, Any]:
    return asyncio.run(
        run_ollama_mcp_agent(
            model=model,
            ollama_url=ollama_url,
            mcp_command=mcp_command,
            user_request=user_request,
            max_tool_rounds=max_tool_rounds,
        )
    )
