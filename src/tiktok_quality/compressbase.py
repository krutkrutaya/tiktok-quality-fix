"""
compressbase.py
---------------
Core CompressBase pipeline orchestrator:
Executes FFmpeg re-encoding, binary ISOBMFF patching, and output validation.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict, Any, Optional, Callable

from . import encoder as fw
from . import patcher as iso
from . import validator as val


def process_video(
    input_path: str,
    output_path: str,
    bitrate_multiplier: float = 1.0,
    audio_bitrate1: int = 190,
    audio_bitrate2: int = 215,
    preset: str = "fast",
    level: str = "4.2",
    comment: str = "Patched by CompressBase",
    audio_multiplier: int = 10,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    Run the CompressBase optimization pipeline on an input video:
      1. Probe source file.
      2. Re-encode video with FFmpeg to H.264 Constrained Baseline L4.2 (CBR)
         and dual stereo AAC tracks (48 kHz, 190k + 215k).
      3. Apply low-level binary ISOBMFF patches:
         - Brand rewrite (isom, iso2, avc1, mp41)
         - Recursive zeroing of creation_time and modification_time
         - Lavf encoder tag binary replacement
         - Pascal-length handler name headers and stco chunk offset shifts
         - Audio track 2 sample inflation (x10)
      4. Validate output file against target_spec.json.

    Returns:
      Dictionary with source and output stream summaries, duration, file sizes, and validation issues.
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    source_probe = fw.probe(input_path)
    if not fw.get_audio_streams(source_probe):
        raise RuntimeError("Input file must contain at least one audio track.")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mp4", prefix="cb_temp_")
    os.close(tmp_fd)

    try:
        # Step 1: Re-encode with FFmpeg
        fw.encode(
            input_path=input_path,
            output_path=tmp_path,
            bitrate_multiplier=bitrate_multiplier,
            audio_bitrate1_kbps=audio_bitrate1,
            audio_bitrate2_kbps=audio_bitrate2,
            preset=preset,
            level=level,
            comment=comment,
            progress_callback=progress_callback,
        )

        # Step 2: Binary ISOBMFF patches
        iso.apply_isobmff_patches(
            input_path=tmp_path,
            output_path=output_path,
            major_brand="isom",
            minor_version=512,
            compatible_brands=["isom", "iso2", "avc1", "mp41"],
            remove_creation_time=True,
            encoder="Lavf59.27.100",
            audio_multiplier=audio_multiplier,
        )
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    # Step 3: Validate output
    output_probe = fw.probe(output_path)
    issues = val.validate_output(output_probe)

    return {
        "source": val.stream_summary(source_probe),
        "output": val.stream_summary(output_probe),
        "validation": {
            "valid": len(issues) == 0,
            "issues": issues,
        },
        "durationSeconds": round(fw.get_duration_seconds(output_probe), 3),
        "sizeBytes": os.path.getsize(output_path),
    }
