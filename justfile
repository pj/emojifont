# emojifont — common developer commands.
#
# Run `just` or `just --list` to see every recipe. Most CLI-wrapping recipes
# take `*args`, so any flag the underlying tool supports works even if there's
# no dedicated recipe for it, e.g. `just fetch dump --overwrite --jobs 4`.

set shell := ["bash", "-uc"]

default:
    @just --list

# --- setup -------------------------------------------------------------------

# Create the venv and install dependencies (uv sync)
install:
    uv sync

# --- tests -------------------------------------------------------------------

# Run the full Python test suite
test:
    uv run pytest tests/ -v

# Run one test file or node id, e.g. `just test-one tests/test_inject.py::TestRenameFont`
test-one target:
    uv run pytest {{ target }} -v

# --- font injection ------------------------------------------------------------

# Inject images into a font: just inject base.ttf out.ttf "U+F900:a.png,U+F901:b.png" MemeFont
inject base out mappings name="MemeFont":
    uv run emojifont {{ base }} {{ out }} --mappings "{{ mappings }}" --font-name "{{ name }}"

# Run any `emojifont` invocation directly, e.g. `just font --help`
font *args:
    uv run emojifont {{ args }}

# Local preview build of MemeFont from dotfiles/nix/memes/ — same base font
# and code-point assignment (sorted stem -> U+100000 + index) as the real
# build, which now happens as a Nix derivation in dotfiles/nix/flake.nix
# (see fonts.packages) rather than a committed file. Use this for a quick
# look at a font change without a full nix build; out defaults to font_build/
# so it never collides with anything nix or git track.
preview-dotfiles-font memes_dir="~/dotfiles/nix/memes" out="font_build/MemeFont-preview.ttf":
    #!/usr/bin/env bash
    set -euo pipefail
    memes_dir=$(eval echo {{memes_dir}})
    out=$(eval echo {{out}})
    uv run emojifont-build-meme-font ~/dotfiles/nix/MonacoNerdFontCompleteMono.ttf "$memes_dir" "$out" --font-name MemeFont

# Build the demo font from font_build/memes/ (mirrors the README example)
build-test-font:
    uv run emojifont font_build/MonacoNerdFontMono-Regular.ttf font_build/MemeFont.ttf \
        --mappings "U+F900:font_build/memes/pepe.jpg,U+F901:font_build/memes/mofusand_shark.jpg" \
        --font-name "MemeFont"

# --- fetching memes --------------------------------------------------------------

# Run any `emojifont-fetch` subcommand directly, e.g. `just fetch list --search shark`
fetch *args:
    uv run emojifont-fetch {{ args }}

# List curated emoji.gg packs, optionally filtered by name
fetch-packs search="":
    uv run emojifont-fetch packs --search "{{ search }}"

# Browse a pack or the whole index, with an optional HTML contact sheet
fetch-list pack="" search="" html="":
    uv run emojifont-fetch list --pack "{{ pack }}" --search "{{ search }}" --html "{{ html }}"

# Bulk-download all emoji.gg packs (or --source slackmojis --no-packs)
fetch-dump *args:
    uv run emojifont-fetch dump {{ args }}

# Bulk-download FrankerFaceZ emotes by popularity
fetch-ffz-dump pages="100":
    uv run emojifont-fetch ffz-dump --pages {{ pages }}

# Download specific memes by name/id: just fetch-get pepehappy pepeok --out memes/
fetch-get *args:
    uv run emojifont-fetch get {{ args }}

# Collapse exact-duplicate images across the dump directories
dedupe *args:
    uv run emojifont-fetch dedupe {{ args }}

# Preview what dedupe would do, without writing anything
dedupe-dry-run:
    uv run emojifont-fetch dedupe --dry-run --show-duplicates

# --- web UI ------------------------------------------------------------------------

# Launch the meme picker web UI (http://127.0.0.1:8877 by default)
web *args:
    uv run emojifont-web {{ args }}

# --- VM test (macOS host, requires Tart) ----------------------------------------------

# MemeTerminal screenshot test (real terminal rendering). Pass --font <path> to use an existing font.
vm-test *args:
    ./vm/run-tests.sh {{ args }}

# Same, keeping the VM running afterward for debugging
vm-test-keep *args:
    ./vm/run-tests.sh --keep {{ args }}

