# Chinese SFUDA Codebase

This repository contains the preprocessing utilities for a source-free unsupervised domain adaptation (SFUDA) study on Chinese CT datasets. The project focuses on quantifying how domain shift from time, geography, and scanner vendor affects model performance.

The datasets used for this work are from:

- [Linyi Central Hospital](https://doi.org/10.5281/zenodo.11024613)
- [Harbin Medical University](https://www.cancerimagingarchive.net/collection/lung-pet-ct-dx/)

## Repository layout

- `requirements.txt` — Python dependencies required by the preprocessing utilities.
- `preprocessing/dicom_tag_extractor.py` — extracts a curated subset of DICOM metadata and writes patient-level JSON aggregates.
- `preprocessing/dicom_to_png.py` — converts DICOM CT slices/volumes to windowed grayscale PNGs, optionally limited to XML-annotated images.
- `preprocessing/organize_annotation_xmls.py` — aggregates XML annotations into `data/input/annotations.csv`.
- `preprocessing/resolution_check.py` — recursively verifies that PNGs under `data/output/` are 512 x 512 pixels.
- `preprocessing/grayscale_check.py` — recursively checks PNGs under `data/output/` for grayscale images.
- `data/dicom_tag_reference.json` — reference list of DICOM tags retained during metadata extraction.

## Setup

Install the required Python dependencies:

```sh
python -m pip install -r requirements.txt
```

## Repository validation

Run a quick syntax check across the project before using the scripts:

```sh
python -m compileall model preprocessing
```

## Extract DICOM metadata

By default, the tag extractor reads DICOM files recursively from `data/input/` and writes one `dicom_properties.json` file per patient folder under `data/output/`:

```sh
python preprocessing/dicom_tag_extractor.py
```

You can override the input and output folders with positional arguments:

```sh
python preprocessing/dicom_tag_extractor.py /path/to/dicom-input /path/to/properties-output
```

By default, the script does not modify or copy the original DICOM files. Each
output JSON aggregates the metadata for one patient and includes:

- `common_properties` — tags with the same value across all processed files
- `properties` — varying tags with occurrence counts, file counts, and file names for each value

The extractor ignores empty values that are uniform across the patient, excludes DICOM values with VR `DA`, `DT`, or `TM`, and omits pixel data tags. Only the universal tag identifiers listed in `data/dicom_tag_reference.json` are retained. Some metadata may contain identifying information, so review outputs before sharing or storing them.

By default, the input files are kept. Pass `--delete-input` to remove successfully processed DICOM files after the metadata aggregates have been written; skipped files are left untouched:

```sh
python preprocessing/dicom_tag_extractor.py --delete-input
```

To write a single aggregate for all files to a custom path instead of patient-level outputs, use:

```sh
python preprocessing/dicom_tag_extractor.py --aggregate-file /path/to/metadata.json
```

## Convert DICOM images to PNG

Convert a DICOM folder to windowed grayscale PNGs by supplying the HU window center and width:

```sh
python preprocessing/dicom_to_png.py \
  --window-center 40 --window-width 400
```

By default the script reads recursively from `data/input/` and writes output PNGs under `data/output/`, preserving the relative folder structure so patient data stays grouped. Override the folders with positional arguments:

```sh
python preprocessing/dicom_to_png.py /path/to/dicom-input /path/to/png-output \
  --window-center 40 --window-width 400
```

To avoid storing PNGs for unannotated slices, add `--annotations-only`:

```sh
python preprocessing/dicom_to_png.py \
  --window-center 40 --window-width 400 --annotations-only
```

In this mode, the script reads annotations from `data/input/<patient>/` (or
from the root of `data/input/` when the patient ID is in the XML filename).
It orders valid DICOMs in each patient folder by filename, then uses each
`<patient id>_<helpful number>.xml` filename to select an image. The selected
one-based DICOM index is the number of valid DICOM files minus the helpful
number. For example, with 70 valid DICOM files and helpful number 41, it
selects the 29th file in filename order. Multiple XML files can select multiple
images. All frames of a selected multiframe DICOM are converted. The selected
files receive the same HU windowing and 512 x 512 resizing as a full
conversion. Malformed or out-of-range annotations stop the run before any
PNGs are written.

The conversion process:

- reads each DICOM file
- applies the modality LUT or rescale slope/intercept when available
- applies the requested HU window
- resizes all output images to 512 x 512 pixels
- writes one PNG per frame for multiframe grayscale DICOMs

By default, the input files are kept. Pass `--delete-input` to remove successfully converted DICOM files after export; skipped or failed files are left untouched.

## Check PNG resolutions

Recursively check that every PNG under `data/output/` is 512 x 512 pixels:

```sh
python preprocessing/resolution_check.py
```

The script reports files with unexpected dimensions or unreadable PNGs and exits
with a nonzero status if any PNG fails validation. To check a different folder,
pass it as an argument:

```sh
python preprocessing/resolution_check.py /path/to/png-output
```

## Check PNG grayscale

Recursively check that PNGs under `data/output/` are grayscale:

```sh
python preprocessing/grayscale_check.py
```

To check a different folder, pass it as an argument:

```sh
python preprocessing/grayscale_check.py /path/to/png-output
```

## Aggregate XML annotations

Aggregate XML files in `data/input/` and its patient folders into
`data/input/annotations.csv`:

```sh
python preprocessing/organize_annotation_xmls.py
```

For each `<patient id>_<helpful number>.xml`, the script uses the same
selection logic as `dicom_to_png.py`: it filters invalid DICOMs, sorts the
remaining files in that patient's folder, and selects the file at
`valid file count - helpful number`. The CSV columns are `filename`, `xmin`,
`ymin`, `xmax`, and `ymax`. `filename` is the selected DICOM's PNG path
relative to the PNG output folder, preserving the patient folder; it is not the
XML's `<filename>` value. For example, if the selected DICOM is
`data/input/0001/_99.DCM`, the CSV filename is `0001/_99.png`. XML files with
multiple objects produce one row per bounding box, and the XML files are left
unchanged. The CSV is written to the selected input folder and replaces any
existing `annotations.csv` there. Override the input folder with a positional
argument:

```sh
python preprocessing/organize_annotation_xmls.py /path/to/dicom-input
```

If any XML file is malformed or missing bounding-box coordinates, or its
helpful number cannot select a DICOM, the script reports the error and does not
write the CSV.

The annotation-selection workflow is already handled by `dicom_to_png.py` via
`--annotations-only`, so a separate PNG filter is unnecessary when generating
the selected subset directly from DICOM inputs.