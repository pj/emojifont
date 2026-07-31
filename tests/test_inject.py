"""Tests for emojifont.inject — font injection logic."""

import io
from pathlib import Path

import pytest
from PIL import Image
from fontTools.ttLib import TTFont

from emojifont.inject import (
    ensure_glyph_exists,
    inject_sbix_memes,
    parse_mappings,
    rename_font,
    resize_image_to_emoji,
)


# ---------------------------------------------------------------------------
# parse_mappings
# ---------------------------------------------------------------------------

class TestParseMappings:
    def test_single_mapping(self):
        result = parse_mappings("U+F900:pepe.png")
        assert result == {0xF900: "pepe.png"}

    def test_multiple_mappings(self):
        result = parse_mappings("U+F900:pepe.png,U+F901:drake.jpg")
        assert result == {0xF900: "pepe.png", 0xF901: "drake.jpg"}

    def test_whitespace_tolerance(self):
        result = parse_mappings("  U+F900 : pepe.png , U+F901 : drake.jpg  ")
        assert result == {0xF900: "pepe.png", 0xF901: "drake.jpg"}

    def test_empty_string(self):
        assert parse_mappings("") == {}

    def test_none(self):
        assert parse_mappings(None) == {}

    def test_invalid_no_colon(self):
        with pytest.raises(ValueError, match="Invalid mapping format"):
            parse_mappings("U+F900pepe.png")

    def test_invalid_no_prefix(self):
        with pytest.raises(ValueError, match="Invalid Unicode format"):
            parse_mappings("F900:pepe.png")

    def test_path_with_directories(self):
        result = parse_mappings("U+F900:/some/path/to/image.png")
        assert result == {0xF900: "/some/path/to/image.png"}


# ---------------------------------------------------------------------------
# resize_image_to_emoji
# ---------------------------------------------------------------------------

class TestResizeImageToEmoji:
    def test_square_image_on_square_canvas(self, red_png_bytes):
        data, w, h = resize_image_to_emoji(red_png_bytes, 100, 100, 100)
        img = Image.open(io.BytesIO(data))
        assert img.size == (100, 100)
        assert img.mode == "RGBA"

    def test_tall_image_fits_content_size(self, tall_png_bytes):
        data, w, h = resize_image_to_emoji(tall_png_bytes, 80, 96, 160)
        img = Image.open(io.BytesIO(data))
        assert img.size == (96, 160)
        # The tall image (32x128) scaled to content_size=80 means height=80, width=20
        # It should be centered on the 96x160 canvas

    def test_wide_image_fits_content_size(self, wide_png_bytes):
        data, w, h = resize_image_to_emoji(wide_png_bytes, 80, 96, 160)
        img = Image.open(io.BytesIO(data))
        assert img.size == (96, 160)

    def test_canvas_dimensions_returned(self, red_png_bytes):
        data, w, h = resize_image_to_emoji(red_png_bytes, 80, 96, 160)
        assert w == 96
        assert h == 160

    def test_y_offset_shifts_content(self, red_png_bytes):
        data_no_offset, _, _ = resize_image_to_emoji(red_png_bytes, 80, 100, 100, y_offset=0)
        data_offset, _, _ = resize_image_to_emoji(red_png_bytes, 80, 100, 100, y_offset=20)
        # Different images due to offset
        assert data_no_offset != data_offset

    def test_output_is_png(self, red_png_bytes):
        data, _, _ = resize_image_to_emoji(red_png_bytes, 80, 96, 160)
        assert data[:4] == b"\x89PNG"

    def test_proportional_canvas(self, red_png_bytes):
        """Canvas width should be proportional to mono_advance/units_per_em."""
        # Simulating Monaco: mono_advance=1229, units_per_em=2048, ppem=160
        canvas_w = int(160 * 1229 / 2048)  # = 96
        data, w, h = resize_image_to_emoji(red_png_bytes, 92, canvas_w, 160)
        img = Image.open(io.BytesIO(data))
        assert img.size == (96, 160)


# ---------------------------------------------------------------------------
# ensure_glyph_exists
# ---------------------------------------------------------------------------

class TestEnsureGlyphExists:
    def test_creates_new_glyph(self, minimal_font):
        font = TTFont(str(minimal_font))
        ensure_glyph_exists(font, "uniF900", 600, 1000)
        assert "uniF900" in font.getGlyphOrder()
        assert "uniF900" in font["glyf"]
        assert font["hmtx"].metrics["uniF900"] == (600, 0)
        font.close()

    def test_existing_glyph_not_replaced(self, minimal_font):
        font = TTFont(str(minimal_font))
        original_order = list(font.getGlyphOrder())
        ensure_glyph_exists(font, "A", 600, 1000)
        assert font.getGlyphOrder() == original_order
        font.close()

    def test_placeholder_has_two_contours(self, minimal_font):
        font = TTFont(str(minimal_font))
        ensure_glyph_exists(font, "uniF900", 600, 1000)
        glyph = font["glyf"]["uniF900"]
        assert glyph.numberOfContours == 2
        assert glyph.endPtsOfContours == [3, 7]
        font.close()

    def test_placeholder_bbox(self, minimal_font):
        font = TTFont(str(minimal_font))
        ensure_glyph_exists(font, "uniF900", 600, 1000)
        glyph = font["glyf"]["uniF900"]
        coords = list(glyph.coordinates)
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        assert min(xs) == 0
        assert max(xs) == 600   # advance_width
        assert min(ys) == 0
        assert max(ys) == 1000  # units_per_em
        font.close()

    def test_raises_for_cff_font(self, tmp_path):
        """Should raise if font has no glyf table."""
        font = TTFont()
        font.setGlyphOrder([".notdef"])
        # No glyf table — simulate CFF
        with pytest.raises(ValueError, match="no 'glyf' table"):
            ensure_glyph_exists(font, "uniF900", 600, 1000)
        font.close()


# ---------------------------------------------------------------------------
# rename_font
# ---------------------------------------------------------------------------

class TestRenameFont:
    def test_renames_family(self, minimal_font):
        font = TTFont(str(minimal_font))
        rename_font(font, "MemeFont")
        name_table = font["name"]
        family = name_table.getName(1, 3, 1, 0x0409).toUnicode()
        assert family == "MemeFont"
        font.close()

    def test_full_name_includes_subfamily(self, minimal_font):
        font = TTFont(str(minimal_font))
        rename_font(font, "MemeFont")
        full = font["name"].getName(4, 3, 1, 0x0409).toUnicode()
        assert full == "MemeFont Regular"
        font.close()

    def test_postscript_name_no_spaces(self, minimal_font):
        font = TTFont(str(minimal_font))
        rename_font(font, "Meme Font")
        ps = font["name"].getName(6, 3, 1, 0x0409).toUnicode()
        assert " " not in ps
        assert ps == "MemeFont"
        font.close()


# ---------------------------------------------------------------------------
# inject_sbix_memes (integration)
# ---------------------------------------------------------------------------

class TestInjectSbixMemes:
    def test_creates_sbix_table(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        assert "sbix" in font
        font.close()

    def test_glyph_added_to_glyph_order(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        assert "uniF900" in font.getGlyphOrder()
        font.close()

    def test_cmap_entry_created(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        cmap = font.getBestCmap()
        assert cmap[0xF900] == "uniF900"
        font.close()

    def test_advance_width_matches_monospace(self, minimal_font, test_image_path, tmp_path):
        """Advance width of injected glyph must match existing monospace width."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        mono_advance = font["hmtx"].metrics["A"][0]  # 600 in minimal font
        injected_advance = font["hmtx"].metrics["uniF900"][0]
        assert injected_advance == mono_advance
        font.close()

    def test_multiple_strikes_created(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        strikes = font["sbix"].strikes
        assert 160 in strikes
        assert len(strikes) > 1  # should have scaled strikes too
        font.close()

    def test_strike_has_glyph_data(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        glyph = font["sbix"].strikes[160].glyphs["uniF900"]
        assert glyph.graphicType == "png "
        assert len(glyph.imageData) > 0
        assert glyph.imageData[:4] == b"\x89PNG"
        font.close()

    def test_canvas_proportional_to_advance(self, minimal_font, test_image_path, tmp_path):
        """SBIX image dimensions should match cell proportions, not be square."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        glyph = font["sbix"].strikes[160].glyphs["uniF900"]
        img = Image.open(io.BytesIO(glyph.imageData))
        # minimal font: advance=600, UPM=1000
        expected_w = int(160 * 600 / 1000)  # 96
        assert img.size[0] == expected_w
        assert img.size[1] == 160
        font.close()

    def test_multiple_mappings(self, minimal_font, test_image_path, second_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path), 0xF901: str(second_image_path)},
        )
        font = TTFont(str(out))
        assert "uniF900" in font["sbix"].strikes[160].glyphs
        assert "uniF901" in font["sbix"].strikes[160].glyphs
        cmap = font.getBestCmap()
        assert cmap[0xF900] == "uniF900"
        assert cmap[0xF901] == "uniF901"
        font.close()

    def test_font_rename_applied(self, minimal_font, test_image_path, tmp_path):
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            font_name="MemeFont",
        )
        font = TTFont(str(out))
        family = font["name"].getName(1, 3, 1, 0x0409).toUnicode()
        assert family == "MemeFont"
        font.close()

    def test_head_flags_bit1_set(self, minimal_font, test_image_path, tmp_path):
        """Bit 1 of head.flags must be set for SBIX fonts."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        assert font["head"].flags & (1 << 1) != 0
        font.close()

    def test_input_output_same_path_raises(self, minimal_font, test_image_path):
        with pytest.raises(ValueError, match="Input and output must be different"):
            inject_sbix_memes(
                str(minimal_font), str(minimal_font),
                {0xF900: str(test_image_path)},
            )

    def test_origin_offset_y_negative(self, minimal_font, test_image_path, tmp_path):
        """originOffsetY should be negative (shifts bitmap down for descent centering)."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        glyph = font["sbix"].strikes[160].glyphs["uniF900"]
        assert glyph.originOffsetY <= 0
        font.close()


# ---------------------------------------------------------------------------
# Integration test with real Monaco font
# ---------------------------------------------------------------------------

class TestWithMonacoFont:
    def test_advance_width_matches_monaco(self, base_font_path, test_image_path, tmp_path):
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        assert font["hmtx"].metrics["uniF900"][0] == 1229
        font.close()

    def test_canvas_width_96_at_ppem_160(self, base_font_path, test_image_path, tmp_path):
        """Monaco: 160 * 1229 / 2048 = 96 pixels wide."""
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        glyph = font["sbix"].strikes[160].glyphs["uniF900"]
        img = Image.open(io.BytesIO(glyph.imageData))
        assert img.size == (96, 160)
        font.close()

    def test_scaled_strikes_proportional(self, base_font_path, test_image_path, tmp_path):
        """All strikes should have proportional canvas width."""
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        for ppem, strike in font["sbix"].strikes.items():
            if "uniF900" in strike.glyphs:
                img = Image.open(io.BytesIO(strike.glyphs["uniF900"].imageData))
                expected_w = int(ppem * 1229 / 2048)
                assert img.size[0] == expected_w, f"Strike {ppem}: expected width {expected_w}, got {img.size[0]}"
                assert img.size[1] == ppem
        font.close()
