# Chinese SFUDA Codebase

This repository contains the preprocessing utilities for a source-free unsupervised domain adaptation (SFUDA) study on Chinese CT datasets. The project focuses on quantifying how domain shift from time, geography, and scanner vendor affects model performance.

The datasets used for this work are from:

- [Linyi Central Hospital](https://doi.org/10.5281/zenodo.11024613)
- [Harbin Medical University](https://www.cancerimagingarchive.net/collection/lung-pet-ct-dx/)

## Repository layout

- `preprocessing/dicom_tag_extractor.py` — extracts a curated subset of DICOM metadata and writes patient-level JSON aggregates.
- `preprocessing/dicom_to_png.py` — converts DICOM CT slices/volumes to windowed grayscale PNGs.
- `data/dicom_tag_reference.json` — reference list of DICOM tags retained during metadata extraction.
- `model/model_a.py` — model scaffold / experimental entry point.

## Setup

Install the required Python dependencies:

```sh
python -m pip install -r requirements.txt
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

The script does not modify or copy the original DICOM files. Each output JSON aggregates the metadata for one patient and includes:

- `common_properties` — tags with the same value across all processed files
- `properties` — varying tags with occurrence counts, file counts, and file names for each value

The extractor ignores empty values that are uniform across the patient, excludes DICOM values with VR `DA`, `DT`, or `TM`, and omits pixel data tags. Only the universal tag identifiers listed in `data/dicom_tag_reference.json` are retained. Some metadata may contain identifying information, so review outputs before sharing or storing them.

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

The conversion process:

- reads each DICOM file
- applies the modality LUT or rescale slope/intercept when available
- applies the requested HU window
- resizes all output images to 512 x 512 pixels
- writes one PNG per frame for multiframe grayscale DICOMs

By default, the input files are kept. Pass `--delete-input` to remove successfully converted DICOM files after export; skipped or failed files are left untouched.