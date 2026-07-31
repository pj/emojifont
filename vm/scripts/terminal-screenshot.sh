#!/bin/bash
set -euo pipefail
#
# terminal-screenshot.sh — Run inside the VM via SSH.
#
# Installs MemeTerminal + MemeFont, launches the terminal with a profile
# that uses the meme font, types test commands, and captures screenshots.
#
# Prerequisites:
#   - VM must have GUI session (tart run without --no-graphics)
#   - User must have granted screen recording permission for com.apple.sshd-session
#     (a dialog appears on first screencapture via SSH — click "Allow")
#
# Usage:
#   terminal-screenshot.sh <font-path> <output-dir> [codepoints...]
#
# Example:
#   terminal-screenshot.sh /tmp/TestMemeFont.ttf /tmp/screenshots F900 F901
#

FONT_PATH="${1:?Usage: terminal-screenshot.sh <font-path> <output-dir> [codepoints...]}"
OUTPUT_DIR="${2:?Usage: terminal-screenshot.sh <font-path> <output-dir> [codepoints...]}"
shift 2
CODEPOINTS=("${@:-F900 F901}")

RELEASE_URL="https://github.com/pj/iTerm2/releases/download/v0.0.1/MemeTerminal.zip"
APP_NAME="MemeTerminal"

mkdir -p "$OUTPUT_DIR"

echo "=== MemeTerminal Screenshot Test ==="
echo "Font: $FONT_PATH"
echo "Output: $OUTPUT_DIR"
echo "Codepoints: ${CODEPOINTS[*]}"
echo ""

# --------------------------------------------------------------------------- #
# 1. Install MemeTerminal                                                      #
# --------------------------------------------------------------------------- #
if [ ! -d "/Applications/${APP_NAME}.app" ]; then
    echo "[1/7] Downloading MemeTerminal..."
    curl -L -o /tmp/MemeTerminal.zip "$RELEASE_URL" 2>&1
    cd /tmp && unzip -o MemeTerminal.zip 2>&1
    cp -R "/tmp/${APP_NAME}.app" /Applications/
    echo "  Installed to /Applications/${APP_NAME}.app"
else
    echo "[1/7] MemeTerminal already installed"
fi

# --------------------------------------------------------------------------- #
# 2. Install the font                                                          #
# --------------------------------------------------------------------------- #
echo "[2/7] Installing font..."
mkdir -p ~/Library/Fonts
DEST_FONT="$HOME/Library/Fonts/$(basename "$FONT_PATH")"
if [ "$(realpath "$FONT_PATH" 2>/dev/null)" != "$(realpath "$DEST_FONT" 2>/dev/null)" ]; then
    cp "$FONT_PATH" "$DEST_FONT"
    echo "  Copied to $DEST_FONT"
else
    echo "  Font already installed at $DEST_FONT"
fi

# --------------------------------------------------------------------------- #
# 3. Create display script                                                     #
# --------------------------------------------------------------------------- #
echo "[3/7] Creating display script..."

DISPLAY_SCRIPT="/tmp/meme-display.sh"
{
    echo '#!/bin/bash'
    echo 'echo ""'
    echo 'echo "Terminal font rendering test"'
    echo 'echo "============================"'
    echo 'echo ""'
    echo 'echo "Regular text: Hgpy ABC 123"'

    # Helper: convert hex codepoint to UTF-8 byte escape sequences
    cp_to_utf8() {
        local DEC=$((16#$1))
        if [ $DEC -le 127 ]; then
            printf '\\x%02x' $DEC
        elif [ $DEC -le 2047 ]; then
            printf '\\x%02x\\x%02x' $(( 0xC0 | (DEC >> 6) )) $(( 0x80 | (DEC & 0x3F) ))
        elif [ $DEC -le 65535 ]; then
            printf '\\x%02x\\x%02x\\x%02x' $(( 0xE0 | (DEC >> 12) )) $(( 0x80 | ((DEC >> 6) & 0x3F) )) $(( 0x80 | (DEC & 0x3F) ))
        else
            printf '\\x%02x\\x%02x\\x%02x\\x%02x' $(( 0xF0 | (DEC >> 18) )) $(( 0x80 | ((DEC >> 12) & 0x3F) )) $(( 0x80 | ((DEC >> 6) & 0x3F) )) $(( 0x80 | (DEC & 0x3F) ))
        fi
    }

    # Build meme glyph sequences
    MEME_CHARS=""
    for cp in "${CODEPOINTS[@]}"; do
        MEME_CHARS="${MEME_CHARS}$(cp_to_utf8 "$cp") "
    done

    # Standard emoji for comparison
    GRIN=$(cp_to_utf8 1F600)        # 😀
    ROCKET=$(cp_to_utf8 1F680)      # 🚀
    FIRE=$(cp_to_utf8 1F525)        # 🔥
    STAR=$(cp_to_utf8 2B50)         # ⭐
    THUMBSUP=$(cp_to_utf8 1F44D)    # 👍
    HEART=$(cp_to_utf8 2764)        # ❤
    EYES=$(cp_to_utf8 1F440)        # 👀
    HUNDRED=$(cp_to_utf8 1F4AF)     # 💯
    EMOJI_CHARS="${GRIN} ${ROCKET} ${FIRE} ${STAR} ${THUMBSUP} ${HEART} ${EYES} ${HUNDRED}"

    echo "printf 'Memes inline: Hello ${MEME_CHARS}World\n'"
    echo "printf 'Memes only:   ${MEME_CHARS}\n'"
    echo 'echo ""'
    echo "printf 'Emoji:        ${EMOJI_CHARS}\n'"
    echo "printf 'Mixed:        ${GRIN} ${MEME_CHARS}${ROCKET} text ${FIRE}\n'"
    echo 'echo ""'
    echo 'echo "============================"'
    echo 'echo ""'
    echo 'exec bash'
} > "$DISPLAY_SCRIPT"
chmod +x "$DISPLAY_SCRIPT"
echo "  Display script: $DISPLAY_SCRIPT"

# --------------------------------------------------------------------------- #
# 4. Configure MemeTerminal profile                                            #
# --------------------------------------------------------------------------- #
echo "[4/7] Configuring MemeTerminal profile..."

# Get the PostScript name from the font file
PS_NAME=$(
    cd ~/Projects/emojifont 2>/dev/null && \
    PATH="$HOME/.local/bin:$PATH" uv run python3 -c "
from fontTools.ttLib import TTFont
f = TTFont('$FONT_PATH')
for r in f['name'].names:
    if r.nameID == 6:
        print(r.toUnicode())
        break
f.close()
" 2>/dev/null || echo "MemeFont"
)

FONT_SIZE=24
DYNAMIC_DIR="$HOME/Library/Application Support/iTerm2/DynamicProfiles"
mkdir -p "$DYNAMIC_DIR"

cat > "$DYNAMIC_DIR/MemeTest.json" << PROFILE_EOF
{
    "Profiles": [{
        "Name": "MemeTest",
        "Guid": "meme-test-profile-001",
        "Normal Font": "${PS_NAME} ${FONT_SIZE}",
        "Horizontal Spacing": 1.0,
        "Vertical Spacing": 1.0,
        "Use Non-ASCII Font": false,
        "Columns": 80,
        "Rows": 25,
        "Default Bookmark": "Yes",
        "Custom Command": "Yes",
        "Command": "/tmp/meme-display.sh",
        "Session Close": 0,
        "Foreground Color": {
            "Red Component": 0.9,
            "Green Component": 0.9,
            "Blue Component": 0.9,
            "Alpha Component": 1.0,
            "Color Space": "sRGB"
        },
        "Background Color": {
            "Red Component": 0.12,
            "Green Component": 0.12,
            "Blue Component": 0.14,
            "Alpha Component": 1.0,
            "Color Space": "sRGB"
        }
    }]
}
PROFILE_EOF
echo "  Profile: ${PS_NAME} ${FONT_SIZE}pt"

# Suppress first-run dialogs
defaults write com.googlecode.iterm2.meme NoSyncDoNotWarnBeforeMultilinePaste -bool true
defaults write com.googlecode.iterm2.meme NoSyncDoNotWarnBeforeMultilinePaste_selection -int 0
defaults write com.googlecode.iterm2.meme NoSyncNeverRemindPrefsChangesLostForFile -bool true
defaults write com.googlecode.iterm2.meme NoSyncNeverRemindPrefsChangesLostForFile_selection -int 0
defaults write com.googlecode.iterm2.meme SUEnableAutomaticChecks -bool false
defaults write com.googlecode.iterm2.meme PromptOnQuit -bool false
defaults write com.googlecode.iterm2.meme OnlyWhenMoreTabs -bool false
defaults write com.googlecode.iterm2.meme NoSyncTipsDisabled -bool true
defaults write com.googlecode.iterm2.meme NoSyncPermissionToShowTip -bool false
defaults write com.googlecode.iterm2.meme HaveShownAutoLaunchDeprecationWarning -bool true
defaults write com.googlecode.iterm2.meme "Default Bookmark Guid" -string "meme-test-profile-001"

# --------------------------------------------------------------------------- #
# 5. Launch MemeTerminal                                                       #
# --------------------------------------------------------------------------- #
echo "[5/7] Launching MemeTerminal..."

killall iTerm2 2>/dev/null || true
sleep 2
rm -rf ~/Library/Saved\ Application\ State/com.googlecode.iterm2.meme.savedState 2>/dev/null || true

open /Applications/MemeTerminal.app
sleep 5

# Dismiss nightly build warning dialog (Return key)
osascript -e "tell application \"System Events\" to tell process \"iTerm2\" to keystroke return" 2>/dev/null || true
sleep 3

# --------------------------------------------------------------------------- #
# 6. Dismiss any banners and run display script                                #
# --------------------------------------------------------------------------- #
echo "[6/7] Running display script..."

# Dismiss "session restored" banner if present
osascript -e "tell application \"System Events\" to tell process \"iTerm2\" to keystroke \" \"" 2>/dev/null || true
sleep 1

# Type the display script path (using System Events keystrokes)
osascript -e "
tell application \"System Events\"
    tell process \"iTerm2\"
        set frontmost to true
        delay 0.5
        keystroke \"/tmp/meme-display.sh\"
        delay 0.3
        keystroke return
    end tell
end tell
" 2>/dev/null || true

sleep 4

# --------------------------------------------------------------------------- #
# 7. Take screenshots                                                         #
# --------------------------------------------------------------------------- #
echo "[7/7] Capturing screenshots..."

screencapture -x "$OUTPUT_DIR/memeterminal_fullscreen.png" 2>/dev/null || true

# Quit MemeTerminal
killall iTerm2 2>/dev/null || true

# Check what we got
SCREENSHOTS=$(ls "$OUTPUT_DIR"/memeterminal_*.png 2>/dev/null | wc -l | tr -d ' ')
if [ "$SCREENSHOTS" -gt 0 ]; then
    echo ""
    echo "=== Screenshots captured ==="
    ls -la "$OUTPUT_DIR"/memeterminal_*.png
    echo ""
    echo "RESULT: PASS — $SCREENSHOTS screenshot(s) saved"
else
    echo ""
    echo "RESULT: FAIL — no screenshots captured"
    echo "NOTE: Screen recording permission for com.apple.sshd-session must be"
    echo "      granted manually on first run (click Allow on the dialog)."
    exit 1
fi
