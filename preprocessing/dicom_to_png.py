#!/usr/bin/env python3
"""Convert DICOM CT images to windowed grayscale PNG files."""

import argparse
import logging
import math
import re
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
    parser.add_argument(
        "--annotations-only",
        action="store_true",
        help=(
            "Convert only images selected by XML annotations in each "
            "patient's annotations folder"
        ),
    )
    return parser.parse_args()


def read_frames(source_path):
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

    return frames, photometric


def validate_dicom_header(source_path):
    dataset = pydicom.dcmread(source_path, stop_before_pixels=True)
    photometric = getattr(dataset, "PhotometricInterpretation", "")
    if photometric not in {"MONOCHROME1", "MONOCHROME2"}:
        raise ValueError(f"unsupported photometric interpretation: {photometric!r}")
    if int(getattr(dataset, "Rows", 0)) < 1 or int(
        getattr(dataset, "Columns", 0)
    ) < 1:
        raise ValueError("DICOM image has invalid rows or columns")


def frame_destinations(destination_base, frame_count):
    if frame_count == 1:
        return [destination_base]
    return [
        destination_base.with_name(f"{destination_base.stem}_{index + 1:04d}.png")
        for index in range(frame_count)
    ]


def convert_file(source_path, destination_base, center, width):
    frames, photometric = read_frames(source_path)
    destinations = frame_destinations(destination_base, len(frames))

    for frame_index, frame in enumerate(frames):
        image = window_hu(frame, center, width)
        if photometric == "MONOCHROME1":
            image = 255 - image
        destination = destinations[frame_index]
        destination.parent.mkdir(parents=True, exist_ok=True)
        png = Image.fromarray(image).resize(OUTPUT_SIZE, Image.Resampling.BILINEAR)
        png.save(destination, format="PNG")


def dicom_sort_key(path):
    numbers = re.findall(r"\d+", path.name)
    number = int(numbers[0]) if numbers else math.inf
    natural_name = tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", path.name)
    )
    return number, natural_name


def annotated_dicom_selections(input_dir, candidate_paths):
    dicoms_by_patient = {}
    for source_path in candidate_paths:
        patient_id = source_path.relative_to(input_dir).parts[0]
        dicoms_by_patient.setdefault(patient_id, []).append(source_path)

    selected_paths = set()
    errors = 0
    for patient_dir in sorted(path for path in input_dir.iterdir() if path.is_dir()):
        patient_id = patient_dir.name
        xml_paths = sorted(
            path
            for path in patient_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".xml"
        )
        if not xml_paths:
            continue

        dicom_paths = sorted(
            dicoms_by_patient.get(patient_id, []),
            key=dicom_sort_key,
        )
        if not dicom_paths:
            logging.error("No convertible DICOM files found for patient %s.", patient_id)
            errors += 1
            continue

        for xml_path in xml_paths:
            match = re.fullmatch(rf"{re.escape(patient_id)}_(\d+)", xml_path.stem)
            if match is None:
                logging.error(
                    "Annotation filename must be %s_<number>.xml: %s",
                    patient_id,
                    xml_path,
                )
                errors += 1
                continue
            helpful_number = int(match.group(1))
            image_number = len(dicom_paths) - helpful_number
            if helpful_number < 1 or not 1 <= image_number <= len(dicom_paths):
                logging.error(
                    "Annotation %s selects image %d, outside the valid range 1-%d "
                    "(%d DICOM files, helpful number %d)",
                    xml_path,
                    image_number,
                    len(dicom_paths),
                    len(dicom_paths),
                    helpful_number,
                )
                errors += 1
                continue

            selected_paths.add(dicom_paths[image_number - 1])

    if errors:
        logging.error(
            "Could not process %d annotation selection(s); no PNGs were written.",
            errors,
        )
        return None
    if not selected_paths:
        logging.error("No matching annotated images were found.")
        return None
    return selected_paths


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
    selected_paths = None
    if args.annotations_only:
        candidate_paths = []
        for patient_dir in sorted(path for path in input_dir.iterdir() if path.is_dir()):
            for source_path in sorted(
                path
                for path in patient_dir.iterdir()
                if path.is_file() and path.suffix.casefold() == ".dcm"
            ):
                try:
                    validate_dicom_header(source_path)
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
                candidate_paths.append(source_path)

        selected_paths = annotated_dicom_selections(input_dir, candidate_paths)
        if selected_paths is None:
            return 1

    for source_path in source_paths:
        relative_path = source_path.relative_to(input_dir)
        destination_base = (output_dir / relative_path).with_suffix(".png")
        if selected_paths is not None and source_path not in selected_paths:
            continue
        try:
            convert_file(
                source_path,
                destination_base,
                args.window_center,
                args.window_width,
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
        logging.error("No selected DICOM images were converted from %s.", input_dir)
        return 1
    deletion_errors = 0
    if args.delete_input:
        for source_path in converted_paths:
            try:
                source_path.unlink()
            except OSError as error:
                logging.error("Could not delete converted input file %s: %s", source_path, error)
                deletion_errors += 1

    logging.info(
        "Converted %d DICOM files; skipped %d files.", converted, skipped
    )
    logging.info("PNG images written to %s", output_dir)

    if args.delete_input:
        logging.info("Deleted %d converted input files.", len(converted_paths) - deletion_errors)
        
    if deletion_errors:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
