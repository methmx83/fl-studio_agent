from __future__ import annotations

from fl_studio_agent_mcp.patterns import normalize_key_scale, render_with_bassline


def _bits_to_cells(bits: list[int]) -> str:
    return "".join("●" if bit else "·" for bit in bits)


def _group_cells(bits: list[int], *, steps_per_bar: int) -> str:
    chunks = [
        _bits_to_cells(bits[offset:offset + steps_per_bar])
        for offset in range(0, len(bits), steps_per_bar)
    ]
    return " | ".join(chunks)


def pattern_preview_lines(
    style: str,
    *,
    bars: int,
    steps_per_bar: int = 16,
    key: str = "C",
    scale: str = "minor",
) -> list[str]:
    norm_key, norm_scale = normalize_key_scale(key, scale)
    pattern = render_with_bassline(
        style,
        total_steps=bars * steps_per_bar,
        steps_per_bar=steps_per_bar,
        key=norm_key,
        scale=norm_scale,
    )
    rows: list[tuple[str, list[int] | None]] = [
        ("Kick", pattern.kick),
        ("Snare", pattern.snare),
        ("Hat", pattern.hat),
        ("Clap", pattern.clap),
        ("Bass", pattern.bass),
    ]
    lines = [f"Style: {style} | Bars: {bars} | Steps/Bar: {steps_per_bar} | Key: {norm_key} {norm_scale}"]
    for label, bits in rows:
        if bits is None:
            continue
        lines.append(f"{label:<5} {_group_cells(bits, steps_per_bar=steps_per_bar)}")
    if pattern.bass_notes:
        compact = ", ".join(f"{ev.step}:{ev.note}({ev.degree})" for ev in pattern.bass_notes[:8])
        lines.append("Bass notes " + compact + (" ..." if len(pattern.bass_notes) > 8 else ""))
    return lines
