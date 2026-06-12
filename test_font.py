#!/usr/bin/env python3
"""
Quick font tester - renders text with a custom font to an image for testing.
Handles fonts with SBIX tables by extracting and compositing the bitmap glyphs.
"""

import sys
import argparse
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

def get_sbix_bitmap(font_ttf, glyph_name, target_ppem=160):
    """
    Extract SBIX bitmap for a glyph if available.
    
    Returns:
        (PIL.Image, originOffsetX, originOffsetY) or (None, 0, 0) if not found
    """
    if 'sbix' not in font_ttf:
        return None, 0, 0
    
    sbix_table = font_ttf['sbix']
    
    # Find the best strike (prefer exact match, or closest)
    best_strike = None
    best_ppem = None
    for ppem in sorted(sbix_table.strikes.keys()):
        if best_ppem is None or abs(ppem - target_ppem) < abs(best_ppem - target_ppem):
            best_ppem = ppem
            best_strike = sbix_table.strikes[ppem]
    
    if best_strike is None:
        return None, 0, 0
    
    # Get glyph bitmap
    if glyph_name not in best_strike.glyphs:
        return None, 0, 0
    
    glyph = best_strike.glyphs[glyph_name]
    if not glyph.imageData:
        return None, 0, 0
    
    # Load the bitmap image
    try:
        img = Image.open(io.BytesIO(glyph.imageData))
        return img, glyph.originOffsetX, glyph.originOffsetY
    except:
        return None, 0, 0

def render_font_test(font_path, text, output_path, font_size=160, bg_color="white", fg_color="black"):
    """
    Render text using a custom font and save as an image.
    Handles SBIX emoji by compositing them directly.
    
    Args:
        font_path: Path to the font file
        text: Text to render (can include Unicode like \uf900)
        output_path: Output image path
        font_size: Font size in points (default: 160)
        bg_color: Background color (default: white)
        fg_color: Foreground/text color (default: black)
    """
    # Load the font with fonttools to check for SBIX
    font_ttf = TTFont(font_path)
    has_sbix = 'sbix' in font_ttf
    
    # Try to load with PIL (may fail if SBIX causes issues)
    font_pil = None
    try:
        font_pil = ImageFont.truetype(font_path, size=font_size)
    except Exception as e:
        if not has_sbix:
            print(f"Error loading font with PIL: {e}")
            sys.exit(1)
        print(f"Note: Font has SBIX table, using fonttools extraction method")
    
    # Calculate image size based on character count and font size
    char_width = font_size
    char_height = font_size
    padding = 40
    
    img_width = len(text) * char_width + padding * 2
    img_height = char_height + padding * 2
    
    # Create the actual image
    img = Image.new('RGBA', (img_width, img_height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Get cmap for Unicode to glyph name mapping
    cmap = font_ttf.getBestCmap()
    
    # Render each character
    x_pos = padding
    y_baseline = padding + int(char_height * 0.5)  # Middle of the cell
    
    for char in text:
        char_code = ord(char)
        
        # Get glyph name
        glyph_name = cmap.get(char_code) if cmap else None
        
        if has_sbix and glyph_name:
            # Try to get SBIX bitmap
            sbix_img, offset_x, offset_y = get_sbix_bitmap(font_ttf, glyph_name, font_size)
            
            if sbix_img:
                # SBIX offsets define where BOTTOM-LEFT corner of bitmap is placed
                # originOffsetX: positive = right, negative = left (from glyph origin)
                # originOffsetY: positive = UP from baseline (font coords), but PIL Y goes DOWN
                # Need to convert: PIL Y increases downward, font Y increases upward
                
                paste_x = x_pos + font_size // 2 + offset_x
                # Subtract offset_y because PIL coordinates are inverted from font coordinates
                paste_y = y_baseline - offset_y
                
                img.paste(sbix_img, (paste_x, paste_y), sbix_img if sbix_img.mode == 'RGBA' else None)
                x_pos += font_size
                continue
        
        # Fallback: draw with PIL font (if available)
        if font_pil:
            draw.text((x_pos, y_baseline), char, font=font_pil, fill=fg_color, anchor="ls")
            # Approximate advance
            bbox = draw.textbbox((x_pos, y_baseline), char, font=font_pil, anchor="ls")
            x_pos += (bbox[2] - bbox[0])
        else:
            # No font available, just draw placeholder text
            draw.text((x_pos, y_baseline), char, fill=fg_color)
            x_pos += char_width
    
    # Crop to actual content (remove excess width)
    img = img.crop((0, 0, x_pos + padding, img_height))
    
    # Save
    img.save(output_path)
    print(f"Rendered: {output_path}")
    print(f"  Text: {repr(text)}")
    print(f"  Size: {img.width}x{img.height}")
    print(f"  Font size: {font_size}pt")
    
    return output_path

def parse_unicode_escapes(text):
    """
    Parse Unicode escape sequences like \\uf900 or \\U0001F600.
    """
    # Python's decode handles \uXXXX and \UXXXXXXXX
    try:
        # Use 'unicode_escape' codec to interpret escape sequences
        return text.encode().decode('unicode_escape')
    except:
        # If that fails, return as-is
        return text

def main():
    parser = argparse.ArgumentParser(
        description='Test a font by rendering text to an image',
        epilog='Examples:\n'
               '  %(prog)s font.ttf "Hello World" test.png\n'
               '  %(prog)s font.ttf "Test \\uf900 emoji" test.png\n'
               '  %(prog)s font.ttf "ABC\\uf900\\uf901" test.png --size 200\n'
               '  %(prog)s font.ttf "\\U0000f900\\U0000f901" test.png',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('font_file', help='Font file to test (.ttf or .otf)')
    parser.add_argument('text', help='Text to render (use \\uf900 for U+F900, etc.)')
    parser.add_argument('output_image', help='Output image path (PNG recommended)')
    parser.add_argument('--size', type=int, default=160,
                        help='Font size in points (default: 160)')
    parser.add_argument('--bg', default='white',
                        help='Background color (default: white)')
    parser.add_argument('--fg', default='black',
                        help='Foreground/text color for non-emoji glyphs (default: black)')
    
    args = parser.parse_args()
    
    # Parse Unicode escapes in the text
    text = parse_unicode_escapes(args.text)
    
    # Render the font
    output_path = render_font_test(
        args.font_file,
        text,
        args.output_image,
        args.size,
        args.bg,
        args.fg
    )

if __name__ == '__main__':
    main()
