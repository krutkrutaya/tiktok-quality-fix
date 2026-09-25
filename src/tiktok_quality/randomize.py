"""Randomization helpers to avoid TikTok's manual moderation queue.

The original tool produced byte-identical output for identical input
and embedded a hardcoded signature string in udta, which TikTok likely
blacklisted. This module adds:

- A pool of unique filler NAL blocks (variable size + payload) used
  to pad mdat, so ghost-frame offsets and stsz entries are no longer
  all identical.
- Jittering of video stts so durations aren't perfectly uniform.
- A random comment string for udta, unique per file.
"""

from __future__ import annotations

import random
import secrets
import struct
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class RandomOptions:
    enabled: bool = False
    seed: int | None = None
    max_filler_payload: int = 128   # bytes of random payload per filler NAL (balanced)
    min_filler_payload: int = 16    # minimum payload size for better variance
    ts_jitter: int = 3              # max +/- ticks per stts entry (balanced)
    rng: random.Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        seed = self.seed if self.seed is not None else secrets.randbits(64)
        self.rng = random.Random(seed)


def make_filler_pool(opts: RandomOptions, count: int) -> List[bytes]:
    """Return `count` length-prefixed AVC NAL blocks.

    When `opts.enabled` is False, all blocks are identical 8-byte fillers
    (back-compat with the previous behaviour). When True, each block has
    a random payload size and content, so stco offsets and stsz sizes
    in the output become statistically indistinguishable from a normal
    video stream.
    """
    if count <= 0:
        return []
    if not opts.enabled:
        return [b'\x00\x00\x00\x04\x00\x00\x00\x00'] * count

    pool: List[bytes] = []
    for _ in range(count):
        # Use wider range for better variance (min_filler_payload to max_filler_payload)
        payload_len = opts.rng.randint(opts.min_filler_payload, opts.max_filler_payload)
        nal_header = 0x00  # NAL type 0 = unspecified, ignored by decoders
        payload = bytes(opts.rng.randint(0, 0xFF) for _ in range(payload_len))
        nal = bytes([nal_header]) + payload
        pool.append(struct.pack('>I', len(nal)) + nal)
    return pool


def expand_stts(entries: List[Tuple[int, int]]) -> List[int]:
    """Flatten [(count, delta), ...] into a per-sample delta list."""
    out: List[int] = []
    for c, d in entries:
        out.extend([d] * c)
    return out


def compress_stts(deltas: List[int]) -> List[Tuple[int, int]]:
    """Collapse a per-sample delta list back to run-length entries."""
    if not deltas:
        return []
    out: List[Tuple[int, int]] = []
    cur_d, cur_c = deltas[0], 1
    for d in deltas[1:]:
        if d == cur_d:
            cur_c += 1
        else:
            out.append((cur_c, cur_d))
            cur_d, cur_c = d, 1
    out.append((cur_c, cur_d))
    return out


def jitter_durations(deltas: List[int], opts: RandomOptions) -> List[int]:
    """Apply +/- `ts_jitter` random perturbations while preserving the sum.

    The total is restored by adjusting the last entry, so mdhd duration
    remains consistent.
    """
    if not opts.enabled or len(deltas) < 2 or opts.ts_jitter <= 0:
        return deltas
    out = deltas[:]
    total = sum(out)
    j = opts.ts_jitter
    for i in range(len(out) - 1):
        delta = opts.rng.randint(-j, j)
        if out[i] + delta >= 1:
            out[i] += delta
    out[-1] = max(1, total - sum(out[:-1]))
    return out


def random_comment() -> str:
    """A unique innocuous comment for the udta box."""
    return secrets.token_hex(8)
