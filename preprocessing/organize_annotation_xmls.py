#!/usr/bin/env python3
"""Move flat XML annotation files into their patient folders."""

import argparse
import logging
import re
import shutil
import sys
from pathlib import Path


ANNOTATION_FILENAME = re.compile(r"(?P<patient_id>.+)_(?P<number>\d+)\.xml", re.IGNORECASE)


def parse_arguments():
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Move XML files directly inside the data folder into "
            "data/input folders named for their patient IDs."
        )
    )
    parser.add_argument(
        "data_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data",
        help="Data folder containing XML files and the input directory (default: data)",
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    data_dir = args.data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        logging.error("Data folder does not exist or is not a directory: %s", data_dir)
        return 2

    xml_paths = sorted(
        path
        for path in data_dir.iterdir()
        if path.is_file() and path.suffix.casefold() == ".xml"
    )
    if not xml_paths:
        logging.error("No XML annotation files found directly inside %s", data_dir)
        return 1

    moves = []
    errors = 0
    for source_path in xml_paths:
        match = ANNOTATION_FILENAME.fullmatch(source_path.name)
        if match is None:
            logging.error(
                "Annotation filename must be <patient id>_<number>.xml: %s",
                source_path,
            )
            errors += 1
            continue

        patient_id = match.group("patient_id")
        if patient_id in {".", "..", "input"} or Path(patient_id).name != patient_id:
            logging.error("Invalid patient ID in annotation filename: %s", source_path)
            errors += 1
            continue

        destination = data_dir / "input" / patient_id / source_path.name
        if destination.exists():
            logging.error("Destination already exists; refusing to overwrite: %s", destination)
            errors += 1
            continue
        moves.append((source_path, destination))

    if errors:
        logging.error("Could not validate %d XML file(s); no files were moved.", errors)
        return 1

    for source_path, destination in moves:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(destination))
        except OSError as error:
            logging.error("Could not move %s to %s: %s", source_path, destination, error)
            return 1

    logging.info("Moved %d XML annotation file(s) into patient folders.", len(moves))
    return 0


if __name__ == "__main__":
    sys.exit(main())
