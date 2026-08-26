# novelTRs — Tandem Repeat SV Annotation Pipeline

Nextflow DSL2 workflow for functional and clinical annotation of novel/non-reference Tandem Repeat (TR) loci recovered from long-read SV insertion calls using **AnnotSV v3.5**.

---

## 🎯 Purpose

Annotates reference-absent TR insertion variants (HPRC & GIAB cohorts) to determine:
- **Gene context**: Exonic, intronic, promoter, 5'/3' UTR, or intergenic TR expansions
- **Coding impact**: CDS overlap percentage, in-frame vs frameshifting repeat expansions
- **Clinical relevance**: ACMG pathogenicity classes (1–5), ClinGen HI/TS scores, OMIM disease associations, and gnomAD population frequencies

---

## 💻 Local Execution

### Prerequisites
- Nextflow (`>=23.04.0`)
- AnnotSV v3.5+ installed (run `bash pipelines/annotsv/install_annotsv.sh` for one-step local setup)

### 1. Annotate TR Insertion VCFs (Single / Multi-sample)
```bash
nextflow run pipelines/annotsv/main.nf \
  --input "data/sv_output/survivor_multi_sample_vcf/first_500_INS.vcf" \
  --outdir "results/tr_annotations" \
  --genome_build "GRCh38"
```

### 2. Batch Annotate Cohort Sniffles SV Directories
```bash
nextflow run pipelines/annotsv/main.nf \
  --input "data/sv_output/sniffles/filtered/" \
  --outdir "results/tr_annotations" \
  --genome_build "GRCh38"
```

---

## ☁️ DNAnexus Cloud Execution

Pre-deployed on DNAnexus project **`Group2_2026`** (`project-JB6zg5Q0pzX96qVJjz7gKg58`):
- **Databases**: `Group2_2026:/resources/AnnotSV/`
- **Pipeline**: `Group2_2026:/Pipelines/annotsv-nf/`

### Run on HPRC Cohort on Cloud Compute:
```bash
dx run nextflow \
  -inextflow_pipeline="Group2_2026:/Pipelines/annotsv-nf" \
  -inextflow_run_opts="-profile conda --genome_build GRCh38 --input 'dx://Group2_2026:/survivor/HPRC_SV.survivor.vcf' --dx_annotations_path 'Group2_2026:/resources/AnnotSV'" \
  --destination="Group2_2026:/Results/AnnotSV" \
  --instance-type="mem2_ssd1_v2_x4" \
  --name="annotsv_hprc_tr_annotation" \
  --yes
```

---

## 📊 Outputs

1. **Annotated TR Table** (`${outdir}/<sample>/annotsv/<sample>.annotated.tsv`):
   - `Gene_name`, `Location` (exon/intron/promoter), `Overlapped_CDS_percent`, `Frameshift`
   - `ACMG_class` (1=Benign to 5=Pathogenic), `OMIM_phenotype`, `GenCC_disease`
   - Preserves all multi-sample cohort genotypes across all 67 HPRC genomes
2. **Summary Statistics** (`${outdir}/summary/annotsv_summary_report.txt` & `.tsv`):
   - Total TR variants annotated, repeat insertion counts, affected genes, and ACMG class distribution

---

## ⚙️ Options

| Parameter | Description | Default |
|---|---|---|
| `--input` | Path, glob, or directory of TR VCF/BED files | *Required* |
| `--outdir` | Output destination directory | `results` |
| `--genome_build` | Reference genome (`GRCh38` or `GRCh37`) | `GRCh38` |
| `--candidate_genes` | Optional gene list file to filter relevant TR loci | `none` |
| `--dx_annotations_path` | DNAnexus project path to AnnotSV databases | `none` (local) |

---

## 📖 Additional Documentation

- **[`ANNOTSV_INSTALLATION_GUIDE.md`](ANNOTSV_INSTALLATION_GUIDE.md)** — Detailed local installation guide & troubleshooting
