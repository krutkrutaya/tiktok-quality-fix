"""Lightweight heuristics to flag files that look obviously manipulated.

Not a security tool -- just enough to catch the self-signature patterns
this tool used to leave behind (uniform chunk offsets, uniform sample
sizes, legacy comment marker).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, List

LEGACY_SIGNATURE = b'TK8vY5VqBA6hUlo1yuGvNA'


def stco_uniqueness(offsets: List[int]) -> float:
    if not offsets:
        return 1.0
    return len(set(offsets)) / len(offsets)


def size_entropy(sizes: Iterable[int]) -> float:
    sizes = list(sizes)
    if not sizes:
        return 0.0
    c = Counter(sizes)
    n = len(sizes)
    return -sum((v / n) * math.log2(v / n) for v in c.values())


def check(data: bytes, video_offsets: List[int], video_sizes: List[int],
          tail_window: int = 200) -> dict:
    """Return a dict with `ok` flag and human-readable findings."""
    tail = video_sizes[-tail_window:] if len(video_sizes) > tail_window else video_sizes
    u = stco_uniqueness(video_offsets)
    h = size_entropy(tail)

    findings: List[str] = []
    if u < 0.5:
        findings.append(f"stco uniqueness too low ({u:.3f}) -- many offsets repeat")
    if h < 1.0:
        findings.append(f"tail stsz entropy too low ({h:.3f}) -- sample sizes nearly identical")
    if LEGACY_SIGNATURE in data:
        findings.append("legacy signature 'TK8vY5VqBA6hUlo1yuGvNA' present in moov")

    return {
        'ok': not findings,
        'stco_uniqueness': u,
        'tail_size_entropy': h,
        'findings': findings,
    }
