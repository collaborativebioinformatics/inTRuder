# AnnotSV TSV Annotation Workflow

This workflow converts a novelty-filtered tandem-repeat TSV file to BED format, removes duplicate records based on `SVID`, annotates the insertions with AnnotSV, and processes the AnnotSV output using htsSidra.

## Input

The expected input is:

```text
HG002_03_04_multisample.trf.noveltyFilter.tsv
```

The TSV file must contain these columns:

- `chrom`
- `ins_coord`
- `SVID`

## Required files

Keep the following files in the pipeline directory:

```text
annotsv_from_tsv.nf
run_pipeline_slurm.sh
```

Create the log directory before submitting the job:

```bash
mkdir -p logs
```

## Submit the workflow

```bash
sbatch \
  -J annotsv \
  -p acpu \
  --qos=cpu-normal \
  --time=23:00:00 \
  --mem=2G \
  --output=logs/%x_%j.out \
  --error=logs/%x_%j.err \
  --wrap="bash run_pipeline_slurm.sh annotsv_from_tsv.nf \
  --input_tsv /pl/active/dashnowlab/work/ealiyev/SVTR_Analysis/tr_from_sv/HG002_03_04_multisample.trf.noveltyFilter.tsv \
  --work_dir /pl/active/dashnowlab/work/ealiyev/SVTR_Analysis/tr_from_sv/"
```

The `--mem=2G` setting applies to the SLURM job running the Nextflow controller. Resources for the AnnotSV process are defined separately inside `annotsv_from_tsv.nf`.

## Workflow steps

1. Read the novelty-filtered TSV file.
2. Derive the project name automatically by removing the `.tsv` extension.
3. Remove duplicate records based on `SVID`, retaining the first occurrence.
4. Convert each unique insertion to a one-base BED interval:

   ```text
   START = ins_coord
   END   = ins_coord + 1
   SVTYPE = INS
   ```

5. Retain the original `SVID` as the fifth BED column.
6. Annotate the BED file against GRCh38 using AnnotSV v3.5.8.
7. Process the AnnotSV result using the htsSidra Java tool.

## Expected outputs

The following files are copied to the directory specified by `--work_dir`:

```text
HG002_03_04_multisample.trf.noveltyFilter.bed
HG002_03_04_multisample.trf.noveltyFilter.annotated.tsv
HG002_03_04_multisample.trf.noveltyFilter.annotated.tsv.processed.tsv
```

The retained BED file has the following structure:

```text
#CHROM  START  END  SVTYPE  SVID
chr1    10862  10863  INS   Sniffles2.INS.3M0
```

## Monitor the job

Check the SLURM queue:

```bash
squeue -u "$USER"
```

Follow the job log:

```bash
tail -f logs/annotsv_<job_id>.out
```

If Nextflow reports that the input file does not exist, verify the complete path and filename:

```bash
stat /pl/active/dashnowlab/work/ealiyev/SVTR_Analysis/tr_from_sv/HG002_03_04_multisample.trf.noveltyFilter.tsv
```

## Resume an interrupted run

If `run_pipeline_slurm.sh` supports forwarding additional Nextflow arguments, add `-resume` after the pipeline filename. Otherwise, run the same submission command after configuring the wrapper to pass `-resume` to Nextflow.

## Reference

The htsSidra Java utility is described in:

Aliyev E, Syed N, Visconti A, et al. *The biomedical landscape of genomic structural variation in the Qatari population*. Nature Communications. 2026;17:1019. <https://doi.org/10.1038/s41467-025-67763-9>
