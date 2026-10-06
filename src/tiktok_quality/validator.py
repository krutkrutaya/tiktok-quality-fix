"""
validator.py
------------
Validation utilities and target specification checks for CompressBase video outputs.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Any, List, Optional
from .encoder import get_video_stream, get_audio_streams, get_video_bitrate, get_duration_seconds


SPEC_PATH = os.path.join(os.path.dirname(__file__), "target_spec.json")

DEFAULT_TARGET_SPEC = {
    "format": {
        "major_brand": "isom",
        "compatible_brands": "isomiso2avc1mp41",
        "require_no_creation_time": True,
    },
    "streams": {
        "video": {
            "codec_name": "h264",
            "profile": "Constrained Baseline",
            "level": "4.2",
            "pix_fmt": "yuv420p",
            "bitrate_range_kbps": [500, 60000],
        },
        "audio": {
            "count": 2,
            "codec_name": "aac",
            "sample_rate": 48000,
        },
    },
}


def load_target_spec() -> Dict[str, Any]:
    """Load target specification from JSON file or fall back to defaults."""
    if os.path.isfile(SPEC_PATH):
        try:
            with open(SPEC_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_TARGET_SPEC


def level_label(level: Any) -> str:
    """Format numeric or string level (e.g. 42 -> 4.2)."""
    if level in (None, "N/A"):
        return "-"
    try:
        value = float(level)
        return f"{value / 10:.1f}" if value >= 10 else str(value)
    except (TypeError, ValueError):
        return str(level)


def stream_summary(probe_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a clean summary of video and audio tracks from probe data."""
    video = get_video_stream(probe_data)
    audio = get_audio_streams(probe_data)

    if video is None:
        raise RuntimeError("No video stream found in probe data.")

    video_bitrate = get_video_bitrate(probe_data)
    video_summary = {
        "codec": video.get("codec_name", "unknown"),
        "profile": video.get("profile", "unknown"),
        "level": level_label(video.get("level")),
        "pixelFormat": video.get("pix_fmt", "unknown"),
        "bitrateKbps": round(video_bitrate / 1000, 1),
        "width": video.get("width"),
        "height": video.get("height"),
    }

    audio_summary = []
    for stream in audio:
        raw_bitrate = stream.get("bit_rate")
        bitrate = 0 if raw_bitrate in (None, "N/A") else int(raw_bitrate)
        sample_rate = stream.get("sample_rate")
        channels = stream.get("channels")
        audio_summary.append({
            "codec": stream.get("codec_name", "unknown"),
            "sampleRate": int(sample_rate) if sample_rate not in (None, "N/A") else 0,
            "channels": int(channels) if channels not in (None, "N/A") else 0,
            "bitrateKbps": round(bitrate / 1000, 1),
        })

    fmt = probe_data.get("format", {})
    tags = fmt.get("tags", {})
    return {
        "durationSeconds": round(get_duration_seconds(probe_data), 3),
        "sizeBytes": int(fmt.get("size", 0) or 0),
        "video": video_summary,
        "audioTracks": audio_summary,
        "format": fmt.get("format_name"),
        "brands": tags.get("compatible_brands"),
    }


def validate_output(
    output_probe: Dict[str, Any],
    spec: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Compare output ffprobe result against target spec.
    Returns list of human-readable mismatch strings (empty list means fully valid).
    """
    if spec is None:
        spec = load_target_spec()

    issues: List[str] = []
    fmt = output_probe.get("format", {})
    fmt_tags = fmt.get("tags", {})

    # Format checks
    spec_fmt = spec.get("format", {})
    if "major_brand" in spec_fmt:
        actual = fmt_tags.get("major_brand", fmt.get("major_brand", ""))
        if actual != spec_fmt["major_brand"]:
            issues.append(f"major_brand: expected '{spec_fmt['major_brand']}', got '{actual}'")

    if "compatible_brands" in spec_fmt:
        actual = fmt_tags.get("compatible_brands", fmt.get("compatible_brands", ""))
        if actual != spec_fmt["compatible_brands"]:
            issues.append(f"compatible_brands: expected '{spec_fmt['compatible_brands']}', got '{actual}'")

    if spec_fmt.get("require_no_creation_time"):
        ct = fmt_tags.get("creation_time", "")
        if ct and ct not in ("", "1904-01-01T00:00:00.000000Z", "0001-01-01T00:00:00.000000Z"):
            issues.append(f"creation_time not removed from format tags (got '{ct}')")

    # Stream checks
    spec_streams = spec.get("streams", {})
    video_stream = get_video_stream(output_probe)
    audio_streams = get_audio_streams(output_probe)

    if video_stream:
        sv = spec_streams.get("video", {})
        if "codec_name" in sv and video_stream.get("codec_name") != sv["codec_name"]:
            issues.append(f"video codec: expected '{sv['codec_name']}', got '{video_stream.get('codec_name')}'")

        if "profile" in sv:
            vp = video_stream.get("profile", "")
            if sv["profile"].lower() not in vp.lower() and "baseline" not in vp.lower():
                issues.append(f"video profile: expected '{sv['profile']}', got '{vp}'")

        if "level" in sv:
            actual_level = video_stream.get("level")
            expected = sv["level"]
            expected_int = int(expected.replace(".", "")) if isinstance(expected, str) and "." in expected else int(expected)
            if actual_level is not None and int(actual_level) != expected_int:
                issues.append(f"video level: expected {expected_int}, got {actual_level}")

        if "pix_fmt" in sv and video_stream.get("pix_fmt") != sv["pix_fmt"]:
            issues.append(f"pix_fmt: expected '{sv['pix_fmt']}', got '{video_stream.get('pix_fmt')}'")

        br_range = sv.get("bitrate_range_kbps")
        if br_range:
            vbr = int(video_stream.get("bit_rate", 0) or 0) // 1000
            if vbr > 0 and not (br_range[0] <= vbr <= br_range[1]):
                issues.append(f"video bitrate: expected {br_range[0]}-{br_range[1]} kbps, got {vbr} kbps")

    sa = spec_streams.get("audio", {})
    expected_audio_count = sa.get("count", 2)
    if len(audio_streams) != expected_audio_count:
        issues.append(f"audio tracks: expected {expected_audio_count}, got {len(audio_streams)}")

    for i, astream in enumerate(audio_streams):
        if "codec_name" in sa and astream.get("codec_name") != sa["codec_name"]:
            issues.append(f"audio[{i}] codec: expected '{sa['codec_name']}', got '{astream.get('codec_name')}'")
        if "sample_rate" in sa and astream.get("sample_rate") != str(sa["sample_rate"]):
            issues.append(f"audio[{i}] sample_rate: expected {sa['sample_rate']}, got {astream.get('sample_rate')}")

    return issues
