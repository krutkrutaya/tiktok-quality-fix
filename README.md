# TikTok Quality Fix (CompressBase Method)

Advanced tool for uploading videos to TikTok with maximum **1080p60fps** fidelity without quality loss, compression degradation, or shadowban risk.

Powered by the **CompressBase** encoding pipeline and low-level **ISOBMFF** container binary patching.

---

## 🎯 What is this?

TikTok often compresses uploaded videos heavily or applies aggressive downscaling and artifact-inducing transcodes. This tool resolves this issue by applying the industry-standard **CompressBase** method:

1. **Precision Re-encoding (FFmpeg)**:
   - Video is encoded to **H.264 Constrained Baseline (L4.2)** with CBR and HRD buffer compliance (`nal-hrd=cbr`), in `yuv420p` color space.
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
4. **Modern GUI & CLI**:
   - Includes a full **Tkinter Graphical User Interface** (`tiktok-quality-gui`) with batch queuing, live logs, progress bars, and preset selectors.

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
pip install -e .
```

---

## 💻 Usage

### 1. Graphical User Interface (GUI)

Launch the batch-processing GUI with one command:

```bash
tiktok-quality-gui
# OR:
python -m tiktok_quality --gui
```

Features of the GUI:
- Add single or multiple video files (batch queue).
- Set bitrate multiplier, preset (`ultrafast` to `slow`), H.264 level, and audio bitrates.
- Dual progress bars (Current file + Overall queue).
- Live colorized log viewer with ffprobe probe breakdown and validation results.

---

### 2. Command Line Interface (CLI)

#### Standard CompressBase Processing (Recommended)
```bash
tiktok-quality input.mp4 output.mp4
# OR:
python -m tiktok_quality input.mp4 output.mp4
```

#### Custom Bitrate & Speed Preset
```bash
tiktok-quality input.mp4 output.mp4 --bitrate-multiplier 0.9 --preset slow
```

#### Custom Audio Bitrates & Level
```bash
tiktok-quality input.mp4 output.mp4 --audio-bitrate1 192 --audio-bitrate2 256 --level 4.2
```

#### Verify an Existing Output File
```bash
tiktok-quality --verify output.mp4
```

#### Check Dependencies
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
| `--gui` | Flag | - | Launch Tkinter GUI |
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
| `--check-deps` | Flag | - | Check Python and FFmpeg availability |

---

## 📂 Project Structure

```
tiktok-quality-fix/
├── pyproject.toml
├── README.md
├── LICENSE
├── proof.png
├── src/tiktok_quality/
│   ├── __init__.py          # Package entry and API exports
│   ├── __main__.py          # CLI / GUI router
│   ├── cli.py               # Unified CLI
│   ├── gui.py               # Tkinter GUI application
│   ├── compressbase.py      # Core CompressBase pipeline orchestrator
│   ├── encoder.py           # FFmpeg wrapper (CBL L4.2, Dual AAC, faststart)
│   ├── patcher.py           # Recursive ISOBMFF parser and binary patcher
│   ├── validator.py         # Target specification compliance validator
│   ├── target_spec.json     # Reference JSON spec for output compliance
│   ├── transform.py         # Legacy ghost-frames container manipulator
│   ├── randomize.py         # Entropy & randomization utilities
│   ├── detect.py            # Heuristic detection analyzer
│   └── mp4/                 # Low-level MP4 box builders and parsers
│       ├── __init__.py
│       ├── parser.py
│       └── builder.py
└── tests/
    ├── test_mp4.py          # MP4 box parsing and building unit tests
    ├── test_patcher.py      # ISOBMFF binary patcher unit tests
    ├── test_randomize.py    # Randomization and entropy unit tests
    └── test_validator.py    # Target spec validation unit tests
```

---

## 🧪 Running Automated Tests

Run the test suite with standard Python (zero external test dependencies required):

```bash
python -m unittest discover -s tests -v
```

---

## 🛡️ Best Practices for Uploading to TikTok

1. **Always export master videos at 1080x1920 (9:16 vertical) 60fps** with clean audio.
2. Enable **"Upload HD / Allow high-quality uploads"** in TikTok's advance settings before posting.
3. Process your video with `tiktok-quality input.mp4 output.mp4` or the GUI.
4. Allow TikTok 2-5 minutes after uploading before making the video public.

---

## 📝 License

MIT — see [LICENSE](LICENSE) for details.
