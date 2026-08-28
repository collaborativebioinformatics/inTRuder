# Plotting inputs (`data/plots/`)

`src/R/plotting/main.R` joins the novelty-screen output for a cohort onto its AnnotSV
annotation, producing one wide table per cohort that the figures are drawn from.

None of these tables are committed. They are derived pipeline output — 165 MB across
five files — so they are regenerated from the pipeline or downloaded from the shared
Drive, and `data/plots/` is in `.gitignore`. Only this description of them lives in git.

## The files

The numeric prefixes are the analysis stages in [Methods overview](../Methods_overview.md),
not part of any tool's output name.

| File | Rows | Size | What it is |
|---|---|---|---|
| `02_HG002_03_04_multisample.trf.novelyFilter.tsv` | 9.7k | 2.8 MB | HG002/03/04 trio: TR calls inside SV insertions, screened for novelty and filtered |
| `02_hprc_multisample.trf.noveltyFiltered.tsv` | 221k | 58 MB | Same table for the 67-genome HPRC cohort |
| `03_HPRC_SV.survivor.ins.trf.in_catalog.tsv` | 619k | 52 MB | HPRC insertions merged with SURVIVOR, TR-called, flagged `in_catalog` — the unfiltered catalogue-membership table |
| `04_HG002_03_04_multisample.trf.novelyFilter.tsv.processed.tsv` | 4.8k | 11 MB | AnnotSV annotation for the trio, post-processed (adds `Genic`, `Exonic`, `Intronic`, `Novel`, `pLOF`, `DISEASE_GENES`) |
| `04_hprc_multisample.trf.noveltyFiltered.tsv.processed.tsv` | 21k | 50 MB | Same for HPRC |

`main.R` reads the `02_` and `04_` pairs and writes `05_HG002_03_04_multisample.tsv` and
`05_hprc_multisample.tsv` into the same directory. The `05_` files are the only thing the
script produces — **the `04_*.processed.tsv` files are inputs, not outputs**: they carry
AnnotSV columns that nothing in this repo generates, and `main.R` only left-joins them
onto `02_` by `SVID`.

`03_HPRC_SV.survivor.ins.trf.in_catalog.tsv` is not read by `main.R`. It is kept
alongside the others because it is the pre-filter view of the same HPRC callset.

## How to regenerate

**`02_`** — the two Python pipeline steps, run per cohort on the merged multi-sample
insertion VCF (see [`scripts/merge-SV/`](../../scripts/merge-SV/) for how those VCFs are
built):

```bash
uv run svpytrf -i <cohort>_multisample.INS.vcf -o <cohort>.trf.tsv
uv run novelty -i <cohort>.trf.tsv           -o <cohort>.trf.novelty.tsv
uv run filter  -i <cohort>.trf.novelty.tsv   -o data/plots/02_<cohort>.trf.noveltyFiltered.tsv
```

See [Novelty screen](../tools/NOVELTY_SCREEN.md) for the catalogues and the known/novel
verdict, and [`src/python/README.md`](../../src/python/README.md) for the environment.

**`03_`** — the same first two commands over the SURVIVOR-merged insertion VCF, without
the `filter` step.

**`04_`** — AnnotSV, run outside this repo. The orchestration pipeline's `ANNOTATE`
process (`workflows/main.nf`) is still a placeholder, so these were produced by hand;
`pipelines/sv_preprocess` is the insertion-to-DUP conversion AnnotSV needs first. Ask the
annotation subgroup before regenerating.

**`05_`** — from the repo root, once `02_` and `04_` are in place:

```bash
Rscript src/R/plotting/main.R
```

The script defaults to `data/plots`. Point it elsewhere with an argument
(`Rscript src/R/plotting/main.R /path/to/dir`) or the `NOVELTRS_PLOT_DATA` environment
variable.

## Where to get them without regenerating

The two `05_` merges are on the shared Drive, linked from the README:
[HG002 trio](https://drive.google.com/file/d/1ppH3vSswUobjRUMFrTC-4MPwbmW_63L5/view?usp=drive_link),
[HPRC samples](https://drive.google.com/file/d/10Byv-tfCglKLdArRO9sW8dqmd-rwrh0W/view?usp=drive_link).
Drop them in `data/plots/` and the plotting scripts can read them directly.

## R environment

`main.R` uses `readr` and `dplyr`. Neither is in `renv.lock` yet — install them and run
`renv::snapshot()` to record them. See [`src/R/README.md`](../../src/R/README.md).
