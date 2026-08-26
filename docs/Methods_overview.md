# Methods Outline — Thursday Presentation

Outline of the novelTR methods

## 1. Pipeline Overview

Reference-based tandem repeat (TR) genotypers require a predefined catalog of loci, typically derived from a reference genome — making them blind to novel, individual- or population-specific TR loci. This project builds a pipeline to detect those novel TRs directly from structural variant calls.

**Top-level flow:**

```
Data Acquisition → Preprocessing → Novel TR Detection → Downstream Annotation + Validation
```

**Preprocessing steps:**

These are assumed to be completed prior to the start of this workflow.

- Alignment (minimap2)
- SNV calling (Clair3)
- Haplotagging (Whatshap)
- SV calling (Sniffles2)
- SV merging (Sniffles2) - optional

Final product:
SV VCF (this VCF feeds into Novel TR Detection)



## 2. Novel TR Detection (core method)

This is the primary contribution of the project — detecting TRs that fall within structural variant insertions and determining which are novel relative to the reference genome.

**Steps:**

1. **Find TRs within SV insertions** — run tandem-repeat finding (`pytrf`) on each inserted ALT allele from the SV VCF
2. **Filter / deal with overlaps** — resolve overlapping repeat calls
3. **Figure out which are novel** — flag loci or motifs not present in the reference genome (HG38 TRF annotation - UCSC SimpleRepeats track)

**Implementation:** `src/python/sv_trfcaller.py` implements step 1 — it takes an SV VCF as input, runs `pytrf.ATRFinder` on each sample's inserted sequence, uses `parasail` alignment to score repeat purity, and outputs a TSV of repeat calls per sample (chrom, position, motif, purity, repeat length, etc.).

## 3. Datasets & Validation

**Datasets:**

- CHM13-T2T
- HG38
- Human Pangenome Reference Consortium (HPRC)
- CHM13 cell line reads
- Family / trio-based data

**Validation approaches:** checkpoint after novel TR detection, before results are used further.

- Use CHM13 reads as a sample, with the CHM13-T2T reference genome TRF annotation as "truth"
- Trio validation — if we find a novel TR in a kid, do we also find it in one of the parents? Samples: HG001-7

## 4. Annotation

Characterize TR insertions in their genomic context using annotSV.

**Features to annotate:**

- Genes
- Coding and non-coding regions
- Splice boundaries
- Regulatory elements
- TADs



## 5. Analyze Novel TR Variation in HPRC

Apply the pipeline across the Human Pangenome Reference Consortium (HPRC) cohort to move from single-sample discovery to describing how novel TR loci behave across individuals and populations.

**Steps:**

1. **Run pipeline per-sample** — apply Sections 2–4 to each HPRC sample's SV VCF to get per-sample novel TR + annotation calls
2. **Merge calls across samples** — reconcile the same novel locus detected in multiple individuals (match by position + motif, as in Section 4)
3. **Compute population-level stats** — presence/absence frequency, allele-length distribution, breakdown by population/ancestry
4. **Visualize** — per-locus frequency and length distributions across samples/populations

---

*Diagram: see the [interactive Miro board](https://miro.com/app/board/uXjVHuDLcpE=/?share_link_id=710821883698) for the full workflow visualization.*