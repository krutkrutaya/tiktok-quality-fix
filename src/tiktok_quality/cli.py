"""CLI interface for tiktok-quality.

Usage:
    tiktok-quality input.mp4 output.mp4 [options]
    python -m tiktok_quality input.mp4 output.mp4 [options]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .randomize import RandomOptions
from .transform import transform


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='tiktok-quality',
        description='TikTok Quality -- MP4 container manipulation (zero re-encoding)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tiktok-quality video.mp4 output.mp4 --randomize
  tiktok-quality video.mp4 output.mp4 -m 10 --randomize --seed 1
  tiktok-quality video.mp4 output.mp4 --randomize --check-detectability
  tiktok-quality --verify output.mp4
  tiktok-quality --check-deps

Recommended:
  Always pass --randomize. Without it, output is byte-identical to
  previous runs and may be flagged by TikTok.
        """
    )
    parser.add_argument('input', nargs='?', help='Input MP4 file (H.264/AVC)')
    parser.add_argument('output', nargs='?', help='Output MP4 file path')
    parser.add_argument('-m', '--multiplier', type=int, default=10,
                        help='Frame count multiplier (default: 10)')
    parser.add_argument('-c', '--comment', type=str, default=None,
                        help="Metadata comment tag (default: none; "
                             "with --randomize, a unique random string)")
    parser.add_argument('--randomize', action='store_true',
                        help="Randomize filler blocks, stts jitter, and "
                             "comment so every output is unique. Strongly "
                             "recommended.")
    parser.add_argument('--seed', type=int, default=None,
                        help="Seed for --randomize (reproducible output).")
    parser.add_argument('--check-detectability', action='store_true',
                        help="Run heuristics on the output and warn if it "
                             "looks obviously manipulated.")
    parser.add_argument('--verify', metavar='FILE',
                        help='Verify a file with ffprobe (no transformation)')
    parser.add_argument('--compare', nargs=2, metavar=('FILE', 'REFERENCE'),
                        help='Byte-compare two files')
    parser.add_argument('--check-deps', action='store_true',
                        help='Check and install dependencies')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='Suppress progress messages')
    parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {__version__}')

    args = parser.parse_args()

    if args.check_deps:
        _check_deps()
        return

    if args.verify:
        if not Path(args.verify).exists():
            print(f"[!] File not found: {args.verify}", file=sys.stderr)
            sys.exit(1)
        _verify_ffprobe(args.verify)
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

    rand = RandomOptions(enabled=args.randomize, seed=args.seed)
    transform(
        input_path=args.input,
        output_path=args.output,
        multiplier=args.multiplier,
        comment=args.comment,
        verbose=not args.quiet,
        rand=rand,
    )

    if not args.quiet:
        _verify_ffprobe(args.output)

    if args.check_detectability and not args.quiet:
        _run_detectability(args.output)


def _verify_ffprobe(path: str):
    """Run ffprobe and print summary."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return
    try:
        r = subprocess.run(
            [ffprobe, '-v', 'quiet', '-show_format', '-show_streams',
             '-print_format', 'json', path],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return
        info = json.loads(r.stdout)
        for s in info.get('streams', []):
            if s.get('codec_type') == 'video':
                print(f"[+] Video: {s.get('codec_name')} "
                      f"{s.get('width')}x{s.get('height')}, "
                      f"{s.get('nb_frames')} frames")
            elif s.get('codec_type') == 'audio':
                print(f"[+] Audio: {s.get('codec_name')} @ {s.get('sample_rate')} Hz")
        fmt = info.get('format', {})
        tags = fmt.get('tags', {})
        print(f"[+] Brand: {tags.get('major_brand', '?')}, "
              f"Comment: {tags.get('comment', '-')}")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass


def _run_detectability(path: str) -> None:
    """Run detect.check on the produced (or user-supplied) file."""
    from .mp4.parser import (
        find_box, find_box_path, find_track_by_handler,
        parse_stco, parse_stsz,
    )
    from .detect import check

    with open(path, 'rb') as f:
        data = f.read()

    moov_pos, moov_size = find_box(data, 'moov')
    if moov_pos is None:
        print("[!] detectability: no moov box")
        return
    vt_pos, vt_size = find_track_by_handler(data, moov_pos, moov_size, b'vide')
    if vt_pos is None:
        print("[!] detectability: no video track")
        return
    stbl_pos, stbl_size = find_box_path(
        data, ['mdia', 'minf', 'stbl'], vt_pos + 8, vt_pos + vt_size)
    if stbl_pos is None:
        print("[!] detectability: no stbl")
        return

    stco_pos, _ = find_box(data, 'stco', stbl_pos + 8, stbl_pos + stbl_size)
    stsz_pos, _ = find_box(data, 'stsz', stbl_pos + 8, stbl_pos + stbl_size)
    offsets = parse_stco(data, stco_pos)
    sizes = parse_stsz(data, stsz_pos)

    res = check(data, offsets, sizes)
    if res['ok']:
        print(f"[+] Detectability: OK "
              f"(stco uniqueness={res['stco_uniqueness']:.3f}, "
              f"size entropy={res['tail_size_entropy']:.3f})")
    else:
        for f in res['findings']:
            print(f"[!] {f}")


def _compare_files(path1: str, path2: str) -> bool:
    """Byte-for-byte comparison, streaming in 1 MiB chunks."""
    chunk = 1 << 20
    same = True
    first_diff = -1
    total = 0
    with open(path1, 'rb') as fa, open(path2, 'rb') as fb:
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
                # keep counting sizes
            total += max(len(a), len(b))

    if same:
        print("[+] PERFECT MATCH - byte-for-byte identical")
        return True
    print(f"[-] Files differ. First diff @ byte {first_diff}")
    return False


def _check_deps():
    """Check all dependencies."""
    v = sys.version_info
    print(f"[+] Python {v.major}.{v.minor}.{v.micro}")

    ffprobe = shutil.which('ffprobe')
    ffmpeg = shutil.which('ffmpeg')
    print(f"[+] ffprobe: {ffprobe or 'NOT FOUND (optional)'}")
    print(f"[+] ffmpeg:  {ffmpeg or 'NOT FOUND (optional)'}")

    if not ffprobe:
        print("\n    Install FFmpeg:")
        print("      Windows: winget install Gyan.FFmpeg")
        print("      macOS:   brew install ffmpeg")
        print("      Linux:   sudo apt install ffmpeg")

    try:
        import tiktok_quality
        print(f"[+] tiktok-quality v{tiktok_quality.__version__}")
    except ImportError:
        print("[!] Package not installed - run: pip install -e .")


if __name__ == '__main__':
    main()
