# Running on DNAnexus (`dx`)

**Authenticate the `dx` CLI, keep jobs billed to the hackathon org rather than
to you, get a machine, work on it interactively, and stop it when you are done.**

| | |
|---|---|
| Project | `Group2_2026` = `project-JB6zg5Q0pzX96qVJjz7gKg58` |
| Region | `aws:us-east-1` |
| Billed to | `org-baylor_hackathon_2020_sales` — the hackathon org, not you |
| Your level | `CONTRIBUTE` — can read, write, and launch jobs |
| GPU to ask for | `mem2_ssd2_gpu1_v2_x8` — 1× L4, 24 GB (see [Instance types](#instance-types)) |
| Job priority | `normal`; `low` is refused for this `billTo`, and `--allow-ssh` forces `high` |

## Quick start

```bash
# 1. put your API token in .env (once) -- see Credentials
cp .env.example .env && chmod 600 .env && $EDITOR .env

# 2. install the dx toolkit into the project venv (once)
uv sync --group dx

# 3. authenticate and pin the project (every new shell) -- see Authenticating
source scripts/dx-env.sh

# 4. check it worked
uv run dx whoami
uv run dx ls /

# 5. see what this project may launch, and what each type is for
scripts/dx-instance.sh --list-instances

# 6. rent a box, get a terminal on it, and terminate it when you exit
scripts/dx-instance.sh --time 1h
```

Step 6 is [one command for the whole session](#the-whole-session-in-one-command);
the sections after it are what that command automates, and what to do when it
does not fit.

## Credentials

Generate a token at
[platform.dnanexus.com](https://platform.dnanexus.com) → Profile → API Tokens.
Scope it to `Group2_2026` at **CONTRIBUTE**: most jobs have to write results
back, so a `VIEW` token authenticates fine and then fails at the last step.
Prefer a short expiry — this is a bearer credential stored in cleartext.

Put it in `.env` at the repo root:

```bash
DX_API_TOKEN=<your token>
DX_PROJECT_NAME=Group2_2026
DX_PROJECT_ID=project-JB6zg5Q0pzX96qVJjz7gKg58
```

`.env` is gitignored (`.gitignore`, under *Environments*); `.env.example` is the
committed template. Never put a real token in `.env.example`. `chmod 600 .env`.

The id is what gets exported. `DX_PROJECT_NAME` is only used to look one up when
`DX_PROJECT_ID` is empty — convenient if you are pointing the scripts at a
different project, one API call slower, and ambiguous if two projects share a
name (the first hit wins, and `dx` sorts by descending permission).

## Installing

`dxpy` is already declared in `pyproject.toml`, in the `dx` dependency group —
you only have to sync it in:

```bash
uv sync --group dx
```

It is a **group**, not a runtime dependency, because nothing under `src/`
imports it and DNAnexus workers already ship the `dx` CLI. It is not in `dev`
either: `uv sync` installs `dev` by default, and this is only useful if you have
a token.

> **Trap.** `uv sync` resyncs to exactly the extras and groups you name, and
> silently *uninstalls* the ones you omit — so a plain `uv sync` removes `dxpy`
> again. `scripts/dx-env.sh` notices and puts it back, because the failure
> otherwise surfaces much later as an opaque `Failed to spawn: dx`.

## Authenticating

The `dx` CLI does **not** read `.env`. It reads `DX_SECURITY_CONTEXT` — a JSON
blob, not the bare token — or `~/.dnanexus_config`. Exporting `DX_API_TOKEN`
alone produces a misleading `At least VIEW permission is required to search
within a project`, which is an auth failure, not a permissions problem.

`scripts/dx-env.sh` does all three exports — the credential, the project pin
(`DX_PROJECT_CONTEXT_ID`, see [Pinning the project](#pinning-the-project)), and
the warning filter — so sourcing it is the whole of setup for a new shell:

```bash
source scripts/dx-env.sh
```

Equivalently, by hand:

```bash
export PYTHONWARNINGS=ignore::SyntaxWarning
export DX_SECURITY_CONTEXT="{\"auth_token_type\":\"Bearer\",\"auth_token\":\"$(awk -F= '/^DX_API_TOKEN=/{print $2}' .env)\"}"
export DX_PROJECT_CONTEXT_ID=project-JB6zg5Q0pzX96qVJjz7gKg58
```

Or log in once, writing `~/.dnanexus_config` so it persists across shells:

```bash
uv run dx login --token "$(awk -F= '/^DX_API_TOKEN=/{print $2}' .env)" --noprojects
uv run dx select project-JB6zg5Q0pzX96qVJjz7gKg58
```

The export route is preferred: the token stays only in `.env`, and
`DX_PROJECT_CONTEXT_ID` does what `dx select` does without writing a second copy
of the credential to your home directory.

`PYTHONWARNINGS` is not housekeeping — dxpy's own regexes raise `SyntaxWarning`
on 3.13, and without it every `dx` call prints ~18 lines of noise first.

> **Trap.** Always `uv run dx`, never bare `dx`. `.venv/bin` is not on `PATH`, so
> a correctly installed dxpy still gives `bash: dx: command not found`. That
> error means your `PATH`, not your install.

## Pinning the project

Pinning is about **billing**, not convenience. Compute bills to the `billTo` of
the project a job *runs in*. `Group2_2026` bills to
`org-baylor_hackathon_2020_sales`, so anything launched there spends org credits
and needs no extra setup.

Any project *you create*, though, defaults to your personal `billTo` and you pay.

`source scripts/dx-env.sh` already pins you to `Group2_2026` by exporting
`DX_PROJECT_CONTEXT_ID`, and that covers every `dx ls`/`download`/`upload`. It is
enough for `dx run` too — but only as ambient context, which is easy to lose to
a stray `dx select` or a shell you forgot to source. For anything that spends
money, name the project on the command as well:

```bash
uv run dx run ... --destination project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/<yours>/
```

`--destination` sets both where output lands and which project the job runs in —
it is the field that decides who pays, and it does not depend on your
environment. Confirm on any job or project:

```bash
uv run dx describe <job-id> | grep "Billed to"
# Billed to     org-baylor_hackathon_2020_sales
```

If that says `user-...` rather than `org-...`, you are paying for it.

You do not need org membership to launch jobs; `CONTRIBUTE` on the project grants
that. Membership would only let you read the credit balance, so ask an org admin
if you need to know what is left.

## Files in and out

```bash
uv run dx ls /survivor/                      # browse
uv run dx ls -l /merge-svs/reference/        # with sizes and IDs
uv run dx find data --name "*.vcf" --class file

uv run dx download -f /survivor/HPRC_SV.survivor.vcf
uv run dx download -r /resources/            # -r for a whole folder

uv run dx upload results.tsv --destination /Results/<yours>/
```

Paths are relative to the pinned project. Prefix with
`project-JB6zg5Q0pzX96qVJjz7gKg58:` to be explicit. The same commands work
unchanged *on* a worker, which inherits the job's credentials.

## Instance types

Ask the wrapper rather than guessing — it reads the project's catalog live and
says what each type is:

```bash
scripts/dx-instance.sh --list-instances        # all 98
scripts/dx-instance.sh --list-instances gpu    # just the GPU boxes
```

```
GPU
  mem2_ssd2_gpu1_v2_x8       8 cores    32 GB RAM   421 GB disk  1x GPU (L4 24 GB), balanced RAM, extra SSD  <- --gpu [boot-verified]
  mem2_ssd1_gpu_x16         16 cores    66 GB RAM   210 GB disk  1x GPU (T4, sm_75 -- too old for current CUDA wheels), balanced RAM, older generation
```

The ones worth knowing by name:

| Instance | GPU | Cores | RAM | Disk | For |
|---|---|---:|---:|---:|---|
| `mem1_ssd1_v2_x4` | — | 4 | 8 GB | 93 GB | the default: a shell, a small job |
| `mem2_ssd1_v2_x8` | — | 8 | 32 GB | 279 GB | CPU work that needs memory |
| `mem2_ssd2_gpu1_v2_x8` | 1× L4, 24 GB | 8 | 32 GB | 421 GB | the GPU default (`--gpu`) |
| `mem3_ssd1_gpu1_x16` | 1× L4, 24 GB | 16 | 128 GB | 560 GB | same GPU, more host RAM and disk |

**The project catalog is the entitlement.** `availableInstanceTypes` on the
project is the list the platform validates a launch against, and every one of
its 98 entries was submitted for real on 2026-08-27 — job created, then
terminated while still `idle`, so nothing was provisioned and nothing was
billed. 97 were accepted. The exceptions, in both directions:

- `mem3_ssd2_gpu8_x96` is in the catalog and is still refused, by the
  workstation app rather than the platform: `InvalidInput: Requested
  instanceType (mem3_ssd2_gpu8_x96) does not support requested nvidiaDriver
  (R535)`.
- A name **outside** the catalog is refused at submit —
  `InvalidInput: Requested instance type mem3_ssd1_gpu_x8 is unavailable from
  the cloud provider` — and a name that is not a type at all gives
  `not a recognized instance type`. Neither creates anything, so a wrong guess
  costs a relaunch and not money.

Two more things testing turned up:

- Accepted at submit is not the same as *booted*. `mem1_ssd1_v2_x4` and
  `mem2_ssd2_gpu1_v2_x8` have run a command end to end and are marked
  `[boot-verified]` in the listing; the rest are known-launchable, not known-good.
- **Low priority is not available for this `billTo`.** `--priority low` fails
  with `PermissionDenied: Low priority is not available for your billTo`, so
  jobs run at `normal`, and `--allow-ssh` forces `high`.

`mem2_ssd1_gpu_*` are T4s: sm_75, below the sm_80 that current CUDA wheels
expect. They launch, then fail at the first kernel. The listing says so on the
row.

From a Nextflow pipeline, request the type by name — `machineType` overrides
`cpus`/`memory`/`disk`, and setting only `cpus`/`memory` never selects a GPU:

```groovy
process {
    withName: 'MY_GPU_STEP' {
        machineType = 'mem2_ssd2_gpu1_v2_x8'
        time        = '24 h'
    }
}
```

## The whole session in one command

`scripts/dx-instance.sh` does everything the rest of this document describes by
hand: launch a box, build this project's environment on it, give you a terminal
(or run your command), bring the results back, and **terminate**. The last step
is the reason it exists — termination sits in an `EXIT` trap, so it fires on
success, on failure and on Ctrl-C alike, which is the failure mode that actually
costs money.

```bash
scripts/dx-instance.sh --time 1h
```

That is the interactive case: a CPU box, this branch checked out, the venv built,
and a shell. **Exiting the shell terminates the box**, and anything you left in
`$OUT` is downloaded first.

With a command after `--` it runs that instead, and the shell never opens:

```bash
scripts/dx-instance.sh --time 2h --output-dir data/dx/run1 \
    --input /TRFoutput/HPRC-survivor/HPRC_SV.survivor.ins.trf.tsv -- \
    'novelty --platform ucsc annotate \
        /home/dnanexus/HPRC_SV.survivor.ins.trf.tsv "$OUT/novelty.tsv"'
```

The whole command is one quoted argument there because it contains `$OUT` and a
redirection target the *worker's* shell has to expand, not yours.

`--dry-run` prints every platform call it would make — including the full text
of the scripts it would send to the worker — and launches nothing. Use it to
check a long invocation before it starts billing.

| Flag | | Default |
|---|---|---|
| `-t, --time` | `max_session_length`; also the backstop if this script is killed | `2h` |
| `-i, --instance` | instance type ([the table above](#instance-types)) | `mem1_ssd1_v2_x4` |
| `-g, --gpu` | shorthand for `-i mem2_ssd2_gpu1_v2_x8` | off |
| `-l, --list-instances` | print what this project may launch, and exit; takes an optional substring filter | — |
| `-f, --input` | stage a platform file into `/home/dnanexus`; repeatable. Takes a `file-xxxx` id **or** a project path, resolved before launch | — |
| `-o, --output-dir` | local directory the results land in | `data/dx/<run>` |
| `-r, --remote-out` | directory on the worker the command writes to, exported as `$OUT` | `/home/dnanexus/out` |
| `-d, --destination` | project folder the results are uploaded to | `/Results/<you>/<run>/` |
| `-b, --branch` | branch the worker clones | your current branch |
| `--setup` | environment build to run on the worker | `scripts/setup-worker.sh` |
| `--no-setup` | leave the box as it boots: no clone, no uv, no venv | off |
| `--job` | attach to a job already running instead of launching one; implies `--keep` | — |
| `--shell` | open an interactive shell after the command, before the fetch | off |
| `--keep` | do **not** terminate at the end (it keeps billing) | off |
| `-n, --dry-run` | print the platform calls instead of running them | off |

Four things it does that are easy to forget by hand:

- **Preflight before the meter starts.** It checks for the SSH key pair, that
  `$BRANCH` exists on GitHub, and whether this checkout has uncommitted changes
  — the worker clones from GitHub, so local edits are *not* there. Discovering
  any of these after launch costs a boot.
- **Two separate waits.** `state=running` means the instance exists; the SSH
  host key is published minutes later. It waits for both.
- **`$OUT`, and the venv on `PATH`.** The command runs in the checkout with
  `.venv/bin` first, so `novelty` and `python -m ...` resolve without `uv run`.
  Quote `'$OUT'` so your shell leaves it for the worker's.
- **Worker → project → here.** Results go to project storage first and are
  downloaded from there, so they outlive the box even if the local download
  fails. `--destination` is also what decides who pays.

The command is joined with spaces and handed to a login `bash` on the worker,
exactly as `ssh` does, so pipes and redirection work and anything containing
spaces needs quoting twice.

## Setting up a worker

`scripts/setup-worker.sh` is what `dx-instance.sh` runs on the box before your
command: it installs `uv`, clones the branch **from GitHub** — nothing on a
workstation survives the session, and the box has no copy of your laptop — and
syncs `uv.lock` into `.venv`. It is idempotent, takes extras and groups through
`SYNC_ARGS`, and can be run by hand against any box:

```bash
uv run dx ssh "$JOB" -T "bash -s" < scripts/setup-worker.sh
```

Afterwards call `.venv/bin/...` directly rather than `uv run`: `uv run` resyncs
to `uv.lock` first, which removes anything you installed on top of it. A run
that needs a package the lock does not have — a CUDA wheel, say — should install
it after the sync and then never call `uv` again.

`--no-setup` skips all of it when you want the bare machine, and
`--setup other-script.sh` swaps in a different build. A setup script signals
success by printing `=== READY ===` as its last line; without that line
`dx-instance.sh` treats the build as failed (fatal for a command, a warning
before an interactive shell, since a shell is exactly where you would fix it).

### `dx ssh` exit codes are meaningless

**`dx ssh` always exits non-zero, however well the remote command ran.** On the
way out it asks `Job job-... is still running. Terminate now? [y/N]`, reads EOF
as N, and reports that as failure:

```bash
uv run dx ssh "$JOB" -T "echo REMOTE_OK"
# REMOTE_OK          <- the command ran perfectly
# Job job-... is still running. Terminate now? [y/N]:
# $? == 1
```

Verified against a live worker: a session that printed `REMOTE_OK`, its hostname
and `NVIDIA L4` exited 1, and so did one running nothing but `true`.

So **never gate anything on `$?`**. Have the far side print a sentinel and grep
for it — which is what `dx-instance.sh` does in all three places that would
otherwise check the status: the ssh-readiness probe, the environment build, and
the command/upload step.

It also writes progress and most complaints to **stdout, not stderr**, so a wait
loop capturing only stderr sees an empty string on every failed attempt.

## Connecting to the job by hand

Interactive work goes through `app-cloud_workstation`: it boots the instance and
holds it open for `max_session_length` so you can SSH in. `dx-instance.sh` uses
it too; this is what it is doing underneath.

**Set up your SSH key first.** `dx` needs a key pair at
`~/.dnanexus_config/ssh_id[.pub]`, and it will not create one at connect time:

```bash
uv run dx ssh_config     # once per machine; generates the pair and uploads it
```

Skip it and the worker boots, starts billing, and *then* the connection fails.

### Launch and attach in one step

```bash
uv run dx run app-cloud_workstation \
    --instance-type mem1_ssd1_v2_x4 \
    -imax_session_length=2h \
    --destination project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/<yours>/ \
    --yes --ssh
```

`--ssh` waits for the job to reach `running`, opens the firewall to your current
IP, and drops you into a shell.

### Launch now, connect later

`--allow-ssh` does everything `--ssh` does except attach, so the job keeps
running when you close the terminal:

```bash
JOB=$(uv run dx run app-cloud_workstation \
    --instance-type mem1_ssd1_v2_x4 \
    -imax_session_length=2h \
    --destination project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/<yours>/ \
    --allow-ssh --yes --brief)

uv run dx describe "$JOB" | head            # wait for state: running
uv run dx ssh "$JOB"                        # attach, as often as you like
```

`dx ssh` re-opens the firewall for whatever IP you are on now, so reconnecting
from a different network works; `--no-firewall-update` skips that. Arguments
after the job id go straight to the SSH client, which is how you forward a port:

```bash
uv run dx ssh "$JOB" -L 8888:localhost:8888   # e.g. a notebook on the worker
```

`scripts/dx-instance.sh --job "$JOB"` attaches to a box launched this way and
gives you its fetch-and-terminate machinery; it implies `--keep`, so add
`--terminate` if you want it stopped on the way out.

Both `--ssh` and `--allow-ssh` force `--priority high`, so the worker is not
preemptible — and is billed accordingly.

### While it runs

```bash
uv run dx watch "$JOB"        # stream the job log
uv run dx describe "$JOB"     # state, instance type, billTo, runtime so far
```

**Nothing on the box survives the session.** Install, run, and `dx upload` the
results before it stops; anything not uploaded is gone.

## Stopping an instance

A workstation bills for wall-clock time until `max_session_length` expires or you
terminate it — whether or not anyone is connected, and whether or not it is doing
any work. Closing your SSH session does **not** stop it.

```bash
uv run dx terminate job-XXXXXXXXXXXXXXXXXXXXXXXX
```

That is the whole thing: no confirmation prompt, effective immediately, and it
accepts several job ids at once. There is no stop-and-resume — terminating is the
only off switch, and it destroys the box.

### Recovering the job id

```bash
uv run dx find jobs --user self --state running --origin-jobs
```

Empty output means you have nothing running.

> **Trap.** `--user self` is not optional. Plain `dx find jobs` lists the **whole
> team's** jobs, and terminating a teammate's run cannot be undone. Each entry
> prints the launching username on its second line — read it before you
> terminate anything you did not start.

### Confirming it stopped

`dx terminate` prints nothing on success, and the state does not flip instantly:

```bash
uv run dx describe "$JOB" | grep "^State"
# State    terminating   <- still billing
# State    terminated    <- done
```

Re-run until it reads `terminated`. Only that ends the billing. `dx-instance.sh`
polls this for you and says which state it saw.

### From inside the session

The worker exports its own job id, so you can shut the box down from the shell
you are sitting in:

```bash
dx terminate "$DX_JOB_ID"
```

> **Trap.** Typing `exit` in a `dx ssh` session asks `Job job-... is still
> running. Terminate now? [y/N]` — and the default is **N**. Press enter out of
> habit, or lose the terminal before answering, and the instance keeps billing
> with nobody attached. Answer `y`, or terminate from your laptop afterwards.
> Under `dx-instance.sh` answer **n**: the script terminates the box itself and
> confirms the state, and its own fetch step still has to run.

### Shortening the clock instead

From inside the session, `dx-set-timeout` resets `max_session_length` counting
from now:

```bash
dx-set-timeout 30m    # cap the damage if you forget to terminate
dx-set-timeout 8h     # extend, rather than losing a long run
```

It is a backstop, not a substitute: the box still bills for the whole time you
leave on the clock.

## Sources

- [Command Line Quickstart](https://documentation.dnanexus.com/getting-started/cli-quickstart) — `dx login`, `dx select`, `dx ls`/`upload`/`download`, `dx run`, `dx watch`
- [Connecting to Jobs](https://documentation.dnanexus.com/developer/apps/execution-environment/connecting-to-jobs) — `dx ssh_config`, `--allow-ssh`, `dx ssh`
- [Cloud Workstation](https://documentation.dnanexus.com/user/cloud-workstation) — `max_session_length`, `dx-set-timeout`
- [Running Nextflow Pipelines](https://documentation.dnanexus.com/user/running-apps-and-workflows/running-nextflow-pipelines) — `machineType`, instance-type precedence
