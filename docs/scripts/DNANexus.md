# Running programs on DNAnexus

Get a terminal on a machine in the cloud, or run one program on it. The machine
receives a copy of this project, your results are copied back to your computer,
and the machine is then terminated.

Complete the [Setup](#setup) before your first run.

## Quick reference

```bash
# a terminal, for 30 minutes at most
scripts/dx-instance-cpu.sh -t 30m
scripts/dx-instance-gpu.sh -t 30m

# run one program, then return
scripts/dx-batch-cpu.sh -t 1h -- .venv/bin/python -m pytest -q
scripts/dx-batch-gpu.sh -t 30m -- nvidia-smi

# with an input file, and a directory for the results
scripts/dx-batch-cpu.sh -t 4h -o data/dx/screen1 \
    -f /survivor/HPRC_SV.survivor.vcf -- \
    novelty screen /home/dnanexus/HPRC_SV.survivor.vcf '$OUT/hits.tsv'
```

| Option | Function | Default |
|---|---|---|
| `-t, --time 4h` | Maximum lifetime of the machine. | `2h` |
| `-f, --input /survivor/x.vcf` | Copy a project file onto the machine. Repeatable. | none |
| `-o, --output-dir data/dx/run1` | Local directory for the results. | `data/dx/<run>` |
| `-b, --branch BRANCH` | Branch the machine clones. | your current branch |
| `--sync-args "--group dx"` | Extra flags for the machine's `uv sync`. | none |
| `-i, --instance TYPE` | Instance type. | see [Instance types](#instance-types) |
| `-n, --dry-run` | Print the commands. Start no machine. | off |

All four scripts accept these options. Use `--help` for the rest.

## Setup

1. Create the environment file.

   ```bash
   cp .env.example .env && chmod 600 .env
   ```

2. Create an API token.

   1. Open [platform.dnanexus.com](https://platform.dnanexus.com).
   2. Select your name, then **My Profile**.
   3. Select the **API Tokens** tab.
   4. Select **New Token**.
   5. Give the token CONTRIBUTE permission on the `Group2_2026` project.
   6. Set a short expiry date.
   7. Select **Generate Token**.
   8. Copy the token. The page shows it once.

   A VIEW token is not enough. It authenticates, and the run then fails when it
   uploads the results.

3. Write the token in `.env` after `DX_API_TOKEN=`. Never write a token in
   `.env.example`. That file is not gitignored.

4. Install the dx toolkit.

   ```bash
   uv sync --group dx
   ```

5. Register your SSH key. Do this once per computer.

   ```bash
   source scripts/dx-env.sh
   uv run dx ssh_config
   ```

6. Verify the setup.

   ```bash
   uv run dx whoami
   uv run dx ls /
   ```

Use `uv run dx`, not `dx`. `.venv/bin` is not on `PATH`, so a bare `dx` reports
`command not found` even when the toolkit is installed correctly.

## Running

The scripts read `.env` and authenticate themselves. You do not source
`scripts/dx-env.sh` first.

The scripts terminate the machine when the program finishes, when you exit the
terminal, when the run fails, and when you press Ctrl-C.

Three rules apply to every run.

- Commit and push your branch first. The machine clones your current branch
  from GitHub. Changes that are only on your computer are not on the machine.
- Write your results to `'$OUT'`, with the single quotes. The scripts copy
  `$OUT` to your computer. Everything else on the machine is deleted. The
  single quotes stop your own shell from replacing `$OUT` before the machine
  receives it.
- Set `-t` above the longest time your program can take. It is the maximum
  lifetime of the machine, not a target. The machine normally stops as soon as
  the program finishes.

Results are downloaded into the `-o` directory, `data/dx/<run>` by default.
They are also kept in the project at `/Results/<your username>/<run>/`.

## Instance types

```bash
scripts/dx-instance.sh --list-instances
scripts/dx-instance.sh --list-instances gpu
```

| Instance type | GPU | Cores | RAM | Disk | Use for |
|---|---|---:|---:|---:|---|
| `mem1_ssd1_v2_x4` | none | 4 | 8 GB | 93 GB | CPU default. A terminal or a small program. |
| `mem2_ssd1_v2_x8` | none | 8 | 32 GB | 279 GB | CPU work that needs more memory. |
| `mem2_ssd2_gpu1_v2_x8` | 1 × L4, 24 GB | 8 | 32 GB | 421 GB | GPU default. |
| `mem3_ssd1_gpu1_x16` | 1 × L4, 24 GB | 16 | 128 GB | 560 GB | The same GPU with more RAM and disk. |

Select a type for one run with `-i`. Change the defaults for a whole shell:

```bash
export DX_INSTANCE=mem2_ssd1_v2_x8
export DX_GPU_INSTANCE=mem3_ssd1_gpu1_x16
```

Do not use the `mem2_ssd1_gpu_*` types. Their T4 GPU is sm_75, and the current
CUDA packages need sm_80 or later. The machine starts, and the first GPU
operation then fails.

## Terminating a machine manually

The scripts terminate the machine for you. Use these commands only if a machine
did not stop. A machine runs until it is terminated. Closing your SSH session
does not stop it.

```bash
uv run dx find jobs --user self --state running --origin-jobs
uv run dx terminate job-XXXXXXXXXXXXXXXXXXXXXXXX
uv run dx describe job-XXXXXXXXXXXXXXXXXXXXXXXX | grep "^State"
```

The state becomes `terminating`, then `terminated`.

Include `--user self`. Without it the command lists the jobs of everyone on the
team, and terminating another person's job cannot be undone.

When you exit a terminal session, `dx` asks `Terminate now? [y/N]`. Answer `n`.
The script terminates the machine itself, and it copies your results first.

## Working with project files

Authenticate the shell before you run `dx` commands yourself:

```bash
source scripts/dx-env.sh

uv run dx ls /survivor/
uv run dx download -f /survivor/HPRC_SV.survivor.vcf
uv run dx upload results.tsv --destination /Results/<yours>/
```

Source `scripts/dx-env.sh`. Do not execute it. It only sets variables.

All paths are relative to the project. The same commands work on a machine.

## Other scripts

| Script | Function |
|---|---|
| `scripts/dx-env.sh` | Reads `.env`, authenticates the dx toolkit, and selects the project. |
| `scripts/dx-instance.sh` | The script the four commands call. Accepts their options and more. |
| `scripts/dx-shard-gpu.sh` | Runs one program across several GPU machines at once, each on a slice of the input, and stops all of them. |
| `scripts/dx-worker-run.sh` | Runs on the machine. Detaches the program from the ssh session, uploads results as they appear, and stops the machine when it ends. |
| `scripts/dx-worker-setup.sh` | Runs on the machine. Installs uv, clones the branch, and builds the environment. |
| `scripts/dx-worker-setup-evo2.sh` | The `--setup` script for Evo 2 runs. The generic one cannot install evo2 or flash-attn. |
| `scripts/dx-wrapper.sh` | Shared code of the four commands. |

### Several machines at once

`scripts/dx-shard-gpu.sh` runs `dx-batch-gpu.sh` once per shard, giving each an
`--offset`/`--limit` slice of the input and its own output directory and log:

```bash
scripts/dx-shard-gpu.sh --shards 4 --calls 6127 --time 6h \
    --setup scripts/dx-worker-setup-evo2.sh -- <program>
```

It exists for the shutdown, not the arithmetic. A machine is stopped by an EXIT
trap in `dx-instance.sh`, but bash defers a trap until the running foreground
command returns — and that command is a `dx ssh` that will not return for hours,
so a Ctrl-C aimed at a hand-backgrounded job is queued behind the very run it
was meant to stop. This script launches each shard in its own **process group**
and signals the whole group, which makes that command return so the trap can
run; it then harvests the job ids from the shard logs and stops any survivor.

`--shell`, `--keep` and `--interactive` are refused, and `--time` must cover the
**largest** shard, not the average.

### Why the program is detached from the connection

By default each shard runs through `scripts/dx-worker-run.sh` on the machine
rather than directly. That exists because of a measured failure on 2026-08-27:
a four-shard run billed **12.3 GPU-hours and produced nothing**. Throughput was
fine — 6.3–8.1 s/window, as profiled. What happened is that all four programs
died **within ten seconds of each other**, 44 minutes into 73 minutes of work.
One dropped connection on the laptop, four dead runs.

Three faults, each independently sufficient to lose the run, and each now closed:

| Fault | Fix |
|---|---|
| The program ran in the foreground of `dx ssh`, so a closing session sent it SIGHUP | started under `setsid nohup` with stdin from `/dev/null` — it has no terminal to lose |
| Results were uploaded only after the program returned, so an interruption at 99% lost everything | each file is uploaded to the project as it is written, and on failure too |
| A finished or dead program did not stop its machine — it idled at `CPU: 1%` for two hours | the program terminates its own job as its last act, on success and on error alike |

The launcher still mirrors the log, so an attached terminal sees progress as
before — but that half is now expendable. If the connection drops, collect with
`uv run dx download -r <destination>`. `--no-detach` restores the old behaviour.

### Push notifications

Both scripts post to [ntfy.sh](https://ntfy.sh) on the topic
**`inTRuder-tandem-repeats`**. Subscribe in the ntfy app or at
<https://ntfy.sh/inTRuder-tandem-repeats>.

The one that matters is sent **from the worker**, not from your laptop, so the
outcome reaches you even if the machine that launched the run is asleep or
offline — the exact case that left the 2026-08-27 failure invisible for two
hours. It carries the job id, the exit status and how many `.npz` were uploaded,
and is sent just before the box terminates itself.

| Flag | | Default |
|---|---|---|
| `--ntfy-topic TOPIC` | topic to post to | `inTRuder-tandem-repeats` |
| `--no-notify` | post nothing | off |

`NTFY_TOPIC` and `NTFY_URL` override the defaults from the environment. Every
call has a 10 s timeout and swallows its errors: ntfy being down must never turn
a good run into a failed one.

A shard that raises also **stops the queue**: the remaining shards are not
launched, because a systematic fault would otherwise cost one GPU box each to
rediscover.

Three further options of `scripts/dx-instance.sh`:

```bash
scripts/dx-instance.sh -t 2h --shell -- pytest -q
scripts/dx-instance.sh --job job-xxxx
scripts/dx-instance.sh --gpu --no-setup -t 30m -- nvidia-smi
```

- `--shell`: run the program, then open a terminal on the same machine.
- `--job`: connect to a machine that is already running.
- `--no-setup`: do not clone the repository or build the environment.

On the machine, call `.venv/bin/...` directly. Do not use `uv run`. It
resynchronises to `uv.lock` and removes anything installed on top of it.

## DNAnexus documentation

- [Command Line Quickstart](https://documentation.dnanexus.com/getting-started/cli-quickstart)
- [Connecting to Jobs](https://documentation.dnanexus.com/developer/apps/execution-environment/connecting-to-jobs)
- [Cloud Workstation](https://documentation.dnanexus.com/user/cloud-workstation)
