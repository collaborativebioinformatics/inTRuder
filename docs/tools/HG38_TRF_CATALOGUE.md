# Building an hg38 TRF catalogue

Builds a tandem-repeat catalogue by running [Tandem Repeats Finder](https://github.com/Benson-Genomics-Lab/TRF)
over hg38, for use as an alternative reference annotation in the
[novelty screen](NOVELTY_SCREEN.md). Addresses issue #43.

## Why

The screen ships with two published catalogues. UCSC `simpleRepeat` is TRF output
but not at this pipeline's parameters, and TRExplorer is not built with TRF at
all. A locus whose motif the reference records differently reads as
`novel_motif`, so some of the reported novelty is annotation disagreement rather
than biology.

## Usage

```bash
scripts/catalog/build_hg38_trf.sh OUTDIR [MINSCORE]     # default minscore 50
```

Then screen against it:

```bash
uv run novelty --platform ucsc,trexplorer,bed \
    --repeats bed=OUTDIR/hg38.trf.minscore50.bed \
    annotate in.trf.tsv out.tsv
```

## Reproducing the comparison below

Every number in the table further down comes from these commands, run against
the test set already in the repository. About 40 minutes end to end, almost all
of it the two genome builds; 15 minutes if you only build `minscore=50`.

```bash
IN=data/sv_output/survivor_multi_sample_vcf/first_500_INS.trf.tsv

# 1. build the catalogues        7 min and 28 min wall clock, 10 cores
scripts/catalog/build_hg38_trf.sh trf50 50
scripts/catalog/build_hg38_trf.sh trf10 10

# 2. the shipped baseline, UCSC + TRExplorer alone
uv run novelty --platform ucsc,trexplorer \
    annotate "$IN" base.tsv --metrics base.metrics.tsv

# 3. add the matched-parameter catalogue at each minscore
uv run novelty --platform ucsc,trexplorer,bed \
    --repeats bed=trf50/hg38.trf.minscore50.bed \
    annotate "$IN" ms50.tsv --metrics ms50.metrics.tsv

uv run novelty --platform ucsc,trexplorer,bed \
    --repeats bed=trf10/hg38.trf.minscore10.bed \
    annotate "$IN" ms10.tsv --metrics ms10.metrics.tsv
```

`--metrics` is what writes the per-locus counts; without it you get an annotated
table but no summary. Read `loci_known`, `loci_novel_motif` and
`loci_novel_locus` from each metrics file, or the per-locus block each run prints
to stderr.

Expected: baseline **48.4%** novel, `ms50` **47.1%**, `ms10` **42.5%**, over 221
loci.

About 12 minutes wall clock on 10 cores, plus ~6 GB of scratch. The catalogues
are 72 MB (`minscore=50`) and 636 MB (`minscore=10`), so they are built rather
than committed.

`trf` must be on `PATH`. It is not in Homebrew core; build it from source:

```bash
git clone --depth 1 https://github.com/Benson-Genomics-Lab/TRF.git
cd TRF && ./configure && make CFLAGS="-O2 -DUNIXCONSOLE"
```

`-DUNIXCONSOLE` is required. `configure` does not set it, and without it the
build fails on `dirsymbol` with an undeclared-identifier error.

## What `minscore` does, and why it matters

The sixth TRF parameter is the minimum alignment score. TRF's default is 50;
issue #43 specifies 10. That single value dominates the size of the catalogue and
therefore the result:

| Catalogue | Intervals, genome-wide | vs UCSC |
|---|---:|---:|
| UCSC `simpleRepeat` | 1,050,000 | 1.0x |
| TRExplorer v2 | 5,600,000 | 5.3x |
| this build, `minscore=10` | 21,848,178 | 20.8x |
| this build, `minscore=50` | 1,502,018 | 1.43x |

## Measured effect on the novelty rate

Screening `first_500_INS.trf.tsv` (221 loci, all chr1):

| Catalogue set | known | novel_motif | novel_locus | % novel |
|---|---:|---:|---:|---:|
| UCSC alone | 86 | 104 | 31 | 61.1% |
| TRExplorer alone | 102 | 88 | 31 | 53.8% |
| UCSC + TRExplorer (shipped) | 114 | 81 | 26 | 48.4% |
| this build, `minscore=10`, alone | 114 | 84 | 23 | 48.4% |
| this build, `minscore=50`, alone | 89 | 104 | 28 | 59.7% |
| all three, `minscore=10` | 127 | 71 | 23 | **42.5%** |
| all three, `minscore=50` | 117 | 79 | 25 | **47.1%** |

**Parameter matching is worth about 1.4 points, not 5.9.** At `minscore=10` the
novelty rate falls 48.4% to 42.5%, but that catalogue is 20x the size of UCSC and
marks loci `known` partly by calling far more of the genome repetitive. At
`minscore=50`, where the catalogue is a comparable 1.43x, the drop is 48.4% to
47.1%, and head to head against UCSC the matched build gives 89 known against 86.

So `minscore` should be chosen deliberately. A low floor is reasonable on the
short inserted sequences the SV side scans; applied to 3.1 Gb it produces a very
permissive reference annotation.

Both runs reproduce identically against the chr1-only and genome-wide catalogues,
with no `unscreened` rows across 24 contigs.

## Caveats

The evaluation above uses chr1 only, because the committed test set is chr1 only;
221 loci is a small and non-random denominator. The input TSV predates the fix for
issue #48, so `rep_start`/`rep_end`-derived quantities are shifted, though the
verdict counts depend on `ins_coord` and motif, which are unaffected.

## Output format

BED4, 0-based half-open, sorted by `(chrom, start)`:

```
chr1	10000	10468	TAACCC
chr1	10481	10498	GCCC
```

Columns are contig, start, end, and the TRF consensus motif (field 14 of the
`.dat` record). TRF reports 1-based inclusive coordinates, so `start - 1` is
written. `src/python/intruder/pipeline/catalog/dat2bed.py` performs that
conversion and is verified record-for-record against the `.dat` input.

The conversion step runs on its own too, over any `.dat` files you already have:

```bash
uv run python -m intruder.pipeline.catalog.dat2bed OUT.bed dat/*.dat
```
