#!/usr/bin/env python3
"""Extract and aggregate selected metadata properties from DICOM files."""

import argparse
import base64
import json
import logging
import math
import sys
from pathlib import Path

import pydicom
from pydicom.errors import InvalidDicomError
from pydicom.multival import MultiValue


DATE_TIME_VRS = {"DA", "DT", "TM"}
PIXEL_DATA_TAGS = {
    pydicom.tag.Tag(0x7FE00008),
    pydicom.tag.Tag(0x7FE00009),
    pydicom.tag.Tag(0x7FE00010),
}


def json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (list, tuple, MultiValue)):
        return [json_value(item) for item in value]
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    return str(value)


def add_property(properties, element, relative_path):
    tag = str(element.tag)
    record = properties.setdefault(
        tag,
        {
            "tag": tag,
            "keyword": element.keyword,
            "name": element.name,
            "vr": element.VR,
            "_files": set(),
            "_values": {},
        },
    )
    record["_files"].add(relative_path)

    value = {"items": len(element.value)} if element.VR == "SQ" else json_value(element.value)
    encoded_value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    value_record = record["_values"].setdefault(
        encoded_value,
        {"value": value, "occurrences": 0, "_files": set()},
    )
    value_record["occurrences"] += 1
    value_record["_files"].add(relative_path)


def is_empty_value(value):
    if value is None or value == "":
        return True
    if isinstance(value, list):
        return not value or all(is_empty_value(item) for item in value)
    if isinstance(value, dict):
        return value.get("items") == 0 or value.get("bytes_base64") == ""
    return False


def serializable_properties(properties, files_processed):
    common_properties = []
    varying_properties = []
    for record in properties.values():
        value_records = list(record["_values"].values())
        if (
            len(record["_files"]) == files_processed
            and value_records
            and all(is_empty_value(item["value"]) for item in value_records)
        ):
            continue

        is_common = (
            len(record["_files"]) == files_processed and len(value_records) == 1
        )
        values = []
        for value_record in sorted(
            value_records,
            key=lambda item: json.dumps(
                item["value"], sort_keys=True, ensure_ascii=False
            ),
        ):
            serialized_value = {
                "value": value_record["value"],
                "occurrences": value_record["occurrences"],
                "files_present": len(value_record["_files"]),
            }
            if not is_common:
                serialized_value["file_names"] = sorted(value_record["_files"])
            values.append(serialized_value)

        serialized_record = {
            "tag": record["tag"],
            "keyword": record["keyword"],
            "name": record["name"],
            "vr": record["vr"],
            "files_present": len(record["_files"]),
            "values": values,
        }
        (common_properties if is_common else varying_properties).append(
            serialized_record
        )

    return (
        sorted(common_properties, key=lambda item: item["tag"]),
        sorted(varying_properties, key=lambda item: item["tag"]),
    )


def load_referenced_tags(reference_file):
    try:
        reference = json.loads(reference_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(
            f"Could not read tag reference file {reference_file}: {error}"
        ) from error

    try:
        return {
            pydicom.tag.Tag(
                tuple(int(part, 16) for part in item["tag"].strip("()").split(","))
            )
            for item in reference["tags"]
        }
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise ValueError(
            f"Invalid tag reference format in {reference_file}; expected a tags array "
            "with universal tag identifiers."
        ) from error


def parse_arguments():
    project_dir = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Extract selected metadata properties from DICOM files and write "
            "JSON aggregates. By default, reads from data/input and writes "
            "aggregates to data/output."
        )
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "input",
        help="Folder containing DICOM files (default: data/input)",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=project_dir / "data" / "output",
        help="Folder for property JSON aggregates (default: data/output)",
    )
    parser.add_argument(
        "--aggregate-file",
        type=Path,
        help=(
            "Write one aggregate across all input files to this path instead of "
            "writing one dicom_properties.json per patient folder"
        ),
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    tag_reference_file = (
        Path(__file__).resolve().parents[1] / "data" / "dicom_tag_reference.json"
    )
    aggregate_file = (
        args.aggregate_file.expanduser().resolve()
        if args.aggregate_file
        else None
    )

    if not input_dir.is_dir():
        logging.error("Input folder does not exist or is not a directory: %s", input_dir)
        return 2
    if input_dir == output_dir:
        logging.error("Output folder must differ from the input folder.")
        return 2
    if output_dir in input_dir.parents:
        logging.error("Output folder must not contain the input folder.")
        return 2
    if aggregate_file and (
        aggregate_file == input_dir or input_dir in aggregate_file.parents
    ):
        logging.error("Aggregate JSON must not be written inside the input folder.")
        return 2
    try:
        referenced_tags = load_referenced_tags(tag_reference_file)
    except ValueError as error:
        logging.error("%s", error)
        return 2

    paths = [
        path
        for path in input_dir.rglob("*")
        if path.is_file()
        and output_dir not in path.resolve().parents
        and (not aggregate_file or path.resolve() != aggregate_file)
    ]
    patient_aggregates = {}
    processed = 0
    skipped = 0

    for source_path in paths:
        relative_path = source_path.relative_to(input_dir)
        patient_dir = (
            Path(relative_path.parts[0])
            if not aggregate_file and len(relative_path.parts) > 1
            else None
        )
        aggregate_key = None if aggregate_file else patient_dir
        patient_data = patient_aggregates.setdefault(
            aggregate_key, {"properties": {}, "processed": 0, "skipped": 0}
        )
        try:
            dataset = pydicom.dcmread(source_path, stop_before_pixels=True)
        except InvalidDicomError:
            logging.warning("Skipping non-DICOM file: %s", source_path)
            skipped += 1
            patient_data["skipped"] += 1
            continue
        except OSError as error:
            logging.warning("Could not read %s: %s", source_path, error)
            skipped += 1
            patient_data["skipped"] += 1
            continue

        property_path = (
            relative_path.relative_to(patient_dir)
            if patient_dir
            else relative_path
        ).as_posix()
        for element in dataset.iterall():
            if (
                element.tag not in referenced_tags
                or element.VR in DATE_TIME_VRS
                or element.tag in PIXEL_DATA_TAGS
            ):
                continue
            add_property(patient_data["properties"], element, property_path)

        processed += 1
        patient_data["processed"] += 1

    if processed == 0:
        logging.error("No readable DICOM files were found in %s.", input_dir)
        return 1

    for patient_dir, patient_data in patient_aggregates.items():
        if patient_data["processed"] == 0:
            continue
        common_properties, varying_properties = serializable_properties(
            patient_data["properties"], patient_data["processed"]
        )
        aggregate = {
            "common_properties": common_properties,
            "files_processed": patient_data["processed"],
            "files_skipped": patient_data["skipped"],
            "excluded_value_representations": sorted(DATE_TIME_VRS),
            "excluded_pixel_data_tags": sorted(str(tag) for tag in PIXEL_DATA_TAGS),
            "properties": varying_properties,
        }
        destination = (
            aggregate_file
            if aggregate_file
            else output_dir / (patient_dir or Path()) / "dicom_properties.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logging.info("Metadata aggregate written to %s", destination)

    logging.info("Processed %d DICOM files; skipped %d files.", processed, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())