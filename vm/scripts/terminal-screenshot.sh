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
#   terminal-screenshot.sh <font-path> <output-dir> <font-ps-name> [codepoints...]
#
# <font-ps-name> is the font's PostScript name (name table ID 6) — the value
# iTerm2's Dynamic Profile needs to select it by name. This script doesn't
# derive it from the font file itself: that would need fontTools, and this
# script intentionally has no Python dependency, so the caller (run-tests.sh)
# reads it from the font on the host and passes it in.
#
# Example:
#   terminal-screenshot.sh /tmp/TestMemeFont.ttf /tmp/screenshots MemeFont F900 F901
#

FONT_PATH="${1:?Usage: terminal-screenshot.sh <font-path> <output-dir> <font-ps-name> [codepoints...]}"
OUTPUT_DIR="${2:?Usage: terminal-screenshot.sh <font-path> <output-dir> <font-ps-name> [codepoints...]}"
PS_NAME="${3:?Usage: terminal-screenshot.sh <font-path> <output-dir> <font-ps-name> [codepoints...]}"
shift 3
# Note: ("${@:-F900 F901}") would collapse the default into a single element
# "F900 F901" rather than two, so spell the fallback out.
if [ $# -gt 0 ]; then
    CODEPOINTS=("$@")
else
    CODEPOINTS=(F900 F901)
fi

RELEASE_URL="https://github.com/pj/iTerm2/releases/download/v0.0.1/MemeTerminal.zip"
APP_NAME="MemeTerminal"

mkdir -p "$OUTPUT_DIR"
# Clear previous captures so the pass check can't be satisfied by stale files
rm -f "$OUTPUT_DIR"/memeterminal_*.png

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

# Copying the file into ~/Library/Fonts is not reliably enough on its own:
# CTFontCreateWithName() (what iTerm2's Dynamic Profile "Normal Font" lookup
# uses under the hood) can silently resolve the name to Helvetica — and from
# there fall back to a system CJK glyph for code points Helvetica doesn't
# cover — until the font is explicitly registered with CoreText's font
# database. CTFontManagerRegisterFontsForURL is what actually makes the
# PostScript/family name resolvable by apps that pick fonts by name.
REGISTER_SCRIPT="/tmp/register-font.swift"
cat > "$REGISTER_SCRIPT" << 'SWIFT_EOF'
import CoreText
import Foundation

guard CommandLine.arguments.count > 1 else {
    print("Usage: register-font.swift <path>")
    exit(1)
}
let url = URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL
var error: Unmanaged<CFError>?
if CTFontManagerRegisterFontsForURL(url, .persistent, &error) {
    print("Registered: \(CommandLine.arguments[1])")
} else {
    // Already-registered is reported as an error by this API; that's fine —
    // it means a previous run already did this and the name still resolves.
    print("Register call did not report success (often means already registered): \(String(describing: error))")
}
SWIFT_EOF
swift "$REGISTER_SCRIPT" "$DEST_FONT" 2>&1 || true

# --------------------------------------------------------------------------- #
# 3. Create display script                                                     #
# --------------------------------------------------------------------------- #
echo "[3/7] Creating display scripts..."

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

# Build meme glyph sequences: MEME_CHARS is space-separated, MEME_LIST holds
# the individual glyphs so the adjacency cases can butt them up against each
# other with nothing in between.
MEME_CHARS=""
MEME_LIST=()
for cp in "${CODEPOINTS[@]}"; do
    ch=$(cp_to_utf8 "$cp")
    MEME_LIST+=("$ch")
    MEME_CHARS="${MEME_CHARS}${ch} "
done
M1="${MEME_LIST[0]}"
M2="${MEME_LIST[1]:-${MEME_LIST[0]}}"

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

# Gallery rows: explicit fixed-width chunks rather than one long line left to
# the terminal's own wrapping. At more than a couple of memes, the "inline"/
# "only"/"mixed" comparison lines below wrap mid-glyph-run and get hard to
# scan, so a real gallery kicks in once there's more to show than that.
GALLERY_COLS=20
GALLERY_LINES=()
if [ "${#MEME_LIST[@]}" -gt 2 ]; then
    for ((i = 0; i < ${#MEME_LIST[@]}; i += GALLERY_COLS)); do
        end=$((i + GALLERY_COLS - 1))
        if [ $end -ge ${#MEME_LIST[@]} ]; then end=$((${#MEME_LIST[@]} - 1)); fi
        chunk=""
        for ((j = i; j <= end; j++)); do
            chunk="${chunk}${MEME_LIST[$j]}"
        done
        label="U+${CODEPOINTS[$i]}-U+${CODEPOINTS[$end]}:"
        GALLERY_LINES+=("printf '%-16s ${chunk}\n' '${label}'")
    done
fi

DISPLAY_SCRIPT="/tmp/meme-display.sh"
{
    echo '#!/bin/bash'
    echo 'echo ""'
    echo 'echo "Terminal font rendering test"'
    echo 'echo "============================"'
    echo 'echo ""'
    echo 'echo "Regular text: Hgpy ABC 123"'
    echo "printf 'Emoji:           ${EMOJI_CHARS}\n'"
    echo 'echo ""'
    if [ "${#GALLERY_LINES[@]}" -gt 0 ]; then
        # Many memes: skip the wrap-prone inline/only/mixed lines and show a
        # clean fixed-width gallery instead.
        echo 'echo "All memes:"'
        for line in "${GALLERY_LINES[@]}"; do
            echo "$line"
        done
    else
        echo "printf 'Memes inline: Hello ${MEME_CHARS}World\n'"
        echo "printf 'Memes only:   ${MEME_CHARS}\n'"
        echo 'echo ""'
        echo "printf 'Mixed:        ${GRIN} ${MEME_CHARS}${ROCKET} text ${FIRE}\n'"
    fi
    echo 'echo ""'
    echo 'echo "============================"'
    echo 'export BASH_SILENCE_DEPRECATION_WARNING=1'
    echo 'exec bash'
} > "$DISPLAY_SCRIPT"
chmod +x "$DISPLAY_SCRIPT"
echo "  Display script: $DISPLAY_SCRIPT"

# --------------------------------------------------------------------------- #
# Adjacency script: glyphs directly abutting, no separating spaces.            #
#                                                                              #
# This is where cell-overlap bugs surface. A meme whose bitmap is wider than    #
# its advance, or whose advance doesn't match the cells the terminal reserved,  #
# looks fine when padded with spaces but clips or overlaps its neighbour when   #
# something is drawn immediately next to it. Every row starts at column 12 and  #
# a ruler sits on top, so a glyph landing off the cell grid is visible.         #
# --------------------------------------------------------------------------- #
ADJACENCY_SCRIPT="/tmp/meme-adjacency.sh"
{
    echo '#!/bin/bash'
    # Scroll the previous page off rather than `clear`: clearing scrollback
    # trips an iTerm2 permission dialog that covers the top rows of output.
    echo "printf '\\n%.0s' \$(seq 1 40)"
    echo 'echo ""'
    echo 'echo "Adjacency test - no separating spaces"'
    echo 'echo "====================================="'
    echo 'echo ""'
    echo "printf 'ruler       0123456789012345678901234567890123456789\n'"
    # Memes packed against memes — the densest case for advance-width errors
    echo "printf 'meme+meme   ${M1}${M2}${M1}${M2}\n'"
    echo "printf 'same meme   ${M1}${M1}${M1}${M1}\n'"
    # Emoji baseline: these are known-good 2-cell glyphs to compare against
    echo "printf 'emoji       ${GRIN}${ROCKET}${FIRE}${STAR}${THUMBSUP}\n'"
    # Memes against emoji — mismatched advances show up as drift along the row
    echo "printf 'meme+emoji  ${M1}${GRIN}${M2}${ROCKET}${M1}${FIRE}\n'"
    # Memes against narrow text — the asymmetric case (2 cells beside 1)
    echo "printf 'meme+text   A${M1}B${M2}C${M1}D\n'"
    echo "printf 'emoji+text  A${GRIN}B${ROCKET}C${FIRE}D\n'"
    echo "printf 'text        ABCDEFGHIJKLMNOPQRST\n'"
    echo "printf 'all mixed   a${M1}${GRIN}b${M2}${ROCKET}c\n'"
    # Explicit space runs: a meme that over-draws will eat into these
    echo "printf 'gap 1       ${M1} ${M1} ${M1} ${M1}\n'"
    echo "printf 'gap 2       ${M1}  ${M1}  ${M1}  ${M1}\n'"
    echo "printf 'gap 3       ${M1}   ${M1}   ${M1}\n'"
    # Line edges: leading glyph and a glyph with text hard against both sides
    echo "printf '${M1}text${M2}text${M1}\n'"
    echo "printf 'trailing    text${M1}\n'"
    echo 'echo "====================================="'
    # Silence bash's zsh-deprecation notice; it costs 4 rows, and the adjacency
    # page needs every row it can get to fit on screen without scrolling.
    echo 'export BASH_SILENCE_DEPRECATION_WARNING=1'
    echo 'exec bash'
} > "$ADJACENCY_SCRIPT"
chmod +x "$ADJACENCY_SCRIPT"
echo "  Adjacency script: $ADJACENCY_SCRIPT"

# --------------------------------------------------------------------------- #
# 4. Configure MemeTerminal profile                                            #
# --------------------------------------------------------------------------- #
echo "[4/7] Configuring MemeTerminal profile..."

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

# Type a script path into the terminal and run it (via System Events keystrokes)
run_in_terminal() {
    osascript -e "
tell application \"System Events\"
    tell process \"iTerm2\"
        set frontmost to true
        delay 0.5
        keystroke \"$1\"
        delay 0.3
        keystroke return
    end tell
end tell
" 2>/dev/null || true
}

run_in_terminal "$DISPLAY_SCRIPT"
sleep 4

# --------------------------------------------------------------------------- #
# 7. Take screenshots                                                         #
# --------------------------------------------------------------------------- #
echo "[7/7] Capturing screenshots..."

screencapture -x "$OUTPUT_DIR/memeterminal_fullscreen.png" 2>/dev/null || true

# Second page: the adjacency cases. Captured separately because both pages
# together exceed the rows that fit on screen at this font size.
echo "  Running adjacency script..."
run_in_terminal "$ADJACENCY_SCRIPT"
sleep 4
screencapture -x "$OUTPUT_DIR/memeterminal_adjacency.png" 2>/dev/null || true

# Quit MemeTerminal
killall iTerm2 2>/dev/null || true

# Check what we got
SCREENSHOTS=$(ls "$OUTPUT_DIR"/memeterminal_*.png 2>/dev/null | wc -l | tr -d ' ')
if [ "$SCREENSHOTS" -ge 2 ]; then
    echo ""
    echo "=== Screenshots captured ==="
    ls -la "$OUTPUT_DIR"/memeterminal_*.png
    echo ""
    echo "RESULT: PASS — $SCREENSHOTS screenshot(s) saved"
else
    echo ""
    echo "RESULT: FAIL — expected 2 screenshots (render + adjacency), got $SCREENSHOTS"
    echo "NOTE: Screen recording permission for com.apple.sshd-session must be"
    echo "      granted manually on first run (click Allow on the dialog)."
    exit 1
fi
