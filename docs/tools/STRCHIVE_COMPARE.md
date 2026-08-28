# STRchive comparison (`strchive`)

The [novelty screen](NOVELTY_SCREEN.md) tells you a tandem repeat is absent from
the reference. This tool asks the next question: **is anyone known to get sick
from a repeat there?**

It takes the filtered output of the novelty screen and compares every candidate
against [STRchive](https://strchive.org)
([repo](https://github.com/dashnowlab/STRchive)), the curated catalogue of
pathogenic TR loci — 82 of them in v2.26.0 — which records, for each locus, its
coordinates in three reference builds, the motifs observed there, and the
copy-number ranges that separate a benign allele from a pathogenic one.

Three questions are answered in order, because each only makes sense if the
previous one was answered yes:

| | question | answered by |
|---|---|---|
| 1 | does the call land on a known disease locus? | `strchive_distance_bp`, `strchive_id` |
| 2 | is its motif one STRchive records **there**? | `strchive_motif_class` |
| 3 | does the resulting copy number reach the pathogenic range? | `strchive_allele_class` |

They are kept as three columns rather than collapsed into one verdict because
they disagree in exactly the cases that matter — see
[Why three columns](#why-three-columns-and-not-one-verdict).

## How to use it

Same two ways as the novelty screen, and the same program:

```bash
# through uv, from anywhere in the repo -- what the examples below use
uv sync                      # once; installs the `strchive` command, editable
uv run strchive --help

# or directly, without installing anything
cd src/python
python -m strchive --help
```

Three commands:

| command | what it does |
|---|---|
| `annotate IN.tsv OUT.tsv` | **the main job.** Compares every row and writes the table back with the STRchive columns added on the right. Nothing is removed or reordered |
| `query --chrom --pos --motif` | compare a single locus and print the result. For checking one case by hand |
| `fetch` | download and cache the catalogue. Optional — `annotate` and `query` do it on demand |

```bash
# the filtered novelty output, which is what this step is for
uv run strchive annotate \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.filtered.tsv \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.strchive.tsv \
    --window 10

# one locus by hand
uv run strchive query --chrom chr4 --pos 39348430 --motif AAGGG --rep-units 500
```

## Input

A TSV with a header. Three columns are required; the rest sharpen the answer
when present, and the step degrades rather than fails without them. The novelty
screen's output carries all of them except `gene`.

| role | default column | required | used for |
|---|---|---|---|
| contig | `chrom` | yes | locus lookup |
| insertion point | `ins_coord` | yes | locus lookup (1-based; see `--coord-base`) |
| repeat motif | `motif` | yes | motif classification |
| motif copies in the insertion | `rep_units` | no | the copy-number estimate |
| gene | `gene` | no | agreement check against STRchive's gene |
| record id | `SVID` | no | labelling |

Rename any of them with `--col-chrom`, `--col-pos`, `--col-motif`,
`--col-rep-units`, `--col-gene`, `--col-label`. Numeric cells may be bare (`138`)
or bracketed (`[138]`, `[0 0]`) as `sv_trfcaller.py` writes them.

## Options

| flag | default | what it does |
|---|---|---|
| `--window BP` | `0` | how far a disease locus may sit from the insertion point and still count. `0` requires strict overlap. The same breakpoint-slop argument as the novelty screen's `--window` applies, so `10` is the natural setting when chaining the two |
| `--max-motif-edits N` | `0` | how many edits two motifs may differ by and still count as equivalent. `0` means exact |
| `--stranded` | off | treat a motif and its reverse complement as different repeats |
| `--build {hg38,hg19,t2t}` | `hg38` | which build your coordinates are in. **Getting this wrong shifts every locus by megabases and silently returns no hits** |
| `--coord-base {0,1}` | `1` | whether positions in your table count from 0 or 1. VCF `POS` counts from 1 |
| `--catalog PATH` | download | use a local `STRchive-loci.json` instead of fetching one |
| `--strchive-version TAG` | pinned | a different STRchive release. Only the pinned release's checksum is verified; asking for another says so on stderr |
| `--cache-dir PATH` | `data/reference/strchive` | where the downloaded catalogue is kept |

## What comes out

The input table, unchanged, plus:

| column | meaning |
|---|---|
| `strchive_status` | the rollup verdict — see below |
| `strchive_id`, `strchive_gene`, `strchive_disease`, `strchive_inheritance`, `strchive_evidence` | the matched locus |
| `strchive_distance_bp`, `strchive_n_nearby` | bp to the locus (`0` = overlapping) and how many were inside the window |
| `strchive_motif_class` | `pathogenic` \| `reference` \| `benign` \| `unknown` \| `interruption` \| `none` |
| `strchive_motif_edits`, `strchive_matched_motif` | how the motif matched, and which STRchive motif it matched |
| `strchive_ref_copies`, `strchive_est_copies`, `strchive_allele_class` | the copy-number estimate and where it falls |
| `strchive_pathogenic_min`, `strchive_pathogenic_max` | the locus's pathogenic range, for eyeballing |
| `strchive_novel_in_ref` | STRchive's own flag: is the pathogenic motif present in hg38 at all? |
| `strchive_gene_agrees` | whether the upstream gene call matches STRchive's |
| `strchive_catalog` | e.g. `STRchive v2.26.0 (hg38)` — provenance, on every row |

Re-annotating an already-annotated table replaces these columns rather than
duplicating them.

| `strchive_status` | meaning |
|---|---|
| `pathogenic_expansion` | disease locus, pathogenic motif, **and** the estimated copy number reaches the pathogenic range |
| `pathogenic_motif` | disease locus and pathogenic motif, but the copy number does not — or could not be estimated |
| `locus_novel_motif` | lands on a disease locus carrying a motif **not catalogued there** |
| `locus_known_motif` | disease locus, and the motif is the reference/benign/unknown one |
| `no_locus_match` | no disease locus within the window. **The expected answer for nearly every row** |

A summary of the counts prints to stderr.

## Why three columns and not one verdict

RFC1 is the case that settles it. Expanded to 500 copies it causes CANVAS with an
`AAGGG` motif and nothing at all with the reference `AAAAG` — the pathogenicity
is in the motif, not the length:

```bash
$ uv run strchive query --chrom chr4 --pos 39348430 --motif AAGGG --rep-units 500
chr4:39348430 AAGGG  ->  pathogenic_expansion
  motif       pathogenic via AAGGG (0 edits)
  estimate    11.8 ref + 500 inserted = 511.8 copies -> pathogenic

$ uv run strchive query --chrom chr4 --pos 39348430 --motif AAAAG --rep-units 500
chr4:39348430 AAAAG  ->  locus_known_motif
  motif       reference via AAAAG (0 edits)
  estimate    11.8 ref + 500 inserted = 511.8 copies -> pathogenic
```

Both are 511.8 copies and both land in the pathogenic range. Only the first is a
finding. Folding motif class into allele class would report both — or neither.

This is also why `strchive_novel_in_ref` is carried through: it is STRchive's own
record of whether the pathogenic motif exists in hg38, which is the same idea as
the novelty screen's `novel_motif` verdict, arrived at independently. Eleven of
the 82 loci are `novel` in that sense.

## How the three questions are decided

### Locus — position, not gene

Matching is driven by coordinates. A novel locus may carry no gene annotation at
all, and gene symbols disagree between annotation sources, so gene is reported as
an independent agreement check (`strchive_gene_agrees`) and never used to accept
or reject a locus. A disagreeing gene is surfaced, not silently dropped.

When several disease loci fall inside the window, the one with the **best motif
match wins**, and proximity only breaks ties. A pathogenic motif match a few
hundred bp away is a more useful report than a motif-less overlap.

### Motif — canonical form

`CCG`, `GCC` and `CGG` are the same repeat read from a different phase or the
other strand. Motifs are reduced to a canonical key before comparison — primitive
unit (`ATAT` → `AT`), then the smallest rotation of that unit or of its reverse
complement — so all three match STRchive's `CCG`. `--stranded` keeps the strands
distinct; `--max-motif-edits` accepts near-misses.

A locus hit whose motif matches **nothing** catalogued there is
`locus_novel_motif`: a known disease locus carrying a unit nobody has recorded at
it. Whether that is interesting or an artefact is the same judgement call the
novelty screen documents — check for near misses first.

### Allele — an estimate, and only an estimate

The insertion is called *against* the reference, so the copies it carries are
additional to the copies already there:

```text
est_copies = ref_copies + rep_units
```

Three things to hold in mind:

- It assumes the insertion **extends** the reference repeat rather than replacing
  it or landing beside it.
- It inherits whatever error `rep_units` carries from TRF.
- 11 of the 82 loci have no `ref_copies` at all, so no estimate is possible.
  `strchive_allele_class` is then `unknown` — it never silently becomes zero.

Treat it as a triage signal, not a genotype. Where a range is missing from
STRchive the class is `unknown` rather than a guess, and where the benign and
intermediate ranges overlap at their edges (RFC1: benign 0–11, intermediate
11–200) the more actionable class wins.

## The catalogue

Pinned to a release tag, verified by SHA-256, cached under
`data/reference/strchive/` and gitignored. We need one 500 kB file out of a
160 MB repository, so this is a download rather than a submodule — and unlike a
submodule the release tag travels into every annotated row via
`strchive_catalog`.

To move to a newer release, bump `STRCHIVE_VERSION` **and** `STRCHIVE_SHA256` in
`catalog.py` together:

```bash
curl -sL https://raw.githubusercontent.com/dashnowlab/STRchive/<tag>/data/STRchive-loci.json | shasum -a 256
```

Where Python has no usable CA bundle (python.org builds on macOS, some HPC
modules), the download falls back to the system `curl` automatically — the
novelty screen downloads through the same `trcore.fetch` helpers, so both
steps survive that trust store rather than only this one.

`STRCHIVE_CACHE` overrides the cache directory, the way `NOVELTY_CACHE` does
for the novelty screen; outside a checkout both fall back to the user cache.

## Reading the output

**`no_locus_match` everywhere is the normal result.** 82 loci against 3 Gb means
the base rate is essentially zero; a run with no hits has told you something
true. Before concluding anything from a run, check two things:

- **How far off were you?** A `no_locus_match` at 12 bp and one at 12 Mb are very
  different results, and the status alone does not distinguish them. Widen
  `--window` and look at `strchive_distance_bp`.
- **Is `--build` right?** A wrong build shifts every locus by megabases and
  returns a clean, confident, entirely wrong set of misses.

### The current run

Run on the filtered novelty output at `--window 10`:

```text
[strchive] 1,468 rows -> first_500_INS.strchive.tsv
[strchive]   no_locus_match  1,468  (100.00%)
```

No hits — and this is structural rather than a threshold artefact. The input is
the first 500 insertions of the SURVIVOR merge, which span **chr1:121,069–3,583,350**,
a 3.5 Mb window. Exactly one STRchive locus lies inside it (`HMNR7_VWA1` at
chr1:1,435,798), and the nearest candidate insertion is **8,331 bp** away from it
— three orders of magnitude beyond any defensible `--window`. Widening the window
would not change the answer.

So this slice is a pipeline test, not a screen. A real screen needs the full
insertion set.

## How it's implemented

Pure standard library. It imports no other pipeline step — only `trcore`, the
shared primitives every step must agree on — so it stays runnable as a
standalone Nextflow process. At 82 loci, at most 10 on any one contig, a
per-contig linear scan beats an interval tree and keeps the dependency count at
zero.

All coordinates are 0-based half-open internally and converted once at the edges.
STRchive's `start_*`/`stop_*` are BED style; VCF `POS` is 1-based; mixing the two
silently shifts every interval by a base.

| file | what it holds |
|---|---|
| `src/python/trcore/motifs.py` | canonical form of a repeat unit, and fuzzy distance between two motifs — shared with the novelty screen |
| `src/python/trcore/coords.py` | 0-based/1-based conversion, contig naming, distance between intervals — shared |
| `src/python/trcore/fetch.py` | where a downloaded catalogue is cached, and the `curl` fallback — shared |
| `src/python/strchive/catalog.py` | fetching, checksumming and parsing `STRchive-loci.json`; the per-contig index; the allele ranges |
| `src/python/strchive/compare.py` | the three questions, the rollup status, and the output row |
| `src/python/strchive/__main__.py` | the three commands and the input-column contract |
| `data/strchive/` | the five-record catalogue the tests run against, offline |
| `tests/python/strchive/` | one test module per source module, offline |
| `tests/python/trcore/` | the shared motif, coordinate and fetch suites |

Steps in this pipeline communicate through files, not imports. The one
exception is [`trcore`](../../src/python/trcore/__init__.py): motif
canonicalisation, the coordinate conventions and the download cache were
provably identical in both
steps, and they are wrong in the same way when they are wrong — two steps that
disagree by one base on what "overlapping" means produce tables that look
comparable and are not. Everything catalogue-shaped stays separate; see the
`trcore` docstring for why the two `catalog.py` modules were *not* merged.

```bash
uv run pytest tests/python/strchive tests/python/trcore
```

Tests never touch the network: they run against five real STRchive records
vendored in `data/strchive/STRchive-loci.mini.json`, chosen to cover
the awkward shapes — a locus whose reference and pathogenic motifs are rotations
of each other, one with four pathogenic motifs and none of them the reference
one, one with `ref_copies` of `0.0` (falsy but present), one with `ref_copies`
missing entirely, and one with no benign range at all.
