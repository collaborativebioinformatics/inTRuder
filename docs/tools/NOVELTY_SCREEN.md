# Novelty screen (`novelty`)

**Screens the tandem repeats that
[`sv_trfcaller.py`](../../src/python/sv_trfcaller.py) found inside SV insertions
against reference TR catalogues, and reports which ones the reference does not
already contain.**

The input is a TSV of TR calls. The output is the same TSV with a verdict column
added:

| verdict | meaning |
|---|---|
| `known` | a reference repeat with a matching motif is present at this locus |
| `novel_motif` | the reference has repeats here, but none with this motif |
| `novel_locus` | the reference annotates no repeat within the search window |
| `unscreened` | this catalogue has no rows on this contig, so it cannot classify the locus |

Catalogues disagree about many loci, so several can be screened in one run.
Two are genome-wide: **UCSC `simpleRepeat`** (1.05M entries, with TRF
measurements) and **TRExplorer** (5.6M entries, position and motif only). A locus
is `known` if at least one catalogue contains it. See
[Combining platforms](#combining-platforms).

A third catalogue, **`pathogenic`**, is kept in the repo at
`data/novelty/pathogenic.hg38.TRGT.bed`: 83 known disease-associated TR loci.
It covers 83 loci only, so a `novel_locus` verdict against it carries no
information. It is therefore marked annotation-only and is excluded from the
combined verdict.

## Quick start

```bash
uv sync                                    # once; installs the `novelty` command

# 1. what can I screen against?
uv run novelty platforms

# 2. check a single locus by hand
uv run novelty query --chrom chr1 --pos 10772 --motif GC

# 3. screen a whole table against both catalogues
uv run novelty --platform ucsc,trexplorer annotate in.trf.tsv out.novelty.tsv

# 4. the same, keeping only rows that pass the filters, plus a summary row
uv run novelty --platform ucsc,trexplorer annotate in.trf.tsv out.tsv \
    --min-purity 0.8 --min-insertion-purity 0.8 --drop-filtered \
    --metrics run.metrics.tsv

# 5. measure how far the result depends on the thresholds
uv run novelty --platform ucsc,trexplorer sweep in.trf.tsv sweep.tsv \
    --window 0,1,10,50 --min-insertion-purity none,0.5,0.8
```

Without installing: `cd src/python && python -m novelty --help`.

Catalogues are downloaded on first use into `data/reference/` (UCSC 30 MB,
TRExplorer 45 MB) and an index is cached beside the file, reducing startup from
about 30 s to about 1 s. Both are gitignored. Set the location with
`--cache-dir` or `$NOVELTY_CACHE`.

## Commands

| command | what it does |
|---|---|
| `annotate IN.tsv OUT.tsv` | the primary command. Screens every row and writes the table back with the verdict added. No rows are removed or reordered |
| `query --chrom --pos --motif` | screens one locus and prints the result. Intended for inspecting individual cases |
| `sweep IN.tsv OUT.tsv` | runs `annotate` repeatedly under different settings, writing one row of counts per run. See [Searching the settings](#searching-the-settings) |
| `platforms` | prints the catalogues, formats and settings this build supports |

## Settings

### Structural options

These describe the input data and the run itself. They do not affect how motifs
are compared.

| flag | default | what it does |
|---|---|---|
| `--platform ucsc,trexplorer` | `ucsc` | catalogue(s) to screen against; each gets its own output columns |
| `--repeats [PLATFORM=]PATH` | download | use a local catalogue file instead |
| `--cache-dir PATH` | `data/reference` | where downloaded catalogues live |
| `--format` | auto | catalogue file layout; detected from the file |
| `--coord-base {0,1}` | `1` | whether input positions count from 0 or 1. VCF `POS` counts from 1. An incorrect value shifts every interval by one base |
| `--db NAME` | `hg38` | assembly to screen against |
| `--no-download` / `--no-cache` | off | fail rather than fetch a missing catalogue / rebuild the index rather than reuse its cache |
| `--drop-filtered` | off | write only rows that pass every filter. Without it, all rows are kept and tagged |
| `--metrics PATH` | off | also append a one-row summary, in the layout `sweep` writes |
| `--chrom-col`, `--pos-col`, `--motif-col`, `--purity-col`, `--rep-start-col`, `--rep-end-col`, `--insert-size-col` | the names below | the input column names the tool reads |
| `--insertion-key COLS` | `chrom,ins_coord,SVID,sample` | which columns identify one insertion, for [insertion purity](#insertion-purity) |
| `--no-insertion-purity` | off | skip the insertion-purity columns entirely |

### Motif equivalence

What makes two motif *strings* the same *repeat*. Catalogue-level: changing one
rebuilds the index, so these cannot be swept.
[In depth](#motif-equivalence-in-depth).

| | flag | default | treats as the same repeat | example |
|---|---|---|---|---|
| period reduction | *(none)* | always on | a motif that is only several copies of a shorter one | `CAGCAG` = `CAG` |
| rotation | `--circular` / `--no-circular` | **on** | the same unit started at a different base | `CAG` = `AGC` = `GCA` |
| reverse complement | `--reverse-complement` | **off** | the same unit read from the other strand | `CAG` = `CTG`, `A` = `T` |
| ↳ length gate | `--reverse-complement-bp BP` | off | the same, but only for units ≥ `BP` | at `6`: `TAACCC` = `GGGTTA`, but `A` ≠ `T` |

None of these is fuzzy matching. No combination of them makes `CAG` match `CAT`.
Approximate matching is controlled by the [tolerance settings](#motif-tolerance),
which are off by default.

### Screening settings

Change the verdict itself, so changing one re-screens the table. `none` switches
a threshold off.

| flag | default | what it does |
|---|---|---|
| `--window BP` | `10` | how far a reference repeat may lie from the insertion point and still count as being at this locus. [Why slack is needed](#window-why-coordinates-need-slack) |
| `--max-motif-edits N` | `0` | edit budget applied at every motif length. `0` means exact matching. At `1` or above, `CAG` also matches `CAT` |
| `--max-motif-edit-fraction FRAC` | off | edit budget as a fraction of motif length, applied to motifs over 6 bp only. Intended for [VNTR consensus disagreements](#motif-tolerance) |
| `--min-subrepeat-motif BP` | off | also match a motif that tiles the other, when the tiling unit is at least this long. See [motif tolerance](#motif-tolerance) |
| `--max-fuzzy-motif BP` | `200` | the longest motif the three settings above are attempted on. Has no effect when they are all off |
| `--min-reference-identity PCT` | off | ignore reference repeats below this identity. A **percentage**, 0–100. UCSC only |
| `--min-reference-copy-num N` | off | ignore reference repeats with fewer copies than this |
| `--min-reference-length BP` | off | ignore reference repeats shorter than this |

The three `--min-reference-*` thresholds decide which catalogue rows count as
annotation at all. Raising one lowers `n_nearby` and can change `known` to
`novel_locus`. A catalogue that lacks the underlying column is unaffected, and
the run reports this on stderr.

### Row filters

These select which already-screened rows are kept, so a sweep can reuse one
screen across several filter settings. Rows are tagged rather than dropped unless
`--drop-filtered` is given. A missing value passes.

| flag | default | drops rows where |
|---|---|---|
| `--min-purity FRAC` | off | TRF identity of this repeat is below this. A **fraction** 0–1 |
| `--min-insertion-purity FRAC` | off | [insertion purity](#insertion-purity) is below this. A **fraction** 0–1 |
| `--min-motif-length BP` | off | the motif is shorter than this |
| `--max-motif-length BP` | off | the motif is longer than this |
| `--min-rep-length BP` | off | the repeat covers fewer bases of the insertion |
| `--min-rep-units N` | off | there are fewer copies of the motif |

Note the two different scales. `--min-reference-identity` is a percentage,
because UCSC records identity that way. `--min-purity` is a fraction, because
`sv_trfcaller.py` writes it that way.

## Input columns

One row per **locus × sample × TRF call**. Three columns are read by default
(`--chrom-col`, `--pos-col`, `--motif-col`). The rest are copied to the output
unchanged; several are used by the row filters.

| column | what it is | example |
|---|---|---|
| `chrom` | contig of the insertion site | `chr1` |
| `ins_coord` | reference position the insertion sits after, 1-based | `10772` |
| `SVID` | the caller's variant ID | `Sniffles2.INS.2S0` |
| `depth` | VCF depth field, copied verbatim including brackets | `[0 0]` |
| `insert_size` | length of the inserted sequence; the first integer is used | `[138]` |
| `sample` | the genome this call came from | `HG00597` |
| `rep_start`, `rep_end` | the repeat's span **inside the insertion**, not in the genome | `1`, `68` |
| `motif` | the repeat unit TRF reported | `GC` |
| `purity` | TRF identity of this one repeat, 0–1 | `0.725` |
| `motif_length`, `rep_length`, `rep_units` | motif size, bases covered, copies | `2`, `67`, `33` |

Only `ins_coord` is a genome coordinate.

## Output columns

The input table unchanged, then the columns below, then one block per platform.
The examples are from the first row of the sample output: a `GC` repeat covering
half of a 138 bp insertion at `chr1:10772`.

| column | what it is | example |
|---|---|---|
| `novelty` | the verdict, [combined across platforms](#combining-platforms) | `novel_motif` |
| `canonical_motif` | the query motif's [canonical form](#motif-equivalence-in-depth) | `CG` |
| `insertion_repeat_bases` | bases of this insertion covered by the union of its TRF calls | `67` |
| `insertion_purity` | [fraction of the insertion that is tandem repeat](#insertion-purity), 0–1 | `0.486` |
| `filter` | `PASS`, or the thresholds this row failed | `PASS` |

Per platform, prefixed with its name (`ucsc_`, `trexplorer_`, …):

| column | what it is | example |
|---|---|---|
| `<p>_novelty` | this catalogue's verdict, taken alone | `novel_motif` |
| `<p>_n_nearby` | reference repeats within `--window`, after the `--min-reference-*` filters. A value of `0` produces `novel_locus` | `2` |
| `<p>_start`, `<p>_end` | span of the best reference repeat, in the `--coord-base` convention | `10628`, `10800` |
| `<p>_distance` | bp from the insertion point to that repeat; `0` means the point is inside it | `0` |
| `<p>_motif`, `<p>_canonical` | that repeat's motif and its canonical form. Compare with `canonical_motif` to see why the verdict was reached | `AGGCGCGCC…` |
| `<p>_motif_edits` | `0` when the motifs are equivalent. [Not a distance when tolerance is off](#motif-tolerance) | `1` |
| `<p>_match` | which rule accepted the motif: `exact`, `fuzzy`, `vntr` or `subrepeat`. Empty when no rule matched | `NA` |

UCSC also carries `<p>_period`, `_copy_num`, `_consensus_size`, `_per_match`,
`_per_indel` (`29`, `6.0`, `29`, `100`, `0` here). TRExplorer carries none.

Two summaries are printed to stderr: one per row and one per locus. Rows are
locus × sample × TRF call, so per-row percentages reflect how often a locus
recurs as much as they reflect novelty. Use the per-locus summary.

---

# Details

## Motif equivalence in depth

Two motifs match when their canonical forms are equal. Three transformations
feed that canonical form, and each has its own flag because they differ in how
likely they are to merge repeats that are genuinely distinct.

**Period reduction** is arithmetic, not a judgement: `CAGCAG` is a 3 bp repeat
written twice. Always applied, no flag.

**Rotation** is on by default. The starting phase of a unit comes from the
caller, not the sequence, and both sides of the comparison are TRF output (the
UCSC track is TRF run over the reference). It matters most for long motifs, where
two catalogues are least likely to have picked the same phase: in the sample data
every match on a motif of 51 bp or more required rotation. It is also safest
there, since a primitive *n*-mer has *n* rotations out of 4ⁿ strings, so a
coincidental rotation match is plausible at 2–3 bp and effectively impossible
above 20 bp. Rotation is a cyclic shift, not a reversal: `ATC` gives `TCA` and
`CAT`, never `CTA`.

**Reverse complement** is off by default, because whether a repeat and its
reverse complement are the same locus feature depends on the question. For a
CAG/CTG expansion they usually are; the same rule also merges `A` and `T`, and a
poly-A tail is not a poly-T tail. `--reverse-complement-bp BP` restricts the fold
to units of at least `BP` bases, where the match is unlikely to be coincidental.

| query | reference | default | `--reverse-complement` | `--no-circular` | why |
|---|---|---|---|---|---|
| `CAG` | `CAG` | match | match | match | identical |
| `CAG` | `CAGCAG` | match | match | match | period reduction |
| `CAG` | `AGC` | match | match | **no** | rotation |
| `GC` | `CG` | match | match | **no** | rotation, *not* a strand pair |
| `CAG` | `CTG` | **no** | match | no | reverse complement |
| `A` | `T` | **no** | match | no | reverse complement |
| `CAG` | `CAT` | **no** | **no** | no | one substitution; not an equivalence |

`GC`/`CG` and `AT`/`TA` are reverse complements but also rotations of each other,
so they match at any `--reverse-complement` setting. Only `--no-circular`
separates them.

## Motif tolerance

Tolerance accepts motifs that are *not* equivalent. It is applied per query
rather than stored in the index, so it can be swept without a rebuild, and unlike
equivalence it can make `CAG` match `CAT`. All three settings are off by default,
and with them off `<p>_match` is `exact` on every match.

**Flat versus proportional budget.** A 47 bp VNTR consensus and its counterpart
in another catalogue typically differ by 3–5 bases, about 8% of their length,
while `CAG` and `CAT` differ by 1. No flat budget accepts the first and rejects
the second. On the sample data `--max-motif-edits 1` reclassifies 575 rows, 344
of them (60%) motifs of 6 bp or less — `CAG`/`CAT` matches between different
STRs. `--max-motif-edit-fraction` scales with length and applies only above 6 bp,
so short motifs keep exact matching; at `0.10` it reclassifies 28 of 81
`novel_motif` loci as `known`, all of them long motifs differing only in
consensus. The 6 bp line is the STR/VNTR boundary used by str-analysis.

**Sub-repeat containment.** TRF picks one representative unit per locus, so the
same repeat can be reported as `ACC` from the insertion and `ACCATC` from the
reference. `--min-subrepeat-motif` tiles the shorter motif across the longer one
at the best phase, and the mismatches must fit the edit budget. The tiling is
what keeps it specific: a plain substring test accepts 80% of the `novel_motif`
rows in the sample data, most of them spurious — `A` inside
`CACCACAGAAAACAGAGC`, `GC` inside any GC-rich compound motif. Requiring the short
motif to account for every base rejects those; `A` tiled across that 18-mer
mismatches 11 of 18. Because it shares the edit budgets, it does nothing on its
own — an exact tiling is already period reduction. Alongside
`--max-motif-edit-fraction 0.10` it moves 2 further loci at
`--min-subrepeat-motif 4`, 3 at `2`, and 1 at `6`.

**Length limit.** Approximate comparison is an edit distance minimised over every
rotation, and the longest UCSC consensus is 1,991 bp. `--max-fuzzy-motif` sets
the length above which motifs must match exactly. The 200 bp default sits above
the VNTR range the fraction budget targets: the sample data has same-length VNTR
pairs up to 77 bp. Runtime over 4,518 rows against both catalogues is 2.5 s with
tolerance off, 8.7 s with all three enabled.

**Reading the columns.** `<p>_motif_edits` is clamped to `budget + 1`, so it is
not a distance; with tolerance off it is binary (`0` matched, `1` did not, empty
means nothing nearby), and once the budget varies with motif length the counts
are not comparable between rows. Read `<p>_match`, which names the rule that
matched. Report the tolerance settings alongside any novelty count derived from
them.

## Window: why coordinates need slack

An insertion has one coordinate, the base it was placed after. A reference repeat
has an interval. Neither is exact: the breakpoint comes from aligning noisy
reads, and the repeat boundaries come from TRF. Requiring a strict overlap would
classify a repeat one base past the edge as `novel_locus` because of where the
caller placed the breakpoint.

```text
                   reference repeat  [==================]
    insertion point       x  <-4bp->
                          |------ window 10 ------|   within range: known
                          |-- window 0 --|             out of range: novel_locus
```

Larger values classify more loci as `known`, and the effect does not plateau: on
the sample data, `0` to `50` reclassifies 28 loci. Report the window alongside
any novelty count.

## Insertion purity

The fraction of the inserted sequence that is tandem repeat. An insertion whose
repeats cover 5% of its length is mostly non-repetitive, and is weak evidence for
a novel TR — in the sample data this is what separates novel TR loci from
mobile-element insertions carrying a poly-A tail.

It is the **union** of the TRF intervals over `insert_size`, not their sum. TRF
reports overlapping calls over the same sequence (one insertion in the sample
data has 64), so summing `rep_length` double-counts and can exceed 1.

## Combining platforms

Each platform is screened independently and gets its own columns. The `novelty`
column takes the least novel verdict across them, so a locus is `novel_locus`
only if no catalogue found anything. Screening two catalogues mainly reclassifies
`novel_motif` rows rather than `novel_locus` ones.

`unscreened` ranks below the other three, so a catalogue without coverage never
overrides one that produced a verdict. This matters because a catalogue limited
to the primary assembly carries no information about alt, random or decoy
contigs, and reporting those as `novel_locus` would turn missing coverage into
apparent novelty — TRExplorer v2 carries 25 contigs against UCSC's 702. It would
also inflate the `agreement` objective, since both catalogues would return the
same verdict there. `annotate` lists the affected contigs on stderr.

`pathogenic` is annotation-only: it produces its columns but is excluded from the
combined verdict, and `--platform pathogenic` alone is rejected. A catalogue of
83 loci would classify everything else in the genome as novel.

## Searching the settings

`sweep` runs `annotate` repeatedly, writing one row of counts per run. It is
built on [Optuna](https://optuna.org), which provides trial storage, resumable
studies and a dashboard. Any setting accepts a list (`0,1,10`), a range (`0:50`),
or a range with a step (`0:50:5`); anything not given stays at its default.

| flag | what it does |
|---|---|
| `--sampler {grid,tpe,random}` | `grid` runs every listed combination; `random` samples at random; `tpe` concentrates later trials near high-scoring regions |
| `--trials N` | number of runs. Defaults to the full grid, or 50 when sampling |
| `--objective {agreement,truth,none}` | the score to optimise |
| `--truth PATH` / `--truth-col` | loci with known answers: chrom/pos plus a known/novel column |
| `--direction {maximize,minimize}` | optimisation direction (default: `maximize`) |
| `--seed N` | fixes the random seed so a search is reproducible |
| `--storage URL` / `--study-name` | for example `sqlite:///study.db`, to persist and browse trials |

Each row records every setting plus `n_rows`, `n_rows_pass`, `n_loci`,
`rows_<status>`, `loci_<status>`, `frac_loci_novel`, the same counts per
platform, and that trial's `objective`/`score`. `annotate --metrics PATH` appends
the same row minus the last two.

The objectives are `agreement` — the Jaccard index of the novel-locus sets the
catalogues produce independently, scored on the novel sets so that a large
`--window` calling everything `known` cannot win, and requiring two platforms;
`truth` — balanced accuracy against `--truth`, the only objective that measures
correctness rather than consistency; and `none`, which just enumerates.

Comparing settings is not selecting them. Without a truth set a sweep measures
how far a conclusion depends on the thresholds, not which thresholds are right. A
result that holds across the grid is robust; one that appears only at particular
cutoffs is a property of those cutoffs. Compare `frac_loci_novel` rather than raw
counts, because row filters change the denominator.

## Causes of inflated novel counts

- **Near misses** — one substitution reads as `novel_motif` with tolerance off.
  For long motifs this is usually a consensus disagreement; see
  [motif tolerance](#motif-tolerance).
- **Sub-repeat containment** — an `ACC` query against an `ACCATC` consensus. See
  [above](#motif-tolerance).
- **Strand** — with `--reverse-complement` off, a repeat annotated on the
  opposite strand reads as `novel_motif`.
- **Uncovered contigs** — reported as `unscreened`, not `novel_locus`, but check
  the stderr line.
- **Recurrence** — one locus can contribute dozens of rows. Read the per-locus
  summary, not the per-row percentages.

## How it's implemented

The catalogue is held column-wise in numpy arrays sorted by `(chrom, start)`.
Overlap search is a `searchsorted` plus a short walk left, bounded by a per-contig
running maximum of the interval ends. Motif strings are interned, so the 1.05M
`simpleRepeat` rows for hg38 canonicalise only their 515,928 distinct sequences.

All coordinates are 0-based half-open internally, converted once at the
boundaries. VCF `POS` is 1-based; UCSC `simpleRepeat`, plain BED and TRGT BED are
0-based half-open. The TRGT convention was verified against the ExpansionHunter
JSON distributed with the same catalogue upstream, whose `ReferenceRegion`
strings are byte-identical to the BED start/end pairs.

The motif and coordinate primitives are not owned by this step. They live in
`src/python/trcore/`, which the STRchive step imports too, because two steps that
disagree by one base on what "overlapping" means — or that fold strands
differently — produce tables that look comparable and are not. `trcore` is pure
standard library, so importing it does not drag pandas into a step that has no
need of it.

| file | what it holds |
|---|---|
| `trcore/motifs.py` | `MotifEquivalence` and `MotifTolerance`, canonical form, fuzzy and tiling distance |
| `trcore/coords.py` | 0-based half-open conversion, contig naming, interval distance |
| `platforms.py` | catalogue sources and readers — UCSC, TRExplorer, BED, TRGT BED — normalised to one schema, plus the pandas-vectorised `canonical_motifs` |
| `catalog.py` | the interval index, the verdict, the index cache |
| `insertions.py` | insertion purity and the `filter` column |
| `search.py` | the Optuna search: axes, samplers, objectives |
| `cli.py` | the four commands, and the table declaring every tunable setting |
| `tests/python/novelty/`, `tests/python/trcore/` | one test module per source module; `uv run pytest` |

Adding a catalogue means a reader plus a registry entry in `platforms.py`. Adding
a setting means one row in `HYPERPARAMS` in `cli.py`, which wires it into
`annotate`, `sweep` and the metrics table at once.

---

## Sources

### `str-analysis` (Ben Weisburd, Broad Institute)

<https://github.com/broadinstitute/str-analysis> — MIT licensed, © 2021 Broad
Institute. Not a dependency: the methods below were re-implemented and one data
file vendored.

- **The STR/VNTR boundary at 6 bp** (`utils/eh_catalog_utils.py`,
  `compute_repeat_unit_id`) — motifs of 6 bp and under are keyed by sequence;
  longer ones vary between callers, so their sequence is not a reliable identity.
  Used as `STR_MAX_MOTIF = 6` in `trcore/motifs.py` to gate `--max-motif-edit-fraction`.
  Their rule itself was not adopted: it treats any two motifs of equal length
  above 6 bp as the same repeat with no sequence check, which reclassifies 365
  rows of the sample data, against 382 for a proportional edit budget that still
  compares sequences.
- **Tiling purity** (`utils/find_motif_utils.py`, `compute_repeat_purity`) —
  tile a motif and count matching bases rather than compare strings. Implemented
  as `tiling_distance()` for `--min-subrepeat-motif`. Theirs tiles across the
  reference genome; this tiles across the other catalogue's consensus, which is
  weaker evidence but needs no FASTA.
- **The IUPAC complement table** (`utils/misc_utils.py`) — fixed a latent bug
  where `reverse_complement` translated only `ACGTN`, so `ACRYN` returned
  `NYRGT` instead of `NRYGT`.
- **83 disease-associated TR loci** (`variant_catalogs/catalog.GRCh38.TRGT.bed`)
  — vendored unchanged as `data/novelty/pathogenic.hg38.TRGT.bed` with a
  provenance header.

Their `compute_canonical_motif` was compared and not adopted: it does not reduce
to the primitive unit (`CAGCAG` → `AGCAGC`), folds in the reverse complement by
default, and raises `KeyError` on lowercase input. On 5,446 primitive motifs the
two agree exactly.

### Not adopted

- **Reference-sequence purity** — tiling the query motif across the reference
  sequence at the locus rather than across another catalogue's consensus. It
  separates real sub-repeats cleanly (at `chr1:1201778-1202830`, a 19 bp query
  motif scores 0.944 against a `CAG` control's 0.315) but needs a FASTA, which
  this tool does not otherwise require.
- **Catalogue boundary extension** (`extend_str_catalog_boundaries.py`) —
  extends loci outward through interrupted copies while purity stays above 90%,
  addressing the same problem as `--window` at the source. Best as a
  preprocessing pass over the catalogue file, which `--repeats` already accepts.
  Also needs a FASTA.
- **Overlap measured in motif copies** rather than base pairs (`merge_loci.py`)
  — would make `--window` scale with motif length.
- **Gene region and mappability annotations** — need a GENCODE GTF, a bigWig and
  `pyBigWig`.

### Other references

- UCSC `simpleRepeat` schema —
  <https://genome.ucsc.edu/cgi-bin/hgTables?db=hg38&hgta_track=simpleRepeat&hgta_doSchema=describe+table+schema>
- TRExplorer catalog — <https://trexplorer.broadinstitute.org>, releases at
  <https://github.com/broadinstitute/trexplorer-catalog>
