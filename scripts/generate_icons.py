#!/usr/bin/env python3
"""Generate the home-screen icon PNGs in icons/.

Draws a simple gold "C" ring on the masthead's dark ink background,
using only the standard library (zlib for PNG compression, no image
library needed). Static output committed to the repo; re-run this
after changing the mark, don't wire it into the daily workflow.
"""

import math
import struct
import zlib
from pathlib import Path

ICONS_DIR = Path(__file__).parent.parent / "icons"

INK = (0x1A, 0x22, 0x33, 255)   # --ink / masthead background
GOLD = (0xB8, 0x86, 0x3C, 255)  # --gold accent

SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
}


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_png(path, size, pixel_at):
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # no per-scanline filter
        for x in range(size):
            raw += bytes(pixel_at(x, y))
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)


def make_c_mark(size):
    cx = cy = size / 2
    outer, inner = size * 0.40, size * 0.24
    gap_start, gap_end = -35, 35  # degrees; opening of the "C" faces right

    def pixel_at(x, y):
        dx, dy = x + 0.5 - cx, y + 0.5 - cy
        r = math.hypot(dx, dy)
        if inner <= r <= outer and not (gap_start <= math.degrees(math.atan2(dy, dx)) <= gap_end):
            return GOLD
        return INK

    return pixel_at


def main():
    ICONS_DIR.mkdir(exist_ok=True)
    for filename, size in SIZES.items():
        write_png(ICONS_DIR / filename, size, make_c_mark(size))
        print(ICONS_DIR / filename)


if __name__ == "__main__":
    main()
