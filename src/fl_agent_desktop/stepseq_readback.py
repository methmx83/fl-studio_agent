from __future__ import annotations

from typing import Any


def _bits_to_cells(bits: list[int]) -> str:
    chars = ["x" if bit else "." for bit in bits]
    return " ".join("".join(chars[idx : idx + 4]) for idx in range(0, len(chars), 4))


def _group_cells(on_steps: list[int], *, total_steps: int, steps_per_bar: int) -> str:
    bits = [0] * max(0, int(total_steps))
    for step in on_steps:
        if 0 <= int(step) < len(bits):
            bits[int(step)] = 1
    groups = [
        _bits_to_cells(bits[offset : offset + steps_per_bar])
        for offset in range(0, len(bits), steps_per_bar)
    ]
    return " | ".join(groups) if groups else "-"


def _compact_param_map(values: dict[str, Any], *, limit: int = 8) -> str:
    pairs: list[tuple[int, int]] = []
    for key, value in values.items():
        try:
            pairs.append((int(key), int(value)))
        except Exception:
            continue
    pairs.sort()
    if not pairs:
        return "-"
    text = ", ".join(f"{step}:{value}" for step, value in pairs[:limit])
    if len(pairs) > limit:
        text += " ..."
    return text


def format_stepseq_snapshot(title: str, payload: dict[str, Any] | None, *, steps_per_bar: int = 16) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{title}: unavailable"]
    if not bool(payload.get("ok", False)):
        return [f"{title}: unavailable", f"error: {payload.get('error', payload)}"]

    result = payload.get("result")
    if not isinstance(result, dict):
        return [f"{title}: unavailable", "error: missing result payload"]

    pat_num = int(result.get("pat_num", 1))
    total_steps = max(1, int(result.get("total_steps", steps_per_bar)))
    max_param_steps = int(result.get("max_param_steps", 0))
    lines = [f"{title}: pattern {pat_num} | steps {total_steps} | param steps {max_param_steps}"]
    tracks = result.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        lines.append("No tracks")
        return lines

    for track in tracks:
        if not isinstance(track, dict):
            continue
        label = str(track.get("name") or f"ch {track.get('channel', '?')}").strip()
        on_steps = track.get("on_steps") if isinstance(track.get("on_steps"), list) else []
        lines.append(f"{label:<5} {_group_cells(on_steps, total_steps=total_steps, steps_per_bar=steps_per_bar)}")
        velocities = track.get("velocities")
        if isinstance(velocities, dict) and velocities:
            lines.append(f"  vel   {_compact_param_map(velocities)}")
        pitches = track.get("pitches")
        if isinstance(pitches, dict) and pitches:
            lines.append(f"  pitch {_compact_param_map(pitches)}")
        track_error = track.get("error")
        if isinstance(track_error, str) and track_error.strip():
            lines.append(f"  error {track_error}")
    warnings = result.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, str) and warning.strip():
                lines.append("warn  " + warning)
    return lines
