"""Tests for MP4 parsing and building."""

from __future__ import annotations

import os
import sys
import struct
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tiktok_quality.mp4.parser import find_box, parse_stts, parse_stsz, read_u32
from tiktok_quality.mp4.builder import (
    build_box, build_ftyp, build_stts, build_stco, build_udta_comment, build_stsz
)


class TestMP4(unittest.TestCase):
    def test_build_box(self):
        box = build_box("test", b"\x01\x02\x03")
        self.assertEqual(len(box), 11)
        self.assertEqual(struct.unpack(">I", box[:4])[0], 11)
        self.assertEqual(box[4:8], b"test")
        self.assertEqual(box[8:], b"\x01\x02\x03")

    def test_build_ftyp(self):
        ftyp = build_ftyp()
        self.assertEqual(len(ftyp), 32)
        self.assertEqual(ftyp[8:12], b"isom")

    def test_build_stts(self):
        stts = build_stts([(1494, 1500), (13446, 1500)])
        self.assertEqual(len(stts), 32)
        self.assertEqual(struct.unpack(">I", stts[:4])[0], 32)

    def test_build_stco(self):
        stco = build_stco([100, 200, 300])
        self.assertEqual(len(stco), 28)

    def test_build_udta_comment(self):
        udta = build_udta_comment("TestTag123")
        self.assertIn(b"TestTag123", udta)
        self.assertIn(b"\xa9cmt", udta)

    def test_find_box(self):
        box1 = build_box("aaaa", b"\x00" * 4)
        box2 = build_box("bbbb", b"\x01" * 8)
        data = box1 + box2

        pos, size = find_box(data, "bbbb")
        self.assertEqual(pos, len(box1))
        self.assertEqual(size, len(box2))

    def test_parse_stts(self):
        entries = [(1494, 1500), (13446, 1500)]
        stts = build_stts(entries)
        parsed = parse_stts(stts, 0)
        self.assertEqual(parsed, entries)

    def test_parse_stsz(self):
        sizes = [519, 145, 67, 67, 190]
        stsz = build_stsz(sizes)
        parsed = parse_stsz(stsz, 0)
        self.assertEqual(parsed, sizes)


if __name__ == "__main__":
    unittest.main()
