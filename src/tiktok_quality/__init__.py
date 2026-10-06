"""tiktok-quality-fix (CompressBase Edition)
----------------------------------------
Upload 1080p60 videos to TikTok with maximum quality using the CompressBase method.

Usage::

    # Process video using CompressBase pipeline
    from tiktok_quality import process_video

    result = process_video("input.mp4", "output.mp4")
    print("Valid:", result["validation"]["valid"])

    # Launch GUI
    from tiktok_quality.gui import main as run_gui
    run_gui()
"""

__version__ = "2.0.0"

from .compressbase import process_video
from .encoder import encode, probe, find_ffmpeg
from .patcher import apply_isobmff_patches, patch_ftyp, zero_creation_times
from .validator import validate_output, stream_summary
from .transform import transform

__all__ = [
    "process_video",
    "encode",
    "probe",
    "find_ffmpeg",
    "apply_isobmff_patches",
    "patch_ftyp",
    "zero_creation_times",
    "validate_output",
    "stream_summary",
    "transform",
    "__version__",
]
