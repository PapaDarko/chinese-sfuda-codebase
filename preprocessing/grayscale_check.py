"""Check that image files are stored as three-channel grayscale images."""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageChops

def check_image(path: Path) -> str | None:
	"""Return an error description if the image is not three-channel grayscale."""
	try:
		with Image.open(path) as image:
			if image.mode != "RGB":
				return f"expected 3-channel RGB, found {image.mode}"

			red, green, blue = image.split()
			if (
				ImageChops.difference(red, green).getbbox() is not None
				or ImageChops.difference(red, blue).getbbox() is not None
			):
				return "RGB channels are not identical"
	except Exception as error:
		return f"could not read image: {error}"
	return None


def main() -> int:
	parser = argparse.ArgumentParser(
		description="Recursively verify that images are three-channel grayscale."
	)
	parser.add_argument(
		"output_dir",
		nargs="?",
		type=Path,
		default=Path("."),
		help="directory containing output images (default: current directory)",
	)
	args = parser.parse_args()

	if not args.output_dir.is_dir():
		print(f"Not a directory: {args.output_dir}", file=sys.stderr)
		return 2

	files = sorted(
		path
		for path in args.output_dir.rglob("*")
		if path.is_file() and path.suffix.lower() == ".png"
	)
	if not files:
		print(f"No image files found under {args.output_dir}", file=sys.stderr)
		return 1

	failures = 0
	for path in files:
		error = check_image(path)
		if error:
			failures += 1
			print(f"FAIL {path}: {error}")

	if failures:
		print(f"Checked {len(files)} image(s): {failures} failed.")
		return 1

	print(f"Checked {len(files)} image(s): all are three-channel grayscale.")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
