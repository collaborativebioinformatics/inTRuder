#!/usr/bin/env bash
# =============================================================================
# install_annotsv.sh — Comprehensive AnnotSV 3.5.10 installer
# =============================================================================
# Usage: bash install_annotsv.sh [--install-dir /path/to/dir]
#
# CRITICAL NOTES encoded in this script:
#   1. Paths with spaces break AnnotSV's Tcl→bedtools calls because Tcl wraps
#      space-containing paths in curly braces {} which bash cannot interpret.
#      FIX: auto-create a symlink to a space-free path when needed.
#   2. bcftools from conda pkgs/ cache (~/miniforge3/pkgs/) fails with
#      missing libhts.so.3 — always use binaries from envs/ directories.
#   3. Correct tar extraction: cd to target dir first, THEN tar -xzf archive
#      (NOT: tar -xzf archive -C target, which can mis-handle relative paths).
#   4. bedtools/bcftools must be passed explicitly via -bedtools / -bcftools
#      flags OR configured in etc/AnnotSV/configfile.
#   5. annotationsDir must also be the symlink path (no spaces).
# =============================================================================

set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[1;34m'
CYN='\033[0;36m'
BOLD='\033[1m'
RST='\033[0m'

ok()   { echo -e "${GRN}[OK]${RST}  $*"; }
err()  { echo -e "${RED}[ERROR]${RST} $*" >&2; }
warn() { echo -e "${YLW}[WARN]${RST} $*"; }
info() { echo -e "${BLU}[INFO]${RST} $*"; }
step() { echo -e "\n${BOLD}${CYN}══ $* ${RST}"; }

# ─── Defaults ─────────────────────────────────────────────────────────────────
INSTALL_DIR="$HOME/tools/AnnotSV"
ANNOTSV_VERSION="3.5.10"
ANNOTSV_REPO="https://github.com/lgmgeo/AnnotSV.git"
ANNOTSV_TAG="v${ANNOTSV_VERSION}"

ANNOTATIONS_URL="https://www.lbgi.fr/~geoffroy/Annotations/Annotations_Human_3.5.tar.gz"
EXOMISER_URL="https://data.monarchinitiative.org/exomiser/data/2406_phenotype.zip"

MINIFORGE="$HOME/miniforge3"

# ─── Argument parsing ─────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir)
            INSTALL_DIR="$2"; shift 2 ;;
        --install-dir=*)
            INSTALL_DIR="${1#*=}"; shift ;;
        -h|--help)
            grep '^# ' "$0" | head -20; exit 0 ;;
        *)
            err "Unknown argument: $1"; exit 1 ;;
    esac
done

# ─── Derived paths ────────────────────────────────────────────────────────────
SRC_DIR="${INSTALL_DIR}/src"
SHARE_DIR="${INSTALL_DIR}/share/AnnotSV"
ANNOTATIONS_DIR="${SHARE_DIR}/Annotations_Human"
EXOMISER_DIR="${SHARE_DIR}/Exomiser"
TEST_OUTPUT_DIR="${INSTALL_DIR}/test_output"
WRAPPER="${INSTALL_DIR}/run_annotsv.sh"
CONFIGFILE="${INSTALL_DIR}/etc/AnnotSV/configfile"

# ─── Symlink handling (spaces in path) ────────────────────────────────────────
EFFECTIVE_INSTALL_DIR="$INSTALL_DIR"
SYMLINK_NEEDED=false
if [[ "$INSTALL_DIR" == *" "* ]]; then
    SYMLINK_TARGET="$HOME/tools/AnnotSV"
    SYMLINK_NEEDED=true
    warn "Install path contains spaces: '$INSTALL_DIR'"
    warn "Tcl cannot handle space-containing paths. Will create symlink:"
    warn "  ${SYMLINK_TARGET} -> ${INSTALL_DIR}"
    EFFECTIVE_INSTALL_DIR="$SYMLINK_TARGET"
fi

EFFECTIVE_SHARE_DIR="${EFFECTIVE_INSTALL_DIR}/share/AnnotSV"
EFFECTIVE_ANNOTATIONS_DIR="${EFFECTIVE_SHARE_DIR}/Annotations_Human"

# ─── Summary vars (filled in as we go) ────────────────────────────────────────
ANNOTSV_BIN=""
BEDTOOLS_BIN=""
BCFTOOLS_BIN=""
TCLSH_BIN=""
CONDA_ENV_USED=""
TEST_RESULT="NOT RUN"

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 1 — Pre-flight checks"
# ══════════════════════════════════════════════════════════════════════════════

info "Install directory : $INSTALL_DIR"
info "Effective dir     : $EFFECTIVE_INSTALL_DIR"
info "AnnotSV version   : $ANNOTSV_VERSION"

# Check required base tools
for tool in git make curl wget tar; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool found: $(command -v $tool)"
    else
        err "$tool is required but not found. Please install it."
        exit 1
    fi
done

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 2 — Auto-detect tclsh"
# ══════════════════════════════════════════════════════════════════════════════

detect_tclsh() {
    local candidates=(
        "${MINIFORGE}/bin/tclsh"
        "${MINIFORGE}/envs/annotsv/bin/tclsh"
        "/usr/bin/tclsh"
        "/usr/local/bin/tclsh"
    )
    # Also check any env that has tclsh
    if [[ -d "${MINIFORGE}/envs" ]]; then
        while IFS= read -r -d '' env_tclsh; do
            candidates+=("$env_tclsh")
        done < <(find "${MINIFORGE}/envs" -name "tclsh" -type f -print0 2>/dev/null)
    fi
    for t in "${candidates[@]}"; do
        if [[ -x "$t" ]]; then
            echo "$t"; return 0
        fi
    done
    # Fallback: PATH
    if command -v tclsh &>/dev/null; then
        command -v tclsh; return 0
    fi
    return 1
}

if TCLSH_BIN=$(detect_tclsh); then
    ok "tclsh found: $TCLSH_BIN"
else
    warn "tclsh not found. AnnotSV requires Tcl. Attempting install via conda..."
    if [[ -x "${MINIFORGE}/bin/conda" ]]; then
        "${MINIFORGE}/bin/conda" install -y -c conda-forge tcl 2>&1 | tail -5
        TCLSH_BIN="${MINIFORGE}/bin/tclsh"
        ok "tclsh installed via conda base: $TCLSH_BIN"
    else
        err "Cannot install tclsh automatically. Please install Tcl manually."
        exit 1
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 3 — Auto-detect or install bedtools + bcftools"
# ══════════════════════════════════════════════════════════════════════════════

# Helper: verify a binary actually runs (catches broken pkgs/ cache binaries)
verify_binary() {
    local bin="$1"
    local test_arg="${2:---version}"
    if [[ -x "$bin" ]] && "$bin" $test_arg &>/dev/null 2>&1; then
        return 0
    fi
    return 1
}

find_tool_in_conda() {
    local toolname="$1"
    # 1. Active conda env
    if [[ -n "${CONDA_PREFIX:-}" ]]; then
        local candidate="${CONDA_PREFIX}/bin/${toolname}"
        if verify_binary "$candidate"; then
            echo "$candidate"; return 0
        fi
    fi
    # 2. Scan miniforge3/envs/ (skip pkgs/ — those can have broken lib deps)
    if [[ -d "${MINIFORGE}/envs" ]]; then
        while IFS= read -r -d '' candidate; do
            if verify_binary "$candidate"; then
                echo "$candidate"; return 0
            fi
        done < <(find "${MINIFORGE}/envs" -path "*/bin/${toolname}" -type f -print0 2>/dev/null)
    fi
    # 3. Conda base env
    local base_candidate="${MINIFORGE}/bin/${toolname}"
    if verify_binary "$base_candidate"; then
        echo "$base_candidate"; return 0
    fi
    # 4. System PATH (but NOT from pkgs/)
    local path_bin
    if path_bin=$(command -v "$toolname" 2>/dev/null); then
        if [[ "$path_bin" != *"/pkgs/"* ]] && verify_binary "$path_bin"; then
            echo "$path_bin"; return 0
        fi
    fi
    return 1
}

info "Searching for bedtools..."
if BEDTOOLS_BIN=$(find_tool_in_conda "bedtools"); then
    ok "bedtools found: $BEDTOOLS_BIN  ($(${BEDTOOLS_BIN} --version 2>&1 | head -1))"
else
    warn "bedtools not found in any conda env."
fi

info "Searching for bcftools..."
if BCFTOOLS_BIN=$(find_tool_in_conda "bcftools"); then
    ok "bcftools found: $BCFTOOLS_BIN  ($(${BCFTOOLS_BIN} --version 2>&1 | head -1))"
else
    warn "bcftools not found in any conda env."
fi

# Offer to create/update conda env if either tool is missing
if [[ -z "$BEDTOOLS_BIN" || -z "$BCFTOOLS_BIN" ]]; then
    warn "One or both tools missing. Attempting to install into conda env 'annotsv'..."
    if [[ -x "${MINIFORGE}/bin/conda" ]]; then
        CONDA_ENV_NAME="annotsv"
        CONDA_ENV_PATH="${MINIFORGE}/envs/${CONDA_ENV_NAME}"
        if [[ ! -d "$CONDA_ENV_PATH" ]]; then
            info "Creating conda env '${CONDA_ENV_NAME}'..."
            "${MINIFORGE}/bin/conda" create -y -n "${CONDA_ENV_NAME}" \
                -c conda-forge -c bioconda \
                bedtools bcftools tcl 2>&1 | tail -10
        else
            info "Conda env '${CONDA_ENV_NAME}' exists. Installing missing tools..."
            "${MINIFORGE}/bin/conda" install -y -n "${CONDA_ENV_NAME}" \
                -c conda-forge -c bioconda \
                bedtools bcftools 2>&1 | tail -10
        fi
        CONDA_ENV_USED="${CONDA_ENV_PATH}"
        BEDTOOLS_BIN="${CONDA_ENV_PATH}/bin/bedtools"
        BCFTOOLS_BIN="${CONDA_ENV_PATH}/bin/bcftools"
        ok "bedtools: $BEDTOOLS_BIN"
        ok "bcftools: $BCFTOOLS_BIN"
    else
        err "conda not found at ${MINIFORGE}/bin/conda. Cannot auto-install tools."
        err "Please install bedtools and bcftools manually and re-run."
        exit 1
    fi
fi

# Final verification
if ! verify_binary "$BEDTOOLS_BIN"; then
    err "bedtools at '$BEDTOOLS_BIN' is not functional (possible broken lib deps)."
    err "HINT: Do NOT use binaries from ~/miniforge3/pkgs/ — use envs/ directories."
    exit 1
fi
if ! verify_binary "$BCFTOOLS_BIN" "--version"; then
    err "bcftools at '$BCFTOOLS_BIN' is not functional (possible missing libhts.so.3)."
    err "HINT: Do NOT use binaries from ~/miniforge3/pkgs/ — use envs/ directories."
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 4 — Clone AnnotSV ${ANNOTSV_VERSION}"
# ══════════════════════════════════════════════════════════════════════════════

mkdir -p "$(dirname "$SRC_DIR")"

if [[ -d "${SRC_DIR}/.git" ]]; then
    ok "Source repo already exists at $SRC_DIR — skipping clone."
    info "Checking out tag ${ANNOTSV_TAG}..."
    git -C "$SRC_DIR" fetch --tags 2>&1 | tail -3
    git -C "$SRC_DIR" checkout "${ANNOTSV_TAG}" 2>&1 | tail -3
else
    info "Cloning AnnotSV ${ANNOTSV_VERSION} from ${ANNOTSV_REPO}..."
    git clone --branch "${ANNOTSV_TAG}" --depth 1 "${ANNOTSV_REPO}" "${SRC_DIR}"
    ok "Clone complete."
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 5 — Build & install (make PREFIX=<install-dir> install)"
# ══════════════════════════════════════════════════════════════════════════════

mkdir -p "$INSTALL_DIR"

ANNOTSV_BIN="${INSTALL_DIR}/bin/AnnotSV"
if [[ -x "$ANNOTSV_BIN" ]]; then
    ok "AnnotSV binary already exists at $ANNOTSV_BIN — skipping build."
else
    info "Running: make PREFIX=\"${INSTALL_DIR}\" install"
    make -C "$SRC_DIR" PREFIX="${INSTALL_DIR}" install 2>&1
    ok "make install complete."
fi

# Symlink creation if path has spaces
if [[ "$SYMLINK_NEEDED" == "true" ]]; then
    step "STEP 5b — Creating symlink (space-in-path fix)"
    mkdir -p "$(dirname "$SYMLINK_TARGET")"
    if [[ -L "$SYMLINK_TARGET" ]]; then
        warn "Symlink already exists: $SYMLINK_TARGET — updating."
        rm -f "$SYMLINK_TARGET"
    fi
    ln -s "$INSTALL_DIR" "$SYMLINK_TARGET"
    ok "Symlink created: ${SYMLINK_TARGET} -> ${INSTALL_DIR}"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 6 — Download & extract Human Annotations (Annotations_Human_3.5)"
# ══════════════════════════════════════════════════════════════════════════════

ANNOTATIONS_ARCHIVE="${SHARE_DIR}/Annotations_Human_3.5.tar.gz"

mkdir -p "$SHARE_DIR"

if [[ -d "$ANNOTATIONS_DIR" ]]; then
    ok "Annotations already extracted at $ANNOTATIONS_DIR — skipping download."
else
    if [[ ! -f "$ANNOTATIONS_ARCHIVE" ]]; then
        info "Downloading Annotations_Human_3.5.tar.gz (~3 GB, please wait)..."
        wget --progress=bar:force:noscroll \
             -O "$ANNOTATIONS_ARCHIVE" \
             "$ANNOTATIONS_URL" 2>&1 || {
            err "wget failed. Trying curl..."
            curl -L --progress-bar \
                 -o "$ANNOTATIONS_ARCHIVE" \
                 "$ANNOTATIONS_URL"
        }
        ok "Download complete."
    else
        ok "Archive already present: $ANNOTATIONS_ARCHIVE"
    fi

    info "Extracting annotations (cd to target dir, then tar -xzf)..."
    # CRITICAL: cd to target dir first, then extract
    # Do NOT use: tar -xzf archive.tar.gz -C target  (can mis-handle paths)
    cd "$SHARE_DIR"
    tar -xzf "$ANNOTATIONS_ARCHIVE"
    cd - > /dev/null
    ok "Annotations extracted to $SHARE_DIR"

    # Verify expected directory
    if [[ -d "$ANNOTATIONS_DIR" ]]; then
        ok "Annotations_Human directory confirmed."
    else
        # The archive might unpack to a differently named dir — find it
        FOUND_DIR=$(find "$SHARE_DIR" -maxdepth 1 -type d -name "Annotations*" | head -1)
        if [[ -n "$FOUND_DIR" ]]; then
            warn "Annotations dir found at: $FOUND_DIR (expected $ANNOTATIONS_DIR)"
            ANNOTATIONS_DIR="$FOUND_DIR"
            EFFECTIVE_ANNOTATIONS_DIR="${EFFECTIVE_SHARE_DIR}/$(basename $FOUND_DIR)"
        else
            err "Could not find extracted Annotations directory under $SHARE_DIR"
            exit 1
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 7 — Download & extract Exomiser 2406_phenotype"
# ══════════════════════════════════════════════════════════════════════════════

EXOMISER_ARCHIVE="${SHARE_DIR}/2406_phenotype.zip"
EXOMISER_EXTRACTED="${SHARE_DIR}/2406_phenotype"

mkdir -p "$EXOMISER_DIR"

if [[ -d "$EXOMISER_EXTRACTED" ]]; then
    ok "Exomiser data already extracted — skipping download."
else
    if [[ ! -f "$EXOMISER_ARCHIVE" ]]; then
        info "Downloading Exomiser 2406_phenotype.zip..."
        wget --progress=bar:force:noscroll \
             -O "$EXOMISER_ARCHIVE" \
             "$EXOMISER_URL" 2>&1 || {
            err "wget failed. Trying curl..."
            curl -L --progress-bar \
                 -o "$EXOMISER_ARCHIVE" \
                 "$EXOMISER_URL"
        }
        ok "Exomiser download complete."
    else
        ok "Exomiser archive already present: $EXOMISER_ARCHIVE"
    fi

    info "Extracting Exomiser data..."
    cd "$SHARE_DIR"
    unzip -q "$EXOMISER_ARCHIVE" || warn "unzip failed — data may be partially extracted."
    cd - > /dev/null
    ok "Exomiser data extracted to $SHARE_DIR"
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 8 — Configure AnnotSV (etc/AnnotSV/configfile)"
# ══════════════════════════════════════════════════════════════════════════════

mkdir -p "$(dirname "$CONFIGFILE")"

# Use effective (symlink-safe, space-free) paths in the config
cat > "$CONFIGFILE" <<EOF
# AnnotSV configfile — auto-generated by install_annotsv.sh
# Generated: $(date)
# IMPORTANT: All paths below use the symlink/space-free path.

bedtools     ${BEDTOOLS_BIN}
bcftools     ${BCFTOOLS_BIN}
annotationsDir  ${EFFECTIVE_ANNOTATIONS_DIR}
EOF

ok "Config written to $CONFIGFILE"

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 9 — Write run_annotsv.sh wrapper"
# ══════════════════════════════════════════════════════════════════════════════

cat > "$WRAPPER" <<WRAPPER
#!/usr/bin/env bash
# run_annotsv.sh — wrapper generated by install_annotsv.sh
# Uses symlink-safe (space-free) paths so Tcl can call bedtools/bcftools.

export ANNOTSV="${EFFECTIVE_INSTALL_DIR}"

exec "\${ANNOTSV}/bin/AnnotSV" \\
    -bedtools  "${BEDTOOLS_BIN}" \\
    -bcftools  "${BCFTOOLS_BIN}" \\
    -annotationsDir "${EFFECTIVE_ANNOTATIONS_DIR}" \\
    "\$@"
WRAPPER

chmod +x "$WRAPPER"
ok "Wrapper written: $WRAPPER"

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 10 — Update ~/.bashrc (idempotent)"
# ══════════════════════════════════════════════════════════════════════════════

BASHRC="$HOME/.bashrc"
MARKER="# >>> AnnotSV environment >>>"
MARKER_END="# <<< AnnotSV environment <<<"

if grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    warn "AnnotSV exports already present in ~/.bashrc — skipping."
else
    info "Adding AnnotSV exports to ~/.bashrc..."
    cat >> "$BASHRC" <<BASHRC_BLOCK

${MARKER}
export ANNOTSV="${EFFECTIVE_INSTALL_DIR}"
export PATH="\${ANNOTSV}/bin:\${PATH}"
export BEDTOOLS="${BEDTOOLS_BIN}"
export BCFTOOLS="${BCFTOOLS_BIN}"
${MARKER_END}
BASHRC_BLOCK
    ok "~/.bashrc updated."
fi

# ══════════════════════════════════════════════════════════════════════════════
step "STEP 11 — Run test with test_02_HG00096 (GRCh37 BED)"
# ══════════════════════════════════════════════════════════════════════════════

# Locate the test BED file
TEST_BED=$(find "${SRC_DIR}" \
    -name "*HG00096*" \( -name "*.bed" -o -name "*.BED" \) \
    2>/dev/null | head -1)

if [[ -z "$TEST_BED" ]]; then
    # Try the share/AnnotSV test dir
    TEST_BED=$(find "${INSTALL_DIR}" \
        -name "*HG00096*" \( -name "*.bed" -o -name "*.BED" \) \
        2>/dev/null | head -1)
fi

if [[ -z "$TEST_BED" ]]; then
    warn "Could not locate test_02_HG00096 BED file. Listing available test files:"
    find "${SRC_DIR}/tests" "${INSTALL_DIR}/share/AnnotSV/Tests" \
         -name "*.bed" -o -name "*.BED" 2>/dev/null | head -10 || true
    TEST_RESULT="SKIPPED — test BED not found"
else
    info "Test BED file: $TEST_BED"
    mkdir -p "$TEST_OUTPUT_DIR"

    export ANNOTSV="${EFFECTIVE_INSTALL_DIR}"
    TEST_PREFIX="${TEST_OUTPUT_DIR}/test_HG00096"

    info "Running AnnotSV annotation (GRCh37)..."
    "${EFFECTIVE_INSTALL_DIR}/bin/AnnotSV" \
        -SVinputFile  "$TEST_BED" \
        -genome       GRCh37 \
        -bedtools     "${BEDTOOLS_BIN}" \
        -bcftools     "${BCFTOOLS_BIN}" \
        -annotationsDir "${EFFECTIVE_ANNOTATIONS_DIR}" \
        -outputDir    "$TEST_OUTPUT_DIR" \
        -outputFile   "$TEST_PREFIX" \
        2>&1 | tee "${TEST_OUTPUT_DIR}/test_run.log"

    # Locate output TSV
    TEST_TSV=$(find "$TEST_OUTPUT_DIR" -name "*.tsv" 2>/dev/null | head -1)

    if [[ -z "$TEST_TSV" ]]; then
        TEST_RESULT="FAILED — no TSV output found"
        warn "$TEST_RESULT"
    else
        LINE_COUNT=$(wc -l < "$TEST_TSV")
        info "Test output: $TEST_TSV  ($LINE_COUNT lines)"
        if [[ "$LINE_COUNT" -gt 1000 ]]; then
            TEST_RESULT="PASSED ✓ ($LINE_COUNT lines > 1000)"
            ok "$TEST_RESULT"
        else
            TEST_RESULT="WARN — only $LINE_COUNT lines (expected >1000)"
            warn "$TEST_RESULT"
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
step "FINAL SUMMARY"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════════╗${RST}"
echo -e "${BOLD}║              AnnotSV ${ANNOTSV_VERSION} — Installation Summary              ║${RST}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════════╝${RST}"
echo ""
printf "  %-22s %s\n" "ANNOTSV (real):"       "${INSTALL_DIR}"
printf "  %-22s %s\n" "ANNOTSV (effective):"  "${EFFECTIVE_INSTALL_DIR}"
printf "  %-22s %s\n" "bedtools:"             "${BEDTOOLS_BIN}"
printf "  %-22s %s\n" "bcftools:"             "${BCFTOOLS_BIN}"
printf "  %-22s %s\n" "tclsh:"                "${TCLSH_BIN}"
printf "  %-22s %s\n" "Annotations dir:"      "${EFFECTIVE_ANNOTATIONS_DIR}"
printf "  %-22s %s\n" "Wrapper script:"       "${WRAPPER}"
printf "  %-22s %s\n" "configfile:"           "${CONFIGFILE}"
printf "  %-22s %s\n" "Test result:"          "${TEST_RESULT}"
if [[ -n "${CONDA_ENV_USED}" ]]; then
    printf "  %-22s %s\n" "Conda env created:" "${CONDA_ENV_USED}"
fi
echo ""
echo -e "${GRN}To use AnnotSV in a new shell:${RST}"
echo "  source ~/.bashrc"
echo "  \$ANNOTSV/bin/AnnotSV -help"
echo ""
echo -e "${GRN}Or use the wrapper (recommended — paths pre-configured):${RST}"
echo "  ${WRAPPER} -SVinputFile my.vcf -genome GRCh38"
echo ""

if [[ "$SYMLINK_NEEDED" == "true" ]]; then
    echo -e "${YLW}NOTE: Your install path has spaces. Always use the symlink path:${RST}"
    echo "  ${SYMLINK_TARGET}"
    echo "  This avoids Tcl curly-brace wrapping that breaks bedtools calls."
    echo ""
fi
