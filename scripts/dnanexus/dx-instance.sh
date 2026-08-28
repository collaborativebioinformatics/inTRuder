#!/usr/bin/env bash
# Rent a DNAnexus box, set it up, drop you into a terminal on it, bring back
# anything you leave in $OUT, and terminate it.
#
#     scripts/dnanexus/dx-instance.sh --time 1h              # a shell on a CPU box
#     scripts/dnanexus/dx-instance.sh --gpu --time 2h        # ... on an L4
#     scripts/dnanexus/dx-instance.sh -t 30m -- pytest -q    # run something instead
#     scripts/dnanexus/dx-instance.sh --list-instances       # what can we even ask for?
#
# The whole point is the last step. A cloud_workstation bills for wall-clock
# time whether or not anyone is attached and whether or not it is doing any
# work, and closing your terminal does not stop it -- so termination lives in an
# EXIT trap here, and fires on success, on failure, and on Ctrl-C alike.
# `--time` is the second line of defence: if this script is SIGKILLed the box
# still dies when max_session_length runs out, so set it to what you can afford
# to lose, not to what the job might need.
#
# With no command it sets the box up and drops you into an interactive shell.
# The shell comes before the fetch either way, so whatever you leave in $OUT is
# downloaded when you exit.
#
# See docs/scripts/DNANexus.md for the platform details this automates: token auth, org
# billing, which instance types actually launch, and how to do each step by hand.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

log()  { echo "[$(date +%H:%M:%S)] $*" >&2; }
warn() { echo "[$(date +%H:%M:%S)] WARNING: $*" >&2; }
die()  { echo "[$(date +%H:%M:%S)] FATAL: $*" >&2; exit 1; }

# --- defaults -----------------------------------------------------------------
# A workstation is charged by the hour and the shell you asked for does not need
# 64 cores; ask for a bigger one by name when the work needs it.
INSTANCE="${DX_INSTANCE:-mem1_ssd1_v2_x4}"
# --gpu is shorthand for this one. It is 1x L4, and it is one of only two GPU
# types this project can actually launch -- see docs/scripts/DNANexus.md.
GPU_INSTANCE="${DX_GPU_INSTANCE:-mem2_ssd2_gpu1_v2_x8}"
TIME="2h"
# The worker clones from GitHub, so the default is whatever branch you are on --
# which is almost always what you meant, and preflight checks it is pushed.
BRANCH="${BRANCH:-$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null)}"
[ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ] || BRANCH=main
REPO_URL="${REPO_URL:-https://github.com/collaborativebioinformatics/novelTRs.git}"
REPO_DIR="${REPO_DIR:-/home/dnanexus/novelTRs}"
# Extra flags for the worker's `uv sync`. The setup script has always taken
# this; until now nothing passed it, so the documented knob did nothing on the
# only path anyone uses.
SYNC_ARGS="${SYNC_ARGS:-}"
REMOTE_OUT="/home/dnanexus/out"
RUN="dx-$(date +%Y%m%d-%H%M%S)"
SETUP="$REPO/scripts/dnanexus/dx-worker-setup.sh"
# How long to wait for sshd after the job reaches 'running'. The host key is
# published minutes after the state flips, and on a slow day the gap has been
# longer than the 10 min this used to allow -- which reads as a hard failure
# rather than as "wait a bit more".
SSH_TRIES="${SSH_TRIES:-90}"
SSH_WAIT="${SSH_WAIT:-10}"
# `dx ssh` ALWAYS exits non-zero, however well the remote command ran: on the
# way out it asks "Job job-... is still running. Terminate now? [y/N]" and reads
# EOF as N, which it reports as failure. Verified 2026-08-27 -- a session that
# printed its output correctly and ran `true` still exited 1.
#
# So nothing here may gate on its exit status. The remote side prints this
# sentinel as its last act and we look for that instead. It carries the PID so
# a line echoed by the remote command itself cannot be mistaken for it.
OK="__dx_remote_ok_$$__"
OUTPUT_DIR=""
DESTINATION=""
JOB=""
ATTACHED=0
KEEP=0
SHELL_AFTER=0
DRY=0
# Which of the two shapes this run is: "" is whichever you asked for, "batch"
# runs a program and never opens a shell, "interactive" opens a shell and takes
# no program. The scripts/dnanexus/dx-{instance,batch}-{cpu,gpu}.sh wrappers set one of
# these instead of re-implementing the option table above to work out whether a
# command was given -- which is the only place that answer is reliably known.
MODE=""
# --job implies --keep; an explicit --keep is a different thing, and --batch
# needs to tell them apart to honour "terminates when it is done".
KEEP_EXPLICIT=0
LIST=0
LIST_FILTER=""
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
  -i, --instance TYPE     instance type                [mem1_ssd1_v2_x4]
  -g, --gpu               shorthand for -i mem2_ssd2_gpu1_v2_x8
  -f, --input ID|PATH     stage a platform file into /home/dnanexus on the
                          worker; repeatable. Takes a file-xxxx id or a project
                          path, which is resolved to an id before launch.
  -o, --output-dir DIR    local directory results are downloaded into
                                                       [data/dx/<run>]
  -r, --remote-out DIR    directory on the worker the command writes to; it is
                          created before the command runs and exported as $OUT
                                                       [/home/dnanexus/out]
  -d, --destination PATH  project folder results are uploaded to
                                                       [/Results/<you>/<run>/]
  -b, --branch BRANCH     branch the worker clones     [your current branch]
      --setup SCRIPT      environment build to run on the worker
                          [scripts/dnanexus/dx-worker-setup.sh]
      --sync-args ARGS    extra flags for the worker's `uv sync`, as one
                          argument, e.g. --sync-args "--group dx"      [none]
      --no-setup          leave the box as it boots: no clone, no uv, no venv
      --run NAME          name for this run, used in the default paths
      --job JOB-ID        attach to a job that is already running instead of
                          launching one. Implies --keep unless --terminate.
      --terminate         terminate even a job given with --job
      --shell             open an interactive shell after the command and before
                          the fetch; anything left in $OUT still comes home
      --keep              do NOT terminate at the end (it keeps billing)
      --batch             run a program and terminate: a command is required,
                          no shell is opened, and --shell/--keep are refused
      --interactive       open a shell and take no command
  -l, --list-instances [PATTERN]
                          print every instance type this project may launch,
                          with what it is for, and exit. PATTERN filters by
                          substring, e.g. `--list-instances gpu`.
  -n, --dry-run           print the platform commands instead of running them
  -h, --help              this

Everything after `--` (or after the last option) is the command. It is joined
with spaces and handed to a login bash on the worker, exactly as ssh does, so
pipes and redirections work and arguments containing spaces need quoting twice.
It runs in the checkout with the project venv first on PATH, so `novelty` and
`python -m ...` resolve there -- avoid `uv run` on the worker, which resyncs to
uv.lock and would uninstall anything you installed on top of it.

Examples:
  # a shell on a CPU box for an hour, with a VCF staged onto it
  scripts/dnanexus/dx-instance.sh -t 1h -f /survivor/HPRC_SV.survivor.vcf

  # run something and bring the results back into data/dx/run1/
  scripts/dnanexus/dx-instance.sh -t 2h -o data/dx/run1 -- \
      novelty screen /home/dnanexus/calls.vcf '$OUT/hits.tsv'

  # a GPU box, no repo, no venv -- just the hardware
  scripts/dnanexus/dx-instance.sh --gpu --no-setup -t 30m -- nvidia-smi
EOF
}

# --- arguments ----------------------------------------------------------------
while [ $# -gt 0 ]; do
    case "$1" in
        -t|--time)        TIME="${2:?}"; shift 2 ;;
        -i|--instance)    INSTANCE="${2:?}"; shift 2 ;;
        -g|--gpu)         INSTANCE="$GPU_INSTANCE"; shift ;;
        -f|--input)       INPUTS+=("${2:?}"); shift 2 ;;
        -o|--output-dir)  OUTPUT_DIR="${2:?}"; shift 2 ;;
        -r|--remote-out)  REMOTE_OUT="${2:?}"; shift 2 ;;
        -d|--destination) DESTINATION="${2:?}"; shift 2 ;;
        -b|--branch)      BRANCH="${2:?}"; shift 2 ;;
        --setup)          SETUP="${2:?}"; shift 2 ;;
        --sync-args)      SYNC_ARGS="${2:?}"; shift 2 ;;
        --no-setup)       SETUP=""; shift ;;
        --run)            RUN="${2:?}"; shift 2 ;;
        --job)            JOB="${2:?}"; ATTACHED=1; KEEP=1; shift 2 ;;
        --terminate)      KEEP=0; shift ;;
        --shell)          SHELL_AFTER=1; shift ;;
        --keep)           KEEP=1; KEEP_EXPLICIT=1; shift ;;
        --batch)          MODE="batch"; shift ;;
        --interactive)    MODE="interactive"; shift ;;
        -l|--list-instances)
                          LIST=1
                          # The pattern is optional, so only swallow the next
                          # argument when it cannot be a flag of our own.
                          if [ $# -gt 1 ] && [[ "$2" != -* ]]; then LIST_FILTER="$2"; shift; fi
                          shift ;;
        -n|--dry-run)     DRY=1; shift ;;
        -h|--help)        usage; exit 0 ;;
        --)               shift; COMMAND=("$@"); break ;;
        -*)               die "unknown option $1 (--help)" ;;
        *)                COMMAND=("$@"); break ;;
    esac
done

# The name to blame in an error. The wrappers export their own so the advice
# names the command that was actually typed.
SELF="${DX_WRAPPER_NAME:-scripts/dnanexus/$(basename "${BASH_SOURCE[0]:-$0}")}"

case "$MODE" in
    batch)
        # Batch's whole promise is that it finishes and stops costing money, so
        # the two flags that break that promise are refused rather than ignored.
        [ ${#COMMAND[@]} -gt 0 ] || die "$SELF needs a program to run:
       $SELF --time 1h -- novelty screen calls.vcf '\$OUT/hits.tsv'
       For a terminal instead, use the matching dx-instance-*.sh."
        [ "$SHELL_AFTER" = 0 ] || die "--shell contradicts $SELF, which never opens one.
       Use the matching dx-instance-*.sh, or scripts/dnanexus/dx-instance.sh --shell."
        [ "$KEEP_EXPLICIT" = 0 ] || die "--keep contradicts $SELF: it would leave the box
       billing after the program finished. Use scripts/dnanexus/dx-instance.sh --keep."
        # --job set KEEP=1 on our behalf. Batch terminates what it attaches
        # to -- that is the mode -- but silently killing a box someone else is
        # using is not a thing to discover afterwards, so say it up front.
        if [ "$ATTACHED" = 1 ]; then
            warn "--batch will TERMINATE $JOB when the program is done, even"
            warn "  though you attached to it. Use scripts/dnanexus/dx-instance.sh --job"
            warn "  --keep to run something on a box and leave it up."
        fi
        KEEP=0
        ;;
    interactive)
        [ ${#COMMAND[@]} -eq 0 ] || die "$SELF opens a terminal and takes no command.
       To run '${COMMAND[*]}' and come straight back, use the matching
       dx-batch-*.sh, which terminates the box when the program is done."
        ;;
esac

[[ "$TIME" =~ ^[0-9]+[smhd]$ ]] || die "--time $TIME: want a number and s/m/h/d, e.g. 2h"
[ -z "$SETUP" ] || [ -f "$SETUP" ] || die "--setup $SETUP: no such file"

# The four settings below are the entire contract with the worker: they are
# interpolated into a remote command string, and a bad one does not fail there,
# it arrives as a plausible wrong value. The worker re-checks all of them, but
# it can only do so after a boot -- so reject them here, where the cost of being
# wrong is a retyped command instead of a provisioned instance.
if [ -n "$SETUP" ]; then
    [ -n "$BRANCH" ] || die "--branch is empty"
    [ -n "$REPO_URL" ] || die "REPO_URL is empty"
    case "$BRANCH" in
        *[[:space:]]*) die "--branch '$BRANCH': a branch name cannot contain whitespace" ;;
    esac
    case "$REPO_DIR" in
        *[[:space:]]*) die "REPO_DIR '$REPO_DIR': no whitespace, it is a path on the worker" ;;
        /*) ;;
        *) die "REPO_DIR '$REPO_DIR' must be absolute -- the worker cd's to it from \$HOME" ;;
    esac
    # `uv sync` flags, not a bare word: --sync-args "dx" is a plausible typo for
    # --sync-args "--group dx" and uv would reject it an environment build later.
    case "${SYNC_ARGS:--}" in
        -*) ;;
        *) die "--sync-args '$SYNC_ARGS': expected uv sync flags, e.g. '--group dx'" ;;
    esac
fi
: "${OUTPUT_DIR:=$REPO/data/dx/$RUN}"

# --- platform plumbing --------------------------------------------------------
# Always `uv run dx`: .venv/bin is not on PATH, so a bare `dx` gives
# "command not found" even when dxpy is correctly installed.
DX=(uv run dx)

dx_do() {
    if [ "$DRY" = 1 ]; then echo "+ dx $*" >&2; return 0; fi
    "${DX[@]}" "$@"
}

# shellcheck source=scripts/dnanexus/dx-env.sh
source "$REPO/scripts/dnanexus/dx-env.sh" || die "could not authenticate; see docs/scripts/DNANexus.md"
PROJECT="${DX_PROJECT_CONTEXT_ID:?dx-env.sh did not pin a project}"

# --- what can we even ask for? ------------------------------------------------
# The project's availableInstanceTypes is the list the platform validates a
# launch against: a name that is not in it is refused outright, before anything
# is created, with "Requested instance type ... is unavailable from the cloud
# provider". So this is the honest answer to "what can we run", and it is read
# live rather than pasted into a table that goes stale.
#
# Every one of the 98 names in it was submitted for real on 2026-08-27 (job
# created, then terminated while still idle, so nothing was provisioned and
# nothing was billed): 97 were accepted and one was refused. The refusal is
# annotated below -- the catalog is the entitlement, but not quite the last word.
if [ "$LIST" = 1 ]; then
    uv run --group dx --no-sync python - \
        "$PROJECT" "$LIST_FILTER" "$INSTANCE" "$GPU_INSTANCE" <<'PYLIST'
import re
import sys

import dxpy

project, pattern, cpu_default, gpu_default = sys.argv[1:5]
catalog = dxpy.api.project_describe(
    project, {"fields": {"availableInstanceTypes": True}}
)["availableInstanceTypes"]

# From the submit test described above. Anything not named here was accepted.
REFUSED = {
    "mem3_ssd2_gpu8_x96": "refused: the workstation app wants nvidiaDriver R535",
}
# Boot-verified, not merely accepted: these two have run a command end to end.
BOOTED = {"mem1_ssd1_v2_x4", "mem2_ssd2_gpu1_v2_x8"}

FAMILY = {"mem1": "lean RAM", "mem2": "balanced RAM", "mem3": "big memory"}


def describe(name):
    """A one-line 'what is this for', built from the name."""
    bits = []
    gpu = re.search(r"gpu(\d*)", name)
    if gpu:
        count = int(gpu.group(1) or 1)
        if "gpu1_v2" in name or "gpu1_x" in name:
            model = "L4 24 GB"
        elif "_gpu_" in name:
            model = "T4, sm_75 -- too old for current CUDA wheels"
        else:
            model = "model unverified"
        bits.append(f"{count}x GPU ({model})")
    bits.append(FAMILY.get(name.split("_")[0], "unknown family"))
    if "hdd" in name:
        bits.append("spinning disk: cheap per GB, slow")
    elif re.search(r"ssd[23]", name):
        bits.append("extra SSD")
    if "_v2" not in name and "_v3" not in name:
        bits.append("older generation")
    return ", ".join(bits)


rows = []
for name, spec in catalog.items():
    if pattern and pattern not in name:
        continue
    marks = []
    if name == cpu_default:
        marks.append("<- default")
    if name == gpu_default:
        marks.append("<- --gpu")
    if name in BOOTED:
        marks.append("[boot-verified]")
    if name in REFUSED:
        marks.append("[%s]" % REFUSED[name])
    rows.append((
        "gpu" in name,
        name.split("_")[0],
        spec["numCores"],
        name,
        spec["totalMemoryMB"] // 1000,
        spec["ephemeralStorageGB"],
        describe(name),
        " ".join(marks),
    ))

if not rows:
    print(f"no instance type in {project} matches '{pattern}'", file=sys.stderr)
    raise SystemExit(1)

print(f"Instance types this project may launch ({len(rows)} of {len(catalog)} shown)\n")
for is_gpu, group in ((True, "GPU"), (False, "CPU")):
    here = sorted(r for r in rows if r[0] is is_gpu)
    if not here:
        continue
    print(group)
    for _, _, cores, name, ram, disk, what, marks in here:
        print(f"  {name:<24} {cores:>3} core{'s' if cores != 1 else ' '}"
              f" {ram:>5} GB RAM {disk:>5} GB disk"
              f"  {what}{'  ' + marks if marks else ''}")
    print()

print("Every name above was submitted for real on 2026-08-27 and accepted, except")
print("any marked refused. A name NOT in this list is rejected at submit with")
print('"Requested instance type ... is unavailable from the cloud provider" --')
print("nothing is created, so it costs a relaunch and not money.")
print("Only terminating stops the billing; see docs/scripts/DNANexus.md.")
PYLIST
    exit $?
fi

# --- preflight ----------------------------------------------------------------
# Everything cheap that can fail goes here, because past this point the meter is
# running: a missing SSH key or an unpushed branch discovered after launch costs
# real money to discover.
if [ "$ATTACHED" = 0 ]; then
    [ -f "$HOME/.dnanexus_config/ssh_id" ] \
        || die "no SSH key pair. Run 'uv run dx ssh_config' once, then retry.
       Without it the worker boots, starts billing, and only then refuses you."
fi

if [ -n "$SETUP" ] && [ "$ATTACHED" = 0 ]; then
    # The worker clones from GitHub, so it runs what is *pushed*, not what is in
    # this checkout. A branch that does not exist there is a guaranteed failure
    # ten minutes and one boot from now.
    remote_head="$(git -C "$REPO" ls-remote --heads "$REPO_URL" "$BRANCH" 2>/dev/null | cut -f1)"
    [ -n "$remote_head" ] || die "branch '$BRANCH' does not exist at $REPO_URL.
       Push it first -- the worker clones from GitHub, not from this checkout --
       or pass '--branch main', or '--no-setup' to skip the clone entirely."
    local_head="$(git -C "$REPO" rev-parse HEAD 2>/dev/null)"
    if [ "$remote_head" != "$local_head" ]; then
        warn "the worker will run ${remote_head:0:8} ($BRANCH on GitHub), not your"
        warn "  local HEAD ${local_head:0:8}. Push if you meant to test local changes."
    fi
    # Matching HEADs are not enough: uncommitted work is invisible to a clone,
    # and this is the cheap moment to notice that the code you have been editing
    # is not the code about to spend an hour of compute.
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
[ -n "$SETUP" ] && log "setup        $(basename "$SETUP") on $BRANCH -> $REPO_DIR"
[ -n "$SETUP" ] && [ -n "$SYNC_ARGS" ] && log "sync args    $SYNC_ARGS"
[ ${#COMMAND[@]} -gt 0 ] && log "command      ${COMMAND[*]}"

# Scratch file for remote output, so it can be both shown live and grepped for
# the sentinel afterwards. Removed by the same trap that terminates the box.
remote_log="$(mktemp)"

# --- terminate on the way out, whatever the way out is ------------------------
cleanup() {
    local rc=$?
    trap - EXIT INT TERM
    rm -f "$remote_log"
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
    log "waiting for state=running (a few minutes) ..."
    for _ in $(seq 1 120); do
        state="$("${DX[@]}" describe "$JOB" 2>/dev/null | awk '$1=="State"{print $2}')"
        case "$state" in
            running) break ;;
            failed|terminated|terminating) die "job went to '$state' before it started" ;;
        esac
        sleep 10
    done
    [ "${state:-}" = "running" ] || die "job never reached 'running' (last: ${state:-unknown})"

    # Keep the last attempt's output. Discarding it turns every connection
    # problem into the same opaque timeout, and the next attempt costs another
    # instance boot to learn nothing again -- an unpublished host key, a
    # firewall that did not open, and a missing key pair all look identical
    # from out here, and they have different fixes. Both streams are kept:
    # dx ssh writes its progress and most of its complaints to STDOUT, so a
    # check that watched only stderr saw an empty string on every failure.
    log "waiting for ssh (up to $((SSH_TRIES * SSH_WAIT / 60)) min) ..."
    ready=0
    ssh_log="$(mktemp)"
    for attempt in $(seq 1 "$SSH_TRIES"); do
        "${DX[@]}" ssh "$JOB" -T "echo $OK" >"$ssh_log" 2>&1
        if grep -q "$OK" "$ssh_log"; then ready=1; break; fi
        if [ $((attempt % 12)) = 0 ]; then
            log "  still waiting (${attempt}/${SSH_TRIES}): $(grep -v '^$' "$ssh_log" | tail -1 | cut -c1-100)"
        fi
        sleep "$SSH_WAIT"
    done
    if [ "$ready" != 1 ]; then
        warn "last ssh attempt said:"
        sed 's/^/  | /' "$ssh_log" >&2
        rm -f "$ssh_log"
        die "ssh never came up after $((SSH_TRIES * SSH_WAIT / 60)) min. The job is
       running and billing; try 'uv run dx ssh $JOB' by hand, or terminate it.
       Raise SSH_TRIES if the box is simply slow today."
    fi
    rm -f "$ssh_log"
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
    # The caller's script, plus a trailing sentinel that is only reached if the
    # script's own exit status was 0. `remote` then returns based on whether the
    # sentinel came back, because dx ssh's own status is meaningless (see $OK).
    local script rc
    script="$(cat)"
    "${DX[@]}" ssh "$JOB" -T "bash -l -s" <<REMOTE_WRAPPER 2>&1 | tee "$remote_log" >&2
$script
__rc=\$?
[ \$__rc = 0 ] && echo "$OK"
exit \$__rc
REMOTE_WRAPPER
    grep -q "$OK" "$remote_log"
    rc=$?
    : > "$remote_log"
    return $rc
}

# --- build the environment ----------------------------------------------------
# Nothing on a workstation survives the session, so the checkout and the venv are
# built fresh every time. --no-setup skips it when you want the bare box.
if [ -n "$SETUP" ]; then
    log "setting up the worker ($(basename "$SETUP"); a few minutes) ..."
    # Exactly one shell evaluation happens on the far side of `dx ssh`, so each
    # value is quoted for it with printf %q rather than wrapped in single quotes
    # and hoped for. The old form broke on any value containing a quote, and
    # SYNC_ARGS -- which has spaces by design -- would have arrived as separate
    # words, silently dropping every flag after the first.
    remote_env="$(printf 'BRANCH=%q REPO_URL=%q REPO_DIR=%q SYNC_ARGS=%q' \
        "$BRANCH" "$REPO_URL" "$REPO_DIR" "$SYNC_ARGS")"
    if [ "$DRY" = 1 ]; then
        echo "+ dx ssh $JOB -T '$remote_env bash -s' < $SETUP" >&2
    else
        # The setup script ends with a "=== READY ===" banner, which is the
        # signal used here -- it is fed on stdin, so there is no room to append
        # a sentinel to it the way remote() does.
        "${DX[@]}" ssh "$JOB" -T "$remote_env bash -s" \
            < "$SETUP" 2>&1 | tee "$remote_log" >&2
        if ! grep -q "=== READY ===" "$remote_log"; then
            # A failed build is fatal for a command that needs the venv, but not
            # for a shell: you asked for a box, the box is up and billing, and
            # fixing the environment by hand is exactly what a shell is for.
            if [ ${#COMMAND[@]} -gt 0 ]; then
                die "environment build failed; the box is still up, attach with:
       uv run dx ssh $JOB"
            fi
            warn "environment build failed -- opening the shell anyway."
        fi
        : > "$remote_log"
    fi
fi

# --- run the command ----------------------------------------------------------
if [ ${#COMMAND[@]} -gt 0 ]; then
    log "running the command ..."
    remote <<EOF || die "the command failed. The box is still up until this script
       exits; attach with 'uv run dx ssh $JOB' to look at it."
set -uo pipefail
export OUT="$REMOTE_OUT"
mkdir -p "\$OUT" || exit 1
# The checkout and its venv if setup built them; \$HOME if it did not.
[ -d "$REPO_DIR/.venv/bin" ] && export PATH="$REPO_DIR/.venv/bin:\$PATH"
cd "$REPO_DIR" 2>/dev/null || cd /home/dnanexus || exit 1
echo "[worker] \$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo 'cpu only')"
echo "[worker] cwd \$PWD, OUT=\$OUT"
${COMMAND[*]}
EOF
    log "command finished."
fi

# --- interactive shell --------------------------------------------------------
# Before the fetch, not after: whatever you make in here is in $OUT too, and
# comes home with everything else.
if [ ${#COMMAND[@]} -eq 0 ] || [ "$SHELL_AFTER" = 1 ]; then
    [ -n "$SETUP" ] && log "opening a shell. The repo is at $REPO_DIR; use .venv/bin/... rather"
    [ -n "$SETUP" ] && log "  than 'uv run', which resyncs and undoes anything you pip-installed."
    log "\$OUT is $REMOTE_OUT -- anything you leave there is fetched when you exit."
    log "Exiting TERMINATES the box. Answer 'n' to dx's own prompt on the way"
    log "  out -- this script does the terminating, and confirms it."
    if [ "$DRY" = 1 ]; then
        echo "+ dx ssh $JOB" >&2
    else
        # mkdir here too: with --no-setup nothing else has created $OUT, and a
        # shell that has to mkdir its own output directory loses what it wrote.
        "${DX[@]}" ssh "$JOB" -T "mkdir -p '$REMOTE_OUT'" >/dev/null 2>&1
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
