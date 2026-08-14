"""Tests for emojifont.inject — font injection logic."""

import io
from pathlib import Path

import pytest
from PIL import Image
from fontTools.ttLib import TTFont

from emojifont.inject import (
    CODEPOINT_BLOCK_END,
    DEFAULT_START_CODEPOINT,
    cells_for_codepoint,
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
        data, w, h = resize_image_to_emoji(red_png_bytes, 100, 100, 100, 100)
        img = Image.open(io.BytesIO(data))
        assert img.size == (100, 100)
        assert img.mode == "RGBA"

    def test_tall_image_limited_by_height(self, tall_png_bytes):
        """A 32x128 image in a 188x156 box is height-bound: 39x156."""
        data, w, h = resize_image_to_emoji(tall_png_bytes, 188, 156, 192, 160)
        img = Image.open(io.BytesIO(data))
        assert img.size == (192, 160)
        assert img.getbbox()[3] - img.getbbox()[1] == 156

    def test_wide_image_limited_by_width(self, wide_png_bytes):
        """A 128x32 image in a 188x156 box is width-bound: 188x47."""
        data, w, h = resize_image_to_emoji(wide_png_bytes, 188, 156, 192, 160)
        img = Image.open(io.BytesIO(data))
        bbox = img.getbbox()
        assert bbox[2] - bbox[0] == 188
        assert bbox[3] - bbox[1] == 47

    def test_non_square_image_fills_content_box(self, tmp_path):
        """A 4:3 meme must fill the box's width, not shrink to a square.

        Fitting to an inscribed square would cap the height at 3/4 of the em,
        which is what made memes look short next to system emoji.
        """
        img = Image.new("RGBA", (347, 281), (0, 255, 0, 255))  # pepe's aspect
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data, _, _ = resize_image_to_emoji(buf.getvalue(), 188, 156, 192, 160)
        bbox = Image.open(io.BytesIO(data)).getbbox()
        height = bbox[3] - bbox[1]
        assert height >= 150  # vs 152 with contain-fit, 126 with square fit

    def test_canvas_dimensions_returned(self, red_png_bytes):
        data, w, h = resize_image_to_emoji(red_png_bytes, 92, 156, 96, 160)
        assert w == 96
        assert h == 160

    def test_y_offset_shifts_content(self, red_png_bytes):
        data_no_offset, _, _ = resize_image_to_emoji(red_png_bytes, 80, 80, 100, 100, y_offset=0)
        data_offset, _, _ = resize_image_to_emoji(red_png_bytes, 80, 80, 100, 100, y_offset=20)
        # Different images due to offset
        assert data_no_offset != data_offset

    def test_output_is_png(self, red_png_bytes):
        data, _, _ = resize_image_to_emoji(red_png_bytes, 92, 156, 96, 160)
        assert data[:4] == b"\x89PNG"

    def test_proportional_canvas(self, red_png_bytes):
        """Canvas width should be proportional to advance/units_per_em."""
        # Simulating Monaco two-cell: advance=2458, units_per_em=2048, ppem=160
        canvas_w = int(160 * 2458 / 2048)  # = 192
        data, w, h = resize_image_to_emoji(red_png_bytes, canvas_w - 4, 156, canvas_w, 160)
        img = Image.open(io.BytesIO(data))
        assert img.size == (192, 160)


# ---------------------------------------------------------------------------
# cells_for_codepoint
# ---------------------------------------------------------------------------

class TestCellsForCodepoint:
    @pytest.mark.parametrize("cp", [0xF900, 0xF901, 0xFAFF])
    def test_cjk_compatibility_ideographs_are_wide(self, cp):
        """No longer the default meme range, but the general East Asian Width
        fallback must still size arbitrary explicit mappings correctly."""
        assert cells_for_codepoint(cp) == 2

    @pytest.mark.parametrize("cp", [0x1F600, 0x1F680, 0x1F525])
    def test_emoji_are_wide(self, cp):
        """Memes must match the cell span of the emoji they sit alongside."""
        assert cells_for_codepoint(cp) == 2

    @pytest.mark.parametrize("cp", [0xE000, 0xF8FF, 0x0041])
    def test_pua_and_ascii_are_narrow(self, cp):
        assert cells_for_codepoint(cp) == 1

    def test_default_range_bounds(self):
        assert (DEFAULT_START_CODEPOINT, CODEPOINT_BLOCK_END) == (0x100000, 0x1003FF)

    @pytest.mark.parametrize("cp", [0x100000, 0x100001, 0x1003FF])
    def test_meme_range_is_wide(self, cp):
        """The default meme range (Plane 16 PUA) must be wide unconditionally
        — its Unicode East Asian Width is 'Ambiguous', not 'Wide', so this
        can't come from the unicodedata fallback; it's an explicit range
        check in cells_for_codepoint that a paired terminal patch mirrors."""
        assert cells_for_codepoint(cp) == 2

    def test_just_past_meme_range_falls_back_to_east_asian_width(self):
        """One past CODEPOINT_BLOCK_END must not still be treated as a meme
        slot — it's plain Plane 16 PUA (Ambiguous), so narrow."""
        assert cells_for_codepoint(CODEPOINT_BLOCK_END + 1) == 1

    def test_just_before_meme_range_is_narrow(self):
        assert cells_for_codepoint(DEFAULT_START_CODEPOINT - 1) == 1


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

    def test_supplementary_plane_glyph_name_uses_agl_convention(self, minimal_font, test_image_path, tmp_path):
        """Adobe Glyph List naming: BMP code points use 'uni' + exactly 4 hex
        digits; code points above the BMP (including the default meme range,
        which lives in Plane 16) use 'u' + 4-6 hex digits with no 'ni'. Glyph
        names aren't looked up by convention when this font renders — cmap
        does the real mapping — but other tools that inspect the font expect
        this, and getting it wrong here would be an easy thing to miss since
        nothing in our own pipeline depends on it being right."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {DEFAULT_START_CODEPOINT: str(test_image_path)},
        )
        font = TTFont(str(out))
        assert "u100000" in font.getGlyphOrder()
        assert "uni100000" not in font.getGlyphOrder()
        cmap = font.getBestCmap()
        assert cmap[DEFAULT_START_CODEPOINT] == "u100000"
        font.close()

    def test_supplementary_plane_injection_preserves_existing_bmp_cmap(self, minimal_font, test_image_path, tmp_path):
        """Regression test: injecting a supplementary-plane (>U+FFFF) code
        point into a font with no existing format 12 cmap subtable used to
        create a NEW, essentially empty one holding only the injected entry.
        getBestCmap() (and real text-rendering engines, which follow the same
        "prefer format 12 as the full-repertoire table" convention) then
        picked that near-empty table over the font's original, far more
        complete format 4 BMP subtable — silently breaking every other
        character in the font, e.g. a Nerd Font's icon glyphs, the moment a
        single meme got injected. The new format 12 subtable must be seeded
        with the existing BMP mappings, not just the newly injected ones."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {DEFAULT_START_CODEPOINT: str(test_image_path)},
        )
        font = TTFont(str(out))
        cmap = font.getBestCmap()
        assert cmap[0x41] == "A", "pre-existing BMP glyph 'A' must survive injection"
        assert cmap[0x20] == "space", "pre-existing BMP glyph 'space' must survive injection"
        assert cmap[DEFAULT_START_CODEPOINT] == "u100000"
        font.close()

    def test_bmp_glyph_name_still_uses_uni_convention(self, minimal_font, test_image_path, tmp_path):
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

    def test_advance_width_spans_two_cells_when_wide(self, minimal_font, test_image_path, tmp_path):
        """U+F900 is East Asian Wide, so its advance covers two monospace cells."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        mono_advance = font["hmtx"].metrics["A"][0]  # 600 in minimal font
        injected_advance = font["hmtx"].metrics["uniF900"][0]
        assert injected_advance == mono_advance * 2
        font.close()

    def test_advance_width_one_cell_when_narrow(self, minimal_font, test_image_path, tmp_path):
        """PUA code points are one cell wide, so the advance must not be doubled."""
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xE000: str(test_image_path)},
        )
        font = TTFont(str(out))
        mono_advance = font["hmtx"].metrics["A"][0]
        assert font["hmtx"].metrics["uniE000"][0] == mono_advance
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
        # minimal font: advance=600, UPM=1000; U+F900 spans two cells
        expected_w = int(160 * 1200 / 1000)  # 192
        assert img.size[0] == expected_w
        assert img.size[1] == 160
        font.close()

    def test_artwork_fills_em_square_when_wide(self, minimal_font, test_image_path, tmp_path):
        """A two-cell canvas is wider than tall, so artwork fills the full em height.

        This is what makes memes render at the same visual size as system emoji;
        a one-cell canvas would clamp them to the narrower cell width.
        """
        out = tmp_path / "out.ttf"
        inject_sbix_memes(
            str(minimal_font), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        img = Image.open(io.BytesIO(font["sbix"].strikes[160].glyphs["uniF900"].imageData))
        bbox = img.getbbox()  # non-transparent extent of the artwork
        assert bbox is not None
        assert bbox[3] - bbox[1] == 156  # ppem - margin, i.e. the full em square
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
        """Monaco cell is 1229 units; U+F900 is wide, so it spans two of them."""
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(test_image_path)},
        )
        font = TTFont(str(out))
        assert font["hmtx"].metrics["uniF900"][0] == 2458
        font.close()

    def test_canvas_width_192_at_ppem_160(self, base_font_path, test_image_path, tmp_path):
        """Monaco: 160 * 2458 / 2048 = 192 pixels wide."""
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(test_image_path)},
            ppem=160,
        )
        font = TTFont(str(out))
        glyph = font["sbix"].strikes[160].glyphs["uniF900"]
        img = Image.open(io.BytesIO(glyph.imageData))
        assert img.size == (192, 160)
        font.close()

    def test_all_strikes_fill_em_height(self, base_font_path, tmp_path):
        """Every strike must fill ~the full em, including the small ones.

        A fixed pixel margin is negligible at 160 ppem but eats 20% of a 20 ppem
        strike, so memes would shrink relative to emoji at small terminal sizes.
        Uses a 4:3 image, the case most sensitive to how the fit is computed.
        """
        meme = tmp_path / "wide_meme.png"
        Image.new("RGBA", (347, 281), (0, 255, 0, 255)).save(meme)
        out = tmp_path / "monaco_out.ttf"
        inject_sbix_memes(
            str(base_font_path), str(out),
            {0xF900: str(meme)},
            ppem=160,
        )
        font = TTFont(str(out))
        for ppem, strike in font["sbix"].strikes.items():
            if "uniF900" not in strike.glyphs:
                continue
            bbox = Image.open(io.BytesIO(strike.glyphs["uniF900"].imageData)).getbbox()
            height = bbox[3] - bbox[1]
            assert height / ppem >= 0.90, f"Strike {ppem}: artwork only {height}/{ppem} tall"
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
                expected_w = int(ppem * 2458 / 2048)
                assert img.size[0] == expected_w, f"Strike {ppem}: expected width {expected_w}, got {img.size[0]}"
                assert img.size[1] == ppem
        font.close()
