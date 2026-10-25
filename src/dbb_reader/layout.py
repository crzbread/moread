"""Grapheme-aware terminal wrapping with stable source offsets."""
from bisect import bisect_right
from dataclasses import dataclass

import regex
from wcwidth import wcswidth


@dataclass(frozen=True)
class Line:
    start: int
    end: int
    text: str


def wrap(text: str, width: int) -> list[Line]:
    width = max(2, width)
    lines: list[Line] = []
    start = 0
    used = 0
    parts: list[str] = []
    for match in regex.finditer(r"\X", text):
        cluster = match.group()
        if cluster in ("\n", "\r\n"):
            lines.append(Line(start, match.end(), "".join(parts)))
            start, used, parts = match.end(), 0, []
            continue
        if cluster == "\t":
            cluster = " " * (4 - used % 4)
        cells = max(0, wcswidth(cluster))
        if used + cells > width and parts:
            lines.append(Line(start, match.start(), "".join(parts)))
            start, used, parts = match.start(), 0, []
        parts.append(cluster)
        used += cells
    if parts or not lines or start < len(text):
        lines.append(Line(start, len(text), "".join(parts)))
    return lines


def line_at(lines: list[Line], offset: int) -> int:
    return max(0, min(len(lines) - 1, bisect_right([line.start for line in lines], offset) - 1))
