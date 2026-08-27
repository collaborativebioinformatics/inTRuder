# Running on DNAnexus (`dx`)

**Authenticate the `dx` CLI, keep jobs billed to the hackathon org rather than
to you, get a GPU worker, connect to it, and stop it when you are done.**

| | |
|---|---|
| Project | `Group2_2026` = `project-JB6zg5Q0pzX96qVJjz7gKg58` |
| Region | `aws:us-east-1` |
| Billed to | `org-baylor_hackathon_2020_sales` — the hackathon org, not you |
| Your level | `CONTRIBUTE` — can read, write, and launch jobs |
| GPU to ask for | `mem2_ssd2_gpu1_v2_x8` — 1× L4, 24 GB (see [Requesting a GPU](#requesting-a-gpu)) |

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
uv run dx ls project-JB6zg5Q0pzX96qVJjz7gKg58:/

# 5. rent a GPU, run something on it, fetch the results, terminate
scripts/dx-gpu-instance.sh --time 2h -- <command>
```

Step 5 is [one command for the whole run](#the-whole-run-in-one-command); the
sections after it are what that command automates, and what to do when it does
not fit.

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
```

`.env` is gitignored (`.gitignore`, under *Environments*); `.env.example` is the
committed template. Never put a real token in `.env.example`. `chmod 600 .env`.

## Installing

`dxpy` is already declared in `pyproject.toml`, in the `dx` dependency group —
you only have to sync it in:

```bash
uv sync --group dx
```

It is a **group**, not a runtime dependency, because nothing under `src/`
imports it and DNAnexus workers already ship the `dx` CLI. It is not in `dev`
either: `uv sync` installs `dev` by default, and this is only useful if you have
a token. `dxpy` has no upper Python bound (`requires-python >=3.8`) and works on
this project's 3.13.

> **Trap.** `uv sync` resyncs to exactly the extras and groups you name, and
> silently *uninstalls* the ones you omit. Name everything you want, every time:
>
> ```bash
> uv sync --group dx --extra notebook
> ```

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

## Requesting a GPU

Pick the instance type by name. Two are available to this project:

| Instance | GPU | VRAM | Cores | RAM | Disk |
|---|---|---:|---:|---:|---:|
| `mem2_ssd2_gpu1_v2_x8` | 1× L4 | 24 GB | 8 | 32 GB | 450 GB |
| `mem3_ssd1_gpu1_x16` | 1× L4 | 24 GB | 16 | 128 GB | 600 GB |

Default to `mem2_ssd2_gpu1_v2_x8`. Take `mem3_ssd1_gpu1_x16` when you want more
host RAM or disk behind the same GPU. *Verified 2026-08-27.*

```bash
uv run dx run <app> --instance-type mem2_ssd2_gpu1_v2_x8 \
    --destination project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/<yours>/ --yes
```

From a Nextflow pipeline, request it by name — `machineType` overrides
`cpus`/`memory`/`disk`, and setting only `cpus`/`memory` never selects a GPU:

```groovy
process {
    withName: 'MY_GPU_STEP' {
        machineType = 'mem2_ssd2_gpu1_v2_x8'
        time        = '24 h'
    }
}
```

> **Two traps.**
> - Any GPU type not in the table above — including every A10G box and anything
>   multi-GPU — fails at launch with `InvalidInput: The requested instance type
>   (...) is unavailable`. Nothing is created; just relaunch with a type from
>   the table.
> - `mem2_ssd1_gpu_x16` (T4) is the exception that *does* launch, then fails at
>   the first kernel launch: it is sm_75, below the sm_80 that current CUDA
>   wheels expect. Don't use it.

## The whole run in one command

`scripts/dx-gpu-instance.sh` does everything the rest of this document
describes by hand: launch a GPU box, build the Evo 2 environment on it, run your
command, bring the results back, and **terminate**. The last step is the reason
it exists — termination sits in an `EXIT` trap, so it fires on success, on
failure and on Ctrl-C alike, which is the failure mode that actually costs money.

```bash
scripts/dx-gpu-instance.sh --time 8h --output-dir data/evo/shard0 \
    --input /Test_Inputs/first_500_INS.vcf \
    --input /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
    --input /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
    python -m evo.embeddings \
        /home/dnanexus/first_500_INS.vcf \
        /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta \
        '$OUT' --offset 0 --limit 2000
```

With **no command** it builds the box and drops you into an interactive shell,
which is how to measure something before committing to a long run:

```bash
scripts/dx-gpu-instance.sh --time 1h
```

The shell runs *before* the fetch in both modes, so anything you leave in `$OUT`
comes home when you exit — and exiting terminates the box.

`--dry-run` prints every platform call it would make — including the full text
of the scripts it would send to the worker — and launches nothing. Use it to
check a long invocation before it starts billing.

| Flag | | Default |
|---|---|---|
| `-t, --time` | `max_session_length`; also the backstop if this script is killed | `2h` |
| `-i, --instance` | GPU type ([the table above](#requesting-a-gpu)) | `mem2_ssd2_gpu1_v2_x8` |
| `-f, --input` | stage a platform file into `/home/dnanexus`; repeatable. Takes a `file-xxxx` id **or** a project path, resolved before launch | — |
| `-o, --output-dir` | local directory the results land in | `data/evo/<run>` |
| `-r, --remote-out` | directory on the worker the command writes to, exported as `$OUT` | `/home/dnanexus/out` |
| `-d, --destination` | project folder the results are uploaded to | `/Results/<you>/<run>/` |
| `-b, --branch` | branch the worker clones | `feature/evo-embeds` |
| `--job` | attach to a job already running instead of launching one; implies `--keep` | — |
| `--shell` | open an interactive shell after the command, before the fetch | off |
| `--keep` | do **not** terminate at the end (it keeps billing) | off |
| `-n, --dry-run` | print the platform calls instead of running them | off |

Four things it does that are easy to forget by hand:

- **Preflight before the meter starts.** It checks for the SSH key pair, that
  `$BRANCH` exists on GitHub, and whether this checkout has uncommitted changes
  — the worker clones from GitHub, so local edits are *not* there. Discovering
  any of these after launch costs a GPU boot.
- **Two separate waits.** `state=running` means the instance exists; the SSH
  host key is published minutes later. It waits for both.
- **`$OUT`, and the venv on `PATH`.** The command runs in the checkout with
  `.venv/bin` first, so `evo-embed` and `python -m evo.embeddings` resolve
  without `uv run` — which would resync to `uv.lock` and uninstall flash-attn.
  Quote `'$OUT'` so your shell leaves it for the worker's.
- **Worker → project → here.** Results go to project storage first and are
  downloaded from there, so they outlive the box even if the local download
  fails. `--destination` is also what decides who pays.

The command is joined with spaces and handed to a login `bash` on the worker,
exactly as `ssh` does, so pipes and redirection work and anything containing
spaces needs quoting twice.

## Connecting to the job

Interactive work goes through `app-cloud_workstation`: it boots the instance and
holds it open for `max_session_length` so you can SSH in. This is also the way to
measure throughput before committing to a pipeline.

**Set up your SSH key first.** `dx` needs a key pair at
`~/.dnanexus_config/ssh_id[.pub]`, and it will not create one at connect time:

```bash
uv run dx ssh_config     # once per machine; generates the pair and uploads it
```

Skip it and the worker boots, starts billing, and *then* the connection fails.

### Launch and attach in one step

```bash
uv run dx run app-cloud_workstation \
    --instance-type mem2_ssd2_gpu1_v2_x8 \
    -imax_session_length=8h \
    --destination project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/<yours>/ \
    --yes --ssh
```

`--ssh` waits for the job to reach `running`, opens the firewall to your current
IP, and drops you into a shell. Check `nvidia-smi` before installing anything.

### Launch now, connect later

`--allow-ssh` does everything `--ssh` does except attach, so the job keeps
running when you close the terminal:

```bash
JOB=$(uv run dx run app-cloud_workstation \
    --instance-type mem2_ssd2_gpu1_v2_x8 \
    -imax_session_length=8h \
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

Re-run until it reads `terminated`. Only that ends the billing.

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
