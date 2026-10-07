"""
encoder.py
----------
Subprocess wrappers for ffmpeg and ffprobe.
Implements the CompressBase encoding pipeline:
  - Video re-encoding to H.264 Constrained Baseline L4.2 (CBR with HRD buffer, yuv420p)
  - Hardware acceleration support (NVENC, QSV, AMF) with seamless CPU (libx264) fallback
  - Dual AAC-LC 48kHz stereo tracks generated from a split filtergraph
  - Strip source metadata, set format comment, video encoder tags, faststart
  - Stream progress callbacks and graceful cancellation
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from typing import Callable, Optional, Tuple, List, Dict, Any

_CACHED_FFMPEG: Optional[str] = None
_CACHED_FFPROBE: Optional[str] = None
_CACHED_ENCODERS: Optional[List[str]] = None


def set_custom_ffmpeg_paths(ffmpeg_path: Optional[str] = None, ffprobe_path: Optional[str] = None) -> None:
    """Manually configure custom paths for ffmpeg and ffprobe."""
    global _CACHED_FFMPEG, _CACHED_FFPROBE, _CACHED_ENCODERS
    if ffmpeg_path and os.path.isfile(ffmpeg_path):
        _CACHED_FFMPEG = ffmpeg_path
        _CACHED_ENCODERS = None
    if ffprobe_path and os.path.isfile(ffprobe_path):
        _CACHED_FFPROBE = ffprobe_path


def find_ffmpeg() -> Tuple[str, str]:
    """
    Return (ffmpeg_path, ffprobe_path).
    Searches user overrides, environment variables, PATH, and standard Windows/Linux locations.
    Raises RuntimeError if ffmpeg or ffprobe cannot be found.
    """
    global _CACHED_FFMPEG, _CACHED_FFPROBE

    if _CACHED_FFMPEG and _CACHED_FFPROBE and os.path.isfile(_CACHED_FFMPEG) and os.path.isfile(_CACHED_FFPROBE):
        return _CACHED_FFMPEG, _CACHED_FFPROBE

    # 1. Environment variables
    ff = os.environ.get("FFMPEG_PATH")
    fp = os.environ.get("FFPROBE_PATH")

    # 2. System PATH
    if not ff:
        ff = shutil.which("ffmpeg")
    if not fp:
        fp = shutil.which("ffprobe")

    # 3. Known standard Windows directories
    if not ff or not fp:
        candidate_dirs = [
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin"),
            os.path.expandvars(r"%ProgramFiles(x86)%\ffmpeg\bin"),
            os.path.expandvars(r"%ProgramData%\chocolatey\bin"),
            os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
            os.path.join(os.path.dirname(__file__), "bin"),
            os.path.join(os.getcwd(), "bin"),
        ]
        for cdir in candidate_dirs:
            if os.path.isdir(cdir):
                direct_ff = os.path.join(cdir, "ffmpeg.exe")
                direct_fp = os.path.join(cdir, "ffprobe.exe")
                if not ff and os.path.isfile(direct_ff):
                    ff = direct_ff
                if not fp and os.path.isfile(direct_fp):
                    fp = direct_fp
                if ff and fp:
                    break

                # Walk one level down for nested package folders
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

    _CACHED_FFMPEG = ff
    _CACHED_FFPROBE = fp
    return ff, fp


def get_available_video_encoders() -> List[str]:
    """Return list of supported H.264 video encoders reported by ffmpeg."""
    global _CACHED_ENCODERS
    if _CACHED_ENCODERS is not None:
        return _CACHED_ENCODERS

    encoders = ["libx264"]
    try:
        ffmpeg_path, _ = find_ffmpeg()
        res = subprocess.run([ffmpeg_path, "-encoders"], capture_output=True, text=True, errors="replace", timeout=10)
        stdout = res.stdout.lower()
        candidates = ["h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox"]
        for cand in candidates:
            if cand in stdout and cand not in encoders:
                encoders.append(cand)
    except Exception:
        pass

    _CACHED_ENCODERS = encoders
    return encoders


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
    video_encoder: str = "libx264",
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
        "-c:v", video_encoder,
    ]

    # Specific video encoder parameters
    if video_encoder == "libx264":
        cmd.extend([
            "-preset", preset,
            "-b:v", f"{target_video_bitrate_kbps}k",
            "-maxrate", f"{target_video_bitrate_kbps}k",
            "-bufsize", f"{target_video_bitrate_kbps * 2}k",
            "-pix_fmt", "yuv420p",
            "-profile:v", "baseline",
            "-level:v", level,
            "-x264-params", "nal-hrd=cbr",
        ])
    elif "nvenc" in video_encoder:
        cmd.extend([
            "-b:v", f"{target_video_bitrate_kbps}k",
            "-maxrate", f"{target_video_bitrate_kbps}k",
            "-bufsize", f"{target_video_bitrate_kbps * 2}k",
            "-pix_fmt", "yuv420p",
            "-profile:v", "baseline",
            "-level:v", level,
            "-rc", "cbr",
        ])
    elif "qsv" in video_encoder:
        cmd.extend([
            "-b:v", f"{target_video_bitrate_kbps}k",
            "-maxrate", f"{target_video_bitrate_kbps}k",
            "-bufsize", f"{target_video_bitrate_kbps * 2}k",
            "-pix_fmt", "nv12",
            "-profile:v", "baseline",
            "-level:v", level,
        ])
    else:
        # Fallback / generic encoder
        cmd.extend([
            "-b:v", f"{target_video_bitrate_kbps}k",
            "-maxrate", f"{target_video_bitrate_kbps}k",
            "-bufsize", f"{target_video_bitrate_kbps * 2}k",
            "-pix_fmt", "yuv420p",
            "-profile:v", "baseline",
            "-level:v", level,
        ])

    cmd.extend([
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
    ])
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
    video_encoder: str = "libx264",
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    Full CompressBase encode pipeline with progress tracking and cancellation.
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

    # Verify requested encoder is available, fallback to libx264 if needed
    avail_encoders = get_available_video_encoders()
    chosen_encoder = video_encoder if video_encoder in avail_encoders else "libx264"

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
        video_encoder=chosen_encoder,
    )

    process = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
        errors="replace",
    )

    time_re = re.compile(r"time=(\d+):(\d+):([\d.]+)")

    try:
        if process.stderr is not None:
            for line in process.stderr:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise RuntimeError("Encoding cancelled by user.")

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

    except Exception:
        if process.poll() is None:
            process.kill()
        raise

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
