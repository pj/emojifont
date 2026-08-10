# Font Injection with SBIX

This guide explains how to inject meme images into fonts using the SBIX (Standard Bitmap Image Extension) format.

## Requirements

The Python script requires:
- Python 3
- fonttools (for font manipulation)
- Pillow (for image resizing)

These are automatically available in the nix development environment.

## Usage

### Basic Usage

```bash
uv run emojifont input.ttf output.ttf --mappings "U+100000:font_build/memes/pepe.jpg"
```

Or with nix:

```bash
uv run emojifont input.ttf output.ttf --mappings "U+100000:font_build/memes/pepe.jpg"
```

### Renaming the Font

You can rename the font family in the metadata:

```bash
uv run emojifont input.ttf font_build/MemeFont.ttf \
  --mappings "U+100000:font_build/memes/pepe.jpg" \
  --font-name "MemeFont"
```

This updates the font's name table so it appears as "MemeFont" in your system's font menu.

### Multiple Memes

Inject multiple memes by separating mappings with commas:

```bash
uv run emojifont input.ttf output.ttf --mappings "U+100000:font_build/memes/pepe.jpg,U+100001:font_build/memes/drake.png"
```

### Options

- `--mappings`: Unicode code point to image file mappings (required)
  - Format: `"U+XXXX:path/to/image.png,U+YYYY:path/to/other.jpg"`
- `--ppem`: Pixels per EM for the SBIX strike (default: 160)
  - Common values: 32, 64, 128, 160 (Apple emoji standard)
- `--ppi`: Pixels per inch resolution (default: 72)
- `--font-name`: New font family name (optional)
  - Example: `--font-name "MemeFont"`
  - Updates the name table metadata so the font appears with your custom name

### Supplementary Private Use Area, Plane 16 (U+100000-U+1003FF)

We use this block by default so memes get their own reserved 1024-code-point
range with no meaning of its own in Unicode, and no collision with the Nerd
Font icon sets that densely populate the more common BMP Private Use Area
(U+E000-U+F8FF). This project previously used the CJK Compatibility
Ideographs block (U+F900-U+FAFF) instead — those are real characters used for
legacy CJK round-trip encoding, so any font/terminal that ever encountered
genuine CJK compatibility text would have silently shown a meme instead.

Unlike the CJK block, Plane 16 PUA's default Unicode East Asian Width is
Ambiguous, not Wide — terminals won't render it at 2 cells automatically.
Getting double-width rendering requires a terminal patched to special-case
this range; see [MemeTerminal](https://github.com/pj/iTerm2) (a fork of
iTerm2) for the reference patch (`iTermIsDoubleWidthCharacter` in
`iTermCharacterWidth.c`). Code points passed explicitly outside this default
range still get sized via standard Unicode East Asian Width — e.g. mapping to
the old CJK block still works and still renders wide everywhere, it's just no
longer the default.

- **U+100000 to U+1003FF** - Supplementary Private Use Area, Plane 16 (1024 code points)
- Code points above U+FFFF need a `cmap` subtable that supports 32-bit values
  (format 12); `emojifont` creates one automatically if the base font doesn't
  already have one (most real fonts, including any with existing emoji or
  Plane 15/16 icon support, already do)

## Features

### Automatic Image Resizing

Images are automatically resized to fit emoji dimensions while maintaining aspect ratio:
- Target size is based on the `ppem` value (default: 160x160 pixels)
- High-quality Lanczos resampling is used
- Output format is PNG for best quality

### Format Support

Input images can be in any format supported by Pillow:
- PNG (recommended)
- JPEG
- GIF
- WebP
- TIFF
- BMP

All images are converted to PNG in the SBIX table for optimal quality.

## Installing the Font on macOS

After creating the modified font:

1. Open Font Book (Applications -> Font Book)
2. Choose File -> Add Fonts...
3. Select your `output.ttf` file
4. The font will be installed and available system-wide

Installing the file is not always enough for apps to find it *by name* —
some apps resolve fonts through CoreText's name-based lookup, which can
require an explicit registration step beyond just placing the file in
`~/Library/Fonts`. See the MemeTerminal VM test infrastructure
(`vm/scripts/terminal-screenshot.sh`) for the reference fix
(`CTFontManagerRegisterFontsForURL`) if a font that's clearly installed still
doesn't get picked up by name.

## Viewing Your Meme Emojis

Once installed, you can type the Unicode characters in any application that
supports the font and (for 2-cell rendering) a terminal patched for this
range:
- Use Character Viewer (Edit -> Emoji & Symbols, or Ctrl+Cmd+Space) — this
  range has no assigned Unicode name, so browse by selecting your font in the
  viewer's font list rather than searching by name
- Or type the Unicode directly in supporting apps (e.g. in Vim, `Ctrl-V U 00100000` —
  note the capital `U` and 8 hex digits, since this is above the BMP)

## Example

```bash
# Create a font with memes at U+100000, U+100001 and rename it
uv run emojifont \
  font_build/MonacoNerdFontMono-Regular.ttf \
  font_build/MemeFont.ttf \
  --mappings "U+100000:font_build/memes/pepe.jpg,U+100001:font_build/memes/shark.jpg" \
  --font-name "MemeFont"

# The output font will be a few MB with the embedded memes
# Install it via Font Book and use it!
```

## Technical Details

The script:
1. Opens the input font using fonttools
2. Creates or modifies the SBIX table
3. Resizes images to fit emoji dimensions (ppem x ppem)
4. Maps Unicode code points to glyph names via the CMAP table (creating a
   format-12 subtable first if the code point is above U+FFFF and the font
   doesn't already have one capable of holding it)
5. Creates bitmap glyphs with PNG data
6. Saves the modified font

The SBIX format is used by Apple for color emoji in macOS and iOS. It stores bitmap images at various sizes (strikes) for each glyph.
