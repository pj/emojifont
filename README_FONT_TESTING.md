# Quick Font Testing

Use `test_font.py` to quickly test fonts without installing them system-wide.

## Usage

```bash
nix develop --command python3 test_font.py <font.ttf> <text> <output.png> [options]
```

## Examples

### Test a meme font with CJK Compatibility characters

```bash
# Test the meme at U+F900
nix develop --command python3 test_font.py \
  MemeFont_multi.ttf \
  "Test \uf900 emoji" \
  test_output.png \
  --size 120
```

### Test multiple memes

```bash
# Test memes at U+F900, U+F901, U+F902
nix develop --command python3 test_font.py \
  MemeFont_multi.ttf \
  "Memes: \uf900 \uf901 \uf902" \
  test_memes.png \
  --size 160
```

### Custom colors

```bash
nix develop --command python3 test_font.py \
  MemeFont_multi.ttf \
  "Text with \uf900" \
  test_dark.png \
  --size 120 \
  --bg black \
  --fg white
```

## Options

- `--size`: Font size in points (default: 160)
- `--bg`: Background color (default: white)
- `--fg`: Foreground/text color for non-emoji glyphs (default: black)

## Unicode Escape Sequences

In the text argument, use:
- `\uf900` for U+F900
- `\uf901` for U+F901
- `\U0000f900` for U+F900 (alternative format)

## How it Works

The script:
1. Loads the font using fonttools
2. Extracts SBIX bitmap glyphs directly from the font file
3. Composites them into an image at the correct positions
4. Saves the result as a PNG

This works even if PIL/Pillow can't load the font normally (which sometimes happens with heavily modified fonts).

## Output

The script creates a PNG image showing your text rendered with the font, with SBIX emoji properly displayed. View the output in Finder or any image viewer.
