#!/bin/bash
set -euo pipefail

echo "=== Emojifont VM Setup ==="

eval "$(/opt/homebrew/bin/brew shellenv)"

# --------------------------------------------------------------------------- #
# Xcode toolchain (pre-installed in the base image)                            #
# --------------------------------------------------------------------------- #
echo "Verifying Xcode toolchain..."
sudo xcodebuild -license accept 2>/dev/null || true
swift --version

# --------------------------------------------------------------------------- #
# Python + uv (for running emojifont)                                          #
# --------------------------------------------------------------------------- #
echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile

# Verify
export PATH="$HOME/.local/bin:$PATH"
uv --version

# --------------------------------------------------------------------------- #
# Working directory                                                            #
# --------------------------------------------------------------------------- #
mkdir -p ~/Projects/emojifont

# --------------------------------------------------------------------------- #
# Performance tweaks                                                           #
# --------------------------------------------------------------------------- #
sudo mdutil -a -i off 2>/dev/null || true
sudo pmset -a sleep 0 displaysleep 0 disksleep 0
defaults write com.apple.screensaver idleTime 0 2>/dev/null || true

echo ""
echo "=== Setup Complete ==="
echo "  Swift: $(swift --version 2>&1 | head -1)"
echo "  uv: $(uv --version)"
echo "Drop the emojifont source into ~/Projects/emojifont and run tests."
