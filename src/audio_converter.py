"""Audio conversion utilities for converting AAC, MP3, and MP4 files to 16kHz mono WAV format."""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger("audio_pipeline")

DEFAULT_SUPPORTED_EXTENSIONS = {".aac", ".mp3", ".mp4", ".m4a", ".ogg", ".flac", ".wma", ".opus"}


@dataclass
class ConversionResult:
    """Result of a single file conversion operation."""

    input_file: Path
    output_file: Path
    success: bool
    input_size_bytes: int = 0
    output_size_bytes: int = 0
    error_message: Optional[str] = None

    @property
    def compression_ratio(self) -> Optional[float]:
        """Return the ratio of output size to input size, if both are non-zero."""
        if self.input_size_bytes > 0 and self.output_size_bytes > 0:
            return self.output_size_bytes / self.input_size_bytes
        return None


def get_ffmpeg_binary() -> str:
    """Find and return the path to the ffmpeg executable.

    Checks system PATH first, then falls back to imageio_ffmpeg bundled binary.
    """
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass

    raise RuntimeError(
        "FFmpeg not found in system PATH and 'imageio-ffmpeg' is not installed. "
        "Please install imageio-ffmpeg via 'pip install imageio-ffmpeg' or add ffmpeg to PATH."
    )


def is_supported_audio_file(
    file_path: Path,
    supported_extensions: Optional[Iterable[str]] = None,
    output_prefix: str = "converted+",
) -> bool:
    """Check if the given file is an audio recording that matches supported extensions.

    Skips any already converted files (matching output_prefix) and files not matching extensions.
    """
    if not file_path.is_file():
        return False

    if output_prefix and file_path.name.startswith(output_prefix):
        return False

    exts = (
        {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in supported_extensions}
        if supported_extensions is not None
        else DEFAULT_SUPPORTED_EXTENSIONS
    )
    return file_path.suffix.lower() in exts


def is_aac_file(file_path: Path) -> bool:
    """Legacy helper strictly checking for .aac files."""
    return is_supported_audio_file(file_path, supported_extensions={".aac"})


def _validate_output_file(output_path: Path) -> None:
    """Validate that the output WAV file was created and is non-empty."""
    if not output_path.exists():
        raise RuntimeError(f"Output file was not created: {output_path}")
    if output_path.stat().st_size == 0:
        output_path.unlink()  # Remove the empty file
        raise RuntimeError(f"Output file is empty (0 bytes), removed: {output_path}")


def convert_audio_to_wav(
    input_file: Path,
    output_file: Optional[Path] = None,
    sample_rate: int = 16000,
    channels: int = 1,
    overwrite: bool = True,
    output_prefix: str = "converted+",
    ffmpeg_bin: Optional[str] = None,
) -> ConversionResult:
    """Convert an audio file (AAC/MP3/MP4/etc.) to a 16kHz mono WAV file.

    Parameters
    ----------
    input_file : Path
        Path to the source audio file.
    output_file : Optional[Path]
        Target .wav path. If None, places the file in the same directory as input_file
        with name: '{output_prefix}{input_file.stem}.wav'.
    sample_rate : int
        Audio sample rate in Hz (default: 16000).
    channels : int
        Number of audio channels (1 = mono, 2 = stereo, default: 1).
    overwrite : bool
        Whether to overwrite the destination file if it already exists.
    output_prefix : str
        Prefix for the output filename when output_file is None (default: 'converted+').
    ffmpeg_bin : Optional[str]
        Path to the ffmpeg binary. If None, detected automatically.

    Returns
    -------
    ConversionResult
        Detailed result of the conversion including file sizes and status.
    """
    input_path = Path(input_file).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")

    input_size = input_path.stat().st_size
    if input_size == 0:
        raise ValueError(f"Input file is empty (0 bytes): {input_path}")

    if output_file is None:
        output_filename = f"{output_prefix}{input_path.stem}.wav"
        output_path = input_path.parent / output_filename
    else:
        output_path = Path(output_file).resolve()

    if output_path.exists() and not overwrite:
        logger.info(f"Skipping (already exists): {output_path.name}")
        return ConversionResult(
            input_file=input_path,
            output_file=output_path,
            success=True,
            input_size_bytes=input_size,
            output_size_bytes=output_path.stat().st_size,
        )

    if ffmpeg_bin is None:
        ffmpeg_bin = get_ffmpeg_binary()

    # Build ffmpeg command:
    # -y: overwrite output
    # -i: input file
    # -vn: disable video stream (if any)
    # -acodec pcm_s16le: standard 16-bit PCM WAV
    # -ar: sample rate (16000)
    # -ac: audio channels (1 for mono)
    cmd = [
        ffmpeg_bin,
        "-y" if overwrite else "-n",
        "-i", str(input_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,  # 2-minute timeout per file
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg timed out after 120s converting: {input_path.name}")

    if result.returncode != 0:
        logger.error(f"FFmpeg error converting {input_path.name}:\n{result.stderr}")
        raise RuntimeError(f"FFmpeg failed with exit code {result.returncode}: {result.stderr}")

    # Validate the output file
    _validate_output_file(output_path)

    output_size = output_path.stat().st_size
    return ConversionResult(
        input_file=input_path,
        output_file=output_path,
        success=True,
        input_size_bytes=input_size,
        output_size_bytes=output_size,
    )


def _format_file_size(size_bytes: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


# Backward compatibility alias
convert_aac_to_wav = convert_audio_to_wav
