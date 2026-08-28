#!/usr/bin/env bash
# Fetch the shared Drive folder "Data_final" into data/plots/.
#
#     scripts/fetch_plot_data.sh              # everything not already present
#     scripts/fetch_plot_data.sh --list       # what is here and what is missing
#     scripts/fetch_plot_data.sh --only 02_   # just the novelty-filtered pair
#
# Seven files, 750 MiB: the five plotting inputs described in
# docs/analysis/PLOTTING.md, plus the two 05_ merges src/R/plotting/main.R
# writes from them. 05_hprc_multisample.tsv is 559 MiB of that total on its
# own, which is why --only exists and why a resumed download is the default.
#
# data/plots/ sits inside the directory docker-compose bind-mounts at /data, so
# a file landed here is visible to the backend container as /data/plots with no
# rebuild and no restart. It is gitignored: derived pipeline output, not source.
#
# No API token and no gdown. The folder is link-shared, and Drive serves these
# directly from drive.usercontent.google.com given confirm=t. The failure worth
# designing around is that when a file is NOT public that same URL returns an
# HTML sign-in page with a 200 and curl exits 0 -- so every download is checked
# against the pinned byte count below instead of being trusted because it
# finished.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

# Same environment variable main.R honours, so pointing the two at one
# directory is a single export rather than two flags that can disagree.
DEST="${NOVELTRS_PLOT_DATA:-${REPO}/data/plots}"

# Folder: https://drive.google.com/drive/folders/1rJwDrMn_R8tMairIDpdd-mwgHmSVtf2B
#
# id, exact size in bytes, filename. The sizes are the pinned integrity check --
# these files carry no published checksum, and a size is enough to catch the two
# failures that actually happen: a sign-in page served instead of the data, and
# a connection dropped mid-transfer.
#
# "novelyFilter" in the two trio names is upstream's typo, not one of ours.
# PLOTTING.md documents that spelling and main.R opens the file by it.
FILES=$(cat <<'EOF'
1z4yJX4oW6kXjWi3G90mw43q6LzZq6fjl 2854180   02_HG002_03_04_multisample.trf.novelyFilter.tsv
18txeCtwThaC-GYkmO-_mWtlsWutC1CMU 57804897  02_hprc_multisample.trf.noveltyFiltered.tsv
1vwaT6DgipZcS8Z9ipRUyrsCm2n0yTENv 51809655  03_HPRC_SV.survivor.ins.trf.in_catalog.tsv
1bm1k2ky76kM8f_gkz9yksK7-0YHRYknx 11325476  04_HG002_03_04_multisample.trf.novelyFilter.tsv.processed.tsv
1JqIaDJIgDyZh5XiI3L7LUUVxN0xR4dC2 50344605  04_hprc_multisample.trf.noveltyFiltered.tsv.processed.tsv
1ppH3vSswUobjRUMFrTC-4MPwbmW_63L5 26400278  05_HG002_03_04_multisample.tsv
10Byv-tfCglKLdArRO9sW8dqmd-rwrh0W 586316881 05_hprc_multisample.tsv
EOF
)

# The web layer wants 02_hprc under a different name. Same bytes -- verified
# head, tail and length against the DNAnexus copy the manifests were built from
# (file-JB8Xg900pzXPjXvpYXg29fYB), so this folder is a token-free route to the
# real HPRC callset for anyone without a DX_API_TOKEN.
WEB_SOURCE="02_hprc_multisample.trf.noveltyFiltered.tsv"
WEB_TARGET="${REPO}/data/web/hprc_multisample.trf.noveltyFiltered.tsv"

ONLY=""
LIST_ONLY=0
LINK_WEB=1
FORCE=0

say() { echo "plot-data: $*" >&2; }

usage() {
    # The header block above, minus the shebang, up to the first line that is
    # not a comment -- so editing that prose cannot desynchronise --help from it.
    awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' \
        "${BASH_SOURCE[0]:-$0}" >&2
    cat >&2 <<'EOF'

Options:
  --only PATTERN   fetch only files whose name contains PATTERN
  --dest DIR       write somewhere other than data/plots (or $NOVELTRS_PLOT_DATA)
  --list           report what is present, missing or the wrong size; download nothing
  --force          re-download even files that are already the right size
  --no-web-link    skip linking 02_hprc into data/web/ for the web backend
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --only)        ONLY="${2:-}"; shift 2 ;;
        --dest)        DEST="${2:-}"; shift 2 ;;
        --list)        LIST_ONLY=1; shift ;;
        --force)       FORCE=1; shift ;;
        --no-web-link) LINK_WEB=0; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             say "unknown option: $1"; usage; exit 2 ;;
    esac
done

# stat is one of the few places BSD and GNU never converged.
filesize() {
    stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo 0
}

human() {
    awk -v b="$1" 'BEGIN {
        split("B KiB MiB GiB", u, " ")
        i = 1
        while (b >= 1024 && i < 4) { b /= 1024; i++ }
        printf (i == 1 ? "%d %s" : "%.1f %s"), b, u[i]
    }'
}

url_for() {
    echo "https://drive.usercontent.google.com/download?id=$1&export=download&confirm=t"
}

mkdir -p "$DEST"

# --list, and the accounting the summary at the end reports.
selected=0
present=0
missing=0
wrong=0
fetched=0
bytes_wanted=0

while read -r id want name; do
    [ -n "$id" ] || continue
    case "$name" in
        *"$ONLY"*) ;;
        *) continue ;;
    esac
    selected=$((selected + 1))
    target="${DEST}/${name}"

    if [ -f "$target" ]; then
        have="$(filesize "$target")"
        if [ "$have" = "$want" ]; then
            present=$((present + 1))
            [ "$LIST_ONLY" = 1 ] && printf '  ok       %-62s %s\n' "$name" "$(human "$want")"
            continue
        fi
        wrong=$((wrong + 1))
        [ "$LIST_ONLY" = 1 ] &&
            printf '  WRONG    %-62s %s, expected %s\n' "$name" "$(human "$have")" "$(human "$want")"
    else
        missing=$((missing + 1))
        [ "$LIST_ONLY" = 1 ] && printf '  missing  %-62s %s\n' "$name" "$(human "$want")"
    fi
    bytes_wanted=$((bytes_wanted + want))
done <<< "$FILES"

if [ "$selected" = 0 ]; then
    say "no file matches --only '${ONLY}'"
    exit 1
fi

if [ "$LIST_ONLY" = 1 ]; then
    say "${DEST}"
    say "$present of $selected present; $((missing + wrong)) to fetch ($(human "$bytes_wanted"))"
    exit 0
fi

# Download to <name>.part and move it into place only once the size is right, so
# an interrupted run never leaves a truncated table looking like a finished one.
# A .part left by a previous run is resumed rather than restarted, which for the
# 559 MiB file is the difference between a retry and a re-download.
while read -r id want name; do
    [ -n "$id" ] || continue
    case "$name" in
        *"$ONLY"*) ;;
        *) continue ;;
    esac

    target="${DEST}/${name}"
    part="${target}.part"

    if [ -f "$target" ] && [ "$FORCE" = 0 ] && [ "$(filesize "$target")" = "$want" ]; then
        say "have ${name}"
        continue
    fi

    # A .part at or past the full size is a corrupt leftover, not a resume point:
    # curl would answer a range request past the end with 416 and stop.
    if [ -f "$part" ] && [ "$(filesize "$part")" -ge "$want" ]; then
        rm -f "$part"
    fi

    say "fetching ${name} ($(human "$want"))"
    if ! curl --fail --location --retry 3 --retry-delay 2 \
              --continue-at - --output "$part" "$(url_for "$id")"; then
        # curl -C - on a fresh file is fine; the retry is for a stale byte range
        # the server rejects outright, which resuming cannot recover from.
        say "resume failed, restarting ${name}"
        rm -f "$part"
        curl --fail --location --retry 3 --retry-delay 2 \
             --output "$part" "$(url_for "$id")"
    fi

    got="$(filesize "$part")"
    if [ "$got" != "$want" ]; then
        say "SIZE MISMATCH for ${name}: got $(human "$got"), expected $(human "$want")"
        # The characteristic shape of a Drive permission failure: a small HTML
        # page delivered with a 200. Worth naming, because "size mismatch" on
        # its own sends people looking for a network problem.
        if [ "$got" -lt 100000 ] && head -c 512 "$part" | grep -qi "<html\|<!doctype"; then
            say "  the server returned an HTML page, not a TSV -- the file is"
            say "  probably no longer shared publicly. Open it in a browser:"
            say "  https://drive.google.com/file/d/${id}/view"
        fi
        say "  left the partial download at ${part}"
        exit 1
    fi

    mv -f "$part" "$target"
    fetched=$((fetched + 1))
    say "  -> ${target}"
done <<< "$FILES"

# The web backend reads this callset under its own name. A hard link keeps one
# copy of 55 MiB on disk; a copy is the fallback for filesystems that will not
# link across the two directories.
if [ "$LINK_WEB" = 1 ] && [ -f "${DEST}/${WEB_SOURCE}" ] && [ ! -f "$WEB_TARGET" ]; then
    mkdir -p "$(dirname "$WEB_TARGET")"
    if ln "${DEST}/${WEB_SOURCE}" "$WEB_TARGET" 2>/dev/null; then
        say "linked ${WEB_SOURCE} -> data/web/$(basename "$WEB_TARGET")"
    else
        cp "${DEST}/${WEB_SOURCE}" "$WEB_TARGET"
        say "copied ${WEB_SOURCE} -> data/web/$(basename "$WEB_TARGET")"
    fi
    say "  build the web tables with: just strchive-data && just hprc-data"
fi

say "done: ${fetched} fetched, ${present} already present, in ${DEST}"
