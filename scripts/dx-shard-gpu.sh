#!/usr/bin/env bash
# Run one program across N DNAnexus GPU boxes at once, each taking a slice of
# the input -- and make sure all N boxes die.
#
#     scripts/dx-shard-gpu.sh -N 4 -c 6127 -t 6h \
#         --setup scripts/dx-worker-setup-evo2.sh \
#         -f /Test_Inputs/first_500_INS.vcf \
#         -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
#         -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
#         python -m evo.embeddings /home/dnanexus/first_500_INS.vcf \
#             /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta '$OUT'
#
# This is a fan-out over scripts/dx-batch-gpu.sh: one copy of it per shard, each
# with its own run name, output directory and log file, and each given the
# shard's `--offset`/`--limit`. Every platform detail -- auth, staging, the
# environment build, the upload, the terminate -- stays there and is not
# duplicated here. Batch mode is the right backend precisely because it refuses
# --shell and --keep: nobody is attached to fifteen boxes.
#
# Sharding is the only real lever on this workload. A single 8192-token pass
# through Evo 2 7B already saturates an L4, so batch size and num_workers buy
# nothing, and both GPU types this project can launch are the same 1x L4 24 GB
# -- see docs/evo_analysis.md. More boxes is what is left.
#
# WHY IT EXISTS, given you could background four dx-batch-gpu.sh by hand
# ----------------------------------------------------------------------
# Because four boxes is four ways to keep billing after you have stopped paying
# attention, and Ctrl-C does not reach them. dx-instance.sh terminates its box
# from an EXIT trap, but bash defers a trap until the running foreground command
# returns -- and that command is a `dx ssh` that will not return for hours. So a
# Ctrl-C aimed at a hand-backgrounded child is queued behind the very run it was
# meant to stop.
#
# The fix is that each shard is launched into its OWN PROCESS GROUP (`set -m`)
# and shutdown signals the whole group: `dx ssh` dies, the child's foreground
# command returns, its EXIT trap finally runs, and it terminates its own box.
# Then, because a trap is only as good as the process it lives in, this script
# ALSO harvests every job id out of the shard logs and sweeps for survivors on
# the way out -- so a child that was killed outright still gets its box stopped.
#
# What it does NOT protect against is this script being SIGKILLed. Nothing can.
# --time remains the real backstop: set it above the WORST shard's run, not the
# average, and to what you can afford to lose. After any abnormal exit:
#
#     uv run dx find jobs --user self --state running --origin-jobs
#
# SHARDING
# --------
# `--offset`/`--limit` index the per-sample *call* stream, so shard k covers
# exactly the same calls however many windows shard k-1 dropped. `--calls` is
# the total to divide; a laptop dry run prints it per allele as
# "calls [0, end): N windows (skipped, contig not in reference: M)", and the
# total is N + M:
#
#     uv run python -m evo.embeddings calls.vcf hg38.fa /tmp/x --dry-run
#
# Overshooting --calls is safe -- the last shard simply runs short -- while
# undershooting silently drops the tail. Round up if you are guessing.
#
# The program is taken verbatim and `--offset X --limit Y` is appended to it. If
# it contains `{offset}`, `{limit}` or `{shard}` those are substituted instead
# and nothing is appended, which is how to shard a program that takes its range
# somewhere other than at the end.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
# Overridable so the shutdown path can be tested against a stub instead of a
# real GPU box; there is no other reason to change it.
BACKEND="${DX_SHARD_BACKEND:-$REPO/scripts/dx-batch-gpu.sh}"

log()  { echo "[$(date +%H:%M:%S)] $*" >&2; }
warn() { echo "[$(date +%H:%M:%S)] WARNING: $*" >&2; }
die()  { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

# --- defaults -----------------------------------------------------------------
SHARDS=0
CALLS=0
START=0
PARALLEL=0
RUN="dx-shard-$(date +%Y%m%d-%H%M%S)"
OUTPUT_DIR=""
LOG_DIR=""
POLL="${POLL:-60}"
DETACH=1
DRY=0
PASS=()
COMMAND=()

usage() {
    awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' \
        "${BASH_SOURCE[0]}"
    cat <<'EOF'

Options:
  -N, --shards N          number of shards, one GPU box each        [required]
  -c, --calls TOTAL       total calls in the input, divided evenly  [required]
  -s, --start OFFSET      call offset the first shard begins at            [0]
  -j, --max-parallel K    boxes to hold at once; the rest queue    [= --shards]
  -o, --output-dir DIR    results land in DIR/shard<k>/        [data/dx/<run>/]
      --run NAME          base run name; shard k is <NAME>-<k>
      --log-dir DIR       per-shard logs                    [<output-dir>/logs]
      --no-detach         run the program in the ssh session, the old way. A
                          dropped connection then kills the run; see below
  -n, --dry-run           print what each shard would do, launch nothing
  -h, --help              this

Every other option goes to scripts/dx-batch-gpu.sh unchanged -- notably
-t/--time (size it for the LARGEST shard), -f/--input, --setup and -i/--instance.
`scripts/dx-instance.sh --help` documents all of them. Everything after `--` is
the program. --shell, --keep and --interactive are refused: this script promises
to shut every box down, and each of those breaks that promise.

Examples:
  # four shards of the working VCF, ~4 h each, both alleles per shard
  scripts/dx-shard-gpu.sh -N 4 -c 6127 -t 6h -o data/dx/evo2 \
      --setup scripts/dx-worker-setup-evo2.sh \
      -f /Test_Inputs/first_500_INS.vcf \
      -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
      -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
      python -m evo.embeddings /home/dnanexus/first_500_INS.vcf \
          /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta '$OUT'

  # check the split and the per-shard commands without spending anything
  scripts/dx-shard-gpu.sh -N 4 -c 6127 --dry-run -- python -m evo.embeddings ...
EOF
}

# --- arguments ----------------------------------------------------------------
# Only the flags this script acts on are intercepted; the rest pass straight
# through, so dx-instance.sh stays the single place that documents them and this
# script does not go stale every time one is added.
while [ $# -gt 0 ]; do
    case "$1" in
        -N|--shards)       SHARDS="${2:?}"; shift 2 ;;
        -c|--calls)        CALLS="${2:?}"; shift 2 ;;
        -s|--start)        START="${2:?}"; shift 2 ;;
        -j|--max-parallel) PARALLEL="${2:?}"; shift 2 ;;
        -o|--output-dir)   OUTPUT_DIR="${2:?}"; shift 2 ;;
        --run)             RUN="${2:?}"; shift 2 ;;
        --log-dir)         LOG_DIR="${2:?}"; shift 2 ;;
        -n|--dry-run)      DRY=1; PASS+=("--dry-run"); shift ;;
        --no-detach)       DETACH=0; shift ;;
        -h|--help)         usage; exit 0 ;;
        # dx-batch-gpu.sh refuses these anyway; saying so here names the reason
        # instead of surfacing it N times from N children at once.
        --shell|--keep|--interactive)
            die "$1 cannot be used with a fan-out: this script exists to
       guarantee every one of $SHARDS boxes is terminated, and $1 would leave
       one attached or billing. For a terminal use scripts/dx-instance-gpu.sh." ;;
        --)                shift; COMMAND=("$@"); break ;;
        # dx-instance.sh's remaining booleans, named so the generic forwarder
        # below does not mistake the next word for their argument.
        --terminate|--no-setup)
                           PASS+=("$1"); shift ;;
        -*)                PASS+=("$1")
                           case "${2:-}" in
                               ""|-*) shift ;;
                               *)     PASS+=("$2"); shift 2 ;;
                           esac ;;
        *)                 COMMAND=("$@"); break ;;
    esac
done

[ "$SHARDS" -gt 0 ] 2>/dev/null || die "--shards N is required (--help)"
[ "$CALLS" -gt 0 ] 2>/dev/null || die "--calls TOTAL is required; a laptop
       'python -m evo.embeddings ... --dry-run' prints it (--help)"
[ "$START" -ge 0 ] 2>/dev/null || die "--start must not be negative"
[ ${#COMMAND[@]} -gt 0 ] || die "no program given; put it after '--'"
[ -x "$BACKEND" ] || die "$BACKEND is missing or not executable"
[ "$PARALLEL" -gt 0 ] 2>/dev/null || PARALLEL="$SHARDS"
[ "$SHARDS" -le "$CALLS" ] || die "--shards $SHARDS exceeds --calls $CALLS"
: "${OUTPUT_DIR:=$REPO/data/dx/$RUN}"
: "${LOG_DIR:=$OUTPUT_DIR/logs}"

# --- preflight, once rather than N times racing each other --------------------
# dx-instance.sh checks these itself, but only after this script has already
# launched every other shard. Failing here costs nothing; failing there costs
# however many boxes were already up.
USER_NAME=""
PROJECT=""
if [ "$DRY" = 0 ]; then
    [ -f "$HOME/.dnanexus_config/ssh_id" ] \
        || die "no SSH key pair. Run 'uv run dx ssh_config' once, then retry."
    if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then
        warn "this checkout has uncommitted changes; the workers clone from"
        warn "  GitHub and will NOT have them. Commit and push first."
    fi
fi

# Authenticate BEFORE any box is launched. An expired token found by a child
# costs a boot to learn; found here it costs nothing -- and the last run began
# with exactly that, a token that had already timed out. It also yields the
# username the upload destinations are built from.
#
# Run in dry mode too, so --dry-run prints the destination a real run would use
# instead of a plausible-looking `:/Results//`. Only a real run dies on failure.
# shellcheck source=scripts/dx-env.sh
source "$REPO/scripts/dx-env.sh" >/dev/null 2>&1 || true
PROJECT="${DX_PROJECT_CONTEXT_ID:-}"
USER_NAME="$(uv run --group dx --no-sync dx whoami 2>/dev/null | tr -d '\r')"
if [ "$DRY" = 0 ]; then
    [ -n "$USER_NAME" ] || die "dx whoami failed -- is the token in .env current?
       It expires on an inactivity timeout, and a stale one only fails at launch."
    [ -n "$PROJECT" ] || die "dx-env.sh did not pin a project; see docs/scripts/DNANexus.md"
else
    : "${USER_NAME:=<you>}"
    : "${PROJECT:=<project>}"
fi

mkdir -p "$LOG_DIR" || die "could not create $LOG_DIR"

# --- work out the shard boundaries --------------------------------------------
# The remainder is spread one call at a time over the leading shards rather than
# dumped on the last: the shards run concurrently, so the run takes as long as
# its LARGEST shard, and an even split is the only one where nobody waits.
OFFSETS=()
LIMITS=()
base=$(( CALLS / SHARDS ))
rem=$(( CALLS % SHARDS ))
offset="$START"
k=0
while [ "$k" -lt "$SHARDS" ]; do
    limit="$base"
    [ "$k" -lt "$rem" ] && limit=$(( base + 1 ))
    OFFSETS+=("$offset")
    LIMITS+=("$limit")
    offset=$(( offset + limit ))
    k=$(( k + 1 ))
done

log "run          $RUN"
log "shards       $SHARDS over calls [$START, $offset), $PARALLEL at a time"
log "output       $OUTPUT_DIR/shard<k>/"
log "logs         $LOG_DIR/shard<k>.log"

# --- shutdown -----------------------------------------------------------------
# Two independent mechanisms, because they fail in different ways. Signalling the
# process GROUP is what lets a child's own EXIT trap run at all -- it is blocked
# in a multi-hour `dx ssh`, and bash defers traps until the foreground command
# returns, so killing the group is what makes that command return. The job-id
# sweep is the backstop for a child that never got to run its trap.
PIDS=()
STATES=()
STATUS=()      # exit code per shard once reaped; empty while it is still running
FAILED=0

# Every job this run created, as recorded in the shard logs by dx-instance.sh's
# own "job          job-xxxx" line.
harvest() {
    grep -ho 'job-[0-9A-Za-z]\{24\}' "$LOG_DIR"/shard*.log 2>/dev/null | sort -u
}

sweep() {
    [ "$DRY" = 1 ] && return 0
    local job state found=0
    for job in $(harvest); do
        state="$(uv run --group dx --no-sync dx describe "$job" 2>/dev/null \
                 | awk '$1=="State"{print $2}')"
        case "$state" in
            ""|terminated|done|failed) ;;
            *)  found=1
                warn "$job is '$state' after its shard exited -- terminating"
                uv run --group dx --no-sync dx terminate "$job" >/dev/null 2>&1 ;;
        esac
    done
    [ "$found" = 1 ] && warn "confirm with: uv run dx find jobs --user self --state running --origin-jobs"
    return 0
}

cleanup() {
    local rc=$? pid i live
    trap - EXIT INT TERM

    live=0
    for pid in ${PIDS+"${PIDS[@]}"}; do
        kill -0 "$pid" 2>/dev/null && live=$(( live + 1 ))
    done
    if [ "$live" -gt 0 ]; then
        log "stopping $live shard(s); each terminates its own box ..."
        for pid in ${PIDS+"${PIDS[@]}"}; do
            # Negative pid = the whole process group, which is the entire point.
            kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
        done
        # Children need a moment to run `dx terminate` and confirm the state.
        for i in $(seq 1 60); do
            live=0
            for pid in ${PIDS+"${PIDS[@]}"}; do
                kill -0 "$pid" 2>/dev/null && live=$(( live + 1 ))
            done
            [ "$live" = 0 ] && break
            sleep 2
        done
        [ "$live" -gt 0 ] && warn "$live shard(s) did not exit; the sweep follows"
    fi

    sweep
    exit "$rc"
}
trap cleanup EXIT INT TERM

# --- launch -------------------------------------------------------------------
# Job control on, so every background child leads its own process group and can
# be signalled as a group. Without it they share ours, and `kill -TERM -$pid`
# would signal this script too.
set -m

launch() {
    local k="$1" off="${OFFSETS[$1]}" lim="${LIMITS[$1]}"
    local out="$OUTPUT_DIR/shard$k" logf="$LOG_DIR/shard$k.log"
    local arg subst=0
    local -a cmd
    cmd=()

    for arg in "${COMMAND[@]}"; do
        case "$arg" in
            *'{offset}'*|*'{limit}'*|*'{shard}'*) subst=1 ;;
        esac
    done
    for arg in "${COMMAND[@]}"; do
        if [ "$subst" = 1 ]; then
            arg="${arg//\{offset\}/$off}"
            arg="${arg//\{limit\}/$lim}"
            arg="${arg//\{shard\}/$k}"
        fi
        cmd+=("$arg")
    done
    [ "$subst" = 0 ] && cmd+=(--offset "$off" --limit "$lim")

    # Run the program through the worker-side runner rather than directly. It
    # detaches the work from the ssh session, uploads each result as it is
    # written, and terminates the box the moment the work ends -- the three
    # things whose absence turned one dropped connection into 12.3 wasted
    # GPU-hours on 2026-08-27. dx-instance.sh still uploads and terminates too;
    # both doing it is the point, since either side can die.
    local dest=""
    if [ "$DETACH" = 1 ]; then
        dest="/Results/$USER_NAME/$RUN-$k/"
        cmd=(scripts/dx-worker-run.sh --destination "$PROJECT:$dest" -- "${cmd[@]}")
    fi

    log "shard $k: calls [$off, $((off + lim))) -> $out"
    STATUS[$k]=""
    "$BACKEND" \
        --run "$RUN-$k" \
        --output-dir "$out" \
        ${dest:+--destination "$dest"} \
        ${PASS+"${PASS[@]}"} \
        -- "${cmd[@]}" >"$logf" 2>&1 &
    PIDS+=("$!")
}

# Start up to --max-parallel, then start another each time one finishes. A queue
# rather than a stampede because GPU capacity is finite: a mem2_ssd2_gpu1_v2_x8
# sat in 'runnable' for 20 minutes one day and never got an instance at all, and
# twenty simultaneous requests make that likelier, not less.
next=0
while [ "$next" -lt "$SHARDS" ] && [ "$next" -lt "$PARALLEL" ]; do
    launch "$next"
    next=$(( next + 1 ))
    # Stagger slightly: otherwise every child hits `dx run` and `git ls-remote`
    # at the same instant, and a rate-limited launch is indistinguishable from a
    # broken one in the logs.
    [ "$DRY" = 0 ] && sleep 3
done

# --- wait, reporting as it goes -----------------------------------------------
# Children write to files, not the terminal: four interleaved progress bars are
# unreadable. This is the digest -- the last thing each live shard said.
running=1
while [ "$running" = 1 ]; do
    running=0
    i=0
    while [ "$i" -lt "${#PIDS[@]}" ]; do
        kill -0 "${PIDS[$i]}" 2>/dev/null && running=1
        i=$(( i + 1 ))
    done

    # Reap whatever has finished. Doing this here rather than only at the end is
    # what lets a failure stop the queue: `wait` on a live pid would block.
    i=0
    while [ "$i" -lt "${#PIDS[@]}" ]; do
        if [ -z "${STATUS[$i]:-}" ] && ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
            wait "${PIDS[$i]}"; STATUS[$i]=$?
            if [ "${STATUS[$i]}" = 0 ]; then
                log "  shard $i: finished ok"
            else
                FAILED=$(( FAILED + 1 ))
                warn "shard $i FAILED (rc=${STATUS[$i]}) -- see $LOG_DIR/shard$i.log"
            fi
        fi
        i=$(( i + 1 ))
    done

    # Backfill the queue as slots free up -- but not into a known failure. If a
    # shard has already raised, the next one almost certainly will too, and
    # launching it spends a GPU box to learn the same thing twice.
    if [ "$FAILED" -gt 0 ] && [ "$next" -lt "$SHARDS" ]; then
        warn "not launching the remaining $(( SHARDS - next )) shard(s): shard(s)
       already failed, and a systematic fault would cost a box each to rediscover.
       Fix, then rerun those with --start/--calls."
        next="$SHARDS"
    fi
    if [ "$next" -lt "$SHARDS" ]; then
        live=0
        for pid in "${PIDS[@]}"; do
            kill -0 "$pid" 2>/dev/null && live=$(( live + 1 ))
        done
        while [ "$live" -lt "$PARALLEL" ] && [ "$next" -lt "$SHARDS" ]; do
            launch "$next"
            next=$(( next + 1 ))
            live=$(( live + 1 ))
            running=1
        done
    fi

    [ "$running" = 0 ] && break

    i=0
    while [ "$i" -lt "${#PIDS[@]}" ]; do
        if kill -0 "${PIDS[$i]}" 2>/dev/null; then
            log "  shard $i: $(grep -v '^[[:space:]]*$' "$LOG_DIR/shard$i.log" 2>/dev/null \
                              | tail -1 | cut -c1-96)"
        fi
        i=$(( i + 1 ))
    done

    # Sleep in short steps rather than one long one, so a set of shards that all
    # finish early is noticed in seconds rather than at the next poll -- and so
    # Ctrl-C is acted on promptly instead of up to $POLL later.
    waited=0
    while [ "$waited" -lt "$POLL" ]; do
        sleep 2
        waited=$(( waited + 2 ))
        live=0
        for pid in "${PIDS[@]}"; do
            kill -0 "$pid" 2>/dev/null && live=$(( live + 1 ))
        done
        [ "$live" = 0 ] && break
    done
done

# --- collect statuses ---------------------------------------------------------
# dx-instance.sh's own exit status IS meaningful (unlike `dx ssh`'s, which is
# always non-zero): it exits 0 only after the program ran and the results came
# home.
failed=0
i=0
while [ "$i" -lt "${#PIDS[@]}" ]; do
    if [ -n "${STATUS[$i]:-}" ]; then rc="${STATUS[$i]}"; else wait "${PIDS[$i]}"; rc=$?; fi
    if [ "$rc" = 0 ]; then
        STATES+=("shard $i: ok")
    else
        STATES+=("shard $i: FAILED (rc=$rc) -- see $LOG_DIR/shard$i.log")
        failed=$(( failed + 1 ))
    fi
    i=$(( i + 1 ))
done

log "--- $RUN ---"
for line in "${STATES[@]}"; do log "$line"; done

if [ "$failed" = 0 ] && [ "$DRY" = 0 ]; then
    log "results in $OUTPUT_DIR/shard*/"
    log "analyse the whole set at once:"
    log "  uv run --extra analysis analysis-cluster $OUTPUT_DIR/shard*/alt*.npz \\"
    log "      --background $OUTPUT_DIR/shard*/reference*.npz --delta"
elif [ "$failed" -gt 0 ]; then
    warn "$failed of $SHARDS shard(s) failed. Rerun one on its own with the same
       arithmetic: --shards 1 --start <its offset> --calls <its limit>."
fi

exit "$failed"
