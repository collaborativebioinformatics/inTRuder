nextflow.enable.dsl = 2

def helpMessage() {
    log.info '''
    Usage:
      nextflow run main.nf --input_tsv <AnnotSV.tsv> --hpo <HP:...,HP:...>

    The input must contain an AnnotSV NCBI_gene_ID column. PhenoGenius is run
    once for the unique genes and the original TSV is preserved with appended
    per-gene and best-gene score columns.
    '''.stripIndent()
}

process PHENOGENIUS_ENRICH {
    tag "${annotated_tsv.simpleName}"
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    path annotated_tsv

    output:
    path "*.phenogenius.tsv", emit: enriched
    path "*.phenogenius.log", emit: log

    script:
    """
    set -euo pipefail
    export PATH="${params.phenogenius_env}/bin:\${PATH}"
    export CONDA_PREFIX="${params.phenogenius_env}"
    export CONDA_DEFAULT_ENV="annotsv"

    python3 "${projectDir}/scripts/enrich_phenogenius.py" \\
      --input "${annotated_tsv}" \\
      --hpo "${params.hpo}" \\
      --phenogenius-cli "${params.phenogenius_cli}" \\
      --resource-dir "${params.resource_dir}" \\
      --python "${params.phenogenius_env}/bin/python" \\
      --output "${annotated_tsv.simpleName}.phenogenius.tsv" \\
      2>&1 | tee "${annotated_tsv.simpleName}.phenogenius.log"
    """
}

workflow {
    if (!params.input_tsv || !params.hpo) {
        log.error 'ERROR: --input_tsv and --hpo are required.'
        helpMessage()
        exit 1
    }
    def hpos = params.hpo.toString().split(/[;,\s]+/).findAll { it }
    if (!hpos || hpos.any { !(it ==~ /HP:\d{7}/) }) {
        log.error "ERROR: --hpo must contain valid HPO identifiers. Got: ${params.hpo}"
        exit 1
    }
    Channel.fromPath(params.input_tsv, checkIfExists: true).set { ch_tsv }
    PHENOGENIUS_ENRICH(ch_tsv)
}
