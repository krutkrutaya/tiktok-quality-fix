# TikTok Quality Fix (CompressBase Method) — Modern Edition

Advanced tool for uploading videos to TikTok with maximum **1080p60fps** fidelity without quality loss, compression degradation, or shadowban risk.

Powered by the **CompressBase** encoding pipeline, hardware-accelerated transcoding (NVENC/QSV/AMF/CPU), low-level **ISOBMFF** container binary patching, and a brand-new **Modern CustomTkinter GUI**.

---

## 🎯 What is this?

TikTok often compresses uploaded videos heavily or applies aggressive downscaling and artifact-inducing transcodes. This tool resolves this issue by applying the industry-standard **CompressBase** method:

1. **Precision Re-encoding (FFmpeg + Hardware Acceleration)**:
   - Video is encoded to **H.264 Constrained Baseline (L4.2)** with CBR and HRD buffer compliance (`nal-hrd=cbr`), in `yuv420p` color space.
   - Support for **NVIDIA NVENC**, **Intel QSV**, and **AMD AMF** GPU acceleration with automatic fallback to high-quality CPU `libx264`.
   - Dual **AAC-LC 48kHz stereo** audio streams are generated via an `asplit` filtergraph (Track 1: 190 kbps, Track 2: 215 kbps) with default disposition and `eng` language tags.
   - Cleans all source metadata (`-map_metadata -1`) and writes faststart atoms with color tags (`+faststart+write_colr`).
2. **Binary ISOBMFF Atom Patching**:
   - **`ftyp` rewrite**: `major_brand = isom`, `minor_version = 512`, `compatible_brands = isom, iso2, avc1, mp41`.
   - **Creation/Modification Timestamp Removal**: Recursively zeroes `creation_time` and `modification_time` fields in `mvhd`, `tkhd`, and `mdhd` boxes to strip platform origin identifiers.
   - **Encoder Tag Normalization**: In-place binary replacement of `Lavf` encoder signatures to `Lavf59.27.100`.
   - **Handler Names Patch**: Prepends Pascal-string length prefix (`0x0C`) to `VideoHandler` and `SoundHandler` in `hdlr` boxes, automatically shifting all `stco` / `co64` chunk offsets across the container.
   - **Audio Track 2 Sample Inflation**: Inflates declared `nb_frames` on the second audio track (x10 multiplier) by restructuring `stsz`, `stts`, and `stsc` tables without altering physical audio frames.
3. **Specification Validation**:
   - Automatically validates the final output against `target_spec.json`.
4. **Modern CustomTkinter GUI & CLI**:
   - Includes a sleek **CustomTkinter Dark/Light Interface** (`tiktok-quality-gui`) with batch queuing, live logs, dual progress bars, preset profiles, and responsive cancellation.

---

## 🚀 Installation & Requirements

### Requirements

- **Python 3.10+** (tested on 3.10, 3.11, 3.12, 3.13, 3.14+)
- **FFmpeg & FFprobe** (required for the CompressBase re-encoding pipeline)

```bash
# Windows
winget install Gyan.FFmpeg

# macOS
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt install ffmpeg
```

### Installation

```bash
git clone https://github.com/krutkrutaya/tiktok-quality-fix.git
cd tiktok-quality-fix
pip install -r requirements.txt
pip install -e .
```

---

## 💻 Usage

### 1. Graphical User Interface (Modern CustomTkinter GUI)

Launch the modern batch-processing GUI with one command:

```bash
tiktok-quality-gui
# OR:
python -m tiktok_quality --gui
```

Features of the Modern GUI:
- **Card-based Responsive Layout**: Dark/Light mode theme switcher.
- **Batch Video Queue**: Add multiple video files or folders, with size and status indicators.
- **Preset Selector**:
  - `⚡ TikTok 1080p60 (Recommended)`
  - `💎 Maximum Quality (HQ)`
  - `🚀 Ultra Fast`
  - `⚙️ Custom Configuration`
- **Hardware Acceleration Dropdown**: Auto, NVIDIA NVENC, Intel QSV, AMD AMF, or CPU libx264.
- **Dual Progress Bars**: Individual file progress + Overall batch queue progress.
- **Live Activity Console**: Real-time FFmpeg time tracking and validation feedback.
- **Cancellation**: Safe and responsive cancellation at any point.

---

### 2. Command Line Interface (CLI)

#### Standard CompressBase Processing (Recommended)
```bash
tiktok-quality input.mp4 output.mp4
# OR:
python -m tiktok_quality input.mp4 output.mp4
```

#### Hardware Acceleration (NVENC / QSV / AMF)
```bash
tiktok-quality input.mp4 output.mp4 --encoder h264_nvenc
```

#### Custom Bitrate & Speed Preset
```bash
tiktok-quality input.mp4 output.mp4 --bitrate-multiplier 1.1 --preset slow
```

#### Custom Audio Bitrates & Level
```bash
tiktok-quality input.mp4 output.mp4 --audio-bitrate1 192 --audio-bitrate2 256 --level 4.2
```

#### Verify an Existing Output File
```bash
tiktok-quality --verify output.mp4
```

#### Check Dependencies & Available Hardware Encoders
```bash
tiktok-quality --check-deps
```

#### Legacy Ghost-Frame Mode (Zero Re-encoding)
For rapid metadata manipulation without FFmpeg re-encoding:
```bash
tiktok-quality input.mp4 output.mp4 --legacy-transform --randomize
```

---

## ⚙️ Parameters Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input` | Path | Required | Path to input video file |
| `output` | Path | Required | Path to save processed MP4 |
| `--gui` | Flag | - | Launch Modern CustomTkinter GUI |
| `--encoder` | String | `auto` | Video encoder (`auto`, `libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`) |
| `--bitrate-multiplier` | Float | `1.0` | Target video bitrate multiplier (1.0 = 100% of source) |
| `--preset` | String | `fast` | FFmpeg preset (`ultrafast`, `faster`, `fast`, `medium`, `slow`) |
| `--level` | String | `4.2` | Target H.264 level |
| `--audio-bitrate1` | Int | `190` | Track 1 AAC bitrate in kbps |
| `--audio-bitrate2` | Int | `215` | Track 2 AAC bitrate in kbps |
| `-c, --comment` | String | `Patched by CompressBase` | Metadata comment string |
| `-m, --multiplier` | Int | `10` | Frame / sample inflation factor |
| `--legacy-transform` | Flag | - | Run legacy ghost-frame injection (no re-encoding) |
| `--randomize` | Flag | - | Enable random filler blocks and timestamp jitter |
| `--verify FILE` | Path | - | Inspect and validate file with ffprobe |
| `--check-deps` | Flag | - | Check Python, FFmpeg, and GPU encoders availability |

---

## 📂 Project Structure

```
tiktok-quality-fix/
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
├── src/
│   └── tiktok_quality/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py             # CLI parser & runner
│       ├── gui.py             # Modern CustomTkinter Graphical Interface
│       ├── compressbase.py    # Main pipeline orchestrator
│       ├── encoder.py         # FFmpeg / ffprobe wrappers & HW accel detection
│       ├── patcher.py         # Low-level binary ISOBMFF atom patcher
│       ├── validator.py       # TikTok CompressBase spec validation
│       ├── target_spec.json   # JSON validation target criteria
│       ├── transform.py       # Legacy ghost-frames injector
│       ├── randomize.py       # Filler NAL generator & jitter
│       ├── detect.py          # Entropy & offset heuristics
│       └── mp4/
│           ├── builder.py     # Atom serialisation primitives
│           └── parser.py      # Low-level MP4 box walker
└── tests/
    ├── test_mp4.py
    ├── test_patcher.py
    ├── test_randomize.py
    └── test_validator.py
```

---

## 🧪 Testing

Run test suite:
```bash
python -m unittest discover tests
```

---

## 📜 License

MIT License. Created by [krutkrutaya](https://github.com/krutkrutaya).
