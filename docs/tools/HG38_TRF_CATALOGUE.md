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
src/python/catalog/build_hg38_trf.sh OUTDIR [MINSCORE]     # default minscore 50
```

Then screen against it:

```bash
uv run novelty --platform ucsc,trexplorer,bed \
    --repeats bed=OUTDIR/hg38.trf.minscore50.bed \
    annotate in.trf.tsv out.tsv
```

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
written. `dat2bed.py` performs that conversion and is verified record-for-record
against the `.dat` input.
