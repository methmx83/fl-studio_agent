from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LlmPlan:
    launch: bool = False
    create_drumloop: bool = False
    bpm: float | None = None
    style: str | None = None
    bars: int | None = None
    key: str | None = None
    scale: str | None = None


def _ollama_chat(model: str, messages: list[dict[str, Any]], *, url: str) -> str:
    payload = {"model": model, "messages": messages, "stream": False, "options": {"temperature": 0.1}}
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


def plan_with_ollama(
    user_text: str,
    *,
    model: str,
    url: str = "http://localhost:11434/api/chat",
) -> LlmPlan:
    system = (
        "You control FL Studio via a small set of actions.\n"
        "Return ONLY JSON. No prose.\n"
        "\n"
        "Valid styles: rock, house, hiphop, trap.\n"
        "\n"
        "Output schema:\n"
        "{\n"
        '  "launch": true|false,\n'
        '  "create_drumloop": true|false,\n'
        '  "bpm": number|null,\n'
        '  "style": "rock|house|hiphop|trap"|null,\n'
        '  "bars": integer|null,\n'
        '  "key": "C|C#|D|D#|E|F|F#|G|G#|A|A#|B"|null,\n'
        '  "scale": "major|minor"|null\n'
        "}\n"
        "\n"
        "Rules:\n"
        "- If user asks to open FL Studio: launch=true.\n"
        "- If user asks for 4/4 drumloop/beat: create_drumloop=true.\n"
        "- If BPM not specified, use null.\n"
        "- If style not specified, use null.\n"
        "- If bars not specified, use null.\n"
        "- If key not specified, use null.\n"
        "- If scale not specified, use null.\n"
    )
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
    content = _ollama_chat(model, messages, url=url)
    obj = _extract_json(content)

    def _maybe_float(v) -> float | None:
        if v is None:
            return None
        return float(v)

    def _maybe_int(v) -> int | None:
        if v is None:
            return None
        return int(v)

    style = obj.get("style", None)
    if style is not None:
        style = str(style).strip().lower()
        if style not in ("rock", "house", "hiphop", "trap"):
            style = None
    key = obj.get("key", None)
    if key is not None:
        key = str(key).strip().upper()
        if key not in ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"):
            key = None

    scale = obj.get("scale", None)
    if scale is not None:
        scale = str(scale).strip().lower()
        if scale not in ("major", "minor"):
            scale = None

    return LlmPlan(
        launch=bool(obj.get("launch", False)),
        create_drumloop=bool(obj.get("create_drumloop", False)),
        bpm=_maybe_float(obj.get("bpm", None)),
        style=style,
        bars=_maybe_int(obj.get("bars", None)),
        key=key,
        scale=scale,
    )
