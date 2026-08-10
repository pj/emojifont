"""
Inject meme images into a font using SBIX (Standard Bitmap Image Extension) format.
This script uses fonttools to create macOS-compatible fonts.
"""

import sys
import io
import unicodedata
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._s_b_i_x import table__s_b_i_x
from fontTools.ttLib.tables.sbixStrike import Strike, Glyph as SbixGlyph
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph, GlyphCoordinates
from fontTools.ttLib.tables import ttProgram
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from PIL import Image

def rename_font(font, new_family_name):
    """
    Rename the font family in the name table.
    
    Args:
        font: TTFont object
        new_family_name: New font family name (e.g., "Meme font")
    """
    if 'name' not in font:
        print("Warning: Font has no name table")
        return
    
    name_table = font['name']
    
    # Get the original subfamily (style) name from ID 2 (e.g., "Regular", "Bold")
    subfamily = "Regular"
    for record in name_table.names:
        if record.nameID == 2:
            subfamily = record.toUnicode()
            break
    
    # PostScript name cannot have spaces
    postscript_name = new_family_name.replace(' ', '')
    if subfamily and subfamily != "Regular":
        postscript_name += "-" + subfamily.replace(' ', '')
    
    # Full name includes subfamily
    full_name = f"{new_family_name} {subfamily}" if subfamily else new_family_name
    
    # Update name records
    # We need to update multiple name IDs for different platforms and encodings
    for record in name_table.names:
        if record.nameID == 1:  # Font Family name
            record.string = new_family_name
        elif record.nameID == 4:  # Full font name
            record.string = full_name
        elif record.nameID == 6:  # PostScript name
            record.string = postscript_name
        elif record.nameID == 16:  # Typographic Family name (if present)
            record.string = new_family_name
    
    print(f"  Family name: {new_family_name}")
    print(f"  Full name: {full_name}")
    print(f"  PostScript name: {postscript_name}")

def resize_image_to_emoji(image_data, content_width, content_height, canvas_width, canvas_height, y_offset=0):
    """
    Resize a meme image and place it on a transparent canvas.

    The artwork is scaled to fit inside content_width x content_height while
    preserving its aspect ratio. Fitting to the actual content box rather than
    to a square inscribed in it matters for non-square memes: a 4:3 image fitted
    to a square would only reach 3/4 of the em height and read as noticeably
    smaller than the system emoji beside it.

    Args:
        image_data: Raw image bytes
        content_width: Max width for the meme artwork in pixels
        content_height: Max height for the meme artwork in pixels
        canvas_width: Canvas width in pixels (e.g. 2 cells for wide glyphs)
        canvas_height: Canvas height in pixels (= ppem, fills the em square)
        y_offset: Pixels to shift the image down within the canvas (positive = down).

    Returns:
        Tuple of (PNG bytes, canvas_width, canvas_height)
    """
    img = Image.open(io.BytesIO(image_data))

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    width, height = img.size
    scale = min(content_width / width, content_height / height)
    new_width = max(1, round(width * scale))
    new_height = max(1, round(height * scale))

    img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Place on transparent canvas, centered horizontally and vertically
    canvas = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
    paste_x = (canvas_width - new_width) // 2
    paste_y = (canvas_height - new_height) // 2 + y_offset
    canvas.paste(img_resized, (paste_x, paste_y), img_resized)

    # Save to PNG format
    output = io.BytesIO()
    canvas.save(output, format='PNG')
    return output.getvalue(), canvas_width, canvas_height


# Meme glyphs live in the Supplementary Private Use Area, Plane 16
# (U+100000-U+10FFFD) — code points the Unicode Standard guarantees will never
# receive real character assignments, unlike the CJK Compatibility Ideographs
# block this project used previously (real characters used for legacy CJK
# round-trip encoding; using them for memes meant any font/terminal that ever
# encountered genuine CJK compatibility text would silently show a meme
# instead). Plane 16 also avoids the Nerd Font icon sets that densely
# populate the BMP Private Use Area (U+E000-U+F8FF) in typical monospace
# fonts, and requires full 4-byte UTF-8 encoding, so almost nothing else on
# a real system ever touches it.
#
# The tradeoff: Plane 16 PUA's default Unicode East Asian Width is
# "Ambiguous", not "Wide" — unlike the old CJK block, terminals won't render
# it at 2 cells for free. See iTermIsDoubleWidthCharacter() in the
# MemeTerminal fork's iTermCharacterWidth.c for the paired terminal-side
# patch that makes this range unconditionally double-width.
DEFAULT_START_CODEPOINT = 0x100000
CODEPOINT_BLOCK_SIZE = 1024
CODEPOINT_BLOCK_END = DEFAULT_START_CODEPOINT + CODEPOINT_BLOCK_SIZE - 1  # 0x1003FF


def cells_for_codepoint(unicode_point):
    """
    Number of terminal cells a code point occupies.

    Meme glyphs (the DEFAULT_START_CODEPOINT..CODEPOINT_BLOCK_END range) always
    get two cells — that's the whole point of injecting them — via an explicit
    range check rather than Unicode East Asian Width, since Private Use Area
    code points report "Ambiguous" width regardless of what a font puts there.

    Everything else falls back to standard Unicode East Asian Width: Wide (W)
    and Fullwidth (F) code points (CJK ideographs, standard emoji, etc.) get
    two cells; everything else gets one. This path matters if a mapping is
    given a code point outside the default meme range (e.g. via --mappings
    with an explicit U+XXXX), so it still sizes sensibly.

    Matching cell count to what the terminal will actually allocate is what
    lets a two-cell glyph fill the full em square the way system emoji do,
    instead of being squeezed into a single narrow cell.
    """
    if DEFAULT_START_CODEPOINT <= unicode_point <= CODEPOINT_BLOCK_END:
        return 2
    return 2 if unicodedata.east_asian_width(chr(unicode_point)) in ('W', 'F') else 1


# cmap format 4 (and formats 0/2/6) store character codes as 16-bit values —
# they physically cannot represent code points above U+FFFF. fontTools raises
# an OverflowError at save() time if you try to put one in, which is a
# confusing place to discover the problem. Format 12 stores 32-bit codes and
# is the one that can hold our default Plane 16 meme range.
BMP_ONLY_CMAP_FORMATS = (0, 2, 4, 6)


def ensure_supplementary_cmap_subtable(font):
    """
    Find (or create) a cmap subtable that can hold code points above U+FFFF.

    Most real fonts already have one — Apple platforms and Windows both
    expect a format 12 subtable for any font claiming supplementary-plane
    coverage. A minimal/synthetic font may not, in which case one is added:
    platform 3 (Windows), encoding 10 (Unicode UCS-4), the conventional pair
    for format 12, matching what real fonts of this kind use.
    """
    if 'cmap' not in font:
        raise ValueError("Font has no 'cmap' table")
    for subtable in font['cmap'].tables:
        if subtable.format not in BMP_ONLY_CMAP_FORMATS and subtable.isUnicode():
            return subtable
    subtable = CmapSubtable.getSubtableClass(12)(12)
    subtable.platformID = 3
    subtable.platEncID = 10
    subtable.language = 0
    subtable.cmap = {}
    font['cmap'].tables.append(subtable)
    return subtable


def ensure_glyph_exists(font, glyph_name, advance_width, units_per_em):
    """
    Ensure a glyph exists in the font (for TrueType with glyf). Creates a
    degenerate placeholder outline matching Apple Color Emoji's pattern:
    bbox from (0, 0) to (advance_width, units_per_em) — baseline to ascent.
    """
    glyph_order = list(font.getGlyphOrder())
    if glyph_name in glyph_order:
        return
    if 'glyf' not in font:
        raise ValueError("Font has no 'glyf' table (TrueType outlines); adding new glyphs not supported for CFF fonts")
    glyph_order.append(glyph_name)
    font.setGlyphOrder(glyph_order)
    # Two identical rectangles with opposite winding directions. Under
    # TrueType's non-zero winding rule they cancel out, rendering nothing
    # visible, but the glyph has a valid bounding box so renderers that
    # don't support SBIX (e.g. iTerm2) still recognise it as a real glyph
    # and allocate the correct advance width.
    placeholder = TTGlyph()
    placeholder.numberOfContours = 2
    # Contour 1: clockwise
    # Contour 2: counter-clockwise (same rectangle, reversed)
    placeholder.coordinates = GlyphCoordinates([
        (0, 0), (advance_width, 0), (advance_width, units_per_em), (0, units_per_em),
        (0, 0), (0, units_per_em), (advance_width, units_per_em), (advance_width, 0),
    ])
    placeholder.flags = bytes([1, 1, 1, 1, 1, 1, 1, 1])  # all on-curve
    placeholder.endPtsOfContours = [3, 7]
    empty_program = ttProgram.Program()
    empty_program.fromBytecode(b'')
    placeholder.program = empty_program
    font['glyf'][glyph_name] = placeholder
    if 'hmtx' in font:
        font['hmtx'].metrics[glyph_name] = (advance_width, 0)


def inject_sbix_memes(font_path, output_path, mappings, ppem=160, ppi=72, resize=True, font_name=None):
    """
    Inject meme images into a font using SBIX format.
    
    Args:
        font_path: Path to input font file
        output_path: Path to output font file
        mappings: Dict mapping Unicode code points (int) to meme file paths (str)
        ppem: Pixels per EM for the SBIX strike (default: 160, typical for emoji)
        ppi: Pixels per inch resolution (default: 72)
        resize: Whether to resize images to fit emoji dimensions (default: True)
        font_name: New font family name (optional, e.g., "Meme font")
    """
    # Load the font (must be the source font, not the output, or we keep rewriting the same file)
    font_path_resolved = Path(font_path).resolve()
    output_path_resolved = Path(output_path).resolve()
    if font_path_resolved == output_path_resolved:
        raise ValueError(
            f"Input and output must be different files. Both are: {font_path_resolved}\n"
            "Use the original font (e.g. Monaco Nerd Font) as first argument and MemeFont.ttf as second."
        )
    print(f"Loading font: {font_path}")
    font = TTFont(font_path)
    
    # Rename font if requested
    if font_name:
        print(f"Renaming font to: {font_name}")
        rename_font(font, font_name)
    
    # Get the cmap to map Unicode to glyph IDs
    cmap = font.getBestCmap()
    if not cmap:
        raise ValueError("Font has no Unicode cmap")
    
    # Get font metrics for proper sizing
    units_per_em = font['head'].unitsPerEm
    if 'hhea' in font:
        ascent = font['hhea'].ascent
        descent = abs(font['hhea'].descent)  # Make positive
    else:
        ascent = int(units_per_em * 0.8)
        descent = int(units_per_em * 0.2)
    
    cap_height = 0
    if 'OS/2' in font and hasattr(font['OS/2'], 'sCapHeight'):
        cap_height = font['OS/2'].sCapHeight
    else:
        cap_height = int(units_per_em * 0.7)  # Estimate

    # Determine the monospace advance width from an existing glyph.
    # SBIX glyphs should match this so they align within terminal cells.
    mono_advance = units_per_em
    if 'hmtx' in font:
        for probe in ['A', 'M', 'space']:
            if probe in font['hmtx'].metrics:
                mono_advance = font['hmtx'].metrics[probe][0]
                break

    # System emoji fills ~100% of font size, centered between ascender and
    # descender, extending below baseline. We match this by:
    # 1. Filling the ppem×ppem canvas (= em square) with artwork centered in it
    # 2. Using originOffsetY to shift the bitmap down so its center aligns with
    #    the ascender/descender midpoint rather than the em-square midpoint
    scale = ppem / units_per_em

    def strike_margin(strike_ppem):
        # Inset the artwork slightly so antialiasing at the edges doesn't bleed
        # into the neighbouring cell. Proportional rather than fixed: a flat 4px
        # is negligible at 160 ppem but eats 20% of a 20 ppem strike, which would
        # make memes shrink relative to emoji at small terminal sizes.
        return max(1, round(strike_ppem * 0.025))

    # Create or get SBIX table
    if 'sbix' not in font:
        print("Creating new SBIX table")
        sbix_table = table__s_b_i_x('sbix')
        sbix_table.version = 1
        sbix_table.flags = 1  # Bit 0 always set
        sbix_table.strikes = {}
        font['sbix'] = sbix_table
    
    # Create multiple strikes for different sizes (improves compatibility).
    # Small sizes (20-48) cover typical terminal fonts on 1x and 2x displays;
    # larger sizes (64-160) cover UI rendering and high-DPI displays.
    strike_sizes = [ppem]
    for size in [20, 24, 28, 32, 48, 64, 96, 128, 160]:
        if size not in strike_sizes and size != ppem:
            strike_sizes.append(size)
    
    strikes = {}
    for strike_ppem in strike_sizes:
        if strike_ppem not in font['sbix'].strikes:
            print(f"Creating strike: {strike_ppem} ppem, {ppi} ppi")
            strike = Strike()
            strike.ppem = strike_ppem
            strike.resolution = ppi
            strike.glyphs = {}
            font['sbix'].strikes[strike_ppem] = strike
            strikes[strike_ppem] = strike
        else:
            strikes[strike_ppem] = font['sbix'].strikes[strike_ppem]
    
    # Use the requested ppem as the main strike
    strike = strikes[ppem]
    
    # Add meme bitmaps: create a new glyph per code point so we don't replace shared glyphs (e.g. Nerd Font icons at E000)
    for unicode_point, meme_path in mappings.items():
        try:
            # Use a dedicated glyph for this code point so only that exact code
            # point shows our bitmap. Adobe Glyph List naming convention: BMP
            # code points (<=U+FFFF) use "uni" + exactly 4 hex digits (e.g.
            # uniF900); code points above the BMP — including our default
            # Plane 16 meme range — use "u" + 4-6 hex digits with no "ni"
            # (e.g. u100000). Glyph names are internal to this font and never
            # looked up by convention when rendering, but other tools that
            # inspect the font do expect this convention.
            if unicode_point <= 0xFFFF:
                glyph_name = f"uni{unicode_point:04X}"
            else:
                glyph_name = f"u{unicode_point:04X}"

            # Terminals lay out wide code points across two cells, so the glyph's
            # advance must span both. Otherwise the bitmap is confined to half the
            # space the terminal reserved and renders smaller than system emoji.
            cells = cells_for_codepoint(unicode_point)
            advance = mono_advance * cells

            ensure_glyph_exists(font, glyph_name, advance, units_per_em)
            glyph_order = font.getGlyphOrder()
            glyph_id = glyph_order.index(glyph_name) if glyph_name in glyph_order else -1

            # Read the meme image
            meme_data = Path(meme_path).read_bytes()

            # Resize meme and center it on a canvas matching the cell proportions.
            # Canvas height = ppem (full em square), canvas width scaled to match
            # the advance width so the image fills the terminal cells it occupies.
            graphic_type = None
            canvas_w = int(ppem * advance / units_per_em)
            img_width = canvas_w
            img_height = ppem

            if resize:
                try:
                    margin = strike_margin(ppem)
                    meme_data, img_width, img_height = resize_image_to_emoji(
                        meme_data,
                        content_width=canvas_w - margin,
                        content_height=ppem - margin,
                        canvas_width=canvas_w, canvas_height=ppem,
                        y_offset=0
                    )
                    graphic_type = 'png '
                except Exception as e:
                    print(f"Warning: Failed to resize {meme_path}: {e}, using original")

            # Determine graphic type from image format (if not already set from resize)
            if graphic_type is None:
                if meme_data[:4] == b'\x89PNG':
                    graphic_type = 'png '
                elif meme_data[:2] == b'\xff\xd8':
                    graphic_type = 'jpg '
                else:
                    print(f"Warning: Unknown image format for {meme_path}, skipping")
                    continue

                # Get actual image dimensions if not resized
                try:
                    img = Image.open(io.BytesIO(meme_data))
                    img_width, img_height = img.size
                except:
                    pass

            # Bitmap is centered in the em square canvas. Shift it down via
            # originOffsetY so the visual center aligns between ascender and
            # descender (like system emoji). The em-square center sits at
            # UPM/2 above baseline; the ascender/descender midpoint sits at
            # (ascent - descent)/2 above baseline. The difference (in pixels):
            originOffsetX = 0
            descent_shift = int(descent * ppem / (2 * units_per_em))
            originOffsetY = -descent_shift
            
            print(f"  U+{unicode_point:04X} ({chr(unicode_point)}) -> glyph '{glyph_name}' (ID: {glyph_id}) <- {Path(meme_path).name}")
            print(f"    Size: {img_width}x{img_height}, Cells: {cells}, Offsets: ({originOffsetX}, {originOffsetY})")
            
            # Create glyph bitmap data
            glyph_bitmap = SbixGlyph(
                glyphName=glyph_name,
                referenceGlyphName=None,
                originOffsetX=originOffsetX,
                originOffsetY=originOffsetY,
                graphicType=graphic_type,
                imageData=meme_data,
                rawdata=None
            )
            
            # Add to main strike
            strike.glyphs[glyph_name] = glyph_bitmap
            
            # Set advance width to span the terminal cells this code point
            # occupies, so the glyph aligns with the cell grid.
            if 'hmtx' in font:
                font['hmtx'].metrics[glyph_name] = (advance, 0)
            
            # Ensure this code point maps to our glyph in every Unicode cmap subtable
            # that can represent it (so the requested code point always shows our
            # bitmap regardless of which subtable the OS consults). Code points
            # above the BMP — including the default meme range — can only go in
            # subtables that support 32-bit codes (format 12); writing one into a
            # BMP-only subtable (format 4 etc.) doesn't raise here, it corrupts the
            # table silently and only fails later, confusingly, when the font is
            # saved.
            if 'cmap' in font:
                if unicode_point > 0xFFFF:
                    target = ensure_supplementary_cmap_subtable(font)
                    target.cmap[unicode_point] = glyph_name
                else:
                    for subtable in font['cmap'].tables:
                        if getattr(subtable, 'isUnicode', lambda: False)():
                            if hasattr(subtable, 'cmap') and subtable.cmap is not None:
                                subtable.cmap[unicode_point] = glyph_name
            
            # Also add scaled versions to other strikes
            for strike_ppem, other_strike in strikes.items():
                if strike_ppem == ppem:
                    continue

                try:
                    scaled_canvas_w = int(strike_ppem * advance / units_per_em)
                    scaled_margin = strike_margin(strike_ppem)
                    scaled_descent_shift = int(descent * strike_ppem / (2 * units_per_em))
                    scaled_data, _, _ = resize_image_to_emoji(
                        Path(meme_path).read_bytes(),
                        content_width=scaled_canvas_w - scaled_margin,
                        content_height=strike_ppem - scaled_margin,
                        canvas_width=scaled_canvas_w, canvas_height=strike_ppem,
                        y_offset=0
                    )
                    scaled_glyph = SbixGlyph(
                        glyphName=glyph_name,
                        referenceGlyphName=None,
                        originOffsetX=0,
                        originOffsetY=-scaled_descent_shift,
                        graphicType='png ',
                        imageData=scaled_data,
                        rawdata=None
                    )
                    other_strike.glyphs[glyph_name] = scaled_glyph
                except:
                    pass
            
        except Exception as e:
            print(f"Error processing U+{unicode_point:04X}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Fix timestamps in head table for compatibility
    if 'head' in font:
        import time
        current_time = int(time.time()) + 2082844800  # Mac epoch offset
        font['head'].modified = current_time

    # Save the modified font
    print(f"Saving font: {output_path}")
    font.save(output_path)
    font.close()

    # fonttools recalculates head.flags on save, clearing bit 1.
    # Re-open and set it: bit 1 tells renderers (e.g. iTerm2) the font
    # contains SBIX bitmap data.
    font2 = TTFont(output_path)
    font2['head'].flags |= (1 << 1)
    font2.save(output_path, reorderTables=False)
    font2.close()

    import time
    print(f"Successfully created: {Path(output_path).resolve()} (at {time.strftime('%H:%M:%S')})")

def parse_mappings(mappings_str):
    """
    Parse mappings string like "U+1F600:pepe,U+0041:drake"
    Returns dict mapping Unicode code points (int) to meme names (str)
    """
    mappings = {}
    if not mappings_str:
        return mappings
    
    for part in mappings_str.split(','):
        part = part.strip()
        if not part:
            continue
        
        if ':' not in part:
            raise ValueError(f"Invalid mapping format: {part} (expected 'U+XXXX:meme')")
        
        unicode_str, meme_name = part.split(':', 1)
        unicode_str = unicode_str.strip()
        meme_name = meme_name.strip()
        
        if not unicode_str.startswith('U+'):
            raise ValueError(f"Invalid Unicode format: {unicode_str} (expected 'U+XXXX')")
        
        unicode_point = int(unicode_str[2:], 16)
        mappings[unicode_point] = meme_name
    
    return mappings

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Inject meme images into a font using SBIX format',
        epilog='Example: %(prog)s input.ttf output.ttf --mappings "U+100000:pepe.png,U+100001:drake.jpg"\n\n'
               'Default meme range: U+100000-U+1003FF (Supplementary PUA, Plane 16; 1024 code\n'
               'points), rendered at 2 cells wide. This range has no meaning of its own in\n'
               'Unicode and is unclaimed by fonts/tools, but terminals do not render it wide by\n'
               'default — pair with a terminal patched to treat it as double-width (see\n'
               'iTermIsDoubleWidthCharacter in the MemeTerminal fork for iTerm2). Explicit\n'
               'code points outside this range fall back to standard Unicode East Asian Width.'
    )
    parser.add_argument('font_file', help='Input font file path')
    parser.add_argument('output_file', help='Output font file path')
    parser.add_argument('--mappings', required=True,
                        help='Comma-separated mappings of Unicode to meme images (e.g., "U+100000:pepe.png,U+100001:drake.jpg")')
    parser.add_argument('--ppem', type=int, default=160,
                        help='Pixels per EM for the SBIX strike (default: 160)')
    parser.add_argument('--ppi', type=int, default=72,
                        help='Pixels per inch resolution (default: 72)')
    parser.add_argument('--font-name', type=str, default=None,
                        help='New font family name (e.g., "Meme font")')
    
    args = parser.parse_args()
    
    # Parse mappings
    try:
        mappings = parse_mappings(args.mappings)
    except ValueError as e:
        print(f"Error parsing mappings: {e}", file=sys.stderr)
        sys.exit(1)
    
    if not mappings:
        print("Error: No mappings provided", file=sys.stderr)
        sys.exit(1)
    
    print(f"Injecting {len(mappings)} meme(s) into font...")
    
    # Inject memes
    try:
        inject_sbix_memes(args.font_file, args.output_file, mappings, args.ppem, args.ppi, resize=True, font_name=args.font_name)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
