#!/usr/bin/env bash
#
# Uninstall the meme font (if installed), install the built font,
# open iTerm2 with a specific profile, and print emoji test text.
#
# Usage:
#   ./install_and_test.sh [font-path] [iterm-profile]
#
# Examples:
#   ./install_and_test.sh
#   ./install_and_test.sh MemeFont.ttf
#   ./install_and_test.sh MemeFont.ttf "Meme"
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FONT_PATH="${1:-$SCRIPT_DIR/font_build/MemeFont.ttf}"
ITERM_PROFILE="${2:-Meme}"
USER_FONTS="$HOME/Library/Fonts"

# --- 1. Uninstall existing font (same filename) from user Fonts ---
INSTALLED_NAME="$(basename "$FONT_PATH")"
if [[ -f "$USER_FONTS/$INSTALLED_NAME" ]]; then
  echo "==> Removing existing: $USER_FONTS/$INSTALLED_NAME"
  rm -f "$USER_FONTS/$INSTALLED_NAME"
else
  echo "==> No existing copy to remove ($INSTALLED_NAME)."
fi

# --- 2. Install the updated font ---
if [[ ! -f "$FONT_PATH" ]]; then
  echo "Error: Font file not found: $FONT_PATH" >&2
  echo 'Build the font first with "uv run emojifont", or pass the path as the first argument.' >&2
  exit 1
fi
echo "==> Installing font: $FONT_PATH"
cp "$FONT_PATH" "$USER_FONTS/"
echo "    Installed to $USER_FONTS/$(basename "$FONT_PATH")"

# --- 3. Open iTerm2 with profile and print emoji test ---
# U+F900/U+F901 = CJK Compatibility (East Asian Width Wide = 2 cells). PUA U+F8FF = 1 cell.
# Backslashes doubled so AppleScript receives literal \uf900 and passes them to the shell
TEST_CMD="echo \$'Testing memes: \\\\\\\\uf900 \\\\\\\\uf901'"
echo "==> Opening iTerm2 with profile \"$ITERM_PROFILE\" and running test"
osascript <<EOF
tell application "iTerm"
  activate
  create window with profile "$ITERM_PROFILE"
  delay 0.3
  tell current session of current window
    write text "$TEST_CMD"
  end tell
end tell
EOF
echo "Done."
