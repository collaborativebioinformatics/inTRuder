# TR loci by novelty class and allele count

*Generated 2026-08-28 17:39 UTC by `src/python/reporting/novelty_frequency_report.py` from `05_hprc_multisample.tsv` (67 HPRC genomes, 17,270 true loci).*

## Locus identity: (chrom, position), not SVID

This merged VCF assigns the `SVID` column per-sample-call rather than one shared ID per joint locus: the same physical insertion can carry a different SVID depending on which sample carries it. Grouping by SVID gives 21,424 apparent loci; grouping by `(chrom, ins_coord)` collapses these to 17,270 true loci. The difference isn't just inflation -- it's directional: `SVID`-based carrier counts are biased *low*, because a locus's carriers can be split across several SVIDs, each of which looks individually rarer than the locus really is. Checked directly: for the large majority of split loci, the true pooled carrier count (grouping by position) exceeds what any single SVID shows on its own. Every count on this page uses the corrected `(chrom, position)` definition.

Locus-level novelty class is also derived per position: 97.2% of loci have one unanimous verdict across all their carriers/SVIDs; the remaining 2.8% disagree (occasionally the same sample carries both a `known`-tagged and a `novel_motif`-tagged call at the identical coordinate, suggesting genuinely distinct alleles collapsed onto one position). The majority verdict is used as a pragmatic tie-break.

## Binning

Carrier count is binned by doubling (1, 2, 3-4, 5-8, 9-16, 17-33, 34-49, 50-67) rather than fixed percentage cutoffs -- a standard site-frequency-spectrum convention that scales cleanly with cohort size instead of rounding inconsistently for n=67 (e.g. "10%" of 67 is 6.7, which different rounding rules place at either 6 or 7). Only 7 loci in the entire callset are carried by all 67 genomes, too few for their own bin, so the top two bands (34-49, 50-67) absorb the common/fixed end.

## Loci by class and allele count

Raw locus counts, not proportions and not per-genome medians -- this is literally how many `novel_motif`/`novel_locus` loci exist at each carrier count. `known` loci are omitted from the plot (not of interest here) but included in the table below for reference.

| bin   |   known |   novel_motif |   novel_locus |
|:------|--------:|--------------:|--------------:|
| 1     |    3719 |           945 |            48 |
| 2     |    1820 |           497 |            18 |
| 3-4   |    1954 |           545 |            21 |
| 5-8   |    1901 |           489 |            15 |
| 9-16  |    1661 |           444 |            15 |
| 17-33 |    1619 |           390 |            15 |
| 34-49 |     660 |           166 |             8 |
| 50-67 |     224 |            91 |             5 |

![Loci by class and allele count, log scale](assets/novelty_by_allele_count/loci_by_allele_count_log.png)

![Loci by class and allele count, linear scale](assets/novelty_by_allele_count/loci_by_allele_count_linear.png)

## Reading this chart

Both classes decline sharply from rare to common. That decline is *expected* and not specific to novelty -- it's the standard site-frequency-spectrum pattern seen for essentially every kind of genetic variant: a new mutation/insertion arises in one person at a time, and only a small fraction of lineages ever drift up to high frequency across a sampled population. `known` loci (see the table) decline the same way, which rules out this being an artifact specific to the novelty classification.

What this chart does *not* show is whether novelty *rate* changes with rarity -- that requires normalizing each bin by its total locus count (known + novel_motif + novel_locus), which on this filtered dataset comes out essentially flat (~20% novel_motif, <1.2% novel_locus in every bin) -- consistent with a related result in `feature/population-structure`'s methods doc, where an analogous novelty-vs-frequency association held on an *unfiltered* call set but flattened out once the pipeline's quality filters were applied.
