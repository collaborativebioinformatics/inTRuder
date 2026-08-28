# Web dataset registry (`data/web`)

Every `*.yaml` file in this directory is a **manifest**: a small description of one
table that the web backend registers as a DuckDB view and exposes to the agent.

Manifests are committed. **Data files are not uploaded anywhere** — the paths in a
manifest point at files on your own machine, and the backend reads them in place.
The only exception is `demo/`, a small synthetic dataset committed so that a fresh
clone runs with no downloads.

## Adding your own dataset

**The short way:** press **Upload** in the web interface, drop the file in, and
name it. That writes the file into `../uploads/` and a manifest here, then
reloads the registry — no restart. Everything below is what it writes, and the
way to do it by hand.

**By hand:**

1. Put your file somewhere on disk. Parquet, CSV, or TSV.
2. Copy `demo-loci.yaml` to `my-dataset.yaml` and edit it.
3. Restart the backend, or `curl -X POST localhost:8000/api/registry/reload`.
   No code changes either way.

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

role: loci                     # optional; see below

provenance:
  source: Where it came from
  license: CC-BY-4.0
```

## `role` — which table the interface draws from

By default a registered dataset is queryable by the assistant and read by no
page. `role` is how a table takes over a surface instead:

| `role` | What reads it |
|---|---|
| `loci` | The candidate-locus catalog, the discovery funnel, the motif-class breakdown |
| `segments` | The per-allele motif barcodes |

The API resolves these by role rather than naming a table, so registering your
own callset with `role: loci` repoints the whole catalog surface without a code
change — and without having to call your table `demo_loci`. With no claimant it
falls back to the committed demo fixtures, which is what a fresh clone has.

A table claiming a role has to carry the columns that surface reads
(`locus_id`, `chrom`, `pos`, `motif`, `motif_len`, `motif_class`, `n_samples`,
`median_len`, `mean_purity`, `novel` for `loci`); the upload dialog checks this
before offering the option, and the API refuses with the missing list rather
than registering a table that would render blanks.

Note that the two are independent. Registering a real locus table without a
matching segments table leaves real rows drawn with the fixture barcodes, and
the header badge says exactly that rather than calling the whole page
synthetic.

`path` may use `${NOVELTRS_DATA_DIR}`, which defaults to the repository's `data/`
directory and can be overridden in `backend/.env`.

## Switching a dataset off

Every dataset has a switch on the **Datasets** page. Off means off everywhere: no
surface draws it, the assistant is not told it exists, and `run_sql` refuses to
name it. It is not a filter on the list.

The **default** is on, with one exception: a `synthetic: true` dataset defaults
**off** as soon as real data is driving a surface — that is, as soon as some
manifest with a `role` and `synthetic: false` has its file on disk. So a fresh
clone draws the demo fixtures, and the moment you fetch the HPRC callset (or
upload your own table with `role: loci`) the fixtures take themselves out of the
way. Nobody has to remember to turn them off, and a fabricated cohort never sits
in the dataset list beside a real one waiting to be quoted.

"Driving a surface" is the test rather than "any real table exists", because the
disease-locus reference is real, is always present, and does not replace the demo
catalog. A manifest committed ahead of its data does not count either — the file
has to be there.

Every switch is overridable in both directions, and the default is only a
starting point: switch a fixture back on to compare it against your callset, or
switch the real callset off to see the interface on the fixtures again.

**The switches live in your browser, not on the server.** One backend serves
everybody who can reach it, so what you hide is hidden for you alone. The split
is that the server computes the *default* — only it knows what data exists — and
the browser stores the *choices*, in `localStorage`, and sends them on every
request as an `X-Dataset-Switches: name=on|off` header. A first-time visitor
sends nothing and still gets the defaults right. Clearing site data resets every
switch to its default; there is nothing to clean up on the server.

Note that the tables stay loaded either way: one materialization serves every
client, so switching off is enforced per request rather than achieved by the rows
not being there. `Registry.query` refuses SQL naming a switched-off table.

If a manifest's file is missing, the backend still starts — the dataset is listed
as unavailable instead of crashing, so a clone without your private data works.

## Why manifests instead of code

The agent gets three fixed tools — `list_datasets`, `describe_dataset`, `run_sql` —
regardless of how many datasets exist. Adding a dataset therefore needs no changes
to the agent, the tools, or the API, and a contribution is one reviewable YAML file.
The `description` and `columns` prose is prompt material, not just documentation:
it is literally what the agent sees when deciding how to answer a question.

## Current manifests

| File | View | Role | Rows | Real? |
|---|---|---|---|---|
| `hprc-loci.yaml` | `hprc_loci` | `loci` | 17,270 | **Real** — 67 HPRC genomes |
| `hprc-segments.yaml` | `hprc_segments` | `segments` | 232,583 | **Real** |
| `hprc-calls.yaml` | `hprc_calls` | — | 221,405 | **Real** — the screen at its native grain |
| `trio-loci.yaml` | `trio_loci` | `loci` | 4,541 | **Real** — GIAB HG002/03/04 |
| `trio-segments.yaml` | `trio_segments` | `segments` | 10,287 | **Real** |
| `demo-loci.yaml` | `demo_loci` | — | 1,200 | Synthetic — off once real data is loaded |
| `demo-segments.yaml` | `demo_segments` | — | 95,840 | Synthetic — off once real data is loaded |
| `strchive-loci.yaml` | `strchive_loci` | — | 82 | Real (curated reference) |
| `strchive-calls.yaml` | `strchive_calls` | — | — | Real, a 500-insertion pipeline test |
| `hpo-gene-phenotype.yaml` | `hpo_gene_phenotype` | — | ~332,600 | Real (HPO Consortium release) |
| `upload-*.yaml` | (yours) | — | — | Generated by the Upload button; gitignored |

```bash
just demo-data      # the synthetic demo tables
just strchive-data  # the disease-locus catalog
just web-data       # the real hprc and trio tables (needs the data below)

cd backend
uv run python scripts/fetch_hpo.py         # the HPO gene-phenotype release
uv run python scripts/build_hpo_index.py   # the HPO term embedding index
```

The last two back `resolve_phenotype` (`app/tools/hpo.py`) — a free-text
clinical description mapped to genes via validated HPO terms. Unlike everything
else here, their output under `data/web/hpo/` **is committed** (62 MB), so a
fresh clone can answer a phenotype question without first rebuilding the index;
re-run the two scripts only when the HPO release or the embedding model
changes. See
`backend/README.md`'s `### resolve_phenotype` section for the pipeline and its
threshold calibration.

## The real callset

`hprc_loci` and `hprc_segments` claim the two roles, so the interface draws the
real cohort — and the demo fixtures switch themselves off, since real data is now
driving both surfaces (see *Switching a dataset off*). The `hprc-*.yaml` and
`trio-*.yaml` manifests are committed; none of the data is. To get it:

```bash
just plot-data          # the Drive folder, 750 MiB, into data/plots
just plot-parquet       # cache it as parquet — 586 MB of TSV becomes 7 MB
just strchive-data      # the disease-locus catalog, for the strchive_* columns
just web-data           # build data/hprc and data/trio
```

Without it the datasets report themselves unavailable, no role is claimed, and
the interface falls back to the demo fixtures — a fresh clone still runs.

Two cohorts come out of this, from one build path: **hprc** (67 unrelated
genomes, 17,270 loci) and **trio** (GIAB HG002/03/04, 4,541 loci). They are
separate tables rather than one table with a `cohort` column, because a family
and a population are not two views of one thing.

Four things about these callsets are worth knowing before quoting a number off
them, and each is argued at length in the manifests and in
`backend/scripts/build_web_tables.py`:

* **A locus is an insertion site**, keyed `(chrom, pos)`, not an SV record. 21,424
  Sniffles records collapse to 17,270 sites; co-located records are alleles of
  one locus.
* **Allele length is constant within an SV record**, because the multisample VCF
  stores one ALT sequence per record. All the cohort allele-size variation lives
  *between* co-located records, which is why the locus is the site.
* **The input carries 58,964 exact duplicate rows** (221,405 total, 162,441
  distinct). The build de-duplicates; `hprc_calls`, which is the raw file, does
  not — count it with `DISTINCT`.
* **AnnotSV's multi-value fields have three different shapes** and mixing them up
  silently mislabels genes. `Gene_name` is `;`-joined per gene; the
  transcript-level `*_merged` columns are `, `-joined and repeat per transcript;
  the gene-level ones are `, `-joined per gene and their free text contains `, `
  itself. The build has one helper per shape, and drops per-gene free text on
  multi-gene loci rather than risk captioning one gene with another's disease.

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
