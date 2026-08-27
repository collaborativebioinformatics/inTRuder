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
    path phenogenius_bundle

    output:
    path "*.phenogenius.tsv", emit: enriched
    path "*.phenogenius.log", emit: log

    script:
    """
    set -euo pipefail
    if [[ -d "${params.phenogenius_env}/bin" ]]; then
        export PATH="${params.phenogenius_env}/bin:\${PATH}"
    fi
    mkdir -p pg_runtime/site
    tar -xzf "${phenogenius_bundle}" -C pg_runtime
    # The source bundle has no Git checkout or installed distribution metadata;
    # provide the metadata queried by PhenoGenius' Click version callback.
    mkdir -p pg_runtime/site/phenogenius_cli-1.1.3.dist-info
    printf 'Metadata-Version: 2.1\nName: phenogenius_cli\nVersion: 1.1.3\n' \\
      > pg_runtime/site/phenogenius_cli-1.1.3.dist-info/METADATA
    python3 -m pip install --disable-pip-version-check --quiet --target pg_runtime/site \\
      'pandas>=1.3' 'ujson>=5.4' 'numpy>=1.24,<2.1' 'scikit-learn>=1.5.1' \\
      'pandarallel>=1.6.5' 'click>=8.1.7' 'pyarrow>=17,<18' 'pronto>=2.5.8'
    export PYTHONPATH="\$(pwd)/pg_runtime/site:\${PYTHONPATH:-}"

    python3 "${projectDir}/scripts/enrich_phenogenius.py" \\
      --input "${annotated_tsv}" \\
      --hpo "${params.hpo}" \\
      --phenogenius-cli "\$(pwd)/pg_runtime/phenogenius_cli.py" \\
      --resource-dir "\$(pwd)/pg_runtime/data/resources" \\
      --python "python3" \\
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
    if (!params.phenogenius_bundle) {
        log.error 'ERROR: --phenogenius_bundle is required.'
        exit 1
    }
    def hpos = params.hpo.toString().split(/[;,\s]+/).findAll { it }
    if (!hpos || hpos.any { !(it ==~ /HP:\d{7}/) }) {
        log.error "ERROR: --hpo must contain valid HPO identifiers. Got: ${params.hpo}"
        exit 1
    }
    def resolved_tsv = params.input_tsv
    if (params.dx_project && resolved_tsv.startsWith('/')) {
        resolved_tsv = "dx://${params.dx_project}:${resolved_tsv}"
    }
    def resolved_bundle = params.phenogenius_bundle
    if (params.dx_project && resolved_bundle.startsWith('/')) {
        resolved_bundle = "dx://${params.dx_project}:${resolved_bundle}"
    }
    Channel.fromPath(resolved_tsv, checkIfExists: true).set { ch_tsv }
    Channel.fromPath(resolved_bundle, checkIfExists: true).set { ch_bundle }
    PHENOGENIUS_ENRICH(ch_tsv, ch_bundle)
}
