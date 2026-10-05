"""Draws the installer artwork from the app's own palette, logo and texture, so the setup looks like the program.

Run from the project root: python installer/make_images.py. Writes installer/art/. The PNGs are committed, so
building the installer needs only Inno Setup, not Pillow."""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from sweeper import brand, texture  # noqa: E402
from sweeper.gui.style import LIGHT  # noqa: E402

ART = ROOT / "installer" / "art"
FONTS = Path("C:/Windows/Fonts")
LARGE = (164, 314)  # layout pixels of the wizard's side panel
SMALL = 55  # layout pixels of the header badge


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def side_panel(scale: int) -> Image.Image:
    width, height = LARGE[0] * scale, LARGE[1] * scale
    tile = Image.open(io.BytesIO(texture.tile_png(LIGHT["bg"], LIGHT["accent"]))).convert("RGB")
    panel = Image.new("RGB", (width, height))
    for x in range(0, width, tile.width):
        for y in range(0, height, tile.height):
            panel.paste(tile, (x, y))
    draw = ImageDraw.Draw(panel)
    draw.rectangle([0, 0, width, 4 * scale], fill=LIGHT["accent"])  # the accent edge the app uses
    logo = Image.open(io.BytesIO(brand.logo_png(96, scale))).convert("RGBA")
    panel.paste(logo, ((width - logo.width) // 2, 40 * scale), logo)
    for text, face, size, colour, top in (
        ("Grammar", "segoeuib.ttf", 21, LIGHT["text"], 168),
        ("Sweeper", "segoeuib.ttf", 21, LIGHT["text"], 194),
        ("Accept Grammarly", "segoeui.ttf", 11, LIGHT["muted"], 244),
        ("suggestions hands free.", "segoeui.ttf", 11, LIGHT["muted"], 260),
    ):
        face_ = font(face, size * scale)
        draw.text(((width - draw.textlength(text, font=face_)) / 2, top * scale), text, font=face_, fill=colour)
    return panel


def badge(scale: int) -> Image.Image:
    """The header logo, transparent so it sits on the light page."""
    size = SMALL * scale
    logo = Image.open(io.BytesIO(brand.logo_png(SMALL - 8, scale))).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    return canvas


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    for scale, suffix in ((1, ""), (2, "@2x")):
        side_panel(scale).save(ART / f"wizard-large{suffix}.png")
        badge(scale).save(ART / f"wizard-small{suffix}.png")
    print("wrote", ", ".join(sorted(p.name for p in ART.glob("*.png"))))


if __name__ == "__main__":
    main()
