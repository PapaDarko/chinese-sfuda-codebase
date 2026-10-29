#!/usr/bin/env python3
"""Aggregate XML bounding-box annotations into a CSV file."""

import argparse
import csv
import logging
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

if __package__:
    from .dicom_to_png import (
        annotation_dicom_candidates,
        annotation_dicom_path,
        dicom_sort_key,
    )
else:
    from dicom_to_png import (
        annotation_dicom_candidates,
        annotation_dicom_path,
        dicom_sort_key,
    )


CSV_FIELDS = ("filename", "xmin", "ymin", "xmax", "ymax")


def parse_arguments():
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate XML annotations from the DICOM input folder into "
            "annotations.csv."
        )
    )
    parser.add_argument(
        "data_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "input",
        help="DICOM input folder containing XML annotations (default: data/input)",
    )
    return parser.parse_args()


def read_annotation_rows(xml_path, image_filename):
    root = ET.parse(xml_path).getroot()
    objects = root.findall("object")
    if not objects:
        raise ValueError("missing <object>")

    rows = []
    for index, obj in enumerate(objects, start=1):
        box = obj.find("bndbox")
        if box is None:
            raise ValueError(f"object {index} is missing <bndbox>")

        coordinates = {}
        for field in CSV_FIELDS[1:]:
            value = box.findtext(field)
            if value is None:
                raise ValueError(f"object {index} is missing <{field}>")
            try:
                coordinates[field] = int(value.strip())
            except ValueError as error:
                raise ValueError(
                    f"object {index} has a non-integer <{field}> value"
                ) from error

        rows.append({"filename": image_filename, **coordinates})
    return rows


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    data_dir = args.data_dir.expanduser().resolve()
    if not data_dir.is_dir():
        logging.error("Data folder does not exist or is not a directory: %s", data_dir)
        return 2

    xml_paths = []
    for path in sorted(data_dir.iterdir()):
        if path.is_file() and path.suffix.casefold() == ".xml":
            xml_paths.append(path)
        elif path.is_dir():
            xml_paths.extend(
                child
                for child in sorted(path.iterdir())
                if child.is_file() and child.suffix.casefold() == ".xml"
            )
    if not xml_paths:
                logging.error(
                    "No XML annotations found in %s or its patient folders.", data_dir
                )
                return 1

    candidate_paths, _ = annotation_dicom_candidates(data_dir)
    dicoms_by_patient = {}
    for path in candidate_paths:
        dicoms_by_patient.setdefault(path.parent.name, []).append(path)

    rows = []
    errors = 0
    for xml_path in xml_paths:
        try:
            if xml_path.parent == data_dir:
                match = re.fullmatch(r"(.+)_(\d+)", xml_path.stem)
                if match is None:
                    raise ValueError(
                        "annotation filename must be <patient id>_<number>.xml"
                    )
                patient_id = match.group(1)
            else:
                patient_id = xml_path.parent.name

            dicom_paths = sorted(
                dicoms_by_patient.get(patient_id, []),
                key=dicom_sort_key,
            )
            if not dicom_paths:
                raise ValueError(f"no convertible DICOM files found for {patient_id}")

            selected_dicom = annotation_dicom_path(
                xml_path, patient_id, dicom_paths
            )
            image_filename = (
                selected_dicom.relative_to(data_dir).with_suffix(".png").as_posix()
            )
            rows.extend(read_annotation_rows(xml_path, image_filename))
        except (ET.ParseError, OSError, ValueError) as error:
            logging.error("Could not process annotation %s: %s", xml_path, error)
            errors += 1

    if errors:
        logging.error("Could not process %d XML file(s); no CSV was written.", errors)
        return 1

    csv_path = data_dir / "annotations.csv"
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as error:
        logging.error("Could not write annotation CSV %s: %s", csv_path, error)
        return 1

    logging.info(
        "Wrote %d annotation(s) from %d XML file(s) to %s.",
        len(rows),
        len(xml_paths),
        csv_path,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
