#!/usr/bin/env python3
"""Convert DICOM CT images to windowed grayscale PNG files."""

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut
from PIL import Image


OUTPUT_SIZE = (512, 512) # I will use this size for the output PNG images


def window_hu(pixels, center, width):
    """Apply the DICOM LINEAR window function to pixels already in HU."""
    if width == 1:
        return np.where(pixels <= center - 0.5, 0, 255).astype(np.uint8)

    windowed = ((pixels - (center - 0.5)) / (width - 1) + 0.5) * 255
    return np.rint(np.clip(windowed, 0, 255)).astype(np.uint8)


def parse_arguments():
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Convert DICOM CT images to PNG using the supplied HU window center "
            "and width. Input folders are searched recursively."
        )
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "input",
        help="Folder containing DICOM images (default: data/input)",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "output",
        help="Folder for PNG images (default: data/output)",
    )
    parser.add_argument(
        "--window-center",
        "--window-level",
        dest="window_center",
        type=float,
        required=True,
        help="Window center/level in HU",
    )
    parser.add_argument(
        "--window-width",
        type=float,
        required=True,
        help="Positive window width in HU (minimum 1)",
    )
    parser.add_argument(
        "--delete-input",
        action="store_true",
        help="Delete successfully converted files from the input folder after conversion",
    )
    return parser.parse_args()


def convert_file(source_path, destination_base, center, width):
    dataset = pydicom.dcmread(source_path)
    photometric = getattr(dataset, "PhotometricInterpretation", "")
    if photometric not in {"MONOCHROME1", "MONOCHROME2"}:
        raise ValueError(f"unsupported photometric interpretation: {photometric!r}")

    pixels = np.asarray(dataset.pixel_array)
    pixels = np.asarray(apply_modality_lut(pixels, dataset), dtype=np.float64)
    if not np.isfinite(pixels).all():
        raise ValueError("pixel data contains non-finite values after HU conversion")

    frame_count = int(getattr(dataset, "NumberOfFrames", 1))
    if frame_count == 1 and pixels.ndim == 2:
        frames = [pixels]
    elif frame_count > 1 and pixels.ndim == 3 and pixels.shape[0] == frame_count:
        frames = list(pixels)
    else:
        raise ValueError(
            f"unsupported pixel array shape {pixels.shape} for {frame_count} frame(s)"
        )

    destination_base.parent.mkdir(parents=True, exist_ok=True)
    for frame_index, frame in enumerate(frames):
        image = window_hu(frame, center, width)
        if photometric == "MONOCHROME1":
            image = 255 - image
        destination = (
            destination_base
            if frame_count == 1
            else destination_base.with_name(
                f"{destination_base.stem}_{frame_index + 1:04d}.png"
            )
        )
        png = Image.fromarray(image).resize(OUTPUT_SIZE, Image.Resampling.BILINEAR)
        png.save(destination, format="PNG")


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        logging.error("Input folder does not exist or is not a directory: %s", input_dir)
        return 2
    if input_dir == output_dir or input_dir in output_dir.parents:
        logging.error("Output folder must differ from and not be inside the input folder.")
        return 2
    if not math.isfinite(args.window_center):
        logging.error("Window center must be a finite number.")
        return 2
    if not math.isfinite(args.window_width) or args.window_width < 1:
        logging.error("Window width must be a finite number greater than or equal to 1.")
        return 2

    source_paths = sorted(path for path in input_dir.rglob("*") if path.is_file())
    converted = 0
    skipped = 0
    converted_paths = []
    for source_path in source_paths:
        relative_path = source_path.relative_to(input_dir)
        destination_base = (output_dir / relative_path).with_suffix(".png")
        try:
            convert_file(
                source_path, destination_base, args.window_center, args.window_width
            )
        except (
            InvalidDicomError,
            OSError,
            ValueError,
            TypeError,
            RuntimeError,
            NotImplementedError,
            EOFError,
            AttributeError,
        ) as error:
            logging.warning("Skipping %s: %s", source_path, error)
            skipped += 1
            continue
        converted += 1
        converted_paths.append(source_path)

    if converted == 0:
        logging.error("No supported DICOM images were converted from %s.", input_dir)
        return 1
    deletion_errors = 0
    if args.delete_input:
        for source_path in converted_paths:
            try:
                source_path.unlink()
            except OSError as error:
                logging.error("Could not delete converted input file %s: %s", source_path, error)
                deletion_errors += 1

    logging.info("Converted %d DICOM files; skipped %d files.", converted, skipped)
    logging.info("PNG images written to %s", output_dir)

    if args.delete_input:
        logging.info("Deleted %d converted input files.", len(converted_paths) - deletion_errors)
        
    if deletion_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
