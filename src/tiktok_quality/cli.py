"""
cli.py
------
CLI interface for tiktok-quality-fix (CompressBase Edition).

Usage:
    tiktok-quality input.mp4 output.mp4 [options]
    python -m tiktok_quality input.mp4 output.mp4 [options]
    python -m tiktok_quality --gui
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .compressbase import process_video
from .encoder import probe, format_probe_summary, find_ffmpeg
from .validator import validate_output, load_target_spec
from .transform import transform
from .randomize import RandomOptions


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="tiktok-quality",
        description="TikTok Quality Fix -- CompressBase Method & MP4 Container Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard CompressBase processing (Recommended):
  tiktok-quality input.mp4 output.mp4

  # Custom bitrates and preset:
  tiktok-quality input.mp4 output.mp4 --bitrate-multiplier 0.9 --preset slow

  # Launch Graphical User Interface (GUI):
  tiktok-quality --gui

  # Legacy container manipulation (ghost-frames without re-encoding):
  tiktok-quality input.mp4 output.mp4 --legacy-transform --randomize

  # Inspect / Verify an existing MP4 file:
  tiktok-quality --verify output.mp4

  # Check FFmpeg and system dependencies:
  tiktok-quality --check-deps
        """,
    )
    parser.add_argument("input", nargs="?", help="Input video file path")
    parser.add_argument("output", nargs="?", help="Output video file path")
    parser.add_argument("--gui", action="store_true", help="Launch Tkinter GUI application")

    # CompressBase parameters
    parser.add_argument(
        "--bitrate-multiplier",
        type=float,
        default=1.0,
        help="Target video bitrate multiplier (default: 1.0 = 100%% of source)",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default="fast",
        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"],
        help="FFmpeg encoding preset (default: fast)",
    )
    parser.add_argument(
        "--level",
        type=str,
        default="4.2",
        help="H.264 level target (default: 4.2)",
    )
    parser.add_argument(
        "--audio-bitrate1",
        type=int,
        default=190,
        help="Track 1 AAC audio bitrate in kbps (default: 190)",
    )
    parser.add_argument(
        "--audio-bitrate2",
        type=int,
        default=215,
        help="Track 2 AAC audio bitrate in kbps (default: 215)",
    )
    parser.add_argument(
        "-c",
        "--comment",
        type=str,
        default="Patched by CompressBase",
        help="Metadata comment tag (default: 'Patched by CompressBase')",
    )
    parser.add_argument(
        "-m",
        "--multiplier",
        type=int,
        default=10,
        help="Sample/frame inflation multiplier (default: 10)",
    )

    # Legacy ghost frame mode
    parser.add_argument(
        "--legacy-transform",
        action="store_true",
        help="Use legacy ghost-frame container manipulation (no re-encoding)",
    )
    parser.add_argument(
        "--randomize",
        action="store_true",
        help="Enable random filler blocks and timestamp jitter (for legacy mode)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed for randomization reproducibility",
    )

    # Verification / utilities
    parser.add_argument(
        "--verify",
        metavar="FILE",
        help="Verify a file with ffprobe and check against target spec",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("FILE1", "FILE2"),
        help="Byte-compare two files",
    )
    parser.add_argument(
        "--check-detectability",
        action="store_true",
        help="Run entropy and uniqueness heuristics on file",
    )
    parser.add_argument(
        "--check-deps",
        action="store_true",
        help="Check FFmpeg and Python dependencies",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress output messages",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    if args.gui:
        from .gui import main as gui_main
        gui_main()
        return

    if args.check_deps:
        _check_deps()
        return

    if args.verify:
        if not Path(args.verify).exists():
            print(f"[!] File not found: {args.verify}", file=sys.stderr)
            sys.exit(1)
        _verify_file(args.verify)
        if args.check_detectability:
            _run_detectability(args.verify)
        return

    if args.compare:
        f1, f2 = args.compare
        for f in (f1, f2):
            if not Path(f).exists():
                print(f"[!] File not found: {f}", file=sys.stderr)
                sys.exit(1)
        ok = _compare_files(f1, f2)
        sys.exit(0 if ok else 1)

    if not args.input or not args.output:
        parser.print_help()
        sys.exit(1)

    if not Path(args.input).exists():
        print(f"[!] File not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Check whether to run legacy container transform or CompressBase pipeline
    if args.legacy_transform:
        if not args.quiet:
            print("[*] Running in Legacy Container Transform mode (ghost-frames)...")
        rand = RandomOptions(enabled=args.randomize, seed=args.seed)
        transform(
            input_path=args.input,
            output_path=args.output,
            multiplier=args.multiplier,
            comment=args.comment,
            verbose=not args.quiet,
            rand=rand,
        )
    else:
        if not args.quiet:
            print("[*] Running CompressBase Optimization Pipeline...")
            print(f"[*] Input:  {args.input}")
            print(f"[*] Output: {args.output}")

        def cli_progress(percent: float, line: str):
            if not args.quiet:
                # Progress update
                sys.stdout.write(f"\r[*] Encoding: {percent:5.1f}%")
                sys.stdout.flush()

        try:
            result = process_video(
                input_path=args.input,
                output_path=args.output,
                bitrate_multiplier=args.bitrate_multiplier,
                audio_bitrate1=args.audio_bitrate1,
                audio_bitrate2=args.audio_bitrate2,
                preset=args.preset,
                level=args.level,
                comment=args.comment,
                audio_multiplier=args.multiplier,
                progress_callback=cli_progress if not args.quiet else None,
            )
            if not args.quiet:
                print("\n[+] Processing and ISOBMFF patching complete!")
                val_info = result["validation"]
                if val_info["valid"]:
                    print("[+] Spec Validation: PASSED (100% compliant with TikTok / CompressBase target)")
                else:
                    print("[!] Spec Validation warnings:")
                    for iss in val_info["issues"]:
                        print(f"    - {iss}")

                src_sz = os.path.getsize(args.input)
                out_sz = result["sizeBytes"]
                print(f"[+] Output size: {out_sz / 1024 / 1024:.2f} MB (from {src_sz / 1024 / 1024:.2f} MB)")
        except Exception as e:
            print(f"\n[!] Error during processing: {e}", file=sys.stderr)
            sys.exit(1)

    if args.check_detectability and not args.quiet:
        _run_detectability(args.output)


def _verify_file(path: str):
    """Run ffprobe, print summary, and validate against spec."""
    try:
        p = probe(path)
        print(format_probe_summary(p, "PROBE RESULT"))
        issues = validate_output(p)
        if not issues:
            print("\n[+] Target spec validation: PASSED")
        else:
            print("\n[!] Target spec validation issues:")
            for iss in issues:
                print(f"    - {iss}")
    except Exception as e:
        print(f"[!] Could not probe {path}: {e}", file=sys.stderr)


def _run_detectability(path: str) -> None:
    """Run detect.check on the produced or supplied file."""
    from .mp4.parser import (
        find_box, find_box_path, find_track_by_handler,
        parse_stco, parse_stsz,
    )
    from .detect import check

    with open(path, "rb") as f:
        data = f.read()

    moov_pos, moov_size = find_box(data, "moov")
    if moov_pos is None:
        print("[!] detectability: no moov box")
        return
    vt_pos, vt_size = find_track_by_handler(data, moov_pos, moov_size, b"vide")
    if vt_pos is None:
        print("[!] detectability: no video track")
        return
    stbl_pos, stbl_size = find_box_path(data, ["mdia", "minf", "stbl"], vt_pos + 8, vt_pos + vt_size)
    if stbl_pos is None:
        print("[!] detectability: no stbl")
        return

    stco_pos, _ = find_box(data, "stco", stbl_pos + 8, stbl_pos + stbl_size)
    stsz_pos, _ = find_box(data, "stsz", stbl_pos + 8, stbl_pos + stbl_size)
    if stco_pos is None or stsz_pos is None:
        print("[!] detectability: missing stco or stsz")
        return

    offsets = parse_stco(data, stco_pos)
    sizes = parse_stsz(data, stsz_pos)

    res = check(data, offsets, sizes)
    if res["ok"]:
        print(f"[+] Detectability: OK (stco uniqueness={res['stco_uniqueness']:.3f}, size entropy={res['tail_size_entropy']:.3f})")
    else:
        for finding in res["findings"]:
            print(f"[!] {finding}")


def _compare_files(path1: str, path2: str) -> bool:
    """Byte-for-byte file comparison."""
    chunk = 1 << 20
    same = True
    first_diff = -1
    total = 0
    with open(path1, "rb") as fa, open(path2, "rb") as fb:
        while True:
            a = fa.read(chunk)
            b = fb.read(chunk)
            if not a and not b:
                break
            if a != b:
                same = False
                if first_diff < 0:
                    for i in range(min(len(a), len(b))):
                        if a[i] != b[i]:
                            first_diff = total + i
                            break
            total += max(len(a), len(b))

    if same:
        print("[+] PERFECT MATCH -- byte-for-byte identical")
        return True
    print(f"[-] Files differ. First difference at byte {first_diff}")
    return False


def _check_deps():
    """Verify system dependencies."""
    v = sys.version_info
    print(f"[+] Python {v.major}.{v.minor}.{v.micro}")

    try:
        ff, fp = find_ffmpeg()
        print(f"[+] ffmpeg:  {ff}")
        print(f"[+] ffprobe: {fp}")
    except RuntimeError as e:
        print(f"[!] FFmpeg status: {e}")

    try:
        import tiktok_quality
        print(f"[+] tiktok-quality v{tiktok_quality.__version__}")
    except ImportError:
        print("[!] Package not installed in environment (run: pip install -e .)")


if __name__ == "__main__":
    main()
