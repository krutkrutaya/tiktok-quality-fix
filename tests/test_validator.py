"""Tests for target spec validation and stream summary."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tiktok_quality.validator import validate_output, level_label, stream_summary


class TestValidator(unittest.TestCase):
    def setUp(self):
        self.valid_probe = {
            "format": {
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "duration": "12.345",
                "size": "5000000",
                "tags": {
                    "major_brand": "isom",
                    "compatible_brands": "isomiso2avc1mp41",
                    "comment": "Patched by CompressBase",
                },
            },
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "profile": "Constrained Baseline",
                    "level": 42,
                    "pix_fmt": "yuv420p",
                    "bit_rate": "15000000",
                    "width": 1080,
                    "height": 1920,
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "bit_rate": "192000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "bit_rate": "215000",
                },
            ],
        }

    def test_level_label(self):
        self.assertEqual(level_label(42), "4.2")
        self.assertEqual(level_label("42"), "4.2")
        self.assertEqual(level_label("4.2"), "4.2")
        self.assertEqual(level_label(None), "-")

    def test_validate_output_success(self):
        issues = validate_output(self.valid_probe)
        self.assertEqual(issues, [])

    def test_validate_output_missing_audio_track(self):
        probe = dict(self.valid_probe)
        # Only keep 1 audio track
        probe["streams"] = [self.valid_probe["streams"][0], self.valid_probe["streams"][1]]
        issues = validate_output(probe)
        self.assertTrue(any("audio tracks: expected 2" in i for i in issues))

    def test_validate_output_wrong_brand(self):
        probe = dict(self.valid_probe)
        probe["format"] = dict(self.valid_probe["format"])
        probe["format"]["tags"] = dict(self.valid_probe["format"]["tags"])
        probe["format"]["tags"]["major_brand"] = "mp42"
        issues = validate_output(probe)
        self.assertTrue(any("major_brand" in i for i in issues))

    def test_stream_summary(self):
        summary = stream_summary(self.valid_probe)
        self.assertEqual(summary["video"]["codec"], "h264")
        self.assertEqual(summary["video"]["profile"], "Constrained Baseline")
        self.assertEqual(summary["video"]["level"], "4.2")
        self.assertEqual(len(summary["audioTracks"]), 2)
        self.assertEqual(summary["audioTracks"][0]["sampleRate"], 48000)


if __name__ == "__main__":
    unittest.main()
