"""Tests for modern features: hardware encoder command building, GUI import, and cancellation."""

from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from tiktok_quality.encoder import (
    build_encode_command,
    get_available_video_encoders,
    set_custom_ffmpeg_paths,
)
from tiktok_quality.gui import PRESETS, _USE_CTK
from tiktok_quality.compressbase import process_video


class TestModernFeatures(unittest.TestCase):
    def test_build_encode_command_libx264(self):
        cmd = build_encode_command(
            ffmpeg_path="ffmpeg",
            input_path="in.mp4",
            output_path="out.mp4",
            target_video_bitrate_kbps=5000,
            video_encoder="libx264",
        )
        self.assertIn("-c:v", cmd)
        self.assertIn("libx264", cmd)
        self.assertIn("-x264-params", cmd)
        self.assertIn("nal-hrd=cbr", cmd)

    def test_build_encode_command_nvenc(self):
        cmd = build_encode_command(
            ffmpeg_path="ffmpeg",
            input_path="in.mp4",
            output_path="out.mp4",
            target_video_bitrate_kbps=6000,
            video_encoder="h264_nvenc",
        )
        self.assertIn("-c:v", cmd)
        self.assertIn("h264_nvenc", cmd)
        self.assertIn("-rc", cmd)
        self.assertIn("cbr", cmd)

    def test_get_available_video_encoders(self):
        encoders = get_available_video_encoders()
        self.assertIsInstance(encoders, list)
        self.assertIn("libx264", encoders)

    def test_presets_exist(self):
        self.assertGreater(len(PRESETS), 0)
        self.assertIn("⚡ TikTok 1080p60 (Рекомендуемый)", PRESETS)

    def test_customtkinter_loaded(self):
        # We installed customtkinter, so _USE_CTK should be True
        self.assertTrue(_USE_CTK)

    def test_cancel_event_pre_check(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises((RuntimeError, FileNotFoundError)) as ctx:
            process_video("nonexistent.mp4", "out.mp4", cancel_event=cancel)
        self.assertTrue("not found" in str(ctx.exception) or "cancelled" in str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
