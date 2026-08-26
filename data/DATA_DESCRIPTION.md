# Data Description

## HPRC genomes

The Human Pangenome Reference Consortium (HPRC) cohort that used for this project contains **67 Oxford Nanopore Technologies (ONT) genomes**. Samples and sequencing runs were identified using the [HPRC Data Explorer](https://data.humanpangenome.org/rawsequencing-data).

ONT runs expected to provide approximately **30–35× sequencing depth from a single flow cell** were selected. The cohort was balanced across two ONT pore chemistries:

| ONT chemistry | Number of genomes |
|---|---:|
| R9.4.1 | 33 |
| R10.4.1 | 34 |
| **Total** | **67** |

The original sequencing data were downloaded from the public HPRC AWS S3 bucket:

```text
s3://human-pangenomics/
```

The processed alignment files were subsequently uploaded to the **1000 Genomes Project AWS S3 bucket**.

### HPRC CRAM file list

The AWS locations of the processed HPRC CRAM files are provided in [`aws_hprc_cram.list`](aws_hprc_cram.list).

### GIAB CRAM file list

The AWS locations of the processed HPRC CRAM files are provided in [`aws_giab_cram.list`](aws_giab_cram.list).

These genomes were used in the following study:

> Aliyev E, Avvaru A, De Coster W, et al.  
> [A comprehensive assessment of tandem repeat genotyping methods for Nanopore long-read genomes](https://link.springer.com/article/10.1186/s13059-026-04210-y).  
> *Genome Biology*. 2026.  
> DOI: [10.1186/s13059-026-04210-y](https://doi.org/10.1186/s13059-026-04210-y)

### Read extraction and alignment

ONT reads were extracted from the unaligned BAM files using [`samtools fastq`](https://www.htslib.org/). The reads were aligned to the **GRCh38 human reference genome** using [`minimap2`](https://github.com/lh3/minimap2), sorted, and written in CRAM format using `samtools sort`.

```bash
samtools fastq -T MM,ML "${unaligned_bam}" \
  | minimap2 -a -y \
      -t "${threads}" \
      -R "${readgroup}" \
      "${ref}" - \
  | samtools sort \
      -@ "${threads}" \
      -O CRAM \
      --reference "${ref}" \
      -T "${sample}.tmp" \
      -o "${sample}.cram"
```

The `MM` and `ML` auxiliary tags containing base-modification information were retained during read extraction. The `minimap2 -y` option was used to copy these tags to the resulting alignments.

Additional details about the alignment workflow are available in the [`align_HPRC` Nextflow pipeline](https://github.com/dashnowlab/TR-Benchmarking/blob/main/align_HPRC/main_align.nf).

### Coverage estimation

Sequencing coverage was estimated for each aligned CRAM file using [`mosdepth`](https://github.com/brentp/mosdepth) version **0.3.10**.

### Data provenance summary

| Dataset property | Description |
|---|---|
| Consortium | Human Pangenome Reference Consortium |
| Number of genomes | 67 |
| Sequencing platform | Oxford Nanopore Technologies |
| Pore chemistries | R9.4.1 and R10.4.1 |
| Expected sequencing depth | Approximately 30–35× |
| Original data source | `s3://human-pangenomics/` |
| Reference genome | GRCh38 |
| Read extraction | `samtools fastq` |
| Alignment | `minimap2` |
| Output format | CRAM |
| Coverage estimation | `mosdepth` v0.3.10 |
| Processed-data destination | 1000 Genomes Project AWS S3 bucket |

### Structural variant calling

Structural variants were called from each aligned CRAM/BAM file using [`Sniffles2`](https://github.com/fritzsedlazeck/Sniffles). A tandem-repeat BED file was supplied to improve variant calling in repetitive regions.

```bash
sniffles \
  -i "${bam}" \
  -v "${sample}.raw.sniffles.vcf" \
  --tandem-repeats "${tr_bed}" \
  --reference "${ref}" \
  --threads "${task.cpus}"
```

The resulting unfiltered structural variant calls were written to `${sample}.raw.sniffles.vcf`.

### Structural variant filtering

Raw Sniffles calls were filtered using [`bcftools`](https://samtools.github.io/bcftools/) to retain structural variants of at least **50 bp**, including records with symbolic or unavailable `SVLEN` values. Translocations, breakends, mitochondrial variants, decoy sequences, unplaced contigs, and alternative contigs were excluded. The generic sample name was also replaced with the corresponding sample ID.

```bash
bcftools view \
  -i '(SVLEN>=50 | SVLEN<=-50 | SVLEN=0 | SVLEN=1 | SVLEN=".")' \
  "${raw_vcf}" \
| grep -v -E 'SVTYPE=TRA|SVTYPE=BND|hs37d5|MT|chrUn|_KI2|_GL|_KB|_JH|chrM' \
| sed "s/SAMPLE/${sample}/" \
> "${sample}.merged.sniffles.vcf"
```

The filtered calls were written to `${sample}.merged.sniffles.vcf`.

### Multi-sample VCF generation - TO-DO!!!

The filtered per-sample VCF files were merged into a multi-sample VCF using [`SURVIVOR`](https://github.com/fritzsedlazeck/SURVIVOR). Variants located within 500 bp were merged when they had matching SV types.

```bash
SURVIVOR merge sample.list 500 1 1 0 0 0 "${proj}.survivor.vcf"
```
 
### Data availability

The structural variant files were uploaded to the **DNAnexus `Group2_2026` project**. A subset of the per-sample Sniffles VCF files and the filtered multi-sample VCF are also available in the GitHub [`data/`](data/) directory.

## UCSC hg38 Simple Repeats track
The Simple Repeats track is UCSC's genome-wide tandem repeat annotation for the hg38 assembly, generated by running Tandem Repeats Finder (TRF) across the reference genome sequence. Each row represents one tandem repeat locus identified in the reference genome itself — this is a reference annotation, not a population or per-sample variant call.

## Where it was found
Interactively, the same data is browsable via the UCSC Table Browser:

-   URL: `https://genome.ucsc.edu/cgi-bin/hgTables`
-   Settings: assembly = **hg38**, group = **Repeats**, track = **Simple
    Repeats**, table = **simpleRepeat**

For reproducibility, the raw table was downloaded directly from [UCSC's
hgdownload
server](https://hgdownload.soe.ucsc.edu/goldenPath/hg38/database/)(the
same data the Table Browser reads from) rather than exported through the
web form, so the download is a fixed URL/ command rather than a manual
UI export

### How to download it
```bash
# Data file
curl -O https://hgdownload.soe.ucsc.edu/goldenPath/hg38/database/simpleRepeat.txt.gz
gunzip simpleRepeat.txt.gz

# Column schema (for reference — describes each column below)
curl -O https://hgdownload.soe.ucsc.edu/goldenPath/hg38/database/simpleRepeat.sql
```

### File format / columns

Tab-delimited, **no header row** in the raw file. Column order per the
UCSC `simpleRepeat` table schema:

| \# | Column | Description |
|-------------------|---------------------|--------------------------------|
| 1 | `bin` | UCSC internal indexing field (not biologically meaningful) |
| 2 | `chrom` | Chromosome |
| 3 | `chromStart` | Repeat start position in chromosome (**0-based**) |
| 4 | `chromEnd` | Repeat end position in chromosome (**0-based, half-open** — standard BED convention) |
| 5 | `name` | Repeat identifier |
| 6 | `period` | Length of the repeat motif (bp) |
| 7 | `copyNum` | Mean number of copies of the motif |
| 8 | `consensusSize` | Size of the consensus motif |
| 9 | `perMatch` | Percent match to consensus (TRF quality metric) |
| 10 | `perIndel` | Percent of bases involved in indels relative to consensus |
| 11 | `score` | TRF alignment score |
| 12–15 | `A`, `C`, `G`, `T` | Base composition percentages |
| 16 | `entropy` | Sequence entropy |
| 17 | `sequence` | Consensus repeat motif sequence |

### Coordinate system note
`chromStart`/`chromEnd` are already in **0-based, half-open** BED
convention — the same convention used by TRExplorer BED exports. No
conversion is needed when comparing directly against TRExplorer.

### Provenance 
-   **Source:** [UCSC Genome Browser, hg38 assembly, `simpleRepeat`
    table (Tandem Repeats Finder
    output)](https://genome.ucsc.edu/cgi-bin/hgTables?db=hg38&hgta_group=rep&hgta_track=simpleRepeat&hgta_table=simpleRepeat&hgta_doSchema=describe+table+schema)
-   **URL:**
    `https://hgdownload.soe.ucsc.edu/goldenPath/hg38/database/simpleRepeat.txt.gz`
-   **Retrieved:** August 26, 2026

### Data Availability
The file was uploaded to the **DNAnexus `Group2_2026` project** in the `/resource` folder.
