#!/usr/bin/env python3
"""Check that PNG images are 512 x 512 pixels."""

import argparse
import logging
import sys
from pathlib import Path

from PIL import Image


EXPECTED_SIZE = (512, 512)


def parse_arguments():
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Recursively check PNG image dimensions."
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "output",
        help="Folder containing PNG images (default: data/output)",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    output_dir = args.output_dir.expanduser().resolve()
    if not output_dir.is_dir():
        logging.error("Output folder does not exist or is not a directory: %s", output_dir)
        return 2

    png_paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() == ".png"
    )
    if not png_paths:
        logging.error("No PNG files were found in %s.", output_dir)
        return 1

    invalid = 0
    for path in png_paths:
        try:
            with Image.open(path) as image:
                size = image.size
                image.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            logging.error("Could not read PNG %s: %s", path, error)
            invalid += 1
            continue

        if size != EXPECTED_SIZE:
            logging.error(
                "Unexpected dimensions for %s: %s (expected %s)",
                path,
                size,
                EXPECTED_SIZE,
            )
            invalid += 1

    checked = len(png_paths)
    if invalid:
        logging.error("Checked %d PNG files; %d failed validation.", checked, invalid)
        return 1

    logging.info("All %d PNG files are %d x %d pixels.", checked, *EXPECTED_SIZE)
    return 0


if __name__ == "__main__":
    sys.exit(main())