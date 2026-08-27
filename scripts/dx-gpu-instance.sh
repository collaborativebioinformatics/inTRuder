#!/usr/bin/env bash
# Rent a DNAnexus GPU box, build the Evo 2 environment on it, run a command,
# bring the results home, and terminate it.
#
#     scripts/dx-gpu-instance.sh --time 2h -- \
#         python -m evo.embeddings ~/first_500_INS.vcf ~/hg38.fasta "$OUT"
#
# The whole point is the last step. A cloud_workstation bills for wall-clock
# time whether or not anyone is attached and whether or not it is doing any
# work, and closing your terminal does not stop it -- so termination lives in an
# EXIT trap here, and fires on success, on failure, and on Ctrl-C alike.
# `--time` is the second line of defence: if this script is SIGKILLed the box
# still dies when max_session_length runs out, so set it to what you can afford
# to lose, not to what the job might need.
#
# With no command it sets the box up and drops you into an interactive shell,
# which is the way to measure something before committing to a long run. The
# shell comes before the fetch either way, so whatever you leave in $OUT is
# downloaded when you exit.
#
# See docs/DNANexus.md for the platform details this automates: token auth, org
# billing, which GPU types actually exist, and why the environment build is not
# just `uv sync`.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

log()  { echo "[$(date +%H:%M:%S)] $*" >&2; }
warn() { echo "[$(date +%H:%M:%S)] WARNING: $*" >&2; }
die()  { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

# --- defaults -----------------------------------------------------------------
# mem2_ssd2_gpu1_v2_x8 (1x L4, 24 GB) and mem3_ssd1_gpu1_x16 are the only GPU
# types this project can launch; everything else fails at launch, and the T4 box
# launches and then dies at the first kernel. docs/DNANexus.md has the table.
INSTANCE="${DX_INSTANCE:-mem2_ssd2_gpu1_v2_x8}"
TIME="2h"
BRANCH="${BRANCH:-feature/evo-embeds}"
REPO_URL="${REPO_URL:-https://github.com/collaborativebioinformatics/novelTRs.git}"
REPO_DIR="${REPO_DIR:-/home/dnanexus/novelTRs}"
REMOTE_OUT="/home/dnanexus/out"
RUN="evo-$(date +%Y%m%d-%H%M%S)"
OUTPUT_DIR=""
DESTINATION=""
JOB=""
ATTACHED=0
KEEP=0
SHELL_AFTER=0
DRY=0
INPUTS=()
COMMAND=()

usage() {
    # The header comment above is the prose half of --help: print it back
    # (minus the shebang) and stop at the first line of actual code.
    awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' \
        "${BASH_SOURCE[0]}"
    cat <<'EOF'

Options:
  -t, --time DURATION     max_session_length, e.g. 30m, 2h, 8h   [2h]
  -i, --instance TYPE     GPU instance type          [mem2_ssd2_gpu1_v2_x8]
  -f, --input ID|PATH     stage a platform file into /home/dnanexus on the
                          worker; repeatable. Takes a file-xxxx id or a project
                          path, which is resolved to an id before launch.
  -o, --output-dir DIR    local directory results are downloaded into
                                                     [data/evo/<run>]
  -r, --remote-out DIR    directory on the worker the command writes to; it is
                          created before the command runs and exported as $OUT
                                                     [/home/dnanexus/out]
  -d, --destination PATH  project folder results are uploaded to
                                                     [/Results/<you>/<run>/]
  -b, --branch BRANCH     branch to clone on the worker  [feature/evo-embeds]
      --run NAME          name for this run, used in the default paths
      --job JOB-ID        attach to a job that is already running instead of
                          launching one. Implies --keep unless --terminate.
      --terminate         terminate even a job given with --job
      --shell             open an interactive shell after the command and before
                          the fetch; anything left in $OUT still comes home
      --keep              do NOT terminate at the end (it keeps billing)
  -n, --dry-run           print the platform commands instead of running them
  -h, --help              this

Everything after `--` (or after the last option) is the command. It is joined
with spaces and handed to a login bash on the worker, exactly as ssh does, so
pipes and redirections work and arguments containing spaces need quoting twice.
It runs in the repo checkout with the project venv first on PATH, so `evo-embed`
and `python -m evo.embeddings` resolve to the venv -- never use `uv run` there,
it resyncs to uv.lock and uninstalls flash-attn.

Examples:
  # both alleles of a shard, results in data/evo/shard0/
  scripts/dx-gpu-instance.sh -t 8h -o data/evo/shard0 \
      -f file-JB7fJKj0pzX9jkpkbbG6jyVG \
      -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
      -f /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
      python -m evo.embeddings /home/dnanexus/first_500_INS.vcf \
          /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta \
          '$OUT' --offset 0 --limit 2000

  # just give me a GPU for an hour
  scripts/dx-gpu-instance.sh --time 1h
EOF
}

# --- arguments ----------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        -t|--time)        TIME="${2:?}"; shift 2 ;;
        -i|--instance)    INSTANCE="${2:?}"; shift 2 ;;
        -f|--input)       INPUTS+=("${2:?}"); shift 2 ;;
        -o|--output-dir)  OUTPUT_DIR="${2:?}"; shift 2 ;;
        -r|--remote-out)  REMOTE_OUT="${2:?}"; shift 2 ;;
        -d|--destination) DESTINATION="${2:?}"; shift 2 ;;
        -b|--branch)      BRANCH="${2:?}"; shift 2 ;;
        --run)            RUN="${2:?}"; shift 2 ;;
        --job)            JOB="${2:?}"; ATTACHED=1; KEEP=1; shift 2 ;;
        --terminate)      KEEP=0; shift ;;
        --shell)          SHELL_AFTER=1; shift ;;
        --keep)           KEEP=1; shift ;;
        -n|--dry-run)     DRY=1; shift ;;
        -h|--help)        usage; exit 0 ;;
        --)               shift; COMMAND=("$@"); break ;;
        -*)               die "unknown option $1 (--help)" ;;
        *)                COMMAND=("$@"); break ;;
    esac
done

[[ "$TIME" =~ ^[0-9]+[smhd]$ ]] || die "--time $TIME: want a number and s/m/h/d, e.g. 2h"
: "${OUTPUT_DIR:=$REPO/data/evo/$RUN}"

# --- platform plumbing --------------------------------------------------------
# Always `uv run dx`: .venv/bin is not on PATH, so a bare `dx` gives
# "command not found" even when dxpy is correctly installed.
DX=(uv run dx)

dx_do() {
    if [ "$DRY" = 1 ]; then echo "+ dx $*" >&2; return 0; fi
    "${DX[@]}" "$@"
}

# shellcheck source=scripts/dx-env.sh
source "$REPO/scripts/dx-env.sh" || die "could not authenticate; see docs/DNANexus.md"
PROJECT="${DX_PROJECT_CONTEXT_ID:?dx-env.sh did not pin a project}"

# --- preflight ----------------------------------------------------------------
# Everything cheap that can fail goes here, because past this point the meter is
# running: a missing SSH key or an unpushed branch discovered after launch costs
# real money to discover.
if [ "$ATTACHED" = 0 ]; then
    [ -f "$HOME/.dnanexus_config/ssh_id" ] \
        || die "no SSH key pair. Run 'uv run dx ssh_config' once, then retry.
       Without it the worker boots, starts billing, and only then refuses you."

    # The worker clones from GitHub, so it runs what is *pushed*, not what is in
    # this checkout. A branch that does not exist there is a guaranteed failure
    # ten minutes and one GPU-boot from now.
    remote_head="$(git -C "$REPO" ls-remote --heads "$REPO_URL" "$BRANCH" 2>/dev/null | cut -f1)"
    [ -n "$remote_head" ] || die "branch '$BRANCH' does not exist at $REPO_URL.
       Push it first -- the worker clones from GitHub, not from this checkout."
    local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
    if [ "$remote_head" != "$local_head" ]; then
        warn "the worker will run ${remote_head:0:8} ($BRANCH on GitHub), not your"
        warn "  local HEAD ${local_head:0:8}. Push if you meant to test local changes."
    fi
    # Matching HEADs are not enough: uncommitted work is invisible to a clone,
    # and this is the cheap moment to notice that the code you have been editing
    # is not the code about to spend an hour of GPU time.
    if [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then
        warn "this checkout has uncommitted changes. The worker clones $BRANCH,"
        warn "  so they will NOT be there. Commit and push first if they matter."
    fi
fi

USER_NAME="$("${DX[@]}" whoami 2>/dev/null | tr -d '\r')"
[ -n "$USER_NAME" ] || die "dx whoami failed; is DX_API_TOKEN valid?"
: "${DESTINATION:=/Results/$USER_NAME/$RUN/}"
case "$DESTINATION" in */) ;; *) DESTINATION="$DESTINATION/" ;; esac

log "run          $RUN"
log "instance     $INSTANCE for $TIME"
log "project      $PROJECT (bills to the org, not to you)"
log "destination  $DESTINATION"
log "local output $OUTPUT_DIR"
[ ${#COMMAND[@]} -gt 0 ] && log "command      ${COMMAND[*]}"

# --- terminate on the way out, whatever the way out is ------------------------
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    if [ -n "$JOB" ] && [ "$KEEP" = 0 ] && [ "$DRY" = 0 ]; then
        log "terminating $JOB"
        "${DX[@]}" terminate "$JOB" >/dev/null 2>&1
        # `dx terminate` prints nothing and the state does not flip instantly.
        # Only 'terminated' ends the billing, so say which one we saw.
        local state=""
        for _ in $(seq 1 20); do
            state="$("${DX[@]}" describe "$JOB" 2>/dev/null | awk '$1=="State"{print $2}')"
            [ "$state" = "terminated" ] && break
            sleep 3
        done
        if [ "$state" = "terminated" ]; then
            log "terminated. Billing stopped."
        else
            warn "state is '${state:-unknown}', not 'terminated'. STILL BILLING --"
            warn "  check with: uv run dx describe $JOB | grep ^State"
        fi
    elif [ -n "$JOB" ] && [ "$DRY" = 0 ]; then
        warn "$JOB left running and BILLING until $TIME elapses."
        warn "  stop it with: uv run dx terminate $JOB"
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

# --- launch -------------------------------------------------------------------
if [ "$ATTACHED" = 1 ]; then
    log "attaching to $JOB"
else
    fids=()
    for want in ${INPUTS+"${INPUTS[@]}"}; do
        case "$want" in
            file-*) fid="$want" ;;
            *)      fid="$("${DX[@]}" ls --brief "$want" 2>/dev/null | head -1 | tr -d '\r')"
                    [ -n "$fid" ] || die "--input $want: no such file in $PROJECT" ;;
        esac
        log "input        $fid  ($want)"
        fids+=("-ifids=$fid")
    done

    # --destination names the project the job RUNS IN, which is the field that
    # decides who pays. Ambient DX_PROJECT_CONTEXT_ID would usually do, but this
    # does not depend on the environment surviving.
    log "launching ..."
    if [ "$DRY" = 1 ]; then
        dx_do run app-cloud_workstation --instance-type "$INSTANCE" \
            "-imax_session_length=$TIME" ${fids+"${fids[@]}"} \
            --destination "$PROJECT:$DESTINATION" --allow-ssh --yes --brief
        JOB="job-DRYRUNDRYRUNDRYRUNDRYR"
    else
        JOB="$("${DX[@]}" run app-cloud_workstation --instance-type "$INSTANCE" \
            "-imax_session_length=$TIME" ${fids+"${fids[@]}"} \
            --destination "$PROJECT:$DESTINATION" --allow-ssh --yes --brief \
            | tr -d '\r')"
        [ -n "$JOB" ] || die "dx run produced no job id"
    fi
    log "job          $JOB"
fi

# --- wait for it to be reachable ----------------------------------------------
# Two separate waits, because they are two separate things: state=running means
# the instance exists, but the SSH host key is published a good few minutes
# later, and connecting before then just fails.
if [ "$DRY" = 0 ]; then
    log "waiting for state=running (a GPU box takes a few minutes) ..."
    for _ in $(seq 1 120); do
        state="$("${DX[@]}" describe "$JOB" 2>/dev/null | awk '$1=="State"{print $2}')"
        case "$state" in
            running) break ;;
            failed|terminated|terminating) die "job went to '$state' before it started" ;;
        esac
        sleep 10
    done
    [ "${state:-}" = "running" ] || die "job never reached 'running' (last: ${state:-unknown})"

    log "waiting for ssh ..."
    ready=0
    for _ in $(seq 1 60); do
        if "${DX[@]}" ssh "$JOB" -T "true" >/dev/null 2>&1; then ready=1; break; fi
        sleep 10
    done
    [ "$ready" = 1 ] || die "ssh never came up. The job is running and billing;
       try 'uv run dx ssh $JOB' by hand, or terminate it."
    log "connected."
fi

# `bash -l` because a non-interactive dx ssh gets no dx credentials otherwise,
# and the upload step needs them.
remote() {
    if [ "$DRY" = 1 ]; then
        echo "+ dx ssh $JOB -T 'bash -l -s' <<'REMOTE'" >&2
        sed 's/^/|   /' >&2
        echo "+ REMOTE" >&2
        return 0
    fi
    "${DX[@]}" ssh "$JOB" -T "bash -l -s"
}

# --- build the environment ----------------------------------------------------
log "building the Evo 2 environment (~2 min; flash-attn, no nvcc -- see the script) ..."
if [ "$DRY" = 1 ]; then
    echo "+ dx ssh $JOB -T 'BRANCH=$BRANCH REPO_DIR=$REPO_DIR bash -s' < scripts/setup-gpu-worker.sh" >&2
else
    "${DX[@]}" ssh "$JOB" -T \
        "BRANCH='$BRANCH' REPO_URL='$REPO_URL' REPO_DIR='$REPO_DIR' bash -s" \
        < "$REPO/scripts/setup-gpu-worker.sh" \
        || die "environment build failed; the box is still up, attach with:
       uv run dx ssh $JOB"
fi

# --- run the command ----------------------------------------------------------
if [ ${#COMMAND[@]} -gt 0 ]; then
    log "running the command ..."
    remote <<EOF || die "the command failed. The box is still up until this script
       exits; attach with 'uv run dx ssh $JOB' to look at it."
set -uo pipefail
export PATH="$REPO_DIR/.venv/bin:\$PATH"
export OUT="$REMOTE_OUT"
mkdir -p "\$OUT" || exit 1
cd "$REPO_DIR" || exit 1
echo "[worker] \$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'no nvidia-smi')"
echo "[worker] cwd \$PWD, OUT=\$OUT"
${COMMAND[*]}
EOF
    log "command finished."
fi

# --- interactive shell --------------------------------------------------------
# Before the fetch, not after: whatever you make in here is in $OUT too, and
# comes home with everything else.
if [ ${#COMMAND[@]} -eq 0 ] || [ "$SHELL_AFTER" = 1 ]; then
    log "opening a shell. The repo is at $REPO_DIR, \$OUT is $REMOTE_OUT, and"
    log "  anything you leave in \$OUT is fetched when you exit. Use"
    log "  .venv/bin/... -- never 'uv run', it uninstalls flash-attn."
    log "Exiting TERMINATES the box. Answer 'n' to dx's own prompt on the way"
    log "  out -- this script does the terminating, and confirms it."
    if [ "$DRY" = 1 ]; then
        echo "+ dx ssh $JOB" >&2
    else
        "${DX[@]}" ssh "$JOB"
    fi
fi

# --- bring the results home ---------------------------------------------------
# Worker -> project storage -> here, rather than straight down the ssh pipe. The
# extra hop buys durability: if the local download dies halfway, or the laptop
# lid closes, the results are already on the platform and outlive the box, which
# nothing on the worker's own disk does.
log "uploading $REMOTE_OUT -> $PROJECT:$DESTINATION"
uploaded=1
remote <<EOF || uploaded=0
set -uo pipefail
cd "$REMOTE_OUT" 2>/dev/null || { echo "[worker] no $REMOTE_OUT to upload"; exit 3; }
[ -n "\$(ls -A)" ] || { echo "[worker] $REMOTE_OUT is empty"; exit 4; }
dx mkdir -p "$PROJECT:$DESTINATION" || exit 1
for entry in *; do
    echo "[worker] uploading \$entry (\$(du -sh "\$entry" | cut -f1))"
    if [ -d "\$entry" ]; then
        dx upload -r "\$entry" --destination "$PROJECT:$DESTINATION" --wait --brief || exit 1
    else
        dx upload "\$entry" --destination "$PROJECT:$DESTINATION" --wait --brief || exit 1
    fi
done
EOF

if [ "$uploaded" = 0 ]; then
    if [ ${#COMMAND[@]} -gt 0 ]; then
        warn "nothing to fetch -- did the command write to \$OUT ($REMOTE_OUT)?"
    else
        log "nothing in $REMOTE_OUT to fetch."
    fi
else
    log "downloading -> $OUTPUT_DIR"
    if [ "$DRY" = 1 ]; then
        echo "+ dx download -r -f -o <staging> $PROJECT:$DESTINATION" >&2
        echo "+ cp -R <staging>/$(basename "$DESTINATION")/. $OUTPUT_DIR/" >&2
    else
        staging="$(mktemp -d)"
        if "${DX[@]}" download -r -f -o "$staging" "$PROJECT:$DESTINATION"; then
            # dx recreates the folder under the target; flatten it so
            # --output-dir means what it says.
            src="$staging/$(basename "$DESTINATION")"
            [ -d "$src" ] || src="$staging"
            mkdir -p "$OUTPUT_DIR" && cp -R "$src"/. "$OUTPUT_DIR"/ \
                && log "results in $OUTPUT_DIR:" \
                && ls -lh "$OUTPUT_DIR" >&2
        else
            warn "download failed, but the results are safe on the platform:"
            warn "  uv run dx download -r $PROJECT:$DESTINATION"
        fi
        rm -rf "$staging"
    fi
fi

log "done."
