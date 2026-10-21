#!/usr/bin/env python3
"""Generate the flush head, T-nut and nyloc label sets.

Each label starts from the M5x10 button head SVG, so the canvas, fonts and
text positions match the screw labels exactly.  Only the icon group and the
heading/size text are replaced.  Output goes to Universal Labels/ as
SVG/PNG/PDF, like gen.sh.

Needs Inkscape and the Fira Code font installed.  The T-nut icons are traced
from PNG, so run it with:

    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py flush
    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py tnut M5 roll-in hammerhead slide-in
    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py nyloc M5 M6
    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py hexnut M6
    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py washer M8
    uv run --with potracer --with pillow --with numpy scripts/gen_labels.py hexbolt M8 25 40
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LABELS = REPO / "Universal Labels"
ICONS = REPO / "Component Icons"
BASE = (LABELS / "Screws/Button Head/M5/SVG/M5x10.svg").read_text()
LENGTHS = (REPO / "scripts/replacements.csv").read_text().split()

ICON_GROUP = re.compile(r'<g\s+id="g3024-5-6-2".*?</g>', re.S)

# Icon boxes in label coordinates (mm): side view on the left, head/top view on the right.
SIDE_BOX = (9.0, 21.05, 14.2, 30.95)
TOP_BOX = (14.8, 21.05, 20.0, 30.95)


def make_svg(icons: str, heading: str, text: str, name: str) -> str:
    svg = ICON_GROUP.sub(lambda _: f'<g id="g3024-5-6-2" style="display:inline">{icons}</g>', BASE)
    return (
        svg.replace(">Button Head<", f">{heading}<")
        .replace(">M5x10<", f">{text}<")
        .replace('docname="M5x10.svg"', f'docname="{name}.svg"')
    )


def write_label(directory: Path, name: str, svg: str) -> None:
    for sub in ("SVG", "PNG", "PDF"):
        (directory / sub).mkdir(parents=True, exist_ok=True)
    source = directory / "SVG" / f"{name}.svg"
    source.write_text(svg)
    for kind in ("png", "pdf"):
        target = directory / kind.upper() / f"{name}.{kind}"
        subprocess.run(
            ["inkscape", f"--export-type={kind}", f"--export-filename={target}", "--export-dpi=1200", str(source)],
            check=True,
            capture_output=True,
        )
    print(f"  {name}")


def flush() -> None:
    icons = ICONS / "Screws/Flush Head"
    path = lambda f: re.search(r' d="([^"]*)"', (icons / f).read_text()).group(1)
    # head.svg / side.svg place their paths inside layers with these offsets.
    group = (
        f'<path style="fill:#000000" transform="translate(13.286,24.286) translate(18.747431,9.5058136)" d="{path("head.svg")}"/>'
        f'<path style="fill:#000000" transform="translate(9.565,21.05) translate(-19.98431,-7.0119751)" d="{path("side.svg")}"/>'
    )
    out = LABELS / "Screws/Flush Head/M5"
    for length in LENGTHS:
        name = f"M5x{length}"
        write_label(out, name, make_svg(group, "Flush Head", name, name))


def trace(png: Path, box: tuple[float, float, float, float]) -> str:
    """Trace an icon PNG to an SVG path element fitted and centred in box."""
    import numpy as np
    import potrace
    from PIL import Image

    im = Image.open(png).convert("RGBA")
    mask = (np.array(im)[..., 3] > 127) & (np.array(im.convert("L")) < 128)
    ys, xs = np.where(mask)
    mask = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    x0, y0, x1, y1 = box
    scale = min((x1 - x0) / mask.shape[1], (y1 - y0) / mask.shape[0])
    tx = x0 + ((x1 - x0) - mask.shape[1] * scale) / 2
    ty = y0 + ((y1 - y0) - mask.shape[0] * scale) / 2
    parts = []
    # potracer traces the False pixels, so feed it the inverted mask.
    for curve in potrace.Bitmap(~mask).trace(turdsize=20, alphamax=0.6, opttolerance=0.4):
        start = curve.start_point
        d = [f"M{start.x:.2f},{start.y:.2f}"]
        for seg in curve.segments:
            if seg.is_corner:
                d.append(f"L{seg.c.x:.2f},{seg.c.y:.2f}L{seg.end_point.x:.2f},{seg.end_point.y:.2f}")
            else:
                d.append(
                    f"C{seg.c1.x:.2f},{seg.c1.y:.2f} {seg.c2.x:.2f},{seg.c2.y:.2f} {seg.end_point.x:.2f},{seg.end_point.y:.2f}"
                )
        parts.append("".join(d) + "Z")
    return (
        f'<path style="fill:#000000;fill-rule:evenodd" '
        f'transform="translate({tx:.3f},{ty:.3f}) scale({scale:.5f})" d="{"".join(parts)}"/>'
    )


# kind -> (icon folder, label name, heading).  The M3 artwork is reused for every size.
TNUT_KINDS = {
    "roll-in": ("M3 Roll-In", "Roll-In T-Nut", "Roll-In Nut"),
    "hammerhead": ("M3 Hammerhead", "Hammerhead T-Nut", "Hammerhead"),
    "slide-in": ("M5 Square", "Slide-In T-Nut", "Slide-In Nut"),
}


def tnut(size: str, kinds: list[str]) -> None:
    for kind in kinds:
        folder, suffix, heading = TNUT_KINDS[kind]
        name = f"{size} {suffix}"
        group = trace(ICONS / "T-Nuts" / folder / "side.png", SIDE_BOX) + trace(
            ICONS / "T-Nuts" / folder / "top.png", TOP_BOX
        )
        write_label(LABELS / "T-Nuts", name, make_svg(group, heading, size, name))


def nyloc(sizes: list[str]) -> None:
    # Side view: hex body in three faces with a rounded nylon collar above it.
    side = (
        "M9,25.3H10.225V28.6H9.35L9,28.25Z "
        "M10.375,25.3H12.825V28.6H10.375Z "
        "M12.975,25.3H14.2V28.25L13.85,28.6H12.975Z "
        "M9.5,25.12V24.6Q9.5,23.4 10.9,23.4H12.3Q13.7,23.4 13.7,24.6V25.12Z"
    )
    # Top view: hex, nylon ring and bolt hole, cut out with even-odd fill.
    cx, cy, r_hex = 17.4, 26.0, 2.6
    hexagon = "M" + "L".join(
        f"{cx + r_hex * math.cos(math.radians(a)):.3f},{cy + r_hex * math.sin(math.radians(a)):.3f}"
        for a in range(0, 360, 60)
    ) + "Z"
    circle = lambda r: f"M{cx - r:.3f},{cy}a{r},{r} 0 1 0 {2 * r},0a{r},{r} 0 1 0 {-2 * r},0Z"
    top = hexagon + circle(2.05) + circle(1.8) + circle(1.1)
    group = (
        f'<path style="fill:#000000" d="{side}"/>'
        f'<path style="fill:#000000;fill-rule:evenodd" d="{top}"/>'
    )
    for size in sizes:
        name = f"{size} Nyloc Nut"
        write_label(LABELS / "Nuts", name, make_svg(group, "Nyloc Nut", size, name))


def retext(subdir: str, kind: str, sizes: list[str]) -> None:
    """Labels for other sizes: the M5 label of this kind with the size text swapped."""
    template = (LABELS / subdir / f"SVG/M5 {kind}.svg").read_text()
    for size in sizes:
        name = f"{size} {kind}"
        svg = template.replace(">M5<", f">{size}<").replace(f"M5 {kind}", name)
        write_label(LABELS / subdir, name, svg)


def hexbolt(size: str, lengths: list[str]) -> None:
    # Side view: head in three faces with a chamfered top, over a plain shank.
    side = (
        "M9,21.4L9.4,21H10.225V24.2H9Z "
        "M10.375,21H12.825V24.2H10.375Z "
        "M12.975,21H13.8L14.2,21.4V24.2H12.975Z "
        "M10.3,24.35H12.9V30.74L12.64,31H10.56L10.3,30.74Z"
    )
    # Top view: hex with the chamfer ring cut out (even-odd fill).
    cx, cy, r_hex = 17.4, 26.0, 2.6
    hexagon = "M" + "L".join(
        f"{cx + r_hex * math.cos(math.radians(a)):.3f},{cy + r_hex * math.sin(math.radians(a)):.3f}"
        for a in range(0, 360, 60)
    ) + "Z"
    circle = lambda r: f"M{cx - r:.3f},{cy}a{r},{r} 0 1 0 {2 * r},0a{r},{r} 0 1 0 {-2 * r},0Z"
    top = hexagon + circle(2.05) + circle(1.8)
    group = (
        f'<path style="fill:#000000" d="{side}"/>'
        f'<path style="fill:#000000;fill-rule:evenodd" d="{top}"/>'
    )
    for length in lengths:
        name = f"{size}x{length}"
        write_label(LABELS / "Screws/Hex Head" / size, name, make_svg(group, "Hex Head", name, name))


def main() -> int:
    command, *args = sys.argv[1:] or ["help"]
    if command == "flush":
        flush()
    elif command == "hexnut" and args:
        retext("Nuts", "Hex Nut", args)
    elif command == "washer" and args:
        retext("Washers and Shims", "Washer", args)
    elif command == "hexbolt" and len(args) > 1:
        hexbolt(args[0], args[1:])
    elif command == "tnut" and len(args) > 1 and all(k in TNUT_KINDS for k in args[1:]):
        tnut(args[0], args[1:])
    elif command == "nyloc" and args:
        nyloc(args)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
