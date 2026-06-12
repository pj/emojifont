# Using Meme Font in Terminal

## Your Meme Mappings

- **U+F900** () - Pepe
- **U+F901** () - Mofusand Shark

CJK Compatibility Ideographs (U+F900–U+FAFF). Unicode East Asian Width = Wide = 2 cells; U+F8FF (PUA) = 1 cell.

## Output in Zsh/Bash

### Using echo

```bash
# Print Pepe (U+F900)
echo "\uf900"

# Print Mofusand Shark (U+F901)
echo "\uf901"

# Print both
echo "\uf900 \uf901"

# Print in a sentence
echo "Here's a meme: \uf900"
```

### Using printf

```bash
# Printf also works
printf "\uf900\n"
printf "\uf901\n"
printf "\uf900 \uf901\n"
```

### Copy-Paste Ready

```bash
# After installing the font, you can copy these directly:
echo ""  # U+F900 (Pepe)
echo ""  # U+F901 (Mofusand Shark)
```

## Setting Your Terminal Font

To see the memes in your terminal, you need to:

1. **Install the font**: Open `MemeFont.ttf` in Font Book
2. **Set terminal font**: 
   - **iTerm2**: Preferences → Profiles → Text → Font → "Meme font"
   - **Terminal.app**: Preferences → Profiles → Font → "Meme font"

## Quick Test

After installing the font and setting it in your terminal:

```bash
# Test it out
echo "Testing memes: \uf900 \uf901"

# Create a function for easy access
meme-pepe() { echo "\uf900"; }
meme-shark() { echo "\uf901"; }

# Use it
meme-pepe
```

## Add to Your .zshrc

```bash
# Add these aliases to ~/.zshrc for quick access
alias pepe='echo "\uf900"'
alias shark='echo "\uf901"'

# Or make it more fun
alias meme='echo "\uf900 \uf901"'
```

## Using in Scripts

```bash
#!/bin/zsh

echo "Build succeeded! \uf900"
echo "Test failed! \uf901"

# Or use variables
PEPE="\uf900"
SHARK="\uf901"

echo "Status: $PEPE All good!"
```

## Vim/Neovim

In Vim/Neovim with the font installed:

```vim
" In insert mode, type Ctrl-V u f900
" This inserts the Unicode character directly
```

Or just paste the character directly.

## Character Viewer (macOS)

1. Press `Ctrl + Cmd + Space` to open Character Viewer
2. Search for "CJK Compatibility" or the character name (e.g. the original U+F900 character)
3. Your memes will appear there (in your font) after installation
4. Click to insert in any app

## Adding More Memes

To add more memes to your font, use more code points from the CJK Compatibility Ideographs block:

```bash
# Map to U+F900, U+F901, U+F902, ...
uv run emojifont \
  font_build/MonacoNerdFontMono-Regular.ttf \
  font_build/MemeFont.ttf \
  --mappings "U+F900:font_build/memes/pepe.jpg,U+F901:font_build/memes/shark.jpg,U+F902:font_build/memes/new_meme.png" \
  --font-name "Meme font"
```

Available range: **U+F900 to U+FAFF** (CJK Compatibility Ideographs, 512 code points; East Asian Width = Wide = 2 cells).

Your base font must include glyphs for the code points you map (many CJK and “complete” Nerd Fonts do).
