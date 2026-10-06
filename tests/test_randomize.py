"""Tests for randomization and detectability."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tiktok_quality.randomize import (
    RandomOptions, make_filler_pool, expand_stts, compress_stts,
    jitter_durations, random_comment,
)
from tiktok_quality.detect import stco_uniqueness, size_entropy, check


class TestRandomize(unittest.TestCase):
    def test_filler_pool_disabled_is_identical(self):
        opts = RandomOptions(enabled=False)
        pool = make_filler_pool(opts, 3)
        self.assertEqual(len(pool), 3)
        self.assertEqual(len(set(pool)), 1)
        self.assertEqual(pool[0], b"\x00\x00\x00\x04\x00\x00\x00\x00")

    def test_filler_pool_enabled_is_varied(self):
        opts = RandomOptions(enabled=True, seed=1)
        pool = make_filler_pool(opts, 50)
        self.assertGreater(len(set(pool)), 10)
        for b in pool:
            size = int.from_bytes(b[:4], "big")
            self.assertEqual(size, len(b) - 4)
            self.assertGreaterEqual(size, 1)

    def test_filler_pool_reproducible_with_seed(self):
        a = make_filler_pool(RandomOptions(enabled=True, seed=42), 20)
        b = make_filler_pool(RandomOptions(enabled=True, seed=42), 20)
        self.assertEqual(a, b)

    def test_expand_compress_roundtrip(self):
        entries = [(3, 1500), (2, 1499)]
        self.assertEqual(compress_stts(expand_stts(entries)), entries)

    def test_jitter_preserves_sum(self):
        opts = RandomOptions(enabled=True, seed=1, ts_jitter=2)
        src = [1500] * 100
        out = jitter_durations(src, opts)
        self.assertEqual(len(out), len(src))
        self.assertTrue(all(d >= 1 for d in out))
        self.assertEqual(sum(out), sum(src))

    def test_jitter_disabled_is_identity(self):
        opts = RandomOptions(enabled=False)
        src = [1500] * 10
        self.assertEqual(jitter_durations(src, opts), src)

    def test_random_comment_unique(self):
        a, b = random_comment(), random_comment()
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 16)

    def test_stco_uniqueness(self):
        self.assertEqual(stco_uniqueness([1, 2, 3, 4]), 1.0)
        self.assertEqual(stco_uniqueness([1, 1, 1, 1]), 0.25)
        self.assertEqual(stco_uniqueness([]), 1.0)

    def test_size_entropy(self):
        self.assertEqual(size_entropy([8, 8, 8, 8]), 0.0)
        self.assertEqual(size_entropy([8, 16, 24, 32]), 2.0)

    def test_check_flags_legacy_signature(self):
        fake = b"....TK8vY5VqBA6hUlo1yuGvNA...."
        res = check(fake, [1, 2, 3], [10, 20, 30])
        self.assertFalse(res["ok"])
        self.assertTrue(any("legacy signature" in f for f in res["findings"]))

    def test_check_flags_uniform_stco(self):
        res = check(b"no sig here", [100, 100, 100, 100], [10, 20, 30, 40])
        self.assertFalse(res["ok"])
        self.assertTrue(any("stco uniqueness" in f for f in res["findings"]))

    def test_check_ok_on_healthy_file(self):
        res = check(b"no sig", [10, 20, 30, 40, 50], [10, 20, 30, 40, 50, 60])
        self.assertTrue(res["ok"])

    def test_filler_pool_zero_count(self):
        self.assertEqual(make_filler_pool(RandomOptions(enabled=True, seed=0), 0), [])
        self.assertEqual(make_filler_pool(RandomOptions(enabled=False), 0), [])


if __name__ == "__main__":
    unittest.main()
