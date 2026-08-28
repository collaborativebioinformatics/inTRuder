# Population structure of candidate novel TR loci

Cohort-level analysis of the candidate loci produced by the novelty screen: how
often each locus is carried, whether carrier burden differs by genetic ancestry,
and whether the carrier frequency spectrum behaves the way real variation should.

## Input

| Path | Contents |
|---|---|
| `data/sv_output/survivor_multi_sample_vcf/first_500_INS.vcf` | carrier information, `SUPP_VEC` |
| `data/sv_output/survivor_multi_sample_vcf/first_500_INS.novelty.tsv` | novelty verdicts |
| `data/metadata/sample_population.tsv` | sample to superpopulation mapping |

The 4,518 screened rows are `locus × sample × TRF call`. They collapse to **221
loci** on `(chrom, ins_coord)`, taking the least-novel verdict per locus, which
reproduces the counts in `first_500_INS.metrics.tsv` exactly (114 known, 81
`novel_motif`, 26 `novel_locus`). Carrier counts are read from the 69-bit
`SUPP_VEC`; the two CHM13 controls are excluded, giving 1 to 67 carriers.

## Sample metadata

`data/metadata/sample_population.tsv` maps all 69 columns of the merged VCF to a
1000 Genomes population and superpopulation.

Labels come from the **3,202-sample pedigree**
(`20130606_g1k_3202_samples_ped_population.txt`), not the commonly cited
2,504-sample phase-3 panel. The phase-3 panel labels only 33 of the 67 cohort
genomes, because HPRC draws from the expanded set. The pedigree labels 66.

`NA21309` is recorded as `UNKNOWN`. It is absent from every 1000 Genomes source
checked, and the HPRC year-1 metadata lists it as `HPRC_PLUS` with its
population fields blank. It is left unlabelled rather than inferred.

| Superpopulation | Genomes |
|---|---:|
| AFR | 19 |
| EAS | 14 |
| AMR | 12 |
| SAS | 12 |
| EUR | 9 |
| UNKNOWN | 1 |

## Results

### 1. Novel loci are carried by fewer genomes

`results/figures/fig1_sharing_spectrum.pdf`

| Class | Singletons | Median carriers |
|---|---:|---:|
| Known (n=114) | 19.3% | 6 |
| Novel motif (n=81) | 37.0% | 3 |
| Novel locus (n=26) | 34.6% | 2 |

Novel loci are singleton-enriched relative to known ones (OR 2.4, Fisher exact
p = 0.0065).

This is an internal consistency check on the screen. If novel verdicts were
predominantly annotation artefacts, they would be scattered across the frequency
spectrum rather than concentrated at low carrier counts. They are not.

### 2. No detectable difference in burden between superpopulations

`results/figures/fig2_ancestry_burden.pdf`

Novel loci carried per genome, by superpopulation: AFR median 22, SAS 20.5,
AMR 20, EAS 19.5, EUR 19. Kruskal-Wallis H = 7.88, **p = 0.096: not
significant**.

AFR versus EUR alone gives p = 0.023, but that is one of ten possible pairwise
comparisons with no correction applied, and it does not survive one. The
between-group median spread is 3 loci against a within-cohort range of 15 to 27.

**This is reported as a null result.** With 9 to 19 genomes per group and 221
loci, the analysis is underpowered for the question. The correct statement is
that no difference is detectable at this scale, not that none exists.

### 3. Novel loci trend toward being confined to one superpopulation

`results/figures/fig3_private_loci.pdf`

| Class | Private to 1 | Shared by 2-4 | In all 5 |
|---|---:|---:|---:|
| Known | 27% | 33% | 39% |
| Novel motif | 41% | 35% | 25% |
| Novel locus | 46% | 42% | 12% |

Monotone in the expected direction, chi-squared p = 0.059. Suggestive, not
significant.

### 4. Half the loci present in every genome are still called novel

`results/figures/fig4_fixed_frequency.pdf`

The novel fraction falls as loci become more common (Spearman rho = -0.20,
p = 0.0025), consistent with result 1. It then **rebounds to 50% at fixed
frequency**: 7 of the 14 loci carried by all 67 genomes are called novel, and
**6 of those 7 are also carried by a CHM13 control**.

A variant at 100% frequency across an ancestry-diverse cohort and an independent
control is not rare variation. Reference annotation is the more likely
explanation. The motif pairs at those loci name the mechanism:

| Locus | Query motif | Nearest reference motif | Insertion purity |
|---|---|---|---:|
| chr1:1245158 | `CTCCT` | `CCCCCCACTCCT` | 0.85 |
| chr1:3026038 | `TGA` | `GTGATG` | 0.83 |
| chr1:3260742 | `TGGTGA` | none annotated | 0.92 |
| chr1:2522791 | `TG` | `GGTGCTATAGTGACTTAACGGA` | 0.07 |
| chr1:191372 | `A` | `CACCACAGAAAACAGAGC` | 0.005 |
| chr1:1993704 | `A` | none annotated | 0.13 |

`TGA` against `GTGATG` is period reduction; `CTCCT` against `CCCCCCACTCCT` is
sub-repeat containment. Both are cases
[`NOVELTY_SCREEN.md`](../tools/NOVELTY_SCREEN.md) lists under causes of inflated
novel counts, here at the frequency where they are hardest to attribute to rare
variation. This supports issue #43: the reference catalogue was not built with
TRF parameters matching this pipeline.

Three of the six have insertion purity below 0.15, meaning under 15% of the
inserted sequence is repeat. `chr1:191372` is a 2,000 bp insertion whose only
repeat is 11 copies of `A`. These have the signature of mobile-element poly-A
tails rather than tandem repeats. All rows carry `filter = PASS` because the
committed run set no `--min-insertion-purity`; the 80% threshold discussed in
issue #25 would remove them.

## Limitations

- **Subset, not the full callset.** 500 records from chr1 only, yielding 221
  loci. Every count scales with the complete merged VCF.
- **Input predates the fix for issue #48.** The committed TSVs still carry its
  signature (`min(insert_size - rep_end) = 68` across 1,125 rows), so
  `rep_start`, `rep_end` and `insertion_purity` are shifted. Carrier counts are
  taken from the VCF `SUPP_VEC` and are unaffected, which is why results 1 to 4
  stand. Insertion-purity values above are indicative only.
- **Coverage and chemistry are uncontrolled.** Neither mosdepth output nor the
  R9.4.1/R10.4.1 assignment is available in the repository, so per-genome counts
  are not adjusted for sequencing depth. Across the 14 committed per-sample VCFs
  total SV yield varies by only 1.9% (CV), which argues against a large depth
  effect but is not a substitute for the measurement.
- **Small groups.** 9 to 19 genomes per superpopulation. Result 2 is reported as
  null for this reason, and no p-values are attached to ancestry comparisons in
  the figures beyond the omnibus test.
- **`novel_locus` has n = 26.** Percentages move in roughly 4-point steps.

## Reproducing

```bash
python src/python/popstruct/make_figures.py
```

Requires `pandas`, `numpy`, `matplotlib` and `scipy`. Writes four PNG/PDF pairs
to `results/figures/` and reads `results/locus_carriers.tsv`, the 221-locus
intermediate table.
