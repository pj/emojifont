import io
from pathlib import Path

import pytest
from PIL import Image
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph
from fontTools.fontBuilder import FontBuilder


FONT_BUILD_DIR = Path(__file__).parents[1] / "font_build"
BASE_FONT = FONT_BUILD_DIR / "MonacoNerdFontMono-Regular.ttf"


@pytest.fixture
def red_png_bytes():
    """A 64x64 red square PNG in bytes."""
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def tall_png_bytes():
    """A 32x128 tall green rectangle PNG."""
    img = Image.new("RGBA", (32, 128), (0, 255, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def wide_png_bytes():
    """A 128x32 wide blue rectangle PNG."""
    img = Image.new("RGBA", (128, 32), (0, 0, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def test_image_path(tmp_path, red_png_bytes):
    """Write a red square PNG to a temp file and return its path."""
    p = tmp_path / "test_meme.png"
    p.write_bytes(red_png_bytes)
    return p


@pytest.fixture
def second_image_path(tmp_path, tall_png_bytes):
    """Write a tall green PNG to a temp file and return its path."""
    p = tmp_path / "test_meme2.png"
    p.write_bytes(tall_png_bytes)
    return p


@pytest.fixture
def base_font_path():
    """Path to the real Monaco Nerd Font used for integration tests."""
    if not BASE_FONT.exists():
        pytest.skip(f"Base font not found: {BASE_FONT}")
    return BASE_FONT


@pytest.fixture
def minimal_font(tmp_path):
    """Create a minimal TrueType font with glyf table for unit tests."""
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space", "A"])
    fb.setupCharacterMap({0x20: "space", 0x41: "A"})

    empty = TTGlyph()
    empty.numberOfContours = 0
    fb.setupGlyf({
        ".notdef": empty,
        "space": TTGlyph(),
        "A": TTGlyph(),
    })

    fb.setupHorizontalMetrics({
        ".notdef": (600, 0),
        "space": (600, 0),
        "A": (600, 33),
    })

    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "TestFont",
        "styleName": "Regular",
    })
    fb.font["name"].setName("TestFont Regular", 4, 3, 1, 0x0409)
    fb.font["name"].setName("TestFont-Regular", 6, 3, 1, 0x0409)
    fb.setupOS2(sCapHeight=700, sxHeight=500)
    fb.setupPost()
    fb.setupHead(unitsPerEm=1000)

    out = tmp_path / "minimal.ttf"
    fb.font.save(str(out))
    return out
