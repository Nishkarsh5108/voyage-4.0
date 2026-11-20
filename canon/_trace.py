"""Shadow bookkeeping for literal explanations of the rule-based parsers (canon.rooms, canon.activities).

The parsers consume their working string by blanking each match (`_take`). SpanTrace follows those edits with a position
map, so every match can be reported as a [start, end) span of the normalised string the parser started from. It only
observes: the parsers compute exactly what they computed before, whether a trace list is passed or not.
"""
from __future__ import annotations


class SpanTrace:
    def __init__(self, s: str, out: list):
        self.base = s
        self.pos = list(range(len(s)))  # pos[i]: index in the normalised string of char i of the working string (-1 = inserted)
        self.out = out

    def span(self, a: int, b: int):
        if self.pos is None:
            return None, None
        idx = [q for q in self.pos[a:b] if q >= 0]
        return (min(idx), max(idx) + 1) if idx else (None, None)

    def hit(self, m, group: str, attr: str, value, pattern: str, consume: bool = True, **extra) -> dict:
        """Record a regex match on the current working string; mirror `_take`'s blanking when it consumed the match."""
        start, end = self.span(m.start(), m.end())
        entry = {"group": group, "attr": attr, "value": value, "pattern": pattern, "matched": m.group(0), "start": start, "end": end}
        entry.update(extra)
        self.out.append(entry)
        if consume and self.pos is not None:
            self.pos = self.pos[:m.start()] + [-1] + self.pos[m.end():]
        return entry

    def note(self, group: str, attr: str, value, pattern: str, matched: str, **extra) -> dict:
        """Record a rule that fired on text outside the working string (no span)."""
        entry = {"group": group, "attr": attr, "value": value, "pattern": pattern, "matched": matched, "start": None, "end": None}
        entry.update(extra)
        self.out.append(entry)
        return entry

    def check(self, s: str) -> None:
        """Stop reporting spans if the map has drifted from the working string (never expected; spans are then omitted)."""
        if self.pos is not None and len(self.pos) != len(s):
            self.pos = None
