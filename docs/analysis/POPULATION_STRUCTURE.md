# Non-reference insertion burden and reference bias across the HPRC cohort

Cohort-level analysis of the inTRuder call set: how non-reference insertion
burden varies with genetic ancestry, what the pipeline's quality filters do to
the reported novelty rate, and a first error estimate from a trio.

## Input

| Path | Contents |
|---|---|
| `hprc_multisample.INS.vcf` | 106,844 insertions, 67 genomes, Sniffles2 2.8.0 joint call. Not in the repo, see the DNAnexus `Group2_2026` project |
| `data/sv_output/novelty_filtered/hprc_multisample.trf.noveltyFiltered.tsv` | filtered TR calls with novelty verdicts (A. Avvaru). Not in the repo, 55 MB |
| `data/sv_output/novelty_filtered/HG002_03_04_multisample.trf.novelyFilter.tsv` | GIAB trio call set |
| `data/metadata/sample_population.tsv` | sample to superpopulation, 66 of 67 labelled |
| `results/locus_carriers_filtered.tsv` | 17,270 filtered loci with carrier counts |
| `results/per_sample_insertion_burden.tsv` | per genome, by rarity stratum, with depth |

Carrier status is taken from **genotype calls**, not `SUPP_VEC`. The two
disagree on 17.4% of records in this joint-called VCF, since `SUPP_VEC` marks
samples with supporting evidence while `GT` is the post-filter call, and
`SUPP_VEC` reports 34,984 singletons against the genotypes' 39,304.

Superpopulation labels come from the **3,202-sample 1000 Genomes pedigree**,
which labels 66 of the 67 genomes. The commonly cited 2,504-sample phase 3 panel
labels only 33, because HPRC draws from the expanded set. `NA21309` is absent
from every 1000 Genomes source checked and from HPRC's own metadata, and is left
`UNKNOWN` rather than inferred.

## Results

### 1. African genomes carry 13.6% more non-reference insertions

`results/figures/fig1_burden_by_ancestry.pdf`

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


### 2. The difference is concentrated in rare insertions, and is not a coverage artefact

`results/figures/fig2_rarity_gradient.pdf`

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


### 3. What quality filtering does, and three results it removes

The pipeline's Methods specify retaining repeats covering at least 80% of the
insertion at purity 0.7 or above, in insertions of at most 10,000 bp supported
by at least 10 reads. Applying those filters to the full call set reduces
43,379 loci to 17,270 and the fraction called novel from **51.0% to 20.2%**,
with `novel_locus` falling from 13,386 loci to 145, a 99% reduction. For
comparison, rebuilding the hg38 catalogue with matched TRF parameters moved the
rate by about 1.4 points. **Low-confidence calls, not reference-catalogue
mismatch, dominate apparent novelty**, and 20.2% is the figure consistent with
the stated method.

An independently produced filtered call set (A. Avvaru) contains exactly the
same 17,270 loci, an exact subset of ours with none absent from our run, which
is a useful reproducibility check on the detection step.

**Three earlier results did not survive the filters and have been withdrawn.**
They were computed on the unfiltered call set:

| | unfiltered (43,379) | filtered (17,270) |
|---|---|---|
| singleton enrichment, novel vs known | OR 1.60, p = 4.6e-109 | **OR 0.90, p = 0.047, direction reversed** |
| private to one superpopulation | chi2 = 1,048, p = 2.8e-228 | **chi2 = 6.9, p = 0.032, non-monotone** |
| novelty vs carrier frequency | rho = -0.090, p = 2.6e-79 | **rho = +0.014, p = 0.058, flat** |

Under the filters, novel-motif loci are singletons 14.5% of the time against
16.3% for known, so slightly *less* singleton-enriched rather than more, and the
novelty rate is close to 20% in every frequency bin from singletons (18.8%) to
fixed (22.5%).

The interpretation is that the apparent association between novelty and rarity
was a property of call quality rather than of biology: low-confidence calls
concentrate among singletons, so removing them removes the signal. **Once
low-confidence calls are excluded, novelty is independent of carrier
frequency.** That is a weaker but honest result, and it argues against reading
the raw novel-locus counts as recent population-specific variation.

Results 1 and 2 are unaffected, as they count insertions from the merged VCF
rather than tandem-repeat verdicts, so the tandem-repeat filters do not apply
to them.

### 4. Mendelian consistency in the GIAB trio

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

- **Results 1 and 2 measure total insertion burden, not novel-TR burden.** They
  count insertions from the merged VCF, so they are unaffected by the
  tandem-repeat filters but also do not speak to novel tandem repeats
  specifically.
- **ONT pore chemistry is uncontrolled.** Sequencing depth is adjusted for in
  result 2, but the R9.4.1/R10.4.1 assignment is not available in the
  repository, so a systematic chemistry difference by ancestry remains untested.
- **Mendelian violations conflate error types.** A violation may be a false
  positive in the child or a false negative in a parent. The known-locus control
  is what carries the information, not the raw rate.
- **The trio comparison rests on 145 `novel_locus` sites genome-wide and 26 in
  the trio** after filtering, so that row is not informative.
- **No recall estimate exists.** The two CHM13 controls present in the cohort
  were never screened against the corresponding telomere-to-telomere annotation,
  which remains the most valuable outstanding work.
- **Three results were withdrawn** after they failed to survive the pipeline's
  own quality filters; see result 3. Any figure or number derived from the
  unfiltered call set should be treated as superseded.

## Reproducing

```bash
python src/python/popstruct/make_figures.py       # figures 1 and 2
python src/python/popstruct/trio_validation.py    # trio error estimate
```

Requires `pandas`, `numpy`, `matplotlib` and `scipy`. Figures are written to
`results/figures/` as PNG and PDF; only the PDFs are tracked.
