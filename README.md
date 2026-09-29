# 🎙️ Audio Converter Pipeline

A batch audio preprocessing pipeline that converts voice recordings (AAC, MP3, MP4, M4A, and more) into standardized **16 kHz mono WAV** files — ready for speaker recognition, speech-to-text, and other downstream ML tasks.

---

## 📋 Overview

This tool is designed for the **SIH Hardware** project's voice enrollment workflow. It scans a root directory containing **person-named subfolders**, identifies audio recordings in each, and converts them to a uniform WAV format using FFmpeg.

### Directory Structure (Expected)

```
data/
├── devendra/
│   ├── WhatsApp Audio 2026-09-28 at 11.04.11 PM.aac
│   ├── WhatsApp Audio 2026-09-28 at 11.04.13 PM.aac
│   └── ...
├── pranvav/
│   ├── WhatsApp Audio 2026-09-28 at 11.29.36 PM.aac
│   └── ...
├── sriakr/
│   ├── WhatsApp Audio 2026-09-28 at 10.46.31 PM.mp4
│   └── ...
└── vasu/
    └── ...
```

After running the pipeline, each folder gets `converted+<original_name>.wav` files:

```
data/devendra/
├── WhatsApp Audio 2026-09-28 at 11.04.11 PM.aac          ← original
├── converted+WhatsApp Audio 2026-09-28 at 11.04.11 PM.wav ← 16kHz mono WAV
└── ...
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

> This installs [`imageio-ffmpeg`](https://github.com/imageio/imageio-ffmpeg), which bundles a portable FFmpeg binary. If you already have FFmpeg in your system PATH, it will use that instead.

### 2. Run the Pipeline

```bash
# From the audio/ directory
python -m src --input-dir ../data
```

That's it! The pipeline will:
1. Discover all person subfolders in `../data`
2. Find supported audio files (`.aac`, `.mp3`, `.mp4`, `.m4a`)
3. Convert each to 16 kHz mono WAV
4. Print a detailed summary report

---

## ⚙️ Configuration

### Config File (`config.json`)

The pipeline reads settings from `config.json` in the project root:

```json
{
  "input_dir": "../data",
  "sample_rate": 16000,
  "channels": 1,
  "overwrite": true,
  "output_prefix": "converted+",
  "supported_extensions": [".aac", ".mp3", ".mp4", ".m4a"],
  "excluded_folders": ["src", ".git", ".venv", "venv", "__pycache__", ".agents", ".gemini", "converter"]
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `input_dir` | `string` | `"."` | Root directory containing person subfolders |
| `sample_rate` | `int` | `16000` | Target sample rate in Hz |
| `channels` | `int` | `1` | Audio channels (`1` = mono, `2` = stereo) |
| `overwrite` | `bool` | `true` | Overwrite existing converted files |
| `output_prefix` | `string` | `"converted+"` | Prefix added to output filenames |
| `supported_extensions` | `list[str]` | `[".aac", ".mp3", ".mp4", ".m4a"]` | File extensions to process |
| `excluded_folders` | `list[str]` | *see above* | Subdirectory names to skip |

### CLI Arguments

CLI arguments **override** config file values:

```
usage: python -m src [-h] [--input-dir INPUT_DIR] [--config CONFIG]
                     [--sample-rate SAMPLE_RATE] [--channels CHANNELS]
                     [--output-prefix OUTPUT_PREFIX] [--no-overwrite]
                     [--dry-run] [--verbose] [--quiet]

Options:
  -i, --input-dir      Input folder with person subdirectories
  --config             Path to custom config.json
  -sr, --sample-rate   Target sample rate in Hz (default: 16000)
  -c, --channels       Audio channels: 1=mono, 2=stereo (default: 1)
  --output-prefix      Prefix for output filenames (default: 'converted+')
  --no-overwrite       Skip if output WAV already exists
  --dry-run            Preview conversions without running FFmpeg
  -v, --verbose        Enable debug-level logging
  -q, --quiet          Suppress all output except errors and summary
```

---

## 📖 Usage Examples

### Preview what would be converted (dry run)
```bash
python -m src --input-dir ../data --dry-run
```

### Convert with custom sample rate
```bash
python -m src --input-dir ../data --sample-rate 44100
```

### Skip already converted files
```bash
python -m src --input-dir ../data --no-overwrite
```

### Use a custom config file
```bash
python -m src --config /path/to/my-config.json
```

### Verbose output for debugging
```bash
python -m src --input-dir ../data --verbose
```

---

## 📊 Sample Output

```
======================================================================
 PIPELINE EXECUTION SUMMARY
======================================================================
 Input Directory       : C:\Users\shree\Desktop\SIH\Hardware\data
 Person Folders Found  : 6
 Audio Identified      : 25
 Successfully Converted: 25 (16kHz mono WAV)
 Non-Supported Skipped : 20
 Failures              : 0
 Total Size (in->out)  : 497.9 KB -> 1.14 MB
 Elapsed Time          : 1.97s
======================================================================
 [OK] Person: devendra       | Found:  5 | Converted:  5 | Skipped:  5
 [OK] Person: pranvav        | Found:  5 | Converted:  5 | Skipped:  5
 [OK] Person: sriakr         | Found:  5 | Converted:  5 | Skipped:  0
 [OK] Person: syntehtic      | Found:  0 | Converted:  0 | Skipped:  0
 [OK] Person: vardhan        | Found:  5 | Converted:  5 | Skipped:  5
 [OK] Person: vasu           | Found:  5 | Converted:  5 | Skipped:  5
======================================================================
```

---

## 🏗️ Project Structure

```
audio/
├── config.json              # Pipeline configuration
├── requirements.txt         # Python dependencies
├── .gitignore               # Git ignore rules
├── README.md                # This file
└── src/
    ├── __init__.py           # Package exports
    ├── __main__.py           # Entry point (python -m src)
    ├── audio_converter.py    # Core FFmpeg conversion logic
    └── pipeline.py           # Pipeline orchestration & CLI
```

### Module Details

| Module | Responsibility |
|--------|---------------|
| [`audio_converter.py`](src/audio_converter.py) | Low-level FFmpeg wrapper: file validation, conversion, output integrity checks |
| [`pipeline.py`](src/pipeline.py) | High-level orchestration: folder discovery, batch processing, config loading, CLI parsing, reporting |

---

## 🔧 Programmatic Usage

You can also use the pipeline as a Python library:

```python
from src import AudioPipeline

pipeline = AudioPipeline(
    root_dir="../data",
    sample_rate=16000,
    channels=1,
    overwrite=True,
)

report = pipeline.run()

print(f"Converted {report.total_converted} files in {report.elapsed_time_sec:.1f}s")
print(f"Failures: {report.total_failed}")
```

Or convert a single file:

```python
from src import convert_audio_to_wav
from pathlib import Path

result = convert_audio_to_wav(
    input_file=Path("recording.aac"),
    sample_rate=16000,
    channels=1,
)
print(f"Output: {result.output_file} ({result.output_size_bytes} bytes)")
```

---

## 📝 Notes

- **FFmpeg resolution**: The pipeline first checks for `ffmpeg` on your system PATH. If not found, it falls back to the bundled binary from `imageio-ffmpeg`.
- **Output format**: All files are converted to **16-bit PCM WAV** (`pcm_s16le`), which is the standard uncompressed format expected by most speech/audio ML pipelines.
- **File size increase**: WAV files are uncompressed, so output files will be larger than compressed inputs (typically 2–4×). This is expected and necessary for lossless audio processing.
- **Timeout**: Each file conversion has a 2-minute timeout to prevent hangs on corrupted files.
- **Exit codes**: The process exits with code `1` if any conversions fail, making it suitable for CI/CD pipelines.

---

## 📄 License

Internal project — SIH Hardware Team.
