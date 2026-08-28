# Python source (`src/python`)

Python code for the project. Environment is managed with [uv](https://docs.astral.sh/uv/).

## Layout

Everything lives under one installed package, `intruder`:

```
src/python/intruder/
├── trcore/       shared primitives — coordinates, motifs, downloads, repo paths
├── pipeline/     the pipeline steps
│   ├── trf/         call repeats inside SV insertions, then filter the calls
│   ├── novelty/     is this repeat absent from the reference and the catalogues?
│   ├── strchive/    is it a known disease locus?
│   ├── compression/ how compressible is the insertion? a cheap repetitiveness proxy
│   └── annotation/  genic / clinical context
└── analysis/     post-hoc analysis of pipeline output — never a pipeline step
    └── benchmark/   score a TRF callset against a published repeat catalogue
```

Two rules hold this together:

- **Steps do not import each other.** Each reads files and writes files, so a
  Nextflow process, a shell loop and a notebook can all drive it unchanged.
  Anything genuinely common goes in `trcore`, which is the only cross-cutting
  import allowed.
- **One owned top-level name.** `intruder` is what gets installed into
  site-packages. Bare `pipeline`, `analysis` or `filter` packages would collide
  with real distributions on PyPI.

Shell scripts live in `../../scripts/`, not here. R lives in `../R/`.

## Setup

```bash
uv sync                       # create .venv and install locked dependencies
```

## Dependency groups

`uv sync` installs the runtime dependencies plus `dev`. The rest are opt-in, so a
Nextflow worker that only writes a TSV never installs a plotting stack:

| Group | Install | What it covers |
|---|---|---|
| *(runtime)* | `uv sync` | what a pipeline step imports — cyvcf2, pysam, pytrf, parasail, pandas, numpy, optuna |
| `dev` | `uv sync` (default) | ruff, pytest, jupyterlab, ipykernel |
| `analysis` | `uv sync --group analysis` | matplotlib, seaborn, scikit-learn, umap-learn, polars — for `intruder.analysis` |
| `dx` | `uv sync --group dx` | dxpy, for `scripts/dnanexus/` — see [DNAnexus docs](../../docs/scripts/DNANexus.md) |

Put a dependency in the runtime set only if a pipeline step imports it. If one
subsystem needs something heavy, give it a group.

## Common tasks

```bash
uv add pandas                 # add a runtime dependency (updates pyproject.toml + uv.lock)
uv add --group analysis seaborn   # add to a group instead
uv run ruff check src/python tests/python   # lint
uv run pytest                 # run tests

# identify repeats using pyTRF from a multisample SV file
uv run svpytrf -i multisample.vcf -o trf_output.tsv

# annotate TRF output with novelty verdicts
uv run novelty -i trf_output.tsv -o trf_novelty.tsv

# filter novelty output by motif purity and repeat coverage, etc.
uv run filter -i trf_novelty.tsv -o trf_novelty_filtered.tsv

# annotate a VCF with per-ALT compressibility (SVCOMP) -- see
# ../../docs/scripts/annotate_compression.md
uv run compression -i multisample.vcf -o multisample_comp.vcf
```

The command names above are unchanged by the move to `intruder/` — only the
module paths behind them shifted. To run a step without the console script, use
its module path: `uv run python -m intruder.pipeline.novelty --help`.

## Tests

Tests live in `../../tests/python/`, mirroring the package layout — never beside
the code. `uv run pytest` from the repo root runs them all; CI runs the same
command on every push and pull request.

The Python version is pinned in `../../.python-version`; dependencies are locked in
`../../uv.lock`. Commit both along with `pyproject.toml`.
