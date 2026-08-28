# Population-level TR distributions by novelty class

*Generated 2026-08-28 16:09 UTC by `src/python/reporting/population_report.py` from `data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv` (4,518 TRF calls across 296 SVs).*

Colours follow the same fixed palette as [`notebooks/novel_tr_results.ipynb`](../../notebooks/novel_tr_results.ipynb): one novelty class, one colour, everywhere. Distributions are shown as raw counts (not density) — class sizes differ by ~4x, so absolute magnitude matters here, not just shape.

## Summary

| novelty     |    n | %     |   median motif_length |   median rep_length |   median purity |   median gc_content |
|:------------|-----:|:------|----------------------:|--------------------:|----------------:|--------------------:|
| known       | 2318 | 51.3% |                     4 |               156.5 |           0.802 |               0.5   |
| novel_motif | 1579 | 34.9% |                     4 |               353   |           0.801 |               0.667 |
| novel_locus |  621 | 13.7% |                     1 |                30   |           0.792 |               0     |

![Calls by novelty class](assets/population_distributions/novelty_counts.png)

## Motif length

Values at or above 30bp are pooled into the `30+` bucket and called out with an annotation — the underlying summary table above is exact. An earlier version of this chart used a fixed axis range that cut the view off at 32bp without pooling the overflow, which silently dropped 8.3% of all calls (actual motif lengths run up to 77bp) from the plot entirely.

![Motif length by novelty class](assets/population_distributions/motif_length.png)

## Repeat tract length

Values at or above 3000bp are pooled into the `3000+` bucket the same way (here the overflow is small: 11 rows, 0.2% of all calls).

![Repeat tract length by novelty class](assets/population_distributions/rep_length.png)

## Purity

`known` calls concentrate sharply around 0.67-0.85 purity; novel calls (both classes) are flatter and skew higher. This matters for interpreting the purity filter used downstream (`src/python/filter/filter_ins_trf.py`): it removes a disproportionate share of `novel_locus` calls relative to `known` ones.

![Purity by novelty class](assets/population_distributions/purity.png)

## GC content

GC content is the fraction of G/C bases in the repeat motif itself (`(motif.count('G') + motif.count('C')) / len(motif)`), bounded in [0, 1] by definition — no capping needed. An earlier version of this chart (`notebooks/pop_viz.ipynb`) computed `motif.str.count('GC') * rep_units` — the literal substring count scaled by copy number — which is unbounded and does not measure base composition; that computation has been replaced here.

![GC content by novelty class](assets/population_distributions/gc_content.png)
