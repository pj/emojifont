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

# Build the test font in the VM from the freshly synced source.
# Always rebuilds: a cached /tmp/TestMemeFont.ttf from an earlier run would
# silently mask source changes and make the tests report on a stale font.
build_test_font() {
    local ip=$1
    ssh_run "$ip" "
        export PATH=\"\$HOME/.local/bin:\$PATH\"
        cd ~/Projects/emojifont

        if [ -f font_build/MonacoNerdFontMono-Regular.ttf ] && [ -d font_build/memes ]; then
            # Build mappings from available meme images, starting at U+F900
            MAPPINGS=''
            CP=63744  # 0xF900
            for img in font_build/memes/*; do
                HEX=\$(printf '%04X' \$CP)
                if [ -n \"\$MAPPINGS\" ]; then MAPPINGS=\"\$MAPPINGS,\"; fi
                MAPPINGS=\"\${MAPPINGS}U+\${HEX}:\${img}\"
                CP=\$((CP + 1))
            done

            rm -f /tmp/TestMemeFont.ttf
            uv run emojifont font_build/MonacoNerdFontMono-Regular.ttf /tmp/TestMemeFont.ttf \\
                --mappings \"\$MAPPINGS\" --font-name 'TestMemeFont' 2>&1
        else
            echo 'SKIP: font_build/MonacoNerdFontMono-Regular.ttf or font_build/memes/ not found'
            exit 2
        fi
    "
}

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  --keep              Keep VM running after tests (for debugging)"
    echo "  --unit-only         Run only Python unit tests (no CoreText rendering)"
    echo "  --render-only       Run only CoreText rendering tests"
    echo "  --screenshot        Launch MemeTerminal in VM, render memes, and screenshot"
    echo "  --screenshot-only   Only run the MemeTerminal screenshot test"
    echo "  --codepoints CP    Comma-separated hex codepoints (default: F900,F901)"
    echo ""
}

run_tests() {
    local keep_vm=false
    local run_unit=true
    local run_render=true
    local run_screenshot=false
    local codepoints="F900,F901"
    local font_built=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --keep)             keep_vm=true;                   shift ;;
            --unit-only)        run_render=false;                shift ;;
            --render-only)      run_unit=false;                  shift ;;
            --screenshot)       run_screenshot=true;             shift ;;
            --screenshot-only)  run_screenshot=true; run_unit=false; run_render=false; shift ;;
            --codepoints)       codepoints="$2";                shift 2 ;;
            --help|-h)          usage; exit 0 ;;
            *)
                log_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    check_tart
    check_vm
    check_sshpass

    if [ "$keep_vm" = false ]; then
        trap cleanup EXIT
    fi

    # ------------------------------------------------------------------ #
    # Boot VM                                                              #
    # ------------------------------------------------------------------ #
    if is_vm_running; then
        log_info "VM already running"
    else
        if [ "$run_screenshot" = true ]; then
            log_info "Starting VM with display (screenshot mode)..."
            tart run "$VM_NAME" &
        else
            log_info "Starting VM headlessly..."
            tart run "$VM_NAME" --no-graphics &
        fi
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

    # ------------------------------------------------------------------ #
    # Sync source                                                          #
    # ------------------------------------------------------------------ #
    log_info "Syncing project to VM..."
    ssh_run "$ip" "mkdir -p ~/Projects/emojifont"
    rsync_to_vm "$ip" "$PROJECT_DIR/" "~/Projects/emojifont/"

    local exit_code=0

    # ------------------------------------------------------------------ #
    # Python unit tests                                                    #
    # ------------------------------------------------------------------ #
    if [ "$run_unit" = true ]; then
        log_info "Setting up Python environment..."
        ssh_run "$ip" "
            export PATH=\"\$HOME/.local/bin:\$PATH\"
            cd ~/Projects/emojifont
            uv sync 2>&1
            uv pip install pytest 2>&1
        " || { log_error "Python setup failed"; exit 1; }

        log_info "Running Python unit tests..."
        if ssh_run "$ip" "
            export PATH=\"\$HOME/.local/bin:\$PATH\"
            cd ~/Projects/emojifont
            uv run python -m pytest tests/ -v 2>&1
        "; then
            log_info "Python unit tests passed."
        else
            log_error "Python unit tests failed."
            exit_code=1
        fi
    fi

    # ------------------------------------------------------------------ #
    # CoreText rendering tests                                             #
    # ------------------------------------------------------------------ #
    if [ "$run_render" = true ]; then
        log_info "Building test font..."
        build_test_font "$ip"
        local build_exit=$?
        font_built=true

        if [ $build_exit -eq 2 ]; then
            log_warn "Skipping render tests — base font or memes not synced"
        elif [ $build_exit -ne 0 ]; then
            log_error "Font build failed"
            exit_code=1
        else
            # Parse codepoints into space-separated args
            local cp_args=""
            IFS=',' read -ra CPS <<< "$codepoints"
            for cp in "${CPS[@]}"; do
                cp_args="$cp_args 0x$cp"
            done

            log_info "Running CoreText render check..."
            # Upload the render-check script
            rsync_to_vm "$ip" "$PROJECT_DIR/vm/scripts/render-check.swift" "/tmp/render-check.swift"

            if ssh_run "$ip" "swift /tmp/render-check.swift /tmp/TestMemeFont.ttf $cp_args 2>&1"; then
                log_info "CoreText render check passed."
            else
                log_error "CoreText render check failed."
                exit_code=1
            fi
        fi
    fi

    # ------------------------------------------------------------------ #
    # MemeTerminal screenshot test                                         #
    # ------------------------------------------------------------------ #
    if [ "$run_screenshot" = true ] && [ "$font_built" = false ]; then
        log_info "Building test font for screenshot..."
        build_test_font "$ip" \
            || { log_warn "Font build failed — skipping screenshot"; run_screenshot=false; }
    fi

    if [ "$run_screenshot" = true ]; then
        log_info "Running MemeTerminal screenshot test..."

        # Upload the screenshot script
        sshpass -p "$SSH_PASS" scp $SSH_OPTS \
            "$PROJECT_DIR/vm/scripts/terminal-screenshot.sh" \
            "${SSH_USER}@${ip}:/tmp/terminal-screenshot.sh"

        # Parse codepoints for the script
        local cp_script_args=""
        IFS=',' read -ra CPS <<< "$codepoints"
        for cp in "${CPS[@]}"; do
            cp_script_args="$cp_script_args $cp"
        done

        if ssh_run "$ip" "chmod +x /tmp/terminal-screenshot.sh && /tmp/terminal-screenshot.sh /tmp/TestMemeFont.ttf /tmp/screenshots $cp_script_args 2>&1"; then
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
