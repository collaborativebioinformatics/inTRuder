# Structural-variant annotation workflow

This directory documents the reproducible novelTRs workflow. AnnotSV remains
the canonical annotation stage; preprocessing and PhenoGenius are separate
optional stages.

## Execution order

1. **Preprocess (optional):** `pipelines/sv_preprocess` converts
   `SVTYPE=INS` to `SVTYPE=DUP`, changes `<INS>` to `<DUP>`, and preserves
   `ORIG_SVTYPE=INS`.
2. **Annotate:** AnnotSV consumes the original or preprocessed VCF and writes
   an AnnotSV TSV.
3. **Enrich (optional):** PhenoGenius consumes that TSV and appends phenotype
   scores; it does not rerun AnnotSV.
4. **Summarize (optional):** `take_info_annotsv.R` extracts selected columns
   and generates downstream tables/figures.

Use comma-separated HPO identifiers, such as
`HP:0001156,HP:0001363,HP:0011304`. Use `--tx ENSEMBL` or `--tx RefSeq`.
Nextflow parameters always use the double-dash form (`--input`, `--tx`,
`--hpo`), including inside DNAnexus `nextflow_pipeline_params`.

## Local execution

```bash
conda activate annotsv
cd /path/to/novelTRs
```

Preprocess:

```bash
nextflow run pipelines/sv_preprocess/main.nf -profile local \
  --input SV_annotsv_JVM/examples/first_500_INS.vcf \
  --outdir SV_annotsv_JVM/examples/preprocessed
```

Annotate with ENSEMBL and HPO terms:

```bash
nextflow run pipelines/annotsv/main.nf -profile local \
  --input SV_annotsv_JVM/examples/preprocessed/first_500_INS.preprocessed.vcf \
  --tx ENSEMBL \
  --hpo HP:0001156,HP:0001363,HP:0011304 \
  --outdir SV_annotsv_JVM/examples/annotsv
```

Enrich an AnnotSV TSV:

```bash
nextflow run pipelines/phenogenius_enrich/main.nf -profile local \
  --input_tsv SV_annotsv_JVM/examples/annotsv/first_500_INS.annotated.tsv \
  --phenogenius_bundle /tmp/PhenoGeniusCli-v1.1.3.tar.gz \
  --hpo HP:0001156,HP:0001363,HP:0011304 \
  --outdir SV_annotsv_JVM/examples/phenogenius
```

The final file is `first_500_INS.phenogenius.tsv`. It retains AnnotSV columns
and appends `PhenoGenius_gene_scores`, `PhenoGenius_gene_specificity`,
`PhenoGenius_best_gene`, `PhenoGenius_best_score`, and
`PhenoGenius_best_specificity`.

## DNAnexus CLI execution

These are the tested applets in project `Group2_2026`
(`project-JB6zg5Q0pzX96qVJjz7gKg58`):

| Stage | Applet ID |
|---|---|
| Preprocessing | `applet-JB87kYQ0pzX1v4qZZyxyZ92q` |
| AnnotSV | `applet-JB8562j0pzX7b1QvbbB9zyg5` |
| PhenoGenius | `applet-JB883gj0pzX5f2FXzpxZKKPp` |

Authenticate:

```bash
dx login
dx select project-JB6zg5Q0pzX96qVJjz7gKg58
```

Preprocess:

```bash
dx run applet-JB87kYQ0pzX1v4qZZyxyZ92q \
  -inextflow_pipeline_params="--input '/Test_Inputs/first_500_INS.vcf'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/Preprocess_Test' \
  --name preprocess_first_500 --yes
```

Use the resulting `*.preprocessed.vcf` path reported by
`dx ls '/Results/Preprocess_Test' --long` as the AnnotSV input. AnnotSV can
also be run directly on the existing test VCF:

```bash
dx run applet-JB8562j0pzX7b1QvbbB9zyg5 \
  -inextflow_run_opts='-profile dnanexus' \
  -inextflow_pipeline_params="--input '/Test_Inputs/first_500_INS.vcf' --tx ENSEMBL --hpo 'HP:0001156,HP:0001363,HP:0011304'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/AnnotSV_Test' \
  --name annotsv_first_500 --yes
```

To use preprocessing, replace the `--input` path with the exact published VCF
path. The AnnotSV output is an `*.annotated.tsv` file.

Run PhenoGenius:

```bash
dx run applet-JB883gj0pzX5f2FXzpxZKKPp \
  -inextflow_run_opts='-profile dnanexus' \
  -inextflow_pipeline_params="--input_tsv '/Results/AnnotSV_Test/results/annotsv/first_500_INS.annotated.tsv' --phenogenius_bundle '/resources/PhenoGenius/PhenoGeniusCli-v1.1.3-dx.tar.gz' --hpo 'HP:0001156,HP:0001363,HP:0011304'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/PhenoGenius_Test' \
  --name phenogenius_first_500 --yes
```

Monitor jobs:

```bash
dx watch JOB_ID --tree
dx describe JOB_ID --json | jq '{state,failureReason,failureMessage,output}'
```

## DNAnexus Web UI execution

1. Open the `Group2_2026` project and open **Tools/Applets**.
2. Open `sv-preprocess`, `annotsv-pipeline`, or `phenogenius-enrich` and click
   **Run**.
3. Set **nextflow_run_opts** to `-profile dnanexus` for AnnotSV and
   PhenoGenius; it is optional for preprocessing.
4. Paste the complete corresponding `nextflow_pipeline_params` string from
   the CLI examples above. Keep single quotes around DNAnexus paths and HPO
   values, and use `--` before every Nextflow parameter.
5. Choose an output folder under `/Results`, provide a job name, and click
   **Run**. Use project paths such as `/Test_Inputs/...` and
   `/Results/...`, not paths from your laptop.
6. Open the job’s **Logs** tab, then verify the published VCF or TSV in the
   output folder.

For PhenoGenius, the runtime bundle must be
`/resources/PhenoGenius/PhenoGeniusCli-v1.1.3-dx.tar.gz`.

## Included examples

Downloaded from the `Group2_2026` test project:

- `examples/first_500_INS.vcf` — source VCF from
  `/Test_Inputs/first_500_INS.vcf`.
- `examples/first_500_INS.phenogenius.tsv` — successful output from
  `/Results/PhenoGenius_Test4/results/first_500_INS.phenogenius.tsv`.
- `examples/demo_output_annot_sv.tsv` — compact AnnotSV demonstration output.
- `examples/column_description.xlsx` — selected AnnotSV column descriptions.
- `src/R/take_info_annotsv.R` — canonical downstream extraction/plotting script.

The example TSV is an output artifact for inspection; rerun the workflow for new
inputs. For cohorts, keep inputs and intermediate outputs in DNAnexus and pass
project paths rather than downloading large files locally.
