#!/usr/bin/env bash
# Run a program ON THE WORKER so that it survives the ssh session that started
# it, and so its results reach the project as soon as they exist.
#
#     scripts/dx-worker-run.sh --destination project-xxxx:/Results/you/run/ -- \
#         python -m evo.embeddings calls.vcf hg38.fa "$OUT"
#
# This runs on the worker, not on your laptop. It is meant to be the command
# handed to scripts/dx-instance.sh (or a dx-batch-*.sh front-end), which clones
# this repo onto the worker, so the path resolves there.
#
# WHY IT EXISTS
# -------------
# On 2026-08-27 a four-shard Evo 2 run billed ~12.3 GPU-hours and produced
# nothing. Nothing was wrong with the model, the environment or the throughput
# -- windows came in at 6.3-8.1 s, exactly as profiled. What happened is that
# all four remote processes died within TEN SECONDS of each other, 44 minutes
# into 73 minutes of work: one dropped network connection on the laptop, four
# dead runs. The boxes then sat at `CPU: 1%` for two hours until
# max_session_length expired, billing the whole time.
#
# Two separate faults, and this script closes both:
#
#   1. **The work died with the connection.** dx-instance.sh runs the command in
#      the FOREGROUND of `dx ssh`; when the session's pty closes the command
#      gets SIGHUP. So here the real program is started under `setsid nohup`
#      with stdin from /dev/null -- it has no controlling terminal to lose, and
#      a dropped ssh no longer reaches it.
#
#   2. **A finished run did not stop its box.** When the work died the machine
#      sat at `CPU: 1%` for two hours, billing, because only max_session_length
#      could end it. So the payload terminates its OWN job as its last act --
#      on success and on failure alike. An error stops the work and releases the
#      machine; it does not leave it idling at $1-ish an hour until the clock
#      runs out.
#
#   3. **Results only left the worker at the very end.** dx-instance.sh uploads
#      after the command returns, so an interruption at 99% loses everything --
#      and it did: four complete reference-allele halves existed on disk and
#      died with the boxes. So the payload uploads to the PROJECT itself, as
#      soon as each file is written, and does it even when the program fails.
#      Results then no longer depend on any local process surviving.
#
# The foreground half mirrors the log so a launcher that IS still attached sees
# progress as before, and exits with the program's status. If the connection
# drops, only that mirror dies; the program keeps running and still uploads.
#
# After a drop, collect with:
#     uv run dx download -r <destination>
set -uo pipefail

DEST=""
POLL="${POLL:-5}"
COMMAND=()

log() { echo "[worker] $*" >&2; }
die() { echo "[worker] FATAL: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        -d|--destination) DEST="${2:?}"; shift 2 ;;
        -o|--out)         OUT="${2:?}"; shift 2 ;;
        --)               shift; COMMAND=("$@"); break ;;
        -h|--help)
            awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' \
                "${BASH_SOURCE[0]:-$0}"; exit 0 ;;
        -*)               die "unknown option $1" ;;
        *)                COMMAND=("$@"); break ;;
    esac
done

[ ${#COMMAND[@]} -gt 0 ] || die "no command; put it after '--'"
OUT="${OUT:-${OUT:-/home/dnanexus/out}}"
[ -n "$OUT" ] || die "\$OUT is not set and --out was not given"
mkdir -p "$OUT" || die "cannot create $OUT"

LOG="$OUT/run.log"
DONE="$OUT/.exit-status"
PAYLOAD="$OUT/.payload.sh"
rm -f "$DONE"

# The payload is written to a FILE rather than passed as a -c string: the
# command has already crossed two shells to get here (your shell, then the login
# bash that dx ssh starts), and %q is the only way to stop a third crossing from
# re-splitting an argument that contains a space.
{
    echo '#!/usr/bin/env bash'
    echo 'set -uo pipefail'
    printf 'cd %q || exit 1\n' "$PWD"
    printf 'export OUT=%q\n' "$OUT"
    echo
    printf '%q ' "${COMMAND[@]}"; echo
    echo 'rc=$?'
    echo 'echo "[worker] program exited $rc" >&2'
    if [ -n "$DEST" ]; then
        cat <<'UPLOAD'
# Upload whatever exists, INCLUDING on failure: a shard that got through its
# reference half is worth more than nothing, which is what waiting for a clean
# exit produced last time. --wait so the upload is durable before we say it is.
shopt -s nullglob
for f in "$OUT"/*; do
    case "$f" in *.payload.sh|*.exit-status) continue ;; esac
    [ -f "$f" ] || continue
    echo "[worker] uploading $(basename "$f") ($(du -h "$f" | cut -f1))" >&2
    dx upload "$f" --destination "$DX_DEST" --wait --brief >/dev/null \
        || echo "[worker] WARNING: upload failed for $f" >&2
done
UPLOAD
    fi
    echo 'echo "$rc" > "$OUT/.exit-status"'
    cat <<'STOP'
# Stop the machine. This is the last thing that runs, and it runs whether the
# program succeeded or raised: an error must release the box, not leave it
# idling until max_session_length. DX_JOB_ID is set in every job environment.
if [ -n "${DX_JOB_ID:-}" ]; then
    echo "[worker] work finished (status $rc) -- terminating $DX_JOB_ID" >&2
    dx terminate "$DX_JOB_ID" >/dev/null 2>&1 \
        || echo "[worker] WARNING: could not terminate $DX_JOB_ID; it bills until --time" >&2
else
    echo "[worker] WARNING: DX_JOB_ID unset; cannot self-terminate" >&2
fi
STOP
} > "$PAYLOAD"
chmod +x "$PAYLOAD"

export DX_DEST="$DEST"

# `bash -l`: the login profile is what puts the job's dx credentials in the
# environment. A non-login shell here means `dx upload` fails with "not logged
# in" at the very end, having done all the work.
#
# setsid + nohup + </dev/null is the actual fix -- no controlling terminal, so
# the SIGHUP from a closing ssh pty never arrives.
# `setsid` (Ubuntu worker) removes the controlling terminal entirely; `nohup`
# alone still blocks the SIGHUP that a closing ssh pty delivers, which is the
# signal that actually killed the last run. Falling back rather than requiring
# setsid keeps this runnable on a laptop, where it is tested.
if command -v setsid >/dev/null 2>&1; then
    setsid nohup bash -l "$PAYLOAD" </dev/null >"$LOG" 2>&1 &
else
    nohup bash -l "$PAYLOAD" </dev/null >"$LOG" 2>&1 &
fi
child=$!
disown "$child" 2>/dev/null || true
log "started PID $child detached; log $LOG"
[ -n "$DEST" ] && log "results upload to $DEST as they are written"
log "an interrupted connection no longer stops this run"

# Mirror the log for whoever is still attached. This half is expendable.
tail -f "$LOG" 2>/dev/null &
mirror=$!
trap 'kill "$mirror" 2>/dev/null' EXIT

while [ ! -f "$DONE" ]; do
    kill -0 "$child" 2>/dev/null || { sleep 2; break; }
    sleep "$POLL"
done
sleep 1
kill "$mirror" 2>/dev/null

rc="$(cat "$DONE" 2>/dev/null || echo 1)"
log "finished with status $rc"
exit "$rc"
