from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedCommand:
    launch: bool = False
    create_drumloop: bool = False
    bpm: float | None = None
    style: str | None = None
    bars: int | None = None


_STYLE_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(house|4otf|four[- ]on[- ]the[- ]floor)\b", re.I), "house"),
    (re.compile(r"\b(hiphop|hip-hop|boom[- ]?bap|boombap)\b", re.I), "hiphop"),
    (re.compile(r"\b(trap)\b", re.I), "trap"),
    (re.compile(r"\b(rock|basic|default)\b", re.I), "rock"),
]


def parse_command(text: str) -> ParsedCommand:
    t = (text or "").strip()
    if not t:
        return ParsedCommand()

    launch = bool(re.search(r"\b(open|launch|start|öffne|starte)\b", t, re.I)) and bool(
        re.search(r"\b(fl|flstudio|fl studio)\b", t, re.I)
    )
    create = bool(re.search(r"\b(drum ?loop|beat|drums|drumloop|loop)\b", t, re.I)) and bool(
        re.search(r"\b(4/4|four[- ]four|vier[- ]vier)\b", t, re.I)
    )

    bpm = None
    m = re.search(r"(\d{2,3}(?:[.,]\d+)?)\s*bpm\b", t, re.I)
    if m:
        bpm = float(m.group(1).replace(",", "."))

    bars = None
    m = re.search(r"\b(\d{1,2})\s*(bars?|takte?)\b", t, re.I)
    if m:
        bars = int(m.group(1))

    style = None
    for pat, s in _STYLE_MAP:
        if pat.search(t):
            style = s
            break

    return ParsedCommand(launch=launch, create_drumloop=create, bpm=bpm, style=style, bars=bars)

