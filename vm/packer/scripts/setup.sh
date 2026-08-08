#!/bin/bash
set -euo pipefail

echo "=== Emojifont VM Setup ==="

eval "$(/opt/homebrew/bin/brew shellenv)"

# --------------------------------------------------------------------------- #
# Xcode toolchain (pre-installed in the base image)                            #
#                                                                              #
# Needed for terminal-screenshot.sh's font registration step                  #
# (CTFontManagerRegisterFontsForURL, called via a small Swift program) —      #
# the VM has no other dependency on Xcode/Swift/Python. Everything else       #
# (building the test font, reading its cmap/PostScript name) runs on the      #
# host before the VM is even booted; see run-tests.sh.                        #
# --------------------------------------------------------------------------- #
echo "Verifying Xcode toolchain..."
sudo xcodebuild -license accept 2>/dev/null || true
swift --version

# --------------------------------------------------------------------------- #
# Performance tweaks                                                           #
# --------------------------------------------------------------------------- #
sudo mdutil -a -i off 2>/dev/null || true
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
defaults write com.apple.screensaver idleTime 0 2>/dev/null || true

echo ""
echo "=== Setup Complete ==="
echo "  Swift: $(swift --version 2>&1 | head -1)"
