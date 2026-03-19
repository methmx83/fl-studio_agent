from __future__ import annotations

from fl_studio_agent_mcp.patterns import render


def _bits_to_cells(bits: list[int]) -> str:
    return "".join("●" if bit else "·" for bit in bits)


def _group_cells(bits: list[int], *, steps_per_bar: int) -> str:
    chunks = [
        _bits_to_cells(bits[offset:offset + steps_per_bar])
        for offset in range(0, len(bits), steps_per_bar)
    ]
    return " | ".join(chunks)


def pattern_preview_lines(style: str, *, bars: int, steps_per_bar: int = 16) -> list[str]:
    pattern = render(style, total_steps=bars * steps_per_bar, steps_per_bar=steps_per_bar)
    rows: list[tuple[str, list[int] | None]] = [
        ("Kick", pattern.kick),
        ("Snare", pattern.snare),
        ("Hat", pattern.hat),
        ("Clap", pattern.clap),
        ("Bass", pattern.bass),
    ]
    lines = [f"Style: {style} | Bars: {bars} | Steps/Bar: {steps_per_bar}"]
    for label, bits in rows:
        if bits is None:
            continue
        lines.append(f"{label:<5} {_group_cells(bits, steps_per_bar=steps_per_bar)}")
    return lines
