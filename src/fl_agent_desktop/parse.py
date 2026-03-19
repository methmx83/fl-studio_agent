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
    key: str | None = None
    scale: str | None = None


_STYLE_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(house|4otf|four[- ]on[- ]the[- ]floor)\b", re.I), "house"),
    (re.compile(r"\b(hiphop|hip-hop|boom[- ]?bap|boombap)\b", re.I), "hiphop"),
    (re.compile(r"\b(trap)\b", re.I), "trap"),
    (re.compile(r"\b(rock|basic|default)\b", re.I), "rock"),
]

_KEY_SCALE_MAP: list[re.Pattern[str]] = [
    re.compile(r"\bin\s+([a-g](?:#|b)?)\s+(major|minor|maj|min)\b", re.I),
    re.compile(r"\bkey\s*[:=]?\s*([a-g](?:#|b)?)(?=\s|$)", re.I),
    re.compile(r"\b([a-g](?:#|b)?)\s+(major|minor|maj|min)\b", re.I),
]


def _normalize_key(v: str | None) -> str | None:
    if not v:
        return None
    s = v.strip().upper()
    if not s:
        return None
    if len(s) > 1 and s[1] in ("#", "B"):
        return s[0] + s[1]
    return s[0]


def _normalize_scale(v: str | None) -> str | None:
    if not v:
        return None
    s = v.strip().lower()
    if s == "maj":
        return "major"
    if s == "min":
        return "minor"
    if s in ("major", "minor"):
        return s
    return None


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

    key = None
    scale = None
    for pat in _KEY_SCALE_MAP:
        m = pat.search(t)
        if not m:
            continue
        # group mapping allows optional 2nd capture group.
        g1 = m.group(1) if m.lastindex and m.lastindex >= 1 else None
        g2 = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        key = _normalize_key(g1) or key
        scale = _normalize_scale(g2) or scale
        if key and scale:
            break

    # Fallback for explicit "scale minor/major" without key.
    if scale is None:
        m = re.search(r"\bscale\s*[:=]?\s*(major|minor|maj|min)\b", t, re.I)
        if m:
            scale = _normalize_scale(m.group(1))

    return ParsedCommand(launch=launch, create_drumloop=create, bpm=bpm, style=style, bars=bars, key=key, scale=scale)
