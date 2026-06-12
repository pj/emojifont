# emojifont

Inject your own images into a TrueType font as color emoji, using Apple's
[SBIX](https://learn.microsoft.com/en-us/typography/opentype/spec/sbix) bitmap
format. Take any font, add your favourite images at unused code points, and use
them in your terminal, editor, or any app — just like real emoji.

```
echo "deploy succeeded \uf900"     # prints your image in the terminal
```

## How it works

- Images are resized and embedded into the font's `sbix` table at multiple
  sizes (strikes), the same mechanism Apple Color Emoji uses on macOS/iOS.
- Code points in the CJK Compatibility Ideographs block (U+F900–U+FAFF) are
  used by default. These have Unicode East Asian Width = Wide, so terminals
  allocate 2 cells — giving your images room to render at full emoji size.
- Images are vertically centered between the ascender and descender and scaled
  to match the size of system emoji.

## Installation

Requires [uv](https://docs.astral.sh/uv/).

```bash
# Run directly without installing
uvx emojifont --help

# Or install as a tool
uv tool install emojifont

# Or from a checkout of this repo
uv tool install .
```

## Usage

```bash
emojifont input.ttf output.ttf \
  --mappings "U+F900:pepe.jpg,U+F901:shark.png" \
  --font-name "MemeFont"
```

| Option | Description |
| --- | --- |
| `--mappings` | Comma-separated `U+XXXX:image` pairs (required) |
| `--font-name` | Rename the font family (optional) |
| `--ppem` | Pixels per em for the main bitmap strike (default 160) |
| `--ppi` | Resolution (default 72) |

Then install the output font (macOS: double-click → Font Book) and select it in
your terminal/editor. Print your new emoji with `echo "\uf900"`.

Notes:

- The base font must be a TrueType font (`glyf` outlines); CFF/OTF fonts are
  not supported.
- SBIX color emoji render on Apple platforms (Terminal, iTerm2, Ghostty, kitty,
  most macOS apps). Other platforms generally don't support SBIX.
- Input images can be PNG, JPEG, GIF, WebP, TIFF, or BMP.

## Development

A Nix flake provides the dev environment (`nix develop`, or `direnv allow`):

```bash
uv sync                 # create venv + install deps
uv run emojifont --help
```

Source fonts and meme images live in `font_build/` (gitignored — images may be
copyrighted). Build the test font into it:

```bash
uv run emojifont font_build/MonacoNerdFontMono-Regular.ttf font_build/MemeFont.ttf \
  --mappings "U+F900:font_build/memes/pepe.jpg,U+F901:font_build/memes/mofusand_shark.jpg" \
  --font-name "MemeFont"
```

The test app loads `font_build/MemeFont.ttf` automatically.

### Test app (macOS)

`FontTestApp/` contains a SwiftUI app that renders the generated font at
multiple sizes alongside normal text and system emoji, with alignment
diagnostics and an embedded terminal (SwiftTerm) for end-to-end testing.

```bash
# Build & run the app (requires full Xcode)
swift run --package-path FontTestApp FontTestApp

# Headless: capture snapshots + alignment report into snapshots/
swift run --package-path FontTestApp FontTestApp --diagnose
```

If building from inside the Nix devshell, point the toolchain at Xcode:

```bash
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
SDKROOT=$DEVELOPER_DIR/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk \
swift run --package-path FontTestApp FontTestApp
```

### More docs

- [FONT_INJECTION.md](FONT_INJECTION.md) — technical details of SBIX injection
- [USAGE.md](USAGE.md) — using the font in terminals, shells, and editors
- [README_FONT_TESTING.md](README_FONT_TESTING.md) — quick font testing with `test_font.py`

## License

MIT. Note: example fonts in this repo retain their original licenses. You are
responsible for the rights to any images you embed and any fonts you modify.
