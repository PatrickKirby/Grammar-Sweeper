"""The logo as shown in the window and the report: the icon on a rounded tile with a fine light edge
and a soft shadow. Drawn once at higher resolution and shrunk, so edges stay clean. The icon file
itself is never altered."""

from __future__ import annotations

import base64
import io
from pathlib import Path

ICON = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
RADIUS = 0.23  # corner radius as a share of the tile
SHADOW = 0.12  # padding for the shadow, as a share of the tile
SUPERSAMPLE = 3


def logo_png(size: int, scale: int = 2) -> bytes:
    """The styled logo as PNG bytes. `size` is the tile in layout pixels; the image is `scale` times
    larger so it is sharp on a high-density screen. Raises if Pillow or the icon is missing."""
    from PIL import Image, ImageDraw, ImageFilter

    tile = size * scale
    pad = round(tile * SHADOW)
    work = tile * SUPERSAMPLE
    big_pad = pad * SUPERSAMPLE
    canvas = work + 2 * big_pad

    with Image.open(ICON) as source:
        art = source.convert("RGBA").resize((work, work), Image.LANCZOS)

    radius = round(work * RADIUS)
    mask = Image.new("L", (work, work), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, work - 1, work - 1), radius=radius, fill=255)

    # soft shadow: the tile's outline, nudged down, blurred, dark and faint
    shadow = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    glow = Image.new("L", (canvas, canvas), 0)
    drop = round(work * 0.035)
    ImageDraw.Draw(glow).rounded_rectangle(
        (big_pad, big_pad + drop, big_pad + work - 1, big_pad + work - 1 + drop), radius=radius, fill=110
    )
    glow = glow.filter(ImageFilter.GaussianBlur(big_pad * 0.45))
    shadow.paste((20, 24, 60, 255), (0, 0), glow)

    # the tile, with a fine light edge just inside its outline
    tile_img = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    tile_img.paste(art, (0, 0), mask)
    edge = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (0, 0, work - 1, work - 1), radius=radius, outline=(255, 255, 255, 70), width=max(2, work // 90)
    )
    tile_img = Image.alpha_composite(tile_img, edge)

    shadow.alpha_composite(tile_img, (big_pad, big_pad))
    final = shadow.resize((tile + 2 * pad, tile + 2 * pad), Image.LANCZOS)
    out = io.BytesIO()
    final.save(out, "PNG", optimize=True)
    return out.getvalue()


def logo_data_uri(size: int) -> str:
    """The styled logo inlined for the report. Empty when it cannot be drawn."""
    try:
        return "data:image/png;base64," + base64.b64encode(logo_png(size)).decode("ascii")
    except Exception:  # noqa: BLE001 - a missing logo must never stop the report
        return ""


def display_size(size: int, scale: int = 2) -> int:
    """The layout size of the whole image from logo_png, shadow included."""
    return (size * scale + 2 * round(size * scale * SHADOW)) // scale
