# PhenoGenius enrichment

Appends PhenoGenius phenotype scores to an existing AnnotSV TSV. This stage
does not rerun AnnotSV. The input must contain the `NCBI_gene_ID` column.

## Local

Provide a local PhenoGenius runtime bundle:

```bash
nextflow run pipelines/phenogenius_enrich/main.nf -profile local \
  --input_tsv annotated.tsv \
  --phenogenius_bundle /path/to/PhenoGeniusCli-v1.1.3.tar.gz \
  --hpo HP:0001156,HP:0001363,HP:0011304 \
  --outdir results/phenogenius
```

## DNAnexus

Applet: `applet-JB883gj0pzX5f2FXzpxZKKPp`

```bash
dx run applet-JB883gj0pzX5f2FXzpxZKKPp \
  -inextflow_run_opts='-profile dnanexus' \
  -inextflow_pipeline_params="--input_tsv '/Results/AnnotSV_Test/results/annotsv/first_500_INS.annotated.tsv' --phenogenius_bundle '/resources/PhenoGenius/PhenoGeniusCli-v1.1.3-dx.tar.gz' --hpo 'HP:0001156,HP:0001363,HP:0011304'" \
  --destination 'project-JB6zg5Q0pzX96qVJjz7gKg58:/Results/PhenoGenius_Test' \
  --name phenogenius_first_500 --yes
```

The output is `*.phenogenius.tsv` plus a log. Five PhenoGenius columns are
appended: per-gene scores/specificity and best gene, score, and specificity.

