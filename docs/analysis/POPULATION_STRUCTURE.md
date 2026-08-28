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

### 5. African genomes carry 13.6% more non-reference insertions

`results/figures/fig5_burden_by_ancestry.pdf`

Results 1 to 4 use the 500-record chr1 subset. This one uses the **full callset**:
`hprc_multisample.INS.vcf`, 106,844 insertions across all 24 chromosomes and the
same 67 genomes, joint-called with Sniffles2 2.8.0.

| Superpopulation | n | Median insertions | Range |
|---|---:|---:|---|
| **AFR** | 19 | **14,947** | 14,650-15,504 |
| AMR | 12 | 13,192 | 12,664-13,600 |
| EUR | 9 | 13,162 | 12,830-13,395 |
| SAS | 12 | 13,115 | 12,933-13,469 |
| EAS | 14 | 13,104 | 12,844-13,430 |

Kruskal-Wallis H = 40.13, **p = 4.1e-08**. AFR versus EUR, **+13.6%, p = 2.9e-05**.

The separation is complete: **the lowest AFR genome (14,650) carries more
insertions than the highest non-AFR genome (13,600)**. All 19 AFR genomes sit
above all 48 others, with no overlap.

This is the signature reference bias predicts. GRCh38 is built predominantly from
individuals of European ancestry, so genomes of African ancestry carry more
sequence the reference lacks, and that sequence surfaces as insertion calls.

**Note that this supersedes result 2, and measures something broader.** Result 2
found no ancestry difference in *novel TR* burden across 221 chr1 loci and was
reported as an underpowered null. This measures *total insertion* burden across
106,844 records, where the signal is unambiguous. The two are consistent: the
earlier analysis lacked the power, not the effect. Whether the difference holds
specifically for novel TR loci still requires running the TR detection and
novelty screen over the full callset.

Carrier status is taken from **genotypes**, not `SUPP_VEC`. In this Sniffles2
joint-called VCF the two disagree on 17.4% of records, because `SUPP_VEC` marks
samples with supporting evidence while `GT` is the post-filter call; `SUPP_VEC`
reports 34,984 singletons against the genotypes' 39,304. In the SURVIVOR file
used for results 1 to 4 they agree exactly on all 500 records.

Coverage remains uncontrolled, and a systematic depth difference by ancestry
could in principle produce this. The complete separation of the groups makes that
unlikely but does not exclude it; per-sample mosdepth output would settle it.


### 6. The difference is concentrated in rare insertions, and is not a coverage artefact

`results/figures/fig6_rarity_gradient.pdf`

Restricting to progressively rarer insertions sharpens the ancestry difference
rather than softening it:

| Restricted to insertions carried by | AFR | AMR | EAS | EUR | SAS | AFR/EUR | Kruskal-Wallis p |
|---|---:|---:|---:|---:|---:|---:|---:|
| all | 14,947 | 13,192 | 13,104 | 13,162 | 13,115 | 1.14x | 4.1e-08 |
| under 50% of samples (<34) | 9,115 | 6,862 | 6,750 | 6,831 | 6,848 | 1.33x | 2.7e-08 |
| at most 10% (<=7) | 4,178 | 2,236 | 1,991 | 1,900 | 2,182 | 2.20x | 5.4e-10 |
| at most 5% (<=3) | 2,284 | 1,212 | 1,018 | 935 | 1,190 | 2.44x | 3.8e-10 |
| **private to one genome** | **931** | 505 | 454 | 374 | 528 | **2.49x** | 4.7e-10 |

African-ancestry genomes carry **2.5 times as many private insertions** as
European-ancestry genomes. Common insertions dilute the signal because they are
shared by everybody; the excess lives in rare variation, which is what reference
bias combined with greater African genetic diversity predicts.

**Sequencing depth does not explain it.** Using `DR + DV` from the genotype
fields as a per-sample depth proxy:

- depth versus insertion count is **negatively** correlated (Pearson r = -0.336,
  p = 0.006), so deeper genomes yield slightly *fewer* calls, the opposite of a
  naive detection-power confound;
- AFR median depth is **35.7** against **37.2** for the other groups, so AFR
  genomes are marginally *under*-covered;
- regressing insertion count on depth and an AFR indicator leaves an AFR effect
  of **+1,777 insertions (t = +29.7)** after adjustment.

If anything the depth difference means the effect above is slightly understated.


### 7. Genome-wide replication, and what filtering does

Running the detection and novelty screen over the full call set (106,844
insertions, 1,044,405 repeat calls, 43,379 loci with a verdict) replicates the
chromosome 1 results at scale and resolves the two that were underpowered.

| | chr1 subset (221 loci) | genome-wide (43,379 loci) |
|---|---|---|
| singleton enrichment, novel vs known | OR 2.4, p = 0.0065 | OR 1.60, **p = 4.6e-109** |
| private to one superpopulation | p = 0.059 (n.s.) | chi2 = 1,048, **p = 2.8e-228** |
| novelty vs carrier frequency | rho = -0.20 | rho = -0.090, **p = 2.6e-79** |
| fraction of loci called novel | 48.4% | 51.0% |

The overall novelty rate held, but its composition did not: `novel_locus` rose
from 11.8% of loci on chromosome 1 to 30.9% genome-wide while `novel_motif`
roughly halved. Chromosome 1 is not representative, and any composition claim
made from the subset should be restated.

**Quality filtering matters far more than the reference catalogue.** An
independently produced, filtered version of the same call set (A. Avvaru,
`hprc_multisample.trf.noveltyFiltered.tsv`, all rows `PASS`) contains 17,270
loci, an exact subset of the 43,379 above, with none absent from our own run.
Its novelty rate is **20.2%** against our unfiltered **51.0%**, and
`novel_locus` falls from 13,386 loci to 145, a 99% reduction.

For comparison, rebuilding the reference catalogue with matched TRF parameters
moved the rate by about 1.4 points (Section 4 of
[the catalogue notes](../tools/HG38_TRF_CATALOGUE.md)). Filtering moves it by
roughly 31. Low-confidence calls, not catalogue mismatch, are the dominant
source of apparent novelty, and any headline figure should be quoted from the
filtered call set.

### 8. Mendelian consistency in the GIAB trio

`src/python/popstruct/trio_validation.py`

A repeat called in the child should normally appear in a parent. Using the
HG002/HG003/HG004 call set, 2,444 loci are carried by the child and 759 (31.1%)
are absent from both parents.

That figure alone is not a false-positive rate. **Known loci violate at 29.7%**
(95% CI 27.7-31.8), and those are loci the reference already annotates. Their
rate is the floor set by parental dropout at 30x coverage and by SV-calling
inconsistency, and it applies to every class equally. The interpretable quantity
is the excess above it.

| class | n | violations | rate | 95% CI | excess over known |
|---|---:|---:|---:|---|---|
| known (control) | 1,877 | 558 | 29.7% | [27.7, 31.8] | reference |
| novel_motif | 541 | 197 | 36.4% | [32.4, 40.5] | **+6.7 pts** (OR 1.35, p = 0.0038) |
| novel_locus | 26 | 4 | 15.4% | [5.4, 32.5] | -14.3 pts (p = 0.13, n.s.) |

Novel-motif calls therefore carry roughly a 7 percentage point excess error rate
over known calls. `novel_locus` shows no excess, but with 26 loci after
filtering that row is not informative. A violation may equally be a false
negative in a parent as a false positive in the child; the known-locus control
is what makes the comparison meaningful, since dropout affects all classes
alike.


## Limitations

- **Results 1 to 4 use a subset.** 500 records from chr1 only, yielding 221 loci.
  Result 5 uses the full 106,844-record callset.
- **Input predates the fix for issue #48.** The committed TSVs still carry its
  signature (`min(insert_size - rep_end) = 68` across 1,125 rows), so
  `rep_start`, `rep_end` and `insertion_purity` are shifted. Carrier counts are
  taken from the VCF `SUPP_VEC` and are unaffected, which is why results 1 to 4
  stand. Insertion-purity values above are indicative only.
- **Depth is now controlled; ONT chemistry is not.** Result 6 adjusts for
  sequencing depth using `DR + DV` and finds the ancestry effect unchanged. The
  R9.4.1/R10.4.1 chemistry assignment is still not available in the repository,
  so a systematic chemistry difference by ancestry remains untested.
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
