# AnnotSV examples

This directory contains small example input/output artifacts and links to the
annotation instructions. The maintained workflow is documented in
[workflow.md](workflow.md); it covers local execution, DNAnexus CLI, and the
DNAnexus Web UI.

The canonical R analysis script is
[src/R/take_info_annotsv.R](../src/R/take_info_annotsv.R). Run it against an
AnnotSV or PhenoGenius-enriched TSV:

```bash
Rscript src/R/take_info_annotsv.R \
  SV_annotsv_JVM/examples/first_500_INS.phenogenius.tsv \
  results/TR_annotsv.tsv
```
