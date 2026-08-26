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

The 30 GB reference databases are pre-deployed in the DNAnexus project **`Group2_2026`** at `Group2_2026:/resources/AnnotSV/`.

### 1. Run TR Annotation on DNAnexus Cloud Compute

```bash
# Ensure you are logged into DNAnexus (dx login) on your local machine
dx run app-swiss-army-knife \
  -icmd="echo '=== Starting Cloud AnnotSV TR Annotation ===' && \
         mkdir -p /home/dnanexus/annotsv_run/annotations /home/dnanexus/annotsv_run/inputs && \
         cd /home/dnanexus/annotsv_run && \
         echo '--- 1. Fetching AnnotSV software ---' && \
         git clone --depth 1 https://github.com/lgmgeo/AnnotSV.git /home/dnanexus/annotsv_app && \
         make -C /home/dnanexus/annotsv_app PREFIX=/home/dnanexus/annotsv_app install && \
         echo '--- 2. Downloading Annotations from project storage ---' && \
         dx download -r \"\${DX_PROJECT_CONTEXT_ID}:/resources/AnnotSV/Annotations_Human\" -o /home/dnanexus/annotsv_run/annotations/ && \
         dx download -r \"\${DX_PROJECT_CONTEXT_ID}:/resources/AnnotSV/Annotations_Exomiser\" -o /home/dnanexus/annotsv_run/annotations/ && \
         echo '--- 3. Downloading Input TR VCF ---' && \
         dx download \"\${DX_PROJECT_CONTEXT_ID}:/survivor/HPRC_SV.survivor.vcf\" -o /home/dnanexus/annotsv_run/inputs/ && \
         echo '--- 4. Running AnnotSV (GRCh38) ---' && \
         /home/dnanexus/annotsv_app/bin/AnnotSV \
           -SVinputFile /home/dnanexus/annotsv_run/inputs/HPRC_SV.survivor.vcf \
           -genomeBuild GRCh38 \
           -annotationsDir /home/dnanexus/annotsv_run/annotations \
           -outputDir /home/dnanexus/annotsv_run/ \
           -outputFile HPRC_SV.survivor.annotated.tsv && \
         echo '--- 5. Uploading Output to DNAnexus Storage ---' && \
         dx upload /home/dnanexus/annotsv_run/HPRC_SV.survivor.annotated.tsv --path /Results/AnnotSV/ && \
         echo '=== Annotation Completed Successfully ==='" \
  --destination="/Results/AnnotSV/" \
  --instance-type="mem2_ssd1_v2_x4" \
  --name="annotsv_hprc_tr_annotation" \
  --yes
```

*(For testing on the 500 INS subset, replace `/survivor/HPRC_SV.survivor.vcf` with `/Test_Inputs/first_500_INS.vcf`).*

### 2. Monitor Job Live
```bash
dx watch <job-id>
```

### 3. Download Results
```bash
dx download /Results/AnnotSV/HPRC_SV.survivor.annotated.tsv
```

---

## 📊 Outputs

1. **Annotated TR Table** (`*.annotated.tsv`):
   - `Gene_name`, `Location` (exon/intron/promoter), `Overlapped_CDS_percent`, `Frameshift`
   - `ACMG_class` (1=Benign to 5=Pathogenic), `OMIM_phenotype`, `GenCC_disease`
   - Preserves all multi-sample cohort genotypes across all 67 HPRC genomes
2. **Summary Statistics** (`annotsv_summary_report.txt` & `.tsv`):
   - Total TR variants annotated, repeat insertion counts, affected genes, and ACMG class distribution

---

## ⚙️ Key Parameters

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
