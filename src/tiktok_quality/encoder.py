"""
encoder.py
----------
Subprocess wrappers for ffmpeg and ffprobe.
Implements the CompressBase encoding pipeline:
  - Video re-encoding to H.264 Constrained Baseline L4.2 (CBR with HRD buffer, yuv420p)
  - Dual AAC-LC 48kHz stereo tracks generated from a split filtergraph
  - Strip source metadata, set format comment, video encoder tags, faststart
  - Stream progress callbacks
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict, Any


def find_ffmpeg() -> Tuple[str, str]:
    """
    Return (ffmpeg_path, ffprobe_path).
    Searches PATH and standard Windows / Linux locations.
    Raises RuntimeError if ffmpeg or ffprobe cannot be found.
    """
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")

    if not ff or not fp:
        # Search common Windows paths if not found directly in PATH
        candidate_dirs = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin"),
            os.path.expandvars(r"%ProgramData%\chocolatey\bin"),
            os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
        ]
        for cdir in candidate_dirs:
            if os.path.isdir(cdir):
                for root, _, files in os.walk(cdir):
                    if not ff and "ffmpeg.exe" in files:
                        ff = os.path.join(root, "ffmpeg.exe")
                    if not fp and "ffprobe.exe" in files:
                        fp = os.path.join(root, "ffprobe.exe")
                    if ff and fp:
                        break
            if ff and fp:
                break

    if not ff:
        raise RuntimeError(
            "ffmpeg not found in PATH or standard directories.\n"
            "Install FFmpeg:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  macOS:   brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )
    if not fp:
        raise RuntimeError(
            "ffprobe not found in PATH or standard directories.\n"
            "Please ensure FFmpeg is properly installed with ffprobe."
        )

    return ff, fp


def probe(file_path: str) -> Dict[str, Any]:
    """Run ffprobe and return parsed JSON dictionary (format + streams)."""
    _, ffprobe_path = find_ffmpeg()
    cmd = [
        ffprobe_path,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {file_path}:\n{result.stderr}")
    return json.loads(result.stdout)


def get_video_stream(probe_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the first video stream from probe data, or None."""
    for s in probe_data.get("streams", []):
        if s.get("codec_type") == "video":
            return s
    return None


def get_audio_streams(probe_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return all audio streams from probe data."""
    return [s for s in probe_data.get("streams", []) if s.get("codec_type") == "audio"]


def get_video_bitrate(probe_data: Dict[str, Any]) -> int:
    """Return video bitrate in bits/sec, falling back to container format bitrate."""
    vstream = get_video_stream(probe_data)
    if vstream:
        br = vstream.get("bit_rate")
        if br and br != "N/A":
            try:
                return int(br)
            except ValueError:
                pass
    fmt_br = probe_data.get("format", {}).get("bit_rate")
    if fmt_br and fmt_br != "N/A":
        try:
            return int(fmt_br)
        except ValueError:
            pass
    return 0


def get_duration_seconds(probe_data: Dict[str, Any]) -> float:
    """Return duration in seconds as float."""
    d = probe_data.get("format", {}).get("duration")
    if d:
        try:
            return float(d)
        except ValueError:
            pass
    vstream = get_video_stream(probe_data)
    if vstream and vstream.get("duration"):
        try:
            return float(vstream["duration"])
        except ValueError:
            pass
    return 0.0


def build_encode_command(
    ffmpeg_path: str,
    input_path: str,
    output_path: str,
    target_video_bitrate_kbps: int,
    audio_bitrate1_kbps: int = 190,
    audio_bitrate2_kbps: int = 215,
    preset: str = "fast",
    level: str = "4.2",
    comment: str = "Patched by CompressBase",
    encoder_tag: str = "Lavf59.27.100",
    video_encoder_tag: str = "Lavc59.37.100 libx264",
) -> List[str]:
    """
    Build the CompressBase FFmpeg command:
      - Video: H.264 Constrained Baseline L4.2, CBR with HRD buffer, yuv420p
      - Audio: Two AAC-LC 48kHz stereo tracks via split filtergraph
      - Format: comment, video encoder tag, faststart, write_colr, brand isom
    """
    filter_complex = (
        "[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "asplit=2[aout0][aout1]"
    )

    cmd = [
        ffmpeg_path,
        "-y",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "0:v:0",
        "-c:v", "libx264",
        "-preset", preset,
        "-b:v", f"{target_video_bitrate_kbps}k",
        "-maxrate", f"{target_video_bitrate_kbps}k",
        "-bufsize", f"{target_video_bitrate_kbps * 2}k",
        "-pix_fmt", "yuv420p",
        "-profile:v", "baseline",
        "-level:v", level,
        "-x264-params", "nal-hrd=cbr",
        "-metadata:s:v:0", "language=eng",
        "-map", "[aout0]",
        "-c:a:0", "aac",
        "-b:a:0", f"{audio_bitrate1_kbps}k",
        "-disposition:a:0", "default",
        "-metadata:s:a:0", "language=eng",
        "-map", "[aout1]",
        "-c:a:1", "aac",
        "-b:a:1", f"{audio_bitrate2_kbps}k",
        "-disposition:a:1", "default",
        "-metadata:s:a:1", "language=eng",
        "-map_metadata", "-1",
        "-metadata", f"comment={comment}",
        "-metadata:s:v:0", f"encoder={video_encoder_tag}",
        "-movflags", "+faststart",
        "-movflags", "+write_colr",
        "-brand", "isom",
        "-f", "mp4",
        output_path,
    ]
    return cmd


def encode(
    input_path: str,
    output_path: str,
    bitrate_multiplier: float = 1.0,
    audio_bitrate1_kbps: int = 190,
    audio_bitrate2_kbps: int = 215,
    preset: str = "fast",
    level: str = "4.2",
    comment: str = "Patched by CompressBase",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    Full CompressBase encode pipeline.
    Calls progress_callback(percent: float, line: str) as encoding proceeds.
    Returns parsed probe dict of the generated MP4.
    """
    ffmpeg_path, _ = find_ffmpeg()

    src_probe = probe(input_path)
    src_bitrate = get_video_bitrate(src_probe)
    duration = get_duration_seconds(src_probe)

    if not get_audio_streams(src_probe):
        raise RuntimeError("Input video must contain at least one audio track.")

    if src_bitrate == 0:
        target_kbps = 13_000
    else:
        target_kbps = max(500, int(src_bitrate * bitrate_multiplier / 1000))

    cmd = build_encode_command(
        ffmpeg_path=ffmpeg_path,
        input_path=input_path,
        output_path=output_path,
        target_video_bitrate_kbps=target_kbps,
        audio_bitrate1_kbps=audio_bitrate1_kbps,
        audio_bitrate2_kbps=audio_bitrate2_kbps,
        preset=preset,
        level=level,
        comment=comment,
    )

    process = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
        errors="replace",
    )

    time_re = re.compile(r"time=(\d+):(\d+):([\d.]+)")

    if process.stderr is not None:
        for line in process.stderr:
            line = line.rstrip()
            if progress_callback:
                percent = 0.0
                m = time_re.search(line)
                if m and duration > 0:
                    h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                    elapsed = h * 3600 + mn * 60 + s
                    percent = min(99.0, elapsed / duration * 100)
                progress_callback(percent, line)

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"ffmpeg encoding failed with exit code {process.returncode}")

    if progress_callback:
        progress_callback(100.0, "Encoding complete.")

    return probe(output_path)


def format_probe_summary(probe_data: Dict[str, Any], label: str = "") -> str:
    """Format probe data into a human-readable multi-line summary string."""
    lines = []
    if label:
        lines.append(f"=== {label} ===")

    fmt = probe_data.get("format", {})
    tags = fmt.get("tags", {})
    lines.append(f"  Format      : {fmt.get('format_long_name', fmt.get('format_name', '?'))}")
    lines.append(f"  Duration    : {float(fmt.get('duration', 0)):.2f}s")
    lines.append(f"  Bitrate     : {int(fmt.get('bit_rate', 0)) // 1000} kbps")
    lines.append(f"  Size        : {int(fmt.get('size', 0)) / 1024 / 1024:.2f} MB")
    lines.append(f"  major_brand : {tags.get('major_brand', tags.get('compatible_brands', '?'))}")
    lines.append(f"  comment     : {tags.get('comment', '-')}")
    lines.append(f"  encoder     : {tags.get('encoder', '-')}")

    for i, s in enumerate(probe_data.get("streams", [])):
        ct = s.get("codec_type", "?")
        cn = s.get("codec_name", "?")
        if ct == "video":
            lines.append(
                f"  Stream #{i} (video): {cn}, {s.get('profile', '?')}, "
                f"L{s.get('level', '?')}, {s.get('width')}x{s.get('height')}, "
                f"{s.get('r_frame_rate', '?')} fps, "
                f"{int(s.get('bit_rate', 0)) // 1000} kbps"
            )
        elif ct == "audio":
            lines.append(
                f"  Stream #{i} (audio): {cn}, {s.get('sample_rate')} Hz, "
                f"{s.get('channel_layout', '?')}, "
                f"{int(s.get('bit_rate', 0)) // 1000} kbps, "
                f"nb_frames={s.get('nb_frames', '?')}"
            )
        stags = s.get("tags", {})
        if stags.get("creation_time"):
            lines.append(f"            creation_time: {stags['creation_time']}")
    return "\n".join(lines)
