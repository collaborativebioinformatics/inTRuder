# Novelty screen (`novelty`)

Tandem repeats called inside SV insertions are only interesting if the reference
genome does not already have them. This tool takes the per-insertion TR calls
from [`sv_trfcaller.py`](../../src/python/sv_trfcaller.py) and asks, for each
one, whether a reference TR catalogue already annotates that repeat at that
locus. Every call comes back as one of three verdicts:

| verdict | meaning |
|---|---|
| `known` | a reference repeat with an equivalent motif sits at this locus |
| `novel_motif` | the reference has repeats here, but none with this motif |
| `novel_locus` | the reference annotates no repeat at all near this locus |

Which reference you ask changes the answer, so the screen is not tied to one
catalogue. It ships adapters for the **UCSC `simpleRepeat`** track (1.05M
entries, with the Tandem Repeat Finder measurements attached) and the
**TRExplorer** catalog (5.6M entries, position and motif only), and can screen
against several at once — a locus is only novel if none of them knows it.

It also computes **insertion purity**: what fraction of the whole inserted
sequence is tandem repeat at all, so insertions that are mostly something else
can be set aside.

## How to use it

There are two ways to run it, and they are the same program:

```bash
# through uv, from anywhere in the repo -- what the examples below use
uv sync                      # once; installs the `novelty` command, editable
uv run novelty --help

# or directly, without installing anything
cd src/python
python -m novelty --help
```

`uv sync` puts the package in editable mode, so the `novelty` command always
tracks your working copy and there is nothing to reinstall after an edit. The
`python -m` form needs `src/python` on the path, which is why it is run from
there; `PYTHONPATH=src/python python -m novelty` from the repo root does the
same. Paths in the examples below are relative to the repo root, so adjust them
if you `cd` into `src/python`.

There are four commands. `annotate` is the one you normally want.

| command | what it does |
|---|---|
| `annotate IN.tsv OUT.tsv` | **the main job.** Screens every row of a `sv_trfcaller.py` table and writes the same table back with the verdict and the matching reference repeat added as columns on the right. Nothing is removed or reordered — your rows are handed back with notes attached |
| `query --chrom --pos --motif` | screen a single locus and print the result. For checking one case by hand |
| `sweep IN.tsv OUT.tsv` | run `annotate` repeatedly under different settings and report what each produced. See [Searching the settings](#searching-the-settings) |
| `platforms` | print the catalogues, file formats and tunable settings this build supports, with their defaults |

```bash
# what can we screen against?
uv run novelty platforms

# one locus
uv run novelty query --chrom chr1 --pos 10772 --motif GC

# the whole sv_trfcaller.py table, against both catalogues
uv run novelty --platform ucsc,trexplorer annotate \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.trf.tsv \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv
```

Catalogues download themselves on first use into `data/reference/` (UCSC 30 MB,
TRExplorer 45 MB) and build an index cache beside the file, which cuts a ~30 s
startup to ~1 s on every later run. Both are gitignored. Put them somewhere else
with `--cache-dir` or the `NOVELTY_CACHE` environment variable.

### Structural options

These describe the data and the run rather than the science, so they are not
things to tune.

| flag | what it does |
|---|---|
| `--platform ucsc,trexplorer` | catalogue(s) to screen against. Each gets its own block of output columns, and the leading `novelty` column combines them |
| `--repeats [PLATFORM=]PATH` | use a local catalogue file instead of downloading one |
| `--cache-dir PATH` | where downloaded catalogues are kept (default: the repo's `data/reference`) |
| `--format` | the catalogue file's layout. Detected from the file unless you say otherwise |
| `--coord-base {0,1}` | whether positions in your table start counting at 0 or at 1. VCF `POS` counts from 1, which is the default; getting it wrong shifts every interval by one base |
| `--stranded` | treat a motif and its reverse complement as different repeats. Canonicalisation happens when the index is built, so this rebuilds the catalogue and cannot be swept |
| `--drop-filtered` | write only the rows that pass your thresholds. Without it every row is kept and simply tagged |
| `--metrics PATH` | also append a one-row summary of this run, in the layout `sweep` writes |

### Tunable settings

Every threshold in the screen is a flag with a default, and
`uv run novelty platforms` lists them. Write `none` to switch one off. They
split into two kinds, which matters for speed: a **screening** setting changes
the verdicts, so changing it means screening the table again; a **row filter**
only decides which already-screened rows you keep.

| flag | default | kind | what it does |
|---|---|---|---|
| `--window BP` | `10` | screening | how far a reference repeat may sit from the insertion point and still count as being at the same locus — [explained below](#--window-how-far-off-the-coordinates-may-be) |
| `--max-motif-edits N` | `0` | screening | how many edits two motifs may differ by and still count as equivalent. `0` means exact. `1` is well supported by our data and resolves most near-misses |
| `--max-fuzzy-motif BP` | `50` | screening | the longest motif near-miss matching is attempted on at all — [explained below](#--max-fuzzy-motif-when-to-stop-looking-for-near-misses) |
| `--min-reference-identity PCT` | off | screening | ignore reference repeats whose sequence identity is below this. A **percentage**, 0–100; only UCSC records it (`perMatch`) |
| `--min-reference-copy-num N` | off | screening | ignore reference repeats with fewer than this many copies of their motif |
| `--min-reference-length BP` | off | screening | ignore reference repeats shorter than this |
| `--min-purity FRAC` | off | row filter | drop rows whose own repeat has lower TRF identity than this. A **fraction**, 0–1 |
| `--min-insertion-purity FRAC` | off | row filter | drop rows whose insertion is less than this fraction tandem repeat. A **fraction**, 0–1 |
| `--min-motif-length BP` | off | row filter | drop very short motifs |
| `--max-motif-length BP` | off | row filter | drop very long or compound ones |
| `--min-rep-length BP` | off | row filter | drop rows where the repeat covers only a little of the insertion |
| `--min-rep-units N` | off | row filter | drop rows with only a few copies of the motif |

Watch the two scales: `--min-reference-identity` is a percentage because that is
how UCSC records it, while `--min-purity` is a fraction because that is how the
`sv_trfcaller.py` table records it.

The three `--min-reference-*` thresholds do more than tidy the output. They
decide what counts as annotation in the first place, so raising one moves
`n_nearby` and can turn a `known` verdict into `novel_locus` — you are saying a
short or low-identity catalogue entry is not enough evidence that a repeat is
already known. A catalogue that lacks the underlying column is left alone, and
the run says so on stderr.

#### `--window`: how far off the coordinates may be

An insertion has one coordinate — the base it was placed after. A reference
repeat has an interval. Neither is exact: the breakpoint comes from aligning
noisy reads, and the annotated repeat has its own boundaries. Requiring the
coordinate to land strictly inside the interval is therefore too harsh, and a
repeat one base past the edge would be called `novel_locus` purely because of
where the caller drew the line.

`--window` is how much distance to forgive, in base pairs. At the default of 10,
any reference repeat coming within 10 bp of the insertion point counts as being
at this locus:

```text
                   reference repeat  [==================]
    insertion point       x  <-4bp->
                          |------ window 10 ------|   close enough: known
                          |-- window 0 --|             too far: novel_locus
```

`0` requires a strict overlap. Larger values are more forgiving and call more
loci `known`. The effect is bigger than you might expect and does not level off:
on our data, going from `0` to `50` moves 28 loci from novel to known. Quote the
window alongside any novelty count.

#### `--max-fuzzy-motif`: when to stop looking for near-misses

Once `--max-motif-edits` is above `0`, deciding whether two motifs are equivalent
means an edit distance minimised over every rotation and both strands — the cost
grows steeply with motif length. It also stops being meaningful: motifs are
usually a handful of bases, but the longest UCSC consensus is 1,991 bp, and "two
1,991-mers differ by one base" says nothing useful.

`--max-fuzzy-motif` is the length above which that comparison is skipped and
motifs must match exactly. At the default of 50, units up to 50 bp get the
near-miss treatment and longer ones do not. Lowering it is faster and stricter;
raising it is slower and more forgiving. It has no effect at all when
`--max-motif-edits` is `0`, since nothing fuzzy happens then.

### What comes out

The input table, unchanged, plus:

- `novelty` — the combined verdict, and `canonical_motif` for the query
- `insertion_repeat_bases`, `insertion_purity`, `filter`
- one block per platform: `<platform>_novelty`, `_n_nearby`, `_start`, `_end`,
  `_distance`, `_motif`, `_canonical`, `_motif_edits`, plus whatever annotations
  that catalogue carries (UCSC adds `_period`, `_copy_num`, `_per_match`, …;
  TRExplorer is position and motif only, so it contributes none)

Two summaries print to stderr: per row **and per locus**. Rows are
locus × sample × TRF call, so one recurrent locus can contribute dozens of them
and per-row percentages track recurrence more than novelty.

### Searching the settings

`sweep` is `annotate` run many times under different thresholds, writing one row
of counts per run instead of an annotated table. It is built on
[Optuna](https://optuna.org), which brings trial storage, resumable studies and
its dashboard along with it.

Any setting can take a list of values (`0,1,10`), a range (`0:50`), or a range
with a step (`0:50:5`). Anything you leave alone stays at its default.

```bash
# try every combination of these values
uv run novelty --platform ucsc,trexplorer sweep \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.trf.tsv \
    data/sv_output/survivor_multi_sample_vcf/first_500_INS.sweep.tsv \
    --window 0,1,10,50 --max-motif-edits 0,1,2 \
    --min-purity none,0.8 --min-insertion-purity none,0.5,0.8

# or let Optuna explore the ranges itself, keeping the study to browse later
uv run novelty --platform ucsc,trexplorer sweep in.tsv out.tsv \
    --sampler tpe --trials 200 --objective agreement \
    --window 0:50 --max-motif-edits 0:3 --min-insertion-purity 0.0:1.0 \
    --storage sqlite:///study.db --study-name novelty
```

| flag | what it does |
|---|---|
| `--sampler {grid,tpe,random}` | `grid` (the default) runs every combination you listed. `random` picks at random. `tpe` learns as it goes, spending later trials near the settings that scored well |
| `--trials N` | how many runs to do (default: the whole grid, or 50 when sampling) |
| `--objective {agreement,truth,none}` | what counts as a good score — see below |
| `--truth PATH` / `--truth-col` | a TSV of loci you already know the answer for: the chrom/pos columns plus a known/novel column |
| `--seed N` | fix the randomness so a search can be repeated exactly |
| `--storage URL` / `--study-name` | e.g. `sqlite:///study.db`, to keep the trials, resume the study, or point `optuna-dashboard` at it |

Each row records every setting plus `n_rows`, `n_rows_pass`, `n_loci`,
`rows_<status>`, `loci_<status>`, `frac_loci_novel`, the same locus counts per
platform, and that trial's `objective`/`score`. `annotate --metrics PATH` writes
the same row minus those last two and appends, so a hand-rolled loop can
accumulate the same table.

#### Comparing settings is not the same as choosing them

There is normally no truth set here, so a grid `sweep` is not finding the best
thresholds — it shows **how much a conclusion depends on them**. A finding that
holds across the grid is solid; one that appears only at particular cutoffs is a
property of the cutoffs. Compare `frac_loci_novel` rather than raw counts,
because the row filters change `n_loci` and so the denominator.

Optuna's optimising samplers do need something to maximise:

- **`agreement`** (the default when several platforms are given) — how far the
  catalogues independently flag the *same* loci as novel, scored as the Jaccard
  index of their novel-locus sets. Where UCSC and TRExplorer, compiled
  separately, agree, the call is a property of the data rather than of the
  cutoff. It is deliberately scored on the novel sets rather than on overall
  agreement, so that a huge `--window` calling everything `known` in both cannot
  win; an empty intersection and an empty union both score `0.0`. Needs at least
  two `--platform` entries.
- **`truth`** — balanced accuracy against `--truth`, i.e. novel-recall and
  known-recall averaged so the rarer class still counts. The only honest way to
  tune if you have a labelled set.
- **`none`** — no score, just enumerate.

Treat a winning `agreement` score as a hypothesis about where the thresholds are
stable, not as the right answer.

### Reading the output

Two things routinely inflate the novel counts, so check them before believing a
number:

- **Near misses.** A single substitution in the unit reads as `novel_motif`.
  Re-run with `--max-motif-edits 1` and see what survives, or sweep the axis. On
  our data this accounted for most of them.
- **Sub-repeat containment.** TRF reports one compound representative unit per
  locus, so an `ACC` query is called novel against a reference consensus of
  `ACCATC` even though it plainly tiles it. This is a known gap — the matching
  rule does not yet test containment.

## How it's implemented

Motifs are compared by canonical form: reduced to their primitive unit
(`ATAT` → `AT`), then to the smallest rotation of that unit or of its reverse
complement, so `GC` and `CG` collapse together. The catalogue is held column-wise
in numpy arrays sorted by `(chrom, start)`, and overlap search is a
`searchsorted` plus a short walk left, bounded by a per-contig running maximum of
the interval ends. Motif strings are interned, so hg38's 1.05M `simpleRepeat`
rows canonicalise only their 515,928 distinct sequences.

All coordinates are 0-based half-open internally and converted once at the edges;
VCF `POS` is 1-based, and mixing the two silently shifts every interval by a base.

| file | what it holds |
|---|---|
| `src/python/novelty/motifs.py` | canonical form of a repeat unit, and fuzzy distance between two motifs |
| `src/python/novelty/platforms.py` | where a catalogue comes from and how to read it — UCSC, TRExplorer, plain BED, TRGT BED — normalised to one schema (`chrom/start/end/motif` plus optional annotations) |
| `src/python/novelty/catalog.py` | the interval index, the known/novel verdict, and the index cache |
| `src/python/novelty/insertions.py` | insertion purity (a union of the TRF intervals, so overlapping calls are not double-counted) and the filter column |
| `src/python/novelty/search.py` | the Optuna search: the axes, the samplers and the objectives |
| `src/python/novelty/cli.py` | the four commands, and the one table declaring every tunable setting |
| `pyproject.toml` | declares the `novelty` command and builds the package from `src/python`; `sv_trfcaller.py` stays a loose script |
| `tests/python/novelty/` | mirrors the source tree, one test module per source module; `uv run pytest` |

Adding a catalogue means adding a reader and a registry entry in `platforms.py`;
nothing downstream knows which platform it is looking at. Adding a setting means
adding one row to `HYPERPARAMS` in `cli.py`, which wires it into `annotate`,
`sweep` and the metrics table at once.
