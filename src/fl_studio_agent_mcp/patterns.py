from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrumPattern:
    kick: list[int]
    snare: list[int]
    hat: list[int]
    clap: list[int] | None = None


def _repeat(base: list[int], total_steps: int) -> list[int]:
    if not base:
        return []
    out: list[int] = []
    i = 0
    while len(out) < total_steps:
        out.append(base[i % len(base)])
        i += 1
    return out[:total_steps]


def get_style(style: str) -> DrumPattern:
    s = (style or "").strip().lower()
    if s in ("rock", "basic", "default"):
        # 16-step bar: kick on 1/2/3/4, snare on 2/4, hats 8ths
        return DrumPattern(
            kick=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        )
    if s in ("house", "four_on_the_floor", "4otf"):
        return DrumPattern(
            kick=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0],
        )
    if s in ("hiphop", "boom_bap", "boom-bap"):
        return DrumPattern(
            kick=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        )
    if s in ("trap",):
        # simple 8th hats; add one extra kick
        return DrumPattern(
            kick=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        )
    raise ValueError(f"Unknown style: {style!r}. Try rock/house/hiphop/trap.")


def render(style: str, *, total_steps: int, steps_per_bar: int = 16) -> DrumPattern:
    base = get_style(style)
    if steps_per_bar != 16:
        # For now, only scale by repetition; future: resample.
        pass
    return DrumPattern(
        kick=_repeat(base.kick, total_steps),
        snare=_repeat(base.snare, total_steps),
        hat=_repeat(base.hat, total_steps),
        clap=_repeat(base.clap, total_steps) if base.clap else None,
    )


def on_steps(bits: list[int]) -> list[int]:
    return [i for i, v in enumerate(bits) if v]

