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

The approximately 34 GB reference databases are pre-deployed in the DNAnexus
project **`Group2_2026`** at `Group2_2026:/resources/AnnotSV/`. Each AnnotSV
child job downloads both database directories into its scratch disk before
starting the pinned AnnotSV 3.5.10 container.

### 1. Build the Nextflow applet

```bash
dx build --nextflow pipelines/annotsv \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Apps/annotsv-pipeline' \
  --archive \
  --yes
```

Archiving preserves the previous applet version while making the new build the
active `/Apps/annotsv-pipeline` object.

### 2. Run TR annotation

```bash
dx run 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Apps/annotsv-pipeline' \
  -inextflow_run_opts='-profile dnanexus' \
  -inextflow_pipeline_params="--input '/Test_Inputs/first_500_INS.vcf'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/AnnotSV_Test/' \
  --name 'annotsv_500_test' \
  --yes
```

For the full cohort, replace the input path with
`/survivor/HPRC_SV.survivor.vcf` and choose the desired output destination.
The applet head job supervises the workflow; Nextaur selects separate child
instances from each process's CPU and memory requirements.

### 3. Run from the DNAnexus Web UI

1. Sign in to the DNAnexus Platform and open the **`Group2_2026`** project.
2. In the project data browser, open **`/Apps`**, select
   **`annotsv-pipeline`**, and choose **Run**.
3. Complete the applet form as follows:

   | Web UI field | Value |
   |---|---|
   | **Nextflow Run Options** | `-profile dnanexus` |
   | **Nextflow Pipeline Parameters** | `--input '/Test_Inputs/first_500_INS.vcf'` |
   | **Nextflow Top-level Options** | Leave empty |
   | **Docker Credentials** | Leave empty; the pipeline image is public |
   | **Debug Mode** | Off, unless detailed troubleshooting logs are needed |
   | **Preserve Cache** | Off for a normal run |

   `Nextflow Pipeline Parameters` is a free-text field, so enter the DNAnexus
   project path manually. For a full-cohort run, use:

   ```text
   --input '/survivor/HPRC_SV.survivor.vcf'
   ```

   Additional pipeline options can be included in the same field, for example:

   ```text
   --input '/Test_Inputs/first_500_INS.vcf' --genome_build GRCh38 --outdir results
   ```

4. In the execution/output settings, use **`Group2_2026`** as the output
   project and **`/Results/AnnotSV_Test/`** as the output folder. Give the run a
   descriptive name such as **`annotsv_500_test`**.
5. Select **Run** or **Start Analysis** to launch the applet. The initial
   Nextflow head job will submit separate AnnotSV and summary child jobs.

### 4. Monitor the run

In the Web UI, open the project **Monitor** view and select the named head job
to see its status and child jobs. From the command line, run:

```bash
dx watch <job-id>
```

Successful outputs appear below the selected destination in
`results/annotsv/` and `results/summary/`.

### 5. Download results

```bash
dx download -r /Results/AnnotSV_Test/results/
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
| `--annotations_dir` | Local directory or DNAnexus URI containing AnnotSV databases | local AnnotSV installation |

---

## 📖 Additional Documentation

- **[`ANNOTSV_INSTALLATION_GUIDE.md`](ANNOTSV_INSTALLATION_GUIDE.md)** — Detailed local installation guide & troubleshooting
