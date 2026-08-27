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
| `strchive-calls.yaml` | `strchive_calls` | — | Real, **not yet produced** |

```bash
cd backend
uv run python scripts/make_demo_data.py   # the synthetic demo tables
uv run python scripts/fetch_strchive.py   # the disease-locus catalog
```

## Manifests committed ahead of their data

`strchive-calls.yaml` points at output the pipeline does not produce yet — the
screened callset from the [novelty screen](../../docs/tools/NOVELTY_SCREEN.md)
and the [STRchive comparison](../../docs/tools/STRCHIVE_COMPARE.md). Registering
it early is deliberate, and it works because a manifest whose file is missing is
reported as unavailable rather than crashing the backend.

Doing it this way buys three things: the column documentation is reviewed
alongside the pipeline step that will fill it, the interface can render its own
"not run yet" state instead of an empty table that reads as a negative finding,
and the day the file appears the whole surface lights up with no code change.

The interface holds up its end of the bargain: a filter whose column does not
exist yet comes back in `ignored_filters` and is drawn struck-through, so a
control never silently matches everything.
