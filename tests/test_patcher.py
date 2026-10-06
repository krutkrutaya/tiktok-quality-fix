"""Tests for ISOBMFF box parser and patcher."""

from __future__ import annotations

import os
import sys
import struct
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tiktok_quality.patcher import (
    build_ftyp, patch_ftyp, zero_creation_times, fix_encoder_tag,
    parse_boxes, find_box, patch_handler_names, inflate_audio2_nb_frames,
    Box
)


class TestPatcher(unittest.TestCase):
    def test_build_and_patch_ftyp(self):
        ftyp = build_ftyp("isom", 512, ["isom", "iso2", "avc1", "mp41"])
        self.assertEqual(len(ftyp), 32)
        self.assertEqual(ftyp[4:8], b"ftyp")
        self.assertEqual(ftyp[8:12], b"isom")
        self.assertEqual(struct.unpack(">I", ftyp[12:16])[0], 512)

        data = bytearray(ftyp + b"\x00\x00\x00\x08free")
        patched = patch_ftyp(data, major_brand="mp42", minor_version=0, compatible_brands=["mp42", "isom"])
        self.assertEqual(patched[8:12], b"mp42")

    def test_fix_encoder_tag(self):
        raw = bytearray(b"some prefix Lavf60.16.100 some suffix")
        target = b"Lavf59.27.100"
        patched = fix_encoder_tag(raw, target=target)
        self.assertIn(target, patched)
        self.assertEqual(len(raw), len(patched))

    def test_zero_creation_times(self):
        # Create an mvhd v0 box with non-zero creation time
        # fullbox: size(4) + 'mvhd'(4) + version(1) + flags(3) + creation(4) + mod(4) + remainder(16)
        creation_time = 3800000000
        mod_time = 3800000001
        payload = (
            b"\x00\x00\x00\x00"  # version 0, flags 0
            + struct.pack(">II", creation_time, mod_time)
            + b"\x00" * 16
        )
        mvhd_box = struct.pack(">I4s", 8 + len(payload), b"mvhd") + payload
        data = bytearray(mvhd_box)

        patched = zero_creation_times(data)
        zeroed_creation = struct.unpack(">I", patched[12:16])[0]
        zeroed_mod = struct.unpack(">I", patched[16:20])[0]
        self.assertEqual(zeroed_creation, 0)
        self.assertEqual(zeroed_mod, 0)

    def test_box_tree_parse_and_serialize(self):
        inner = Box(b"free")
        inner.payload = b"hello"
        outer = Box(b"moov")
        outer.children = [inner]

        serialized = outer.serialize()
        self.assertEqual(serialized[4:8], b"moov")
        self.assertIn(b"free", serialized)
        self.assertIn(b"hello", serialized)

        parsed = parse_boxes(serialized, 0, len(serialized))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].type, b"moov")
        self.assertIsNotNone(parsed[0].children)
        self.assertEqual(parsed[0].children[0].type, b"free")
        self.assertEqual(parsed[0].children[0].payload, b"hello")

    def test_patch_handler_names(self):
        # Build an hdlr box with "VideoHandler"
        # fixed header: version(1)+flags(3)+pre(4)+type(4)+reserved(12) = 24 bytes
        hdlr_payload = b"\x00" * 8 + b"vide" + b"\x00" * 12 + b"VideoHandler\x00"
        hdlr_box = Box(b"hdlr")
        hdlr_box.payload = hdlr_payload

        mdia = Box(b"mdia")
        mdia.children = [hdlr_box]
        trak = Box(b"trak")
        trak.children = [mdia]
        moov = Box(b"moov")
        moov.children = [trak]

        raw = bytearray(moov.serialize())
        patched = patch_handler_names(raw)
        # Check that Pascal length \x0c (12) is prepended before VideoHandler
        self.assertIn(b"\x0cVideoHandler", patched)


if __name__ == "__main__":
    unittest.main()
