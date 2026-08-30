# Getting Started

Everything needed to set up inTRuder, run the web interface, and run the pipeline — both through
Nextflow and as standalone commands.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — manages both the pipeline and backend Python environments
- Node.js 20+ — for the frontend
- [`just`](https://github.com/casey/just) — task runner; every command below is also a `just`
  recipe. Run `just` on its own to list them all.
- [Docker](https://docs.docker.com/get-docker/) — only needed for the containerized setup or for
  running the Nextflow pipeline

## 1. Clone and set up

```bash
git clone https://github.com/collaborativebioinformatics/inTRuder.git
cd inTRuder
just setup     # uv sync for the pipeline, uv sync + npm install for the web app,
               # plus the synthetic demo dataset the interface opens on
```

`just setup` also copies `backend/.env.example` to `backend/.env` — add a model credential there
to enable chat in the web interface. Skip this step entirely if you only want the containers.

## 2. Run the web interface

```bash
just dev       # backend on :8000, frontend on :3000
```

Or in containers, with no toolchain to install:

```bash
docker compose up --build      # same two ports; your data/ is bind-mounted, not baked in
```

Either way, open [http://localhost:3000](http://localhost:3000). `just backend` and
`just frontend` run the two halves on their own. Backend internals — model providers, the agent's
tools, the SQL sandbox — are covered in [`backend/README.md`](../backend/README.md).

## 3. Run the pipeline

The [Nextflow](https://www.nextflow.io/) entrypoint is `workflows/main.nf`, and its processes run
inside the image built from this repository's `Dockerfile` — so build that once first:

```bash
docker build -t novel-tr-pipeline:latest .
nextflow run workflows/main.nf -profile docker
```

With no `--input_vcf`, that runs stage 01 (TR detection) over the 500 committed insertions in
`data/sv_output/sniffles/first_500_INS.vcf`. Point it at your own SV calls and turn the optional
stages on with flags:

```bash
nextflow run workflows/main.nf -profile docker \
    --input_vcf path/to/insertions.vcf \
    --run_novelty \
    --run_annotation \
    --run_validation --tr_catalogue_bed path/to/tandem_repeats.bed
```

Results are published under `results/`, with `results/final/final_output.tsv` as the one
predictable endpoint and run reports in `reports/`. Which processes are real and which are still
placeholders is tracked in the
[Methods outline](Methods_overview.md#5-pipeline-orchestration).

Each step is also a standalone CLI, file in and file out, so nothing forces you through Nextflow:

```bash
uv run svpytrf -i multisample.vcf -o trf.tsv                    # 01  TRs inside inserted alleles
uv run novelty --platform ucsc,trexplorer annotate trf.tsv trf.novelty.tsv   # 02  known or novel?
```

See the [Novelty screen](tools/NOVELTY_SCREEN.md) and [STRchive comparison](tools/STRCHIVE_COMPARE.md)
docs for what each stage actually does, and the [Methods outline](Methods_overview.md) for the
full pipeline write-up.

## Other environments

- [Python source](../src/python/README.md) — uv-managed environment, adding dependencies, running
  scripts, linting and tests
- [R source](../src/R/README.md) — renv-managed environment, `renv::restore()`, snapshotting new
  packages
- [Run programs on DNAnexus](scripts/DNANexus.md) — `scripts/dnanexus/dx-*.sh`: start a machine,
  get a terminal or run one program on it, then stop the machine
