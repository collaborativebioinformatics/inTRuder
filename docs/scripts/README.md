# `scripts/`

Shell entry points for working on DNAnexus. Each script's own header comment has
the details and the traps; this page is just what to type. The platform side —
tokens, billing, instance types, terminating — is
[docs/DNANexus.md](../DNANexus.md).

| Script | What it does |
|---|---|
| [`dx-env.sh`](../../scripts/dx-env.sh) | Authenticates `dx` from `.env` and pins the project. Source it, don't run it. |
| [`dx-instance.sh`](../../scripts/dx-instance.sh) | Rents a box, sets it up, gives you a terminal on it, fetches the results, terminates it. |
| [`setup-worker.sh`](../../scripts/setup-worker.sh) | Builds this project's environment on a worker. Called for you by `dx-instance.sh`. |

## `dx-env.sh`

```bash
source scripts/dx-env.sh          # every new shell
uv run dx whoami                  # check it worked
```

Needs `.env` at the repo root — `cp .env.example .env`, then paste in a token.
It reinstalls `dxpy` if a plain `uv sync` has removed it again.

## `dx-instance.sh`

```bash
# what can we launch, and what is each one for?
scripts/dx-instance.sh --list-instances
scripts/dx-instance.sh --list-instances gpu

# a shell on a CPU box; exiting terminates it
scripts/dx-instance.sh --time 1h

# a GPU box instead
scripts/dx-instance.sh --gpu --time 2h

# run a command, stage an input, fetch what it writes to $OUT
scripts/dx-instance.sh --time 2h --output-dir data/dx/run1 \
    --input /survivor/HPRC_SV.survivor.vcf -- \
    novelty screen /home/dnanexus/HPRC_SV.survivor.vcf '$OUT/hits.tsv'

# print the platform calls, launch nothing
scripts/dx-instance.sh --dry-run --time 2h -- nvidia-smi
```

| Flag | | Default |
|---|---|---|
| `-t, --time` | how long the box may live | `2h` |
| `-i, --instance` | instance type | `mem1_ssd1_v2_x4` |
| `-g, --gpu` | shorthand for `-i mem2_ssd2_gpu1_v2_x8` | off |
| `-l, --list-instances` | print what the project may launch (optional substring filter), then exit | — |
| `-f, --input` | file id or project path to stage onto the worker; repeatable | — |
| `-o, --output-dir` | where results land locally | `data/dx/<run>` |
| `-r, --remote-out` | worker directory the command writes to, exported as `$OUT` | `/home/dnanexus/out` |
| `-d, --destination` | project folder results are uploaded to | `/Results/<you>/<run>/` |
| `-b, --branch` | branch the worker clones | your current branch |
| `--setup` / `--no-setup` | swap or skip the environment build | `setup-worker.sh` |
| `--job` | attach to a running job instead of launching | — |
| `--shell` | open a shell after the command, before the fetch | off |
| `--keep` | don't terminate at the end | off |
| `-n, --dry-run` | print the platform calls instead of running them | off |

`--help` for the rest. Three things that bite:

- The worker clones from **GitHub**, so push before you run — preflight says so
  before anything starts billing.
- Quote `'$OUT'` so your shell leaves it for the worker's.
- Exiting the shell **terminates the box**. Answer `n` to `dx`'s own prompt on
  the way out; the script does the terminating, and confirms the state.

## `setup-worker.sh`

```bash
uv run dx ssh "$JOB" -T "bash -s" < scripts/setup-worker.sh
SYNC_ARGS="--group dx" bash scripts/setup-worker.sh      # extras and groups
```

Idempotent. Installs `uv`, clones `$BRANCH`, syncs `uv.lock` into `.venv`, and
prints `=== READY ===` when that worked — which is the line `dx-instance.sh`
looks for. Afterwards use `.venv/bin/...` on the worker, never `uv run`: it
resyncs to the lock and removes anything installed on top of it.
