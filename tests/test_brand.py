"""The styled logo: a rounded tile with a shadow, drawn sharp, never altering the icon file."""

import hashlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from sweeper import brand  # noqa: E402
from sweeper.changes import REPORT_LOGO, build_report  # noqa: E402


def drawn(size=60, scale=2):
    return Image.open(io.BytesIO(brand.logo_png(size, scale)))


def test_the_image_is_the_tile_plus_its_shadow_at_double_resolution():
    image = drawn(60, 2)
    assert image.size == (brand.display_size(60) * 2, brand.display_size(60) * 2)
    assert image.mode == "RGBA"


def test_the_corners_are_transparent_and_the_middle_is_solid():
    image = drawn()
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((image.width // 2, image.height // 2))[3] == 255


def test_the_tile_itself_has_rounded_corners():
    image = drawn()
    pad = (image.width - 60 * 2) // 2
    corner = image.getpixel((pad + 2, pad + 2))  # inside the tile's square corner
    assert corner[3] < 255  # cut away by the rounding, not a hard square edge


def test_the_shadow_falls_below_more_than_above():
    image = drawn()
    x = image.width // 2
    above = image.getpixel((x, 1))[3]
    below = image.getpixel((x, image.height - 2))[3]
    assert below >= above


def test_the_icon_file_is_never_altered():
    before = hashlib.sha256(brand.ICON.read_bytes()).hexdigest()
    brand.logo_png(44)
    assert hashlib.sha256(brand.ICON.read_bytes()).hexdigest() == before


def test_the_report_inlines_the_styled_logo_at_the_display_size(tmp_path):
    html = build_report(tmp_path / "r.html", {"Applied": 1}, [{"category": "Correctness", "original": "a", "revised": "b", "page": 1}]).read_text(encoding="utf-8")
    shown = brand.display_size(REPORT_LOGO)
    assert f"width:{shown}px;height:{shown}px" in html and html.count("data:image/png;base64,") >= 2


def test_a_missing_icon_gives_no_logo_and_no_crash(monkeypatch):
    monkeypatch.setattr(brand, "ICON", Path("does-not-exist.png"))
    assert brand.logo_data_uri(60) == ""
