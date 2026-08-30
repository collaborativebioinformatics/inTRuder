# Withdrawn figures

These three figures were computed on the **unfiltered** call set (43,379 loci)
and do not survive the quality filters the pipeline actually applies: repeats
covering at least 80% of the insertion, purity at least 0.7, insertions of at
most 10,000 bp supported by at least 10 reads. Applying those filters leaves
17,270 loci.

They are kept as a record of the withdrawal, not as results. **Do not cite the
numbers on them.**

| Figure | Unfiltered (43,379 loci) | Filtered (17,270 loci) |
|---|---|---|
| `withdrawn_sharing_spectrum` | novel loci singleton-enriched, OR 1.60, p = 4.6e-109 | **OR 0.90, p = 0.047, direction reversed** |
| `withdrawn_private_loci` | private-to-one-superpopulation gradient, chi2 = 1,048, p = 2.8e-228 | **chi2 = 6.9, p = 0.032, non-monotone** |
| `withdrawn_fixed_frequency` | novelty declines with carrier frequency, rho = -0.090, p = 2.6e-79 | **rho = +0.014, p = 0.058, flat** |

Under the filters, novel-motif loci are singletons 14.5% of the time against
16.3% for known loci, so slightly *less* singleton-enriched rather than more,
and the novelty rate sits near 20% in every carrier-frequency bin from
singletons (18.8%) to fixed (22.5%).

The apparent association between novelty and rarity was a property of call
quality rather than of biology: low-confidence calls concentrate among
singletons, so removing them removes the signal. Once low-confidence calls are
excluded, novelty is independent of carrier frequency.

The surviving figures in the parent directory count insertions from the merged
VCF rather than tandem-repeat verdicts, so the tandem-repeat filters do not
apply to them and they are unaffected.

Regenerate with `python src/python/popstruct/make_figures.py`; see
[the analysis notes](../../../docs/analysis/POPULATION_STRUCTURE.md), result 3.
