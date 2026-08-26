# AnnotSV Structural Variant Annotation Pipeline

Nextflow DSL2 pipeline for automated, parallel annotation of structural variants (SVs) and copy number variants (CNVs) using AnnotSV v3.5. Supports single files, batches, directories of VCFs/BEDs, and automated summary reporting.

---

## 📚 Complete Installation Guide & Bug Fixes

For complete instructions on installing AnnotSV from source or conda, downloading human annotation databases, and troubleshooting common issues, see:
👉 **[`ANNOTSV_INSTALLATION_GUIDE.md`](ANNOTSV_INSTALLATION_GUIDE.md)**

To install AnnotSV locally in one command:
```bash
bash pipelines/annotsv/install_annotsv.sh
```

---

## 💻 Local Execution

### 1. Prerequisites
- Nextflow (`>=23.04.0`)
- `bedtools`, `bcftools`, `tclsh` (available via conda/mamba)
- AnnotSV v3.5+ installed (e.g. at `/home/$USER/tools/AnnotSV`)

### 2. Run on a single file:
```bash
nextflow run pipelines/annotsv/main.nf \
  --input "data/sv_output/survivor_multi_sample_vcf/first_500_INS.vcf" \
  --outdir "results/annotsv" \
  --genome_build "GRCh38"
```

### 3. Run on an entire directory of VCFs:
```bash
nextflow run pipelines/annotsv/main.nf \
  --input "data/sv_output/sniffles/filtered/" \
  --outdir "results/annotsv" \
  --genome_build "GRCh38"
```

---

## ☁️ DNAnexus Cloud Execution

### Run on DNAnexus Cloud Compute:
```bash
dx run nextflow \
  -inextflow_pipeline="Group2_2026:/Pipelines/annotsv-nf" \
  -inextflow_run_opts="-profile conda --genome_build GRCh38 --input 'dx://Group2_2026:/survivor/' --dx_annotations_path 'Group2_2026:/resources/AnnotSV'" \
  --destination="Group2_2026:/Results/AnnotSV" \
  --instance-type="mem2_ssd1_v2_x4" \
  --name="annotsv_batch_annotation" \
  --yes
```

---

## 📊 Outputs Generated

1. **Annotated TSVs**:
   - `${outdir}/<sample_id>/annotsv/<sample_id>.annotated.tsv` (107 annotation columns: ACMG classification, ClinVar, gnomAD AFs, OMIM, HI/TS scores)
2. **Summary Statistics Table**:
   - `${outdir}/summary/annotsv_summary_report.txt` (Human-readable overview table)
   - `${outdir}/summary/annotsv_summary_report.tsv` (Machine-readable table)
3. **Logs**:
   - `${outdir}/<sample_id>/annotsv/logs/<sample_id>.annotsv.log`

---

## ⚙️ Key Pipeline Options

| Option | Description | Default |
|---|---|---|
| `--input` | Path, glob, or directory containing VCF/BED files | *Required* |
| `--outdir` | Output destination directory | `results` |
| `--genome_build` | `GRCh38` or `GRCh37` | `GRCh38` |
| `--candidate_genes` | Optional candidate genes file to filter on | `none` |
| `--annotsv_dir` | Local AnnotSV installation path | `/home/taimoor/tools/AnnotSV` |
| `--dx_annotations_path` | DNAnexus path to annotation databases | `none` (local) |
