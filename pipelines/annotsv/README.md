# AnnotSV annotation

Nextflow DSL2 pipeline for AnnotSV 3.5.10 structural-variant annotation.

## Local

Install AnnotSV, its annotation databases, Nextflow, bedtools, and bcftools.
See [ANNOTSV_INSTALLATION_GUIDE.md](ANNOTSV_INSTALLATION_GUIDE.md).

```bash
nextflow run pipelines/annotsv/main.nf -profile local \
  --input input.vcf \
  --genome_build GRCh38 \
  --tx ENSEMBL \
  --hpo HP:0001156,HP:0001363,HP:0011304 \
  --outdir results/annotsv
```

A directory can be supplied to `--input`; each supported VCF/BED file is
processed independently.

## DNAnexus

The tested applet is `applet-JB8562j0pzX7b1QvbbB9zyg5`. Annotation databases
are stored in project `Group2_2026` under `/resources/AnnotSV`.

```bash
dx run applet-JB8562j0pzX7b1QvbbB9zyg5 \
  -inextflow_run_opts='-profile dnanexus' \
  -inextflow_pipeline_params="--input '/Test_Inputs/first_500_INS.vcf' --tx ENSEMBL --hpo 'HP:0001156,HP:0001363,HP:0011304'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/AnnotSV_Test' \
  --name annotsv_first_500 --yes
```

Outputs are published under `results/annotsv/` and
`results/summary/`. For Web UI instructions and the full three-stage order,
see [SV_annotsv_JVM/workflow.md](../../SV_annotsv_JVM/workflow.md).
