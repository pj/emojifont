#!/bin/bash
set -euo pipefail

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #
VM_NAME="emojifont-test"
SSH_USER="admin"
SSH_PASS="admin"
SSH_TIMEOUT=90
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --------------------------------------------------------------------------- #
# Prerequisites                                                                #
# --------------------------------------------------------------------------- #

check_tart() {
    if ! command -v tart &>/dev/null; then
        log_error "Tart is not installed.  Install with: brew install cirruslabs/cli/tart"
        exit 1
    fi
}

check_vm() {
    if ! tart list | grep -q "^local.*${VM_NAME}"; then
        log_error "VM '${VM_NAME}' not found."
        log_info  "Build it first with: cd vm/packer && packer init emojifont-test.pkr.hcl && packer build emojifont-test.pkr.hcl"
        exit 1
    fi
}

check_sshpass() {
    if ! command -v sshpass &>/dev/null; then
        log_error "sshpass is not installed.  Install with: brew install hudochenkov/sshpass/sshpass"
        exit 1
    fi
}

# --------------------------------------------------------------------------- #
# VM control                                                                   #
# --------------------------------------------------------------------------- #

is_vm_running() {
    tart list | grep "^local.*${VM_NAME}" | grep -q "running"
}

get_vm_ip() {
    tart ip "$VM_NAME" 2>/dev/null || echo ""
}

wait_for_ssh() {
    local ip=$1
    local timeout=$SSH_TIMEOUT
    local elapsed=0

    log_info "Waiting for SSH on $ip..."
    while ! nc -z "$ip" 22 2>/dev/null; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [ $elapsed -ge $timeout ]; then
            log_error "SSH timeout after ${timeout}s"
            return 1
        fi
    done
    log_info "SSH available"
    sleep 2
}

cleanup() {
    log_info "Stopping VM..."
    tart stop "$VM_NAME" 2>/dev/null || true
}

# --------------------------------------------------------------------------- #
# SSH helpers                                                                  #
# --------------------------------------------------------------------------- #

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -o IdentitiesOnly=yes -o PubkeyAuthentication=no"

ssh_run() {
    local ip=$1
    shift
    sshpass -p "$SSH_PASS" ssh $SSH_OPTS "${SSH_USER}@${ip}" "$@"
}

rsync_to_vm() {
    local ip=$1
    local src=$2
    local dst=$3
    sshpass -p "$SSH_PASS" rsync -az --delete \
        --exclude '.build' --exclude '.git' --exclude '.venv' \
        --exclude 'vm' --exclude 'snapshots' --exclude 'dist' \
        --exclude '__pycache__' --exclude '*.pyc' \
        -e "ssh $SSH_OPTS" \
        "$src" "${SSH_USER}@${ip}:${dst}"
}

# --------------------------------------------------------------------------- #
# Main test execution                                                          #
# --------------------------------------------------------------------------- #

rsync_from_vm() {
    local ip=$1
    local src=$2
    local dst=$3
    sshpass -p "$SSH_PASS" rsync -az \
        -e "ssh $SSH_OPTS" \
        "${SSH_USER}@${ip}:${src}" "$dst"
}

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Runs the MemeTerminal screenshot test: installs a fork of iTerm2 with"
    echo "SBIX support in the VM, renders the memes in a real terminal, and"
    echo "captures a screenshot."
    echo ""
    echo "Options:"
    echo "  --keep              Keep VM running after the test (for debugging)"
    echo "  --codepoints CP    Comma-separated hex codepoints (default: 100000,100001)"
    echo "  --font PATH        Use this already-built font instead of building one from"
    echo "                     font_build/memes/. If --codepoints isn't also given, every"
    echo "                     meme code point actually present in the font is used."
    echo ""
}

# Build the test font locally from font_build/memes/, mirroring what
# emojifont-web's default output does. Runs on the host, not the VM — the VM
# only needs the resulting font file, not a Python environment.
build_local_test_font() {
    local out=$1
    local base="$PROJECT_DIR/font_build/MonacoNerdFontMono-Regular.ttf"
    local memes_dir="$PROJECT_DIR/font_build/memes"

    if [ ! -f "$base" ] || [ ! -d "$memes_dir" ] || [ -z "$(ls -A "$memes_dir" 2>/dev/null)" ]; then
        return 2
    fi

    local mappings="" cp=1048576  # 0x100000
    for img in "$memes_dir"/*; do
        local hex
        hex=$(printf '%04X' "$cp")
        if [ -n "$mappings" ]; then mappings="$mappings,"; fi
        mappings="${mappings}U+${hex}:${img}"
        cp=$((cp + 1))
    done

    "$PROJECT_DIR/.venv/bin/emojifont" "$base" "$out" \
        --mappings "$mappings" --font-name "TestMemeFont"
}

# Read the meme code points (U+100000-U+1003FF, Supplementary PUA Plane 16)
# actually present in a font's cmap, as a comma-separated hex list — so
# --font can be pointed at any generated font (e.g. one built via the web
# UI) without having to know or retype its mappings by hand.
codepoints_from_font() {
    local font_path=$1
    "$PROJECT_DIR/.venv/bin/python" -c "
from fontTools.ttLib import TTFont
f = TTFont('$font_path')
cmap = f.getBestCmap()
cps = sorted(cp for cp in cmap if 0x100000 <= cp <= 0x1003FF)
print(','.join(f'{cp:04X}' for cp in cps))
f.close()
"
}

# Read a font's PostScript name (name table ID 6) — what iTerm2's Dynamic
# Profile needs to select it by name.
ps_name_from_font() {
    local font_path=$1
    "$PROJECT_DIR/.venv/bin/python" -c "
from fontTools.ttLib import TTFont
f = TTFont('$font_path')
name = 'MemeFont'
for r in f['name'].names:
    if r.nameID == 6:
        name = r.toUnicode()
        break
print(name)
f.close()
"
}

run_tests() {
    local keep_vm=false
    local codepoints=""
    local codepoints_explicit=false
    local custom_font=""

    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep)             keep_vm=true;                   shift ;;
            --codepoints)       codepoints="$2"; codepoints_explicit=true; shift 2 ;;
            --font)             custom_font="$2";               shift 2 ;;
            --help|-h)          usage; exit 0 ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # ------------------------------------------------------------------ #
    # Obtain the font, locally, before touching the VM at all              #
    # ------------------------------------------------------------------ #
    local font_path
    if [ -n "$custom_font" ]; then
        if [ ! -f "$custom_font" ]; then
            log_error "Font not found: $custom_font"
            exit 1
        fi
        font_path="$custom_font"
    else
        # mktemp with a template suffix appends its own random string rather
        # than honoring trailing characters after the X's (at least on BSD/
        # macOS mktemp), so a plain `mktemp ... .ttf` doesn't give a file
        # actually named *.ttf — use a scratch directory instead and name the
        # file within it ourselves.
        local scratch_dir
        scratch_dir=$(mktemp -d -t emojifont-test)
        font_path="$scratch_dir/TestMemeFont.ttf"
        log_info "Building test font from font_build/memes/..."
        if ! build_local_test_font "$font_path"; then
            log_error "Could not build a test font — font_build/MonacoNerdFontMono-Regular.ttf" \
                       "or font_build/memes/ not found. Pass --font to use an existing font instead."
            exit 1
        fi
    fi

    if [ "$codepoints_explicit" = false ]; then
        codepoints=$(codepoints_from_font "$font_path")
        if [ -z "$codepoints" ]; then
            log_error "No U+100000-U+1003FF code points found in $font_path"
            exit 1
        fi
    fi
    log_info "Code points: $codepoints"

    local ps_name
    ps_name=$(ps_name_from_font "$font_path")
    log_info "Font PostScript name: $ps_name"

    check_tart
    check_vm
    check_sshpass

    if [ "$keep_vm" = false ]; then
        trap cleanup EXIT
    fi

    # ------------------------------------------------------------------ #
    # Boot VM (needs a GUI session to launch MemeTerminal and screenshot)  #
    # ------------------------------------------------------------------ #
    if is_vm_running; then
        log_info "VM already running"
    else
        log_info "Starting VM with display..."
        tart run "$VM_NAME" &
        sleep 5
    fi

    local ip=""
    for i in {1..30}; do
        ip=$(get_vm_ip)
        [ -n "$ip" ] && break
        sleep 2
    done

    if [ -z "$ip" ]; then
        log_error "Could not get VM IP address"
        exit 1
    fi

    log_info "VM IP: $ip"
    wait_for_ssh "$ip"

    local exit_code=0

    # ------------------------------------------------------------------ #
    # MemeTerminal screenshot test                                         #
    # ------------------------------------------------------------------ #
    log_info "Uploading font..."
    rsync_to_vm "$ip" "$font_path" "/tmp/TestMemeFont.ttf"

    log_info "Uploading screenshot script..."
    sshpass -p "$SSH_PASS" scp $SSH_OPTS \
        "$PROJECT_DIR/vm/scripts/terminal-screenshot.sh" \
        "${SSH_USER}@${ip}:/tmp/terminal-screenshot.sh"

    # Parse codepoints into space-separated args
    local cp_script_args=""
    IFS=',' read -ra CPS <<< "$codepoints"
    for cp in "${CPS[@]}"; do
        cp_script_args="$cp_script_args $cp"
    done

    log_info "Running MemeTerminal screenshot test..."
    if ssh_run "$ip" "chmod +x /tmp/terminal-screenshot.sh && /tmp/terminal-screenshot.sh /tmp/TestMemeFont.ttf /tmp/screenshots '$ps_name' $cp_script_args 2>&1"; then
        log_info "Screenshot test passed."

        # Copy screenshots back to host
        local local_output="$PROJECT_DIR/vm/output/screenshots"
        mkdir -p "$local_output"
        rsync_from_vm "$ip" "/tmp/screenshots/" "$local_output/"
        log_info "Screenshots saved to vm/output/screenshots/"
    else
        log_error "Screenshot test failed."
        exit_code=1
    fi

    if [ -z "$custom_font" ]; then
        rm -rf "$scratch_dir"
    fi

    # ------------------------------------------------------------------ #
    # Post-run                                                             #
    # ------------------------------------------------------------------ #
    if [ "$keep_vm" = true ]; then
        log_info "VM kept running (--keep).  Connect with:"
        log_info "  sshpass -p '$SSH_PASS' ssh ${SSH_USER}@${ip}"
        log_info "  tart stop $VM_NAME  # to shut down"
        trap - EXIT
    fi

    return $exit_code
}

run_tests "$@"
