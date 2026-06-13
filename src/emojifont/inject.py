"""
Inject meme images into a font using SBIX (Standard Bitmap Image Extension) format.
This script uses fonttools to create macOS-compatible fonts.
"""

import sys
import io
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._s_b_i_x import table__s_b_i_x
from fontTools.ttLib.tables.sbixStrike import Strike, Glyph as SbixGlyph
from fontTools.ttLib.tables._g_l_y_f import Glyph as TTGlyph, GlyphCoordinates
from fontTools.ttLib.tables import ttProgram
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

def resize_image_to_emoji(image_data, content_size, canvas_width, canvas_height, y_offset=0):
    """
    Resize a meme image and place it on a transparent canvas.

    Args:
        image_data: Raw image bytes
        content_size: Max size for the meme artwork in pixels
        canvas_width: Canvas width in pixels (e.g. 2*ppem for 2-cell glyphs)
        canvas_height: Canvas height in pixels (= ppem, fills the em square)
        y_offset: Pixels to shift the image down within the canvas (positive = down).

    Returns:
        Tuple of (PNG bytes, canvas_width, canvas_height)
    """
    img = Image.open(io.BytesIO(image_data))

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    width, height = img.size
    max_dim = max(width, height)
    scale = content_size / max_dim
    new_width = int(width * scale)
    new_height = int(height * scale)

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

    # System emoji fills ~100% of font size, centered between ascender and
    # descender, extending below baseline. We match this by:
    # 1. Filling the ppem×ppem canvas (= em square) with artwork centered in it
    # 2. Using originOffsetY to shift the bitmap down so its center aligns with
    #    the ascender/descender midpoint rather than the em-square midpoint
    scale = ppem / units_per_em
    margin = 4
    emoji_height = ppem - margin  # Fill nearly the full em square
    
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
            # Use a dedicated glyph for this code point (e.g. uniF900) so only U+F900 shows our bitmap
            glyph_name = f"uni{unicode_point:04X}"
            ensure_glyph_exists(font, glyph_name, units_per_em, units_per_em)
            glyph_order = font.getGlyphOrder()
            glyph_id = glyph_order.index(glyph_name) if glyph_name in glyph_order else -1

            # Read the meme image
            meme_data = Path(meme_path).read_bytes()

            # Resize meme and center it on a ppem×ppem transparent canvas.
            # Artwork is centered in the canvas (no y_offset in the bitmap itself).
            # Instead, we use SBIX originOffsetY to shift the whole bitmap down
            # so that it's centered between ascender and descender.
            graphic_type = None
            img_width = ppem
            img_height = ppem

            if resize:
                try:
                    meme_data, img_width, img_height = resize_image_to_emoji(
                        meme_data, content_size=emoji_height,
                        canvas_width=ppem, canvas_height=ppem,
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
            print(f"    Size: {img_width}x{img_height}, Offsets: ({originOffsetX}, {originOffsetY})")
            
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
            
            # Set advance width to 1 em (matching system emoji visual width).
            # Terminal 2-cell allocation comes from Unicode East Asian Width, not advance.
            if 'hmtx' in font:
                font['hmtx'].metrics[glyph_name] = (units_per_em, 0)
            
            # Ensure this code point maps to our glyph in all Unicode cmap subtables
            # (so the requested U+F900 etc. always show our bitmap regardless of which subtable the OS uses)
            if 'cmap' in font:
                for subtable in font['cmap'].tables:
                    if getattr(subtable, 'isUnicode', lambda: False)():
                        if hasattr(subtable, 'cmap') and subtable.cmap is not None:
                            subtable.cmap[unicode_point] = glyph_name
            
            # Also add scaled versions to other strikes
            for strike_ppem, other_strike in strikes.items():
                if strike_ppem == ppem:
                    continue

                try:
                    scaled_emoji_height = strike_ppem - margin
                    scaled_descent_shift = int(descent * strike_ppem / (2 * units_per_em))
                    scaled_data, _, _ = resize_image_to_emoji(
                        Path(meme_path).read_bytes(),
                        content_size=scaled_emoji_height,
                        canvas_width=strike_ppem, canvas_height=strike_ppem,
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
        epilog='Example: %(prog)s input.ttf output.ttf --mappings "U+F900:pepe.png,U+F901:drake.jpg"\n\n'
               'CJK Compatibility Ideographs: U+F900 to U+FAFF. Unicode East Asian Width = Wide (2 cells).\n'
               'U+F8FF and below (PUA) = 1 cell; U+F900+ = 2 cells. Terminals (e.g. iTerm2) follow this.'
    )
    parser.add_argument('font_file', help='Input font file path')
    parser.add_argument('output_file', help='Output font file path')
    parser.add_argument('--mappings', required=True,
                        help='Comma-separated mappings of Unicode to meme images (e.g., "U+F900:pepe.png,U+F901:drake.jpg")')
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
