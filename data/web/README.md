# Web dataset registry (`data/web`)

Every `*.yaml` file in this directory is a **manifest**: a small description of one
table that the web backend registers as a DuckDB view and exposes to the agent.

Manifests are committed. **Data files are not uploaded anywhere** — the paths in a
manifest point at files on your own machine, and the backend reads them in place.
The only exception is `demo/`, a small synthetic dataset committed so that a fresh
clone runs with no downloads.

## Adding your own dataset

1. Put your file somewhere on disk. Parquet, CSV, or TSV.
2. Copy `demo-loci.yaml` to `my-dataset.yaml` and edit it.
3. Restart the backend. That's it — no code changes.

```yaml
name: my_tr_calls              # SQL identifier; becomes the view name
title: My TR calls             # short human label
synthetic: false               # set true for fabricated/demo data
path: ~/work/my_calls.parquet  # absolute, ~-relative, or relative to data/web
format: parquet                # parquet | csv | tsv

description: >
  Free prose. THIS IS WHAT THE AGENT READS to decide whether your table can
  answer a question, so say what one row means and what the table is good for.

columns:
  locus_id: What this column holds. One line each, also read by the agent.
  motif: Canonicalized repeat motif.

provenance:
  source: Where it came from
  license: CC-BY-4.0
```

`path` may use `${NOVELTRS_DATA_DIR}`, which defaults to the repository's `data/`
directory and can be overridden in `backend/.env`.

If a manifest's file is missing, the backend still starts — the dataset is listed
as unavailable instead of crashing, so a clone without your private data works.

## Why manifests instead of code

The agent gets three fixed tools — `list_datasets`, `describe_dataset`, `run_sql` —
regardless of how many datasets exist. Adding a dataset therefore needs no changes
to the agent, the tools, or the API, and a contribution is one reviewable YAML file.
The `description` and `columns` prose is prompt material, not just documentation:
it is literally what the agent sees when deciding how to answer a question.

## Current manifests

| File | View | Rows | Real? |
|---|---|---|---|
| `demo-loci.yaml` | `demo_loci` | 1,200 | Synthetic |
| `demo-segments.yaml` | `demo_segments` | 132,479 | Synthetic |
| `strchive-loci.yaml` | `strchive_loci` | 82 | Real (curated reference) |

```bash
cd backend
uv run python scripts/make_demo_data.py   # the synthetic demo tables
uv run python scripts/fetch_strchive.py   # the disease-locus catalog
```
