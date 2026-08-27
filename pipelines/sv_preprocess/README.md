# SV preprocessing

Converts only records with `INFO/SVTYPE=INS` to `DUP` for AnnotSV
compatibility. Symbolic `<INS>` is changed to `<DUP>`, and
`ORIG_SVTYPE=INS` is added for traceability.

## Local

```bash
nextflow run pipelines/sv_preprocess/main.nf -profile local \
  --input input.vcf --outdir results/preprocessed
```

## DNAnexus

```bash
dx run applet-JB87kYQ0pzX1v4qZZyxyZ92q \
  -inextflow_pipeline_params="--input '/Test_Inputs/first_500_INS.vcf'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/Preprocess_Test' \
  --name preprocess_first_500 --yes
```

The output is `*.preprocessed.vcf` and a conversion log.

