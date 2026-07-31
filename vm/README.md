# Emojifont VM Testing Infrastructure

Integration testing for emojifont using [Tart](https://tart.run/) (macOS-on-Apple-Silicon VM runner built on Virtualization.framework).

The VM provides:
- A real macOS environment with CoreText for SBIX rendering verification
- Python unit tests running in an isolated environment
- CoreText render checks confirming glyphs are visible and properly aligned at multiple sizes

---

## Prerequisites

```bash
brew install cirruslabs/cli/tart         # VM runner
brew install packer                      # Image builder (one-time VM build only)
brew install hudochenkov/sshpass/sshpass  # Non-interactive SSH
```

---

## Quick Start

### 1. Build the VM image (one-time, ~20-30 min)

```bash
cd vm/packer
packer init emojifont-test.pkr.hcl
packer build emojifont-test.pkr.hcl
```

This creates a local VM named `emojifont-test` with:
- macOS Sequoia + Xcode (Swift/CoreText)
- uv for Python package management
- Sleep and Spotlight disabled for performance

### 2. Run the tests

```bash
# All tests (Python unit + CoreText rendering)
./vm/run-tests.sh

# Python unit tests only
./vm/run-tests.sh --unit-only

# CoreText rendering tests only
./vm/run-tests.sh --render-only

# Custom codepoints
./vm/run-tests.sh --codepoints "F900,F901,F902"

# Keep the VM alive after tests for debugging
./vm/run-tests.sh --keep
```

`run-tests.sh` sequence:
1. Starts the VM headlessly (`tart run --no-graphics`)
2. rsyncs source to the VM (excludes `.build`, `.git`, `.venv`)
3. Installs Python deps via uv
4. Runs `pytest` for unit tests
5. Builds a test font with `emojifont`
6. Runs `render-check.swift` against the font at 16/24/32/48/64/96pt
7. Stops the VM unless `--keep`

---

## Running locally (no VM)

The render-check script works directly on macOS:

```bash
# Run CoreText rendering check against any font
swift vm/scripts/render-check.swift font_build/MemeFont.ttf 0xF900 0xF901

# Run Python unit tests
uv run python -m pytest tests/ -v
```

---

## Manual VM Usage

```bash
tart list
tart run emojifont-test                       # with GUI
tart run emojifont-test --no-graphics &       # headless
tart ip emojifont-test                        # get IP
sshpass -p admin ssh admin@$(tart ip emojifont-test)
tart stop emojifont-test
```

---

## Directory Structure

```
vm/
├── README.md
├── run-tests.sh                  # Main test runner
├── scripts/
│   └── render-check.swift        # CoreText SBIX rendering verification
└── packer/
    ├── emojifont-test.pkr.hcl    # Packer template
    └── scripts/
        └── setup.sh              # VM provisioning
```

---

## Troubleshooting

**SSH timeout** — VM takes 60-90s to boot. `run-tests.sh` waits up to 90s. If still failing, try `tart run emojifont-test` with GUI to confirm the VM is healthy.

**Render check empty glyphs** — If glyphs render as invisible, the font's SBIX table may not have the right strike sizes, or the cmap may not map the codepoints correctly. Run the Python unit tests first to verify font structure.

**Rebuild the image**:
```bash
tart delete emojifont-test
cd vm/packer && packer build emojifont-test.pkr.hcl
```
