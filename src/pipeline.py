"""Pipeline for processing AAC, MP3, MP4, and other voice recordings in person subfolders.

Scans the input directory for person subdirectories, identifies supported
recordings (.aac, .mp3, .mp4, .m4a, .ogg, .flac, .wma, .opus), converts them
into 16kHz mono WAV audio, and saves the converted files directly into their
respective person subfolders with the format: converted+<original_name>.wav.
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

# Enable UTF-8 encoding on standard output/stderr if supported on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure parent directory is in sys.path when running file directly
_parent_dir = str(Path(__file__).resolve().parent.parent)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

try:
    from src.audio_converter import (
        ConversionResult,
        _format_file_size,
        convert_audio_to_wav,
        get_ffmpeg_binary,
        is_supported_audio_file,
    )
except ImportError:
    from audio_converter import (
        ConversionResult,
        _format_file_size,
        convert_audio_to_wav,
        get_ffmpeg_binary,
        is_supported_audio_file,
    )

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("audio_pipeline")

DEFAULT_CONFIG_PATH = Path(_parent_dir) / "config.json"

# JSON schema definition for config validation
CONFIG_SCHEMA = {
    "input_dir": str,
    "sample_rate": int,
    "channels": int,
    "overwrite": bool,
    "output_prefix": str,
    "supported_extensions": list,
    "excluded_folders": list,
}


def validate_config(config: dict) -> list[str]:
    """Validate config values and return a list of warnings for any issues."""
    warnings = []

    sample_rate = config.get("sample_rate")
    if sample_rate is not None:
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            warnings.append(f"Invalid 'sample_rate': {sample_rate} (must be a positive integer)")
        elif sample_rate not in (8000, 16000, 22050, 44100, 48000):
            warnings.append(
                f"Unusual 'sample_rate': {sample_rate}Hz. "
                f"Common values: 8000, 16000, 22050, 44100, 48000"
            )

    channels = config.get("channels")
    if channels is not None:
        if not isinstance(channels, int) or channels not in (1, 2):
            warnings.append(f"Invalid 'channels': {channels} (must be 1 for mono or 2 for stereo)")

    extensions = config.get("supported_extensions")
    if extensions is not None:
        if not isinstance(extensions, list):
            warnings.append(f"'supported_extensions' must be a list, got {type(extensions).__name__}")
        else:
            for ext in extensions:
                if not isinstance(ext, str) or not ext.startswith("."):
                    warnings.append(f"Invalid extension in 'supported_extensions': '{ext}' (must start with '.')")

    excluded = config.get("excluded_folders")
    if excluded is not None:
        if not isinstance(excluded, list):
            warnings.append(f"'excluded_folders' must be a list, got {type(excluded).__name__}")

    prefix = config.get("output_prefix")
    if prefix is not None:
        if not isinstance(prefix, str):
            warnings.append(f"'output_prefix' must be a string, got {type(prefix).__name__}")

    return warnings


def load_config(config_file: Optional[Path | str] = None) -> dict:
    """Load configuration from a JSON file, or return defaults if not found."""
    path = Path(config_file) if config_file else DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"Loaded configuration from: {path.resolve()}")

                # Validate config values
                warnings = validate_config(data)
                for w in warnings:
                    logger.warning(f"Config warning: {w}")

                return data
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file {path}: {e}. Using defaults.")
        except Exception as e:
            logger.warning(f"Failed to read config file {path}: {e}. Using defaults.")
    return {}


@dataclass
class ConversionSummary:
    person_name: str
    folder_path: Path
    audio_files_count: int
    converted_files: List[Path] = field(default_factory=list)
    skipped_files: List[Path] = field(default_factory=list)
    failed_files: List[tuple[Path, str]] = field(default_factory=list)
    total_input_bytes: int = 0
    total_output_bytes: int = 0


@dataclass
class PipelineReport:
    root_dir: Path
    total_persons: int = 0
    total_audio_identified: int = 0
    total_converted: int = 0
    total_non_supported_skipped: int = 0
    total_failed: int = 0
    total_input_bytes: int = 0
    total_output_bytes: int = 0
    person_summaries: List[ConversionSummary] = field(default_factory=list)
    elapsed_time_sec: float = 0.0
    dry_run: bool = False


class AudioPipeline:
    """Pipeline to scan person directories and convert voice recordings to 16kHz mono WAV."""

    DEFAULT_EXCLUDED_FOLDERS = {
        "src", ".git", ".venv", "venv", "__pycache__", ".agents", ".gemini", "converter"
    }

    def __init__(
        self,
        root_dir: Path | str = ".",
        sample_rate: int = 16000,
        channels: int = 1,
        overwrite: bool = True,
        output_prefix: str = "converted+",
        supported_extensions: Optional[List[str]] = None,
        excluded_folders: Optional[Set[str]] = None,
        dry_run: bool = False,
    ):
        self.root_dir = Path(root_dir).resolve()
        self.sample_rate = sample_rate
        self.channels = channels
        self.overwrite = overwrite
        self.output_prefix = output_prefix
        self.supported_extensions = (
            supported_extensions if supported_extensions is not None
            else [".aac", ".mp3", ".mp4", ".m4a", ".ogg", ".flac", ".wma", ".opus"]
        )
        self.excluded_folders = (
            set(excluded_folders) if excluded_folders is not None else self.DEFAULT_EXCLUDED_FOLDERS
        )
        self.dry_run = dry_run
        self.ffmpeg_bin = get_ffmpeg_binary()
        logger.info(f"Using FFmpeg binary: {self.ffmpeg_bin}")

    def discover_person_folders(self) -> List[Path]:
        """Find all immediate subdirectories representing individuals."""
        if not self.root_dir.exists():
            raise FileNotFoundError(f"Input directory does not exist: {self.root_dir}")

        person_folders = [
            folder
            for folder in self.root_dir.iterdir()
            if folder.is_dir() and folder.name not in self.excluded_folders
        ]
        person_folders.sort(key=lambda p: p.name.lower())
        return person_folders

    def scan_person_folder(self, person_folder: Path) -> tuple[List[Path], List[Path]]:
        """Identify supported audio recordings and non-supported files in a person folder."""
        valid_files: List[Path] = []
        skipped_files: List[Path] = []

        for item in person_folder.iterdir():
            if item.is_file():
                # Ignore already converted output files
                if self.output_prefix and item.name.startswith(self.output_prefix):
                    continue

                if is_supported_audio_file(
                    item,
                    supported_extensions=self.supported_extensions,
                    output_prefix=self.output_prefix,
                ):
                    valid_files.append(item)
                else:
                    skipped_files.append(item)

        valid_files.sort(key=lambda p: p.name.lower())
        skipped_files.sort(key=lambda p: p.name.lower())
        return valid_files, skipped_files

    def process_person_folder(self, person_folder: Path) -> ConversionSummary:
        """Process all supported recordings in a person's folder."""
        audio_files, non_audio_files = self.scan_person_folder(person_folder)
        summary = ConversionSummary(
            person_name=person_folder.name,
            folder_path=person_folder,
            audio_files_count=len(audio_files),
            skipped_files=non_audio_files,
        )

        logger.info(
            f"Processing folder: '{person_folder.name}' -> Found {len(audio_files)} recording(s), "
            f"Skipped {len(non_audio_files)} file(s)"
        )

        if len(audio_files) == 0 and len(non_audio_files) > 0:
            ext_set = {f.suffix.lower() for f in non_audio_files}
            logger.warning(
                f"  No supported audio in '{person_folder.name}', but found files with "
                f"extensions: {', '.join(sorted(ext_set))}. Consider adding them to "
                f"'supported_extensions' in config.json if they contain audio."
            )

        for src_path in audio_files:
            output_filename = f"{self.output_prefix}{src_path.stem}.wav"
            output_wav = src_path.parent / output_filename

            if self.dry_run:
                logger.info(f"  [DRY-RUN] Would convert: {src_path.name} -> {output_filename}")
                summary.converted_files.append(output_wav)
                continue

            try:
                result: ConversionResult = convert_audio_to_wav(
                    input_file=src_path,
                    output_file=output_wav,
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                    overwrite=self.overwrite,
                    output_prefix=self.output_prefix,
                    ffmpeg_bin=self.ffmpeg_bin,
                )
                summary.converted_files.append(result.output_file)
                summary.total_input_bytes += result.input_size_bytes
                summary.total_output_bytes += result.output_size_bytes
                logger.info(
                    f"  [OK] Converted: {src_path.name} -> {output_wav.name} "
                    f"({_format_file_size(result.input_size_bytes)} -> "
                    f"{_format_file_size(result.output_size_bytes)})"
                )
            except Exception as e:
                logger.error(f"  [ERR] Failed to convert {src_path.name}: {e}")
                summary.failed_files.append((src_path, str(e)))

        return summary

    def run(self) -> PipelineReport:
        """Execute the entire pipeline across all person subdirectories."""
        start_time = time.time()
        mode_label = " [DRY-RUN MODE]" if self.dry_run else ""
        logger.info(f"Starting Audio Pipeline on: {self.root_dir}{mode_label}")
        logger.info(
            f"Configuration: Sample Rate={self.sample_rate}Hz, Channels={self.channels} "
            f"({'mono' if self.channels == 1 else 'stereo'}), "
            f"Output Naming='{self.output_prefix}<original>.wav', "
            f"Extensions={self.supported_extensions}, Overwrite={self.overwrite}"
        )

        person_folders = self.discover_person_folders()
        report = PipelineReport(
            root_dir=self.root_dir,
            total_persons=len(person_folders),
            dry_run=self.dry_run,
        )

        if len(person_folders) == 0:
            logger.warning(
                f"No person subdirectories found in: {self.root_dir}. "
                f"Ensure the input directory contains subfolders for each person."
            )

        for folder in person_folders:
            summary = self.process_person_folder(folder)
            report.person_summaries.append(summary)
            report.total_audio_identified += summary.audio_files_count
            report.total_converted += len(summary.converted_files)
            report.total_non_supported_skipped += len(summary.skipped_files)
            report.total_failed += len(summary.failed_files)
            report.total_input_bytes += summary.total_input_bytes
            report.total_output_bytes += summary.total_output_bytes

        report.elapsed_time_sec = time.time() - start_time
        self.print_summary_report(report)
        return report

    @staticmethod
    def print_summary_report(report: PipelineReport) -> None:
        """Print a structured summary of the pipeline execution."""
        separator = "=" * 70
        mode_label = " (DRY-RUN)" if report.dry_run else ""
        print("\n" + separator)
        print(f" PIPELINE EXECUTION SUMMARY{mode_label}")
        print(separator)
        print(f" Input Directory       : {report.root_dir}")
        print(f" Person Folders Found  : {report.total_persons}")
        print(f" Audio Identified      : {report.total_audio_identified}")
        print(f" Successfully Converted: {report.total_converted} (16kHz mono WAV)")
        print(f" Non-Supported Skipped : {report.total_non_supported_skipped}")
        print(f" Failures              : {report.total_failed}")

        if not report.dry_run and report.total_input_bytes > 0:
            print(
                f" Total Size (in->out)  : "
                f"{_format_file_size(report.total_input_bytes)} -> "
                f"{_format_file_size(report.total_output_bytes)}"
            )

        print(f" Elapsed Time          : {report.elapsed_time_sec:.2f}s")
        print(separator)

        for summary in report.person_summaries:
            status_tag = "[OK]" if not summary.failed_files else "[WARN]"
            print(
                f" {status_tag} Person: {summary.person_name:<14} "
                f"| Found: {summary.audio_files_count:2d} "
                f"| Converted: {len(summary.converted_files):2d} "
                f"| Skipped: {len(summary.skipped_files):2d}"
            )
            if summary.failed_files:
                for failed_file, err in summary.failed_files:
                    print(f"     ! Error in {failed_file.name}: {err}")

        print(separator + "\n")


def resolve_input_directory(cli_input: Optional[str], config_input: Optional[str]) -> Path:
    """Determine the input folder via CLI arg, interactive prompt, or config."""
    # 1. If passed via CLI argument, use it directly
    if cli_input:
        chosen_path = Path(cli_input.strip("\"'"))
        if not chosen_path.exists():
            raise FileNotFoundError(f"Provided input folder does not exist: {chosen_path}")
        return chosen_path.resolve()

    default_dir = config_input if config_input else "."

    # 2. If running interactively, prompt the user
    if sys.stdin.isatty():
        try:
            print(f"\n--- Audio Pipeline Input Configuration ---")
            prompt_str = f"Enter input folder path [press Enter for '{default_dir}']: "
            user_input = input(prompt_str).strip().strip("\"'")
            if user_input:
                chosen_path = Path(user_input)
                if not chosen_path.exists():
                    logger.warning(f"Path '{chosen_path}' does not exist! Falling back to '{default_dir}'.")
                else:
                    return chosen_path.resolve()
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            sys.exit(0)

    # 3. Fall back to config / default
    fallback_path = Path(default_dir)
    if not fallback_path.is_absolute():
        fallback_path = (Path(_parent_dir) / fallback_path).resolve()

    if not fallback_path.exists():
        # Check current working directory
        if Path(".").resolve().exists():
            fallback_path = Path(".").resolve()

    return fallback_path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Batch convert audio recordings in person subfolders to 16kHz mono WAV."
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        type=str,
        default=None,
        help="Input folder containing person subdirectories (interactive prompt/config used if omitted).",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to custom config.json file (default: config.json in root).",
    )
    parser.add_argument(
        "--sample-rate",
        "-sr",
        type=int,
        default=None,
        help="Target sample rate in Hz (default: from config or 16000).",
    )
    parser.add_argument(
        "--channels",
        "-c",
        type=int,
        default=None,
        help="Audio channels, 1 for mono, 2 for stereo (default: from config or 1).",
    )
    parser.add_argument(
        "--output-prefix",
        type=str,
        default=None,
        help="Prefix for converted output audio (default: 'converted+').",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Skip conversion if output WAV already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be converted without actually running FFmpeg.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug-level logging for more detailed output.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress all output except errors and the final summary.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Set log level based on CLI flags
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)
        logger.setLevel(logging.ERROR)

    config = load_config(args.config)

    # Resolve input directory (CLI arg -> interactive prompt -> config file -> current dir)
    input_dir = resolve_input_directory(args.input_dir, config.get("input_dir"))
    sample_rate = args.sample_rate or config.get("sample_rate", 16000)
    channels = args.channels or config.get("channels", 1)
    output_prefix = args.output_prefix or config.get("output_prefix", "converted+")
    supported_extensions = config.get("supported_extensions", [".aac", ".mp3", ".mp4", ".m4a"])
    excluded_folders = set(config.get("excluded_folders", [])) or None
    overwrite = not args.no_overwrite if args.no_overwrite else config.get("overwrite", True)

    pipeline = AudioPipeline(
        root_dir=input_dir,
        sample_rate=sample_rate,
        channels=channels,
        overwrite=overwrite,
        output_prefix=output_prefix,
        supported_extensions=supported_extensions,
        excluded_folders=excluded_folders,
        dry_run=args.dry_run,
    )
    report = pipeline.run()

    # Exit with non-zero code if there were any failures
    if report.total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
