from __future__ import annotations

DEFAULT_CHANNEL_MAP: dict[str, int] = {"kick": 0, "snare": 1, "hat": 2, "clap": 3, "bass": 4}
STYLE_OPTIONS = ("rock", "house", "hiphop", "trap")
PRESET_SETTINGS: dict[str, tuple[float, str, int]] = {
    "rock": (94.0, "rock", 1),
    "house": (128.0, "house", 1),
    "hiphop": (92.0, "hiphop", 1),
    "trap": (140.0, "trap", 1),
}


def mapping_label_text(name: str, channel_map: dict[str, int], one_based_cfg: bool) -> str:
    configured = channel_map.get(name)
    if configured is None:
        return "not mapped"
    internal = max(0, int(configured) - 1) if one_based_cfg else int(configured)
    if one_based_cfg:
        return f"configured {configured} → internal {internal}"
    return f"channel {internal}"


def resolved_loop_settings(
    current: tuple[float, str, int],
    bpm: float | None,
    style: str | None,
    bars: int | None,
) -> tuple[float, str, int]:
    current_bpm, current_style, current_bars = current
    return (
        bpm if bpm is not None else current_bpm,
        style or current_style,
        bars if bars is not None else current_bars,
    )
