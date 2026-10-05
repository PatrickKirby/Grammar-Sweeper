"""A very light, fine texture for backgrounds: paper grain with a faint dot grid.

One tile, generated once from the page colour and written to a PNG (the window) or inlined (the
report). The grain is random but seeded, so the tile is the same every time, and it repeats
without a seam because the dot grid divides the tile evenly."""

from __future__ import annotations

import random

TILE = 96
GRID = 24  # a dot every this many pixels; must divide TILE
GRAIN = 3  # most a pixel strays from the page colour, out of 255


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)


def tile(background: str, accent: str, seed: int = 7):
    """The tile as a Pillow image."""
    from PIL import Image

    base, dot = _rgb(background), _rgb(accent)
    rng = random.Random(seed)
    pixels = []
    for y in range(TILE):
        for x in range(TILE):
            shift = rng.randint(-GRAIN, GRAIN)
            r, g, b = (max(0, min(255, channel + shift)) for channel in base)
            if x % GRID == 0 and y % GRID == 0:  # the dot grid: the accent, mixed in at a tenth
                r, g, b = (round(channel * 0.9 + target * 0.1) for channel, target in zip((r, g, b), dot))
            pixels.append((r, g, b))
    image = Image.new("RGB", (TILE, TILE))
    image.putdata(pixels)
    return image


def tile_png(background: str, accent: str) -> bytes:
    import io

    buffer = io.BytesIO()
    tile(background, accent).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()
