# Using Meme Font in Terminal

## Your Meme Mappings

- **U+100000** - Pepe
- **U+100001** - Mofusand Shark

Supplementary Private Use Area, Plane 16 (U+100000-U+1003FF, 1024 code points
reserved). This block has no meaning of its own in Unicode and is unclaimed by
fonts/tools. Its default Unicode East Asian Width is Ambiguous (1 cell); a
terminal patched to treat this specific range as double-width (see
[MemeTerminal](https://github.com/pj/iTerm2), a fork of iTerm2) renders it at
2 cells instead.

Note the escape syntax: these code points are above U+FFFF, so they need the
8-digit `\U` form, not the 4-digit `\u` form used for BMP characters like the
CJK Compatibility Ideographs this project used to use.

## Output in Zsh/Bash

zsh supports `\U` (and `\u`) natively in `printf`, `echo`, and `$'...'`
quoting. The stock macOS `/bin/bash` (3.2) supports neither — it's only ever
relevant here if you run a script with a `#!/bin/bash` shebang; an
interactive zsh session (the macOS default) is unaffected.

### Using echo

```bash
# Print Pepe (U+100000)
echo "\U00100000"

# Print Mofusand Shark (U+100001)
echo "\U00100001"

# Print both
echo "\U00100000 \U00100001"

# Print in a sentence
echo "Here's a meme: \U00100000"
```

### Using printf

```bash
# Printf also works
printf "\U00100000\n"
printf "\U00100001\n"
printf "\U00100000 \U00100001\n"
```

### Copy-Paste Ready

```bash
# After installing the font, you can copy these directly:
echo "𐀀"  # U+100000 (Pepe)
echo "𐀁"  # U+100001 (Mofusand Shark)
```

## Setting Your Terminal Font

To see the memes in your terminal, you need to:

1. **Install the font**: Open `MemeFont.ttf` in Font Book
2. **Set terminal font**:
   - **MemeTerminal** (fork of iTerm2 with SBIX + Plane 16 double-width support): Preferences -> Profiles -> Text -> Font -> "MemeFont"
   - Other terminals will show the font's SBIX images, but at 1 cell wide unless similarly patched — see the main [README.md](README.md).

## Quick Test

After installing the font and setting it in your terminal:

```bash
# Test it out
echo "Testing memes: \U00100000 \U00100001"

# Create a function for easy access
meme-pepe() { echo "\U00100000"; }
meme-shark() { echo "\U00100001"; }

# Use it
meme-pepe
```

## Add to Your .zshrc

```bash
# Add these aliases to ~/.zshrc for quick access
alias pepe='echo "\U00100000"'
alias shark='echo "\U00100001"'

# Or make it more fun
alias meme='echo "\U00100000 \U00100001"'
```

## Using in Scripts

```bash
#!/bin/zsh

echo "Build succeeded! \U00100000"
echo "Test failed! \U00100001"

# Or use variables
PEPE="\U00100000"
SHARK="\U00100001"

echo "Status: $PEPE All good!"
```

## Vim/Neovim

In Vim/Neovim with the font installed:

```vim
" In insert mode, type Ctrl-V u then the code point (Vim's u digraph entry
" is 4 hex digits; for code points above U+FFFF use Ctrl-V U with 8 digits)
" Ctrl-V U 00100000
```

Or just paste the character directly.

## Character Viewer (macOS)

1. Press `Ctrl + Cmd + Space` to open Character Viewer
2. This code point has no assigned Unicode name (Private Use Area) — search by
   font instead: select "MemeFont" in the viewer's font list to browse it directly
3. Your memes will appear there (in your font) after installation
4. Click to insert in any app

## Adding More Memes

To add more memes to your font, use more code points from the reserved range:

```bash
# Map to U+100000, U+100001, U+100002, ...
uv run emojifont \
  font_build/MonacoNerdFontMono-Regular.ttf \
  font_build/MemeFont.ttf \
  --mappings "U+100000:font_build/memes/pepe.jpg,U+100001:font_build/memes/shark.jpg,U+100002:font_build/memes/new_meme.png" \
  --font-name "MemeFont"
```

Available range: **U+100000 to U+1003FF** (Supplementary PUA, Plane 16, 1024
code points). `emojifont-fetch get`/`emojifont-web` assign these automatically
in selection order — you only need to type code points by hand if you're
calling `emojifont` directly.

Your base font must include glyphs for the code points you map — `emojifont`
generates a placeholder outline itself, so this isn't usually a concern, but
the base font's own `cmap` table does need a format capable of encoding code
points above U+FFFF (format 12); `emojifont` creates one automatically if the
font doesn't already have it.
