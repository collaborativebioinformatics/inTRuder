# Running programs on DNAnexus

Get a terminal on a machine in the cloud, or run one program on it. The machine
receives a copy of this project, your results are copied back to your computer,
and the machine is then terminated.

Complete the [Setup](#setup) before your first run.

## Quick reference

```bash
# a terminal, for 30 minutes at most
scripts/dnanexus/dx-instance-cpu.sh -t 30m
scripts/dnanexus/dx-instance-gpu.sh -t 30m

# run one program, then return
scripts/dnanexus/dx-batch-cpu.sh -t 1h -- .venv/bin/python -m pytest -q
scripts/dnanexus/dx-batch-gpu.sh -t 30m -- nvidia-smi

# with an input file, and a directory for the results
scripts/dnanexus/dx-batch-cpu.sh -t 4h -o data/dx/screen1 \
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
   source scripts/dnanexus/dx-env.sh
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
`scripts/dnanexus/dx-env.sh` first.

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
scripts/dnanexus/dx-instance.sh --list-instances
scripts/dnanexus/dx-instance.sh --list-instances gpu
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
source scripts/dnanexus/dx-env.sh

uv run dx ls /survivor/
uv run dx download -f /survivor/HPRC_SV.survivor.vcf
uv run dx upload results.tsv --destination /Results/<yours>/
```

Source `scripts/dnanexus/dx-env.sh`. Do not execute it. It only sets variables.

All paths are relative to the project. The same commands work on a machine.

## Other scripts

| Script | Function |
|---|---|
| `scripts/dnanexus/dx-env.sh` | Reads `.env`, authenticates the dx toolkit, and selects the project. |
| `scripts/dnanexus/dx-instance.sh` | The script the four commands call. Accepts their options and more. |
| `scripts/dnanexus/dx-worker-setup.sh` | Runs on the machine. Installs uv, clones the branch, and builds the environment. |
| `scripts/dnanexus/dx-wrapper.sh` | Shared code of the four commands. |

Three further options of `scripts/dnanexus/dx-instance.sh`:

```bash
scripts/dnanexus/dx-instance.sh -t 2h --shell -- pytest -q
scripts/dnanexus/dx-instance.sh --job job-xxxx
scripts/dnanexus/dx-instance.sh --gpu --no-setup -t 30m -- nvidia-smi
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
