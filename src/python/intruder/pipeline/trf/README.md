# filter_ins_trf.py

Filter a TSV of structural-variant insertions annotated with TRF (Tandem
Repeats Finder) output, and generate a companion summary-stats TSV.

## What it does

Given a TSV where each row is a TRF hit inside an insertion sequence, the
script applies a configurable chain of filters and writes:

1. **A filtered TSV** — same columns as the input, plus a new
   `repeat_coverage` column.
2. **A stats TSV** — a filtering funnel, unique-insertion counts, and a
   breakdown by `motif_length` for the final filtered set.

## Input format

Tab-separated, with a header row containing at least these columns:

| Column        | Meaning                                              |
|---------------|-------------------------------------------------------|
| `chrom`       | Chromosome                                             |
| `ins_coord`   | Insertion coordinate                                   |
| `SVID`        | Structural variant ID (not globally unique across samples) |
| `depth`       | Number of reads supporting the insertion               |
| `insert_size` | Length of the insertion (bp)                           |
| `sample`      | Sample ID                                               |
| `allele`      | Allele (e.g., reference or alternate)                   |
| `rep_start`   | TRF repeat start position within the insertion          |
| `rep_end`     | TRF repeat end position within the insertion             |
| `motif`       | Repeat motif sequence                                   |
| `purity`      | TRF purity score (0–1)                                  |
| `motif_length`| Length of the repeat motif (bp)                         |
| `rep_length`  | Length of the repeat region covered by TRF (bp)          |
| `rep_units`   | Number of repeat units                                   |

NOTE: The input could be from the novelty script. With the additional columns from the novelty script output.

A single insertion (`chrom` + `ins_coord` + `SVID` + `sample`) can have
multiple rows if TRF found more than one repeat region inside it.

## Installation

No dependencies beyond the Python 3 standard library.

```bash
python3 --version   # 3.7+
```

## Usage

```bash
python filter_ins_trf.py -i input.tsv -o filtered.tsv
```

With all filters set explicitly:

```bash
python filter_ins_trf.py \
    -i input.tsv \
    -o filtered.tsv \
    -s filtered.stats.tsv \
    --exclude-motif-sizes 1,2,3,10 \
    --min-repeat-coverage 0.8 \
    --min-purity 0.7 \
    --max-insert-size 10000 \
    --min-depth 10
```

## Arguments

| Flag | Default | Description |
|---|---|---|
| `-i, --input` | *required* | Input TSV path |
| `-o, --output` | *required* | Filtered output TSV path |
| `-s, --stats-output` | `<output>.stats.tsv` | Stats TSV path |
| `--exclude-motif-sizes` | *(none)* | Comma-separated motif sizes to drop, e.g. `1,2,3,10` |
| `--keep-motif-sizes` | *(none)* | Comma-separated motif sizes to keep exclusively (applied after `--exclude-motif-sizes`) |
| `--min-repeat-coverage` | `0.8` | Minimum `rep_length / insert_size` fraction |
| `--min-purity` | `0.7` | Minimum TRF purity |
| `--max-insert-size` | `10000` | Maximum insertion length (bp); longer insertions are dropped |
| `--min-depth` | `10` | Minimum supporting read depth |

## Filters applied (in order)

1. **Motif size exclusion/inclusion** — drop rows by `motif_length`, or
   restrict to a whitelist.
2. **Repeat coverage** — keep rows where the TRF repeat covers at least
   `--min-repeat-coverage` of the insertion (`rep_length / insert_size`).
3. **Purity** — keep rows with `purity >= --min-purity`.
4. **Insertion size cap** — drop rows with `insert_size >
   --max-insert-size`.
5. **Depth** — keep rows with `depth >= --min-depth`.

Each step is applied to the output of the previous step, and the order
above is fixed. If you need a different order or additional filters, see
[Extending the script](#extending-the-script).

## Output files

### Filtered TSV

All original columns, unchanged, plus:

- `repeat_coverage` — `rep_length / insert_size`, rounded to 4 decimal
  places. Rows with `insert_size == 0` get `repeat_coverage = 0`.

### Stats TSV

Three sections in one file (plain-text section headers start with `##`):

**1. Filtering funnel** — rows in/removed/remaining at each step, so you
can see which filter is doing the most trimming:

```
## Filtering funnel
step	rows_in	rows_removed	rows_remaining
input	9	0	9
exclude_motif_sizes([1])	9	2	7
min_repeat_coverage(>=0.8)	7	1	6
min_purity(>=0.7)	6	0	6
max_insert_size(<=10000)	6	0	6
min_depth(>=10)	6	0	6
```

**2. Unique insertion counts** — before and after filtering, counted as
distinct `(chrom, ins_coord, SVID, sample)` combinations (since a single
insertion can have multiple TRF-hit rows):

```
## Unique insertion counts (chrom+ins_coord+SVID+sample)
unique_insertions_input	8
unique_insertions_output	6
```

**3. Summary by motif_length** — for the *final filtered* set, grouped by
`motif_length`:

```
## Summary by motif_length (final filtered set)
motif_length	n_trf_hits	n_unique_insertions	n_unique_samples	mean_purity	median_purity	mean_repeat_coverage	median_repeat_coverage	mean_insert_size	median_insert_size
2	2	2	2	0.71	0.71	0.6182	0.6182	198	198.0
5	4	4	4	0.8133	0.8135	0.6903	0.6791	221.8	213.5
```

## Notes and gotchas

- **`--min-purity` has no universally "correct" default.** The script
  defaults to `0.7`; tune this to your data.
- **`--min-depth 10`** will drop everything if your `depth` column is
  all zeros or otherwise not populated — check that column has real
  values before assuming the script is broken.
- Rows with non-numeric values in a numeric column (`depth`,
  `insert_size`, `rep_start`, `rep_end`, `purity`, `motif_length`,
  `rep_length`, `rep_units`) are skipped with a warning printed to
  stderr; they don't crash the run.
- `SVID` is only unique *within* a sample in this dataset (the same
  `SVID` string can appear for different samples), so unique-insertion
  counting always includes `sample` in the key.

## Extending the script

The filters live in `run_filters()` as a sequence of `apply_step(name,
predicate)` calls — add, remove, or reorder steps there to change the
filtering logic. The per-`motif_length` summary lives in
`summarize_by_motif_length()`; group by a different column (e.g.
`motif`, `chrom`, or `sample`) by changing the `groups.setdefault(...)`
key.