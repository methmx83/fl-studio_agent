from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BassNoteEvent:
    step: int
    degree: str
    note: str
    midi: int


@dataclass(frozen=True)
class DrumPattern:
    kick: list[int]
    snare: list[int]
    hat: list[int]
    clap: list[int] | None = None
    bass: list[int] | None = None
    bass_notes: list[BassNoteEvent] | None = None


def _repeat(base: list[int], total_steps: int) -> list[int]:
    if not base:
        return []
    out: list[int] = []
    i = 0
    while len(out) < total_steps:
        out.append(base[i % len(base)])
        i += 1
    return out[:total_steps]


_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_TO_SHARP = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}
_SCALE_INTERVALS: dict[str, tuple[int, ...]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),
}
_BASS_DEGREE_PATTERNS: dict[str, tuple[str, ...]] = {
    "rock": ("R", "5", "R", "8"),
    "house": ("R", "R", "5", "R"),
    "hiphop": ("R", "5", "R", "R"),
    "trap": ("R", "8", "5", "R"),
}


def normalize_key_scale(key: str | None, scale: str | None) -> tuple[str, str]:
    k = (key or "C").strip().upper().replace("♯", "#").replace("♭", "B")
    if not k:
        k = "C"
    if len(k) > 1 and k[1] in ("#", "B"):
        k = k[0] + k[1]
    else:
        k = k[0]
    if k not in _NOTE_NAMES:
        k = _FLAT_TO_SHARP.get(k, "C")

    s = (scale or "minor").strip().lower()
    if s in ("maj", "ionian"):
        s = "major"
    elif s in ("min", "aeolian", "natural_minor"):
        s = "minor"
    if s not in _SCALE_INTERVALS:
        s = "minor"
    return k, s


def _note_for_degree(root_key: str, scale: str, degree: str) -> str:
    root_idx = _NOTE_NAMES.index(root_key)
    intervals = _SCALE_INTERVALS[scale]
    if degree == "R":
        semis = intervals[0]
    elif degree == "5":
        semis = intervals[4]
    else:  # "8" (octave root)
        semis = intervals[0] + 12
    return _NOTE_NAMES[(root_idx + (semis % 12)) % 12]


def _midi_for_degree(root_key: str, scale: str, degree: str, *, base_octave: int = 2) -> int:
    root_idx = _NOTE_NAMES.index(root_key)
    intervals = _SCALE_INTERVALS[scale]
    if degree == "R":
        semis = intervals[0]
    elif degree == "5":
        semis = intervals[4]
    else:  # "8"
        semis = intervals[0] + 12
    # MIDI mapping: C-1=0, C4=60.
    midi_note = 12 * (base_octave + 1) + root_idx + semis
    return max(0, min(127, int(midi_note)))


def build_bassline(
    style: str,
    bass_bits: list[int] | None,
    *,
    key: str | None = None,
    scale: str | None = None,
) -> list[BassNoteEvent]:
    if not bass_bits:
        return []
    root_key, scale_name = normalize_key_scale(key, scale)
    style_key = (style or "").strip().lower()
    degree_cycle = _BASS_DEGREE_PATTERNS.get(style_key, ("R", "5", "R", "8"))

    events: list[BassNoteEvent] = []
    idx = 0
    for step, on in enumerate(bass_bits):
        if not on:
            continue
        degree = degree_cycle[idx % len(degree_cycle)]
        events.append(
            BassNoteEvent(
                step=step,
                degree=degree,
                note=_note_for_degree(root_key, scale_name, degree),
                midi=_midi_for_degree(root_key, scale_name, degree),
            )
        )
        idx += 1
    return events


def get_style(style: str) -> DrumPattern:
    s = (style or "").strip().lower()
    if s in ("rock", "basic", "default"):
        # 16-step bar: kick on 1/2/3/4, snare on 2/4, hats 8ths
        return DrumPattern(
            kick=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
            bass=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
        )
    if s in ("house", "four_on_the_floor", "4otf"):
        return DrumPattern(
            kick=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0],
            bass=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
        )
    if s in ("hiphop", "boom_bap", "boom-bap"):
        return DrumPattern(
            kick=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            clap=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            bass=[1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
        )
    if s in ("trap",):
        # simple 8th hats; add one extra kick
        return DrumPattern(
            kick=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0],
            snare=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            hat=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
            clap=[0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
            bass=[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
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
        bass=_repeat(base.bass, total_steps) if base.bass else None,
    )


def render_with_bassline(
    style: str,
    *,
    total_steps: int,
    steps_per_bar: int = 16,
    key: str | None = None,
    scale: str | None = None,
) -> DrumPattern:
    pat = render(style, total_steps=total_steps, steps_per_bar=steps_per_bar)
    bassline = build_bassline(style, pat.bass, key=key, scale=scale)
    return DrumPattern(
        kick=pat.kick,
        snare=pat.snare,
        hat=pat.hat,
        clap=pat.clap,
        bass=pat.bass,
        bass_notes=bassline or None,
    )


def on_steps(bits: list[int]) -> list[int]:
    return [i for i, v in enumerate(bits) if v]
