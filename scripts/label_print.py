#!/usr/bin/env python3
"""Batch-print Gridfinity component label images on a Brother PT-P710BT.

The defaults are calibrated for 12 mm TZe tape and the EllaFoxo
Gridfinity-Component-Labels artwork:

    227 px wide x 70 px printable height

227 px (about 1 mm shorter than the original 234 px) was physically calibrated to fit comfortably in the user's
Gridfinity label recess with the ptouch default 2 mm feed margin.
"""

from __future__ import annotations

import argparse
import glob
import re
import sys
from pathlib import Path
from typing import Iterable

from PIL import Image
from ptouch import (
    ConnectionUSB,
    Label,
    PrinterConnectionError,
    PTP710BT,
    Tape12mm,
)

TARGET_WIDTH_PX = 227
TARGET_HEIGHT_PX = 70
SUPPORTED_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}

# These are useful source assets, but not individual labels.  Skip them when
# a directory or glob is supplied.  An explicitly named file is still accepted.
META_ASSET_RE = re.compile(r"(?:^complete set(?: \(no cut lines\))?$| header$)", re.I)


def natural_key(path: Path) -> list[object]:
    """Sort M3x6 before M3x10."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


def is_supported(path: Path) -> bool:
    return path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES


def is_meta_asset(path: Path) -> bool:
    return bool(META_ASSET_RE.search(path.stem))


def expand_directory(path: Path) -> list[Path]:
    return sorted(
        (p for p in path.rglob("*") if is_supported(p) and not is_meta_asset(p)),
        key=natural_key,
    )


def expand_glob(pattern: str) -> list[Path]:
    matches = [Path(p).expanduser().resolve() for p in glob.glob(str(Path(pattern).expanduser()), recursive=True)]
    return sorted(
        (p for p in matches if is_supported(p) and not is_meta_asset(p)),
        key=natural_key,
    )


def resolve_inputs(inputs: Iterable[str]) -> list[Path]:
    """Resolve explicit files, directories, and shell-like glob patterns."""
    resolved: list[Path] = []

    for raw in inputs:
        expanded = str(Path(raw).expanduser())

        if glob.has_magic(expanded):
            matches = expand_glob(expanded)
            if not matches:
                raise FileNotFoundError(f"No supported images matched pattern: {raw}")
            resolved.extend(matches)
            continue

        path = Path(expanded).resolve()
        if path.is_dir():
            matches = expand_directory(path)
            if not matches:
                raise FileNotFoundError(f"No supported individual label images found under: {path}")
            resolved.extend(matches)
        elif is_supported(path):
            # Explicit files are never filtered as meta assets: if you name a
            # Complete Set image directly, assume you know what you are doing.
            resolved.append(path)
        elif path.exists():
            raise ValueError(f"Unsupported image type: {path}")
        else:
            raise FileNotFoundError(path)

    # De-duplicate while preserving the requested order.
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in resolved:
        if path not in seen:
            seen.add(path)
            unique.append(path)

    if not unique:
        raise ValueError("No labels selected")

    return unique


def flatten_on_white(image: Image.Image) -> Image.Image:
    """Match the ImageMagick '-background white -alpha remove' test."""
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, "white")
    white.alpha_composite(rgba)
    return white.convert("RGB")


def prepare_image(path: Path, width: int, height: int) -> Image.Image:
    """Fit source artwork inside a fixed white width x height raster."""
    with Image.open(path) as source:
        source = flatten_on_white(source)

        scale = min(width / source.width, height / source.height)
        new_width = max(1, round(source.width * scale))
        new_height = max(1, round(source.height * scale))

        resized = source.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # A fixed-width canvas makes every finished Gridfinity label the same
    # physical length.  The artwork is centered exactly as ptouch would center
    # the 234x64 test image in the 70-dot printable region.
    canvas = Image.new("RGB", (width, height), "white")
    x = (width - new_width) // 2
    y = (height - new_height) // 2
    canvas.paste(resized, (x, y))
    return canvas


def save_previews(prepared: list[tuple[Path, Image.Image]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for index, (source, image) in enumerate(prepared, 1):
        destination = directory / f"{index:03d}-{source.stem}.png"
        image.save(destination)
        print(f"preview: {destination}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-print individual Gridfinity label images on a Brother PT-P710BT.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Image files, directories, or glob patterns. Directories are scanned recursively.",
    )
    parser.add_argument(
        "--width-px",
        type=int,
        default=TARGET_WIDTH_PX,
        help=f"Fixed raster width (default: {TARGET_WIDTH_PX}, physically calibrated for the Gridfinity recess).",
    )
    parser.add_argument(
        "--height-px",
        type=int,
        default=TARGET_HEIGHT_PX,
        help=f"Printable raster height (default: {TARGET_HEIGHT_PX} for 12 mm TZe tape).",
    )
    parser.add_argument(
        "--margin-mm",
        type=float,
        default=2.0,
        help="ptouch feed margin in mm (default: 2.0).",
    )
    parser.add_argument(
        "--copies",
        type=int,
        default=1,
        help="Copies of each selected label, adjacent in the batch (default: 1).",
    )
    parser.add_argument(
        "--precut",
        action="store_true",
        help="Ask ptouch to eject/cut the initial leader before the first label.",
    )
    parser.add_argument(
        "--preview-dir",
        type=Path,
        help="Save normalized printer rasters here before printing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and render the batch but do not contact the printer.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.width_px < 1 or args.height_px < 1:
        raise ValueError("width/height must be positive")
    if args.copies < 1:
        raise ValueError("copies must be at least 1")

    sources = resolve_inputs(args.inputs)

    expanded_sources: list[Path] = []
    for source in sources:
        expanded_sources.extend([source] * args.copies)

    prepared = [
        (source, prepare_image(source, args.width_px, args.height_px))
        for source in expanded_sources
    ]

    print(f"Selected {len(prepared)} label(s)")
    print(f"Raster: {args.width_px}x{args.height_px}px; tape: 12 mm; margin: {args.margin_mm:g} mm")
    for index, (source, _image) in enumerate(prepared, 1):
        print(f"  {index:3d}. {source}")

    if args.preview_dir:
        save_previews(prepared, args.preview_dir.expanduser().resolve())

    if args.dry_run:
        print("Dry run: printer not contacted.")
        return 0

    labels = [Label(image, Tape12mm) for _source, image in prepared]

    try:
        printer = PTP710BT(ConnectionUSB())
        # P710BT has no half-cutter. One multi-label job gives us one initial
        # leader and full cuts between the individual labels.
        printer.print_multi(
            labels,
            margin_mm=args.margin_mm,
            half_cut=False,
            precut=args.precut,
        )
    except PrinterConnectionError as exc:
        print(f"Printer error: {exc}", file=sys.stderr)
        return 2

    print("Done.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
