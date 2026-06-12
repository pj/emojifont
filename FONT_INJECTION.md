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
uv run emojifont input.ttf output.ttf --mappings "U+F900:font_build/memes/pepe.jpg"
```

Or with nix:

```bash
uv run emojifont input.ttf output.ttf --mappings "U+F900:font_build/memes/pepe.jpg"
```

### Renaming the Font

You can rename the font family in the metadata:

```bash
uv run emojifont input.ttf font_build/MemeFont.ttf \
  --mappings "U+F900:font_build/memes/pepe.jpg" \
  --font-name "Meme font"
```

This updates the font's name table so it appears as "Meme font" in your system's font menu.

### Multiple Memes

Inject multiple memes by separating mappings with commas:

```bash
uv run emojifont input.ttf output.ttf --mappings "U+F900:font_build/memes/pepe.jpg,U+F901:font_build/memes/drake.png"
```

### Options

- `--mappings`: Unicode code point to image file mappings (required)
  - Format: `"U+XXXX:path/to/image.png,U+YYYY:path/to/other.jpg"`
- `--ppem`: Pixels per EM for the SBIX strike (default: 160)
  - Common values: 32, 64, 128, 160 (Apple emoji standard)
- `--ppi`: Pixels per inch resolution (default: 72)
- `--font-name`: New font family name (optional)
  - Example: `--font-name "Meme font"`
  - Updates the name table metadata so the font appears with your custom name

### CJK Compatibility Ideographs (U+F900–U+FAFF)

We use this block so memes get **2 cells** (double-width). Unicode East Asian Width: U+F8FF and below (PUA) = 1 cell; U+F900–U+FAFF = Wide = 2 cells. Terminals like iTerm2 follow this.

- **U+F900 to U+FAFF** – CJK Compatibility Ideographs (512 code points)
- Your base font must include glyphs for the code points you map (many CJK and "complete" Nerd Fonts do)

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

1. Open Font Book (Applications → Font Book)
2. Choose File → Add Fonts...
3. Select your `output.ttf` file
4. The font will be installed and available system-wide

## Viewing Your Meme Emojis

Once installed, you can type the Unicode characters in any application:
- Use Character Viewer (Edit → Emoji & Symbols, or Ctrl+Cmd+Space)
- Search for "CJK Compatibility" or the character name
- Or type the Unicode directly in supporting apps (e.g. Ctrl-V u f900 in Vim)

## Example

```bash
# Create a font with memes at U+F900, U+F901 and rename it
uv run emojifont \
  font_build/MonacoNerdFontMono-Regular.ttf \
  font_build/MemeFont.ttf \
  --mappings "U+F900:font_build/memes/pepe.jpg,U+F901:font_build/memes/shark.jpg" \
  --font-name "Meme font"

# The output font will be ~2.3MB with the embedded memes
# Install it via Font Book and use it!
```

## Technical Details

The script:
1. Opens the input font using fonttools
2. Creates or modifies the SBIX table
3. Resizes images to fit emoji dimensions (ppem × ppem)
4. Maps Unicode code points to glyph names via the CMAP table
5. Creates bitmap glyphs with PNG data
6. Saves the modified font

The SBIX format is used by Apple for color emoji in macOS and iOS. It stores bitmap images at various sizes (strikes) for each glyph.
