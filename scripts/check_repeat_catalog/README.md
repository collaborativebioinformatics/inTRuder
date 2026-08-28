## intersect.sh

This script will find intersection between internal tandem repeats can be found in the TR catalog by [Chiu et. al.](https://www.nature.com/articles/s41467-025-66153-5#citeas) It can be invoked like this:

```bash
bash intersect.sh
```

## join-hits

The above script calls `join-hits`, the console script for
[`intruder.analysis.benchmark.join_hits`](../../src/python/intruder/analysis/benchmark/join_hits.py),
to label which internal TRs are found in the catalog. It adds an extra field to the input TSV file as described below:

```
...
- in_catalog: true if TR is found in the catalog else false
```

Briefly, the TRs found in the catalog (hits) are joined back to the original file. If unsuccessful join then the internally-found TR isn't in the catalog and vice-versa. This script is being called from 'intersect.sh' like so:

```bash
uv sync --group analysis   # join-hits needs polars, which lives in the analysis group
uv run join-hits --query $TR_RESULTS_FILE --hits $INTERSECTIONS_FILE --output $OUTPUT
```

## example output

The output from this is the original TSV file with an extra column to denote whether internal TR is found in the catalog.

```
chrom	ins_coord	SVID	depth	insert_size	sample	rep_start	rep_end	motif	purity	motif_length	rep_length	rep_units   in_catalog
chr1	10772	Sniffles2.INS.2S0	0	138	HG00597	0	69	GC	0.718	2	69	36  true
chr1	10772	Sniffles2.INS.4S0	0	258	HG01993	1	191	GC	0.702	2	190	97  true
chr1	20849	Sniffles2.INS.6S0	0	1995	NA19240	303	314	A	1.0	1	11	13  false
chr1	34044	Sniffles2.INS.5S0	0	3056	HG02071	71	108	T	0.784	1	37	39  true
chr1	34044	Sniffles2.INS.5S0	0	3056	HG02071	791	1135	TCTGT	0.558	5	344	70 true
```