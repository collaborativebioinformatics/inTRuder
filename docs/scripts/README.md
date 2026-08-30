# `scripts/`

Shell entry points. Each script's own header comment has the details and the
traps; this page is just what to type.

| Script | What it does |
|---|---|
| [`dx-env.sh`](../../scripts/dx-env.sh) | Authenticates `dx` from `.env` and pins the project. Source it, don't run it. |
| [`dx-gpu-instance.sh`](../../scripts/dx-gpu-instance.sh) | Rents a DNAnexus GPU box, runs a command on it, fetches the results, terminates it. |
| [`setup-gpu-worker.sh`](../../scripts/setup-gpu-worker.sh) | Builds the Evo 2 environment on a GPU worker. Called for you by `dx-gpu-instance.sh`. |

## `dx-env.sh`

```bash
source scripts/dx-env.sh          # every new shell
uv run dx whoami                  # check it worked
```

## `dx-gpu-instance.sh`

```bash
# both alleles of a shard: launch, run, download, terminate
scripts/dx-gpu-instance.sh --time 8h --output-dir data/evo/shard0 \
    --input /Test_Inputs/first_500_INS.vcf \
    --input /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta \
    --input /merge-svs/reference/human_GRCh38_no_alt_analysis_set.fasta.fai -- \
    python -m evo.embeddings \
        /home/dnanexus/first_500_INS.vcf \
        /home/dnanexus/human_GRCh38_no_alt_analysis_set.fasta \
        '$OUT' --offset 0 --limit 2000

# no command: set the box up and drop me into a shell
scripts/dx-gpu-instance.sh --time 1h

# print the platform calls, launch nothing
scripts/dx-gpu-instance.sh --dry-run --time 2h -- nvidia-smi
```

| Flag | | Default |
|---|---|---|
| `-t, --time` | how long the box may live | `2h` |
| `-i, --instance` | GPU type | `mem2_ssd2_gpu1_v2_x8` |
| `-f, --input` | file id or project path to stage onto the worker; repeatable | — |
| `-o, --output-dir` | where results land locally | `data/evo/<run>` |
| `-r, --remote-out` | worker directory the command writes to, exported as `$OUT` | `/home/dnanexus/out` |
| `-d, --destination` | project folder results are uploaded to | `/Results/<you>/<run>/` |
| `-b, --branch` | branch the worker clones | `feature/evo-embeds` |
| `--job` | attach to a running job instead of launching | — |
| `--shell` | open a shell after the command, before the fetch | off |
| `--keep` | don't terminate at the end | off |
| `-n, --dry-run` | print the platform calls instead of running them | off |

`--help` for the rest. Two things that bite:

- The worker clones from **GitHub**, so push before you run.
- Quote `'$OUT'` so your shell leaves it for the worker's.

## `setup-gpu-worker.sh`

```bash
uv run dx ssh "$JOB" -T "bash -s" < scripts/setup-gpu-worker.sh
```

Idempotent. Afterwards use `.venv/bin/...` on the worker, never `uv run` — it
resyncs to `uv.lock` and uninstalls flash-attn.
