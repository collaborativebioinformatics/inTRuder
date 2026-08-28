#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

// ============================================================================
// Helper: Show help message
// ============================================================================
def helpMessage() {
    log.info """
    Usage:
      nextflow run main.nf [options]

    Required Parameters:
      --input               <path/glob>  Input VCF file (.vcf or .vcf.gz) or folder
      --hpo                 <str>        Comma-separated HPO terms (e.g. 'HP:0001156,HP:0001363')
      --phenogenius_bundle  <path>       Path to PhenoGeniusCli tarball

    Optional Parameters:
      --outdir              <dir>        Output directory                [default: results]
      --genome_build        <str>        GRCh38 or GRCh37                [default: GRCh38]
      --tx                  <str>        ENSEMBL or RefSeq               [default: ENSEMBL]
      --candidate_genes     <file>       Candidate genes list file       [default: none]
      --annotations_dir     <dir>        AnnotSV database directory
      --publish_dir_mode    <str>        Output file publish mode        [default: copy]
      --help                             Show this help message
    """.stripIndent()
}

// ============================================================================
// Helper: Resolve DNAnexus project path prefix
// ============================================================================
def resolve_dx_path(path_str, dx_proj) {
    if (!path_str) return path_str
    if (dx_proj && !path_str.startsWith('dx://') && (path_str.startsWith('/') || path_str.startsWith('project-'))) {
        return path_str.startsWith('/') ? "dx://${dx_proj}:${path_str}" : "dx://${path_str}"
    }
    return path_str
}

// ============================================================================
// Process 1: SV_PREPROCESS (Normalize INS -> DUP)
// ============================================================================
process SV_PREPROCESS {
    tag "${meta.id}"

    input:
    tuple val(meta), path(input_vcf)

    output:
    tuple val(meta), path("${meta.id}.preprocessed.vcf"), emit: vcf
    path "${meta.id}.preprocess.log", emit: log

    script:
    """
    python3 "${projectDir}/scripts/normalize_svtype.py" \\
      --input "${input_vcf}" \\
      --output "${meta.id}.preprocessed.vcf" \\
      2>&1 | tee "${meta.id}.preprocess.log"
    """

    stub:
    """
    touch "${meta.id}.preprocessed.vcf"
    touch "${meta.id}.preprocess.log"
    """
}

// ============================================================================
// Process 2: ANNOTSV (AnnotSV 3.5.10 Annotation)
// ============================================================================
process ANNOTSV {
    tag "${meta.id}"

    input:
    tuple val(meta), path(sv_vcf)
    path candidate_genes
    val annotations_source

    output:
    tuple val(meta), path("${meta.id}.annotsv.tsv"), emit: tsv
    path "${meta.id}.annotsv.log", emit: log

    script:
    def has_candidate_genes = candidate_genes && !(candidate_genes instanceof List && candidate_genes.isEmpty())
    def cg_arg = has_candidate_genes ? "-candidateGenesFile \"${candidate_genes}\"" : ""
    def out_prefix = "${meta.id}.annotsv"
    def cloud_mode = params.use_docker ? 'true' : 'false'
    def annotsv_cmd = params.annotsv_dir ? "${params.annotsv_dir}/bin/AnnotSV" : "AnnotSV"
    def hpo_arg = params.hpo ? "-hpo \"${params.hpo}\"" : ""
    def tx_arg = "-tx \"${params.tx ?: 'ENSEMBL'}\""

    """
    set -euo pipefail

    echo "[annotsv] Running AnnotSV on ${sv_vcf} (${params.genome_build})" >&2

    EFFECTIVE_ANNOTATIONS_DIR="${annotations_source}"

    if [[ "${cloud_mode}" == "true" ]]; then
        if ! command -v dx >/dev/null 2>&1; then
            echo "[annotsv] ERROR: dx-toolkit is required on the DNAnexus worker." >&2
            exit 1
        fi

        DX_ANNOTATIONS_PATH="${annotations_source}"
        DX_ANNOTATIONS_PATH="\${DX_ANNOTATIONS_PATH#dx://}"
        if [[ -z "\${DX_ANNOTATIONS_PATH}" ]]; then
            echo "[annotsv] ERROR: The DNAnexus annotation path is empty." >&2
            exit 1
        fi

        ANNOTATIONS_STAGE="\$(pwd)/annotations"
        mkdir -p "\${ANNOTATIONS_STAGE}"
        echo "[annotsv] Downloading annotation databases from \${DX_ANNOTATIONS_PATH}" >&2
        dx download --no-progress -r "\${DX_ANNOTATIONS_PATH}/Annotations_Human" -o "\${ANNOTATIONS_STAGE}/"
        dx download --no-progress -r "\${DX_ANNOTATIONS_PATH}/Annotations_Exomiser" -o "\${ANNOTATIONS_STAGE}/"

        if [[ ! -d "\${ANNOTATIONS_STAGE}/Annotations_Human" || ! -d "\${ANNOTATIONS_STAGE}/Annotations_Exomiser" ]]; then
            echo "[annotsv] ERROR: Annotation databases were not downloaded with the expected directory structure." >&2
            exit 1
        fi
        EFFECTIVE_ANNOTATIONS_DIR="\${ANNOTATIONS_STAGE}"
    fi

    echo "[annotsv] Annotation directory: \${EFFECTIVE_ANNOTATIONS_DIR}" >&2

    if [[ "${cloud_mode}" == "true" ]]; then
        docker run -u root --rm \\
            -v "\$(pwd):\$(pwd)" \\
            -w "\$(pwd)" \\
            -e "ANNOTSV_HPO=${params.hpo ?: ''}" \\
            "${params.annotsv_image}" \\
            bash -c '
                if [[ -n "\${ANNOTSV_HPO}" ]]; then
                    annotsv_bin="\$(command -v AnnotSV)"
                    annotsv_root="\$(cd "\$(dirname "\${annotsv_bin}")/.." && pwd)"
                    # AnnotSV 3.5.x writes an optional PhenoGenius warning log
                    # even when PhenoGenius is absent; ensure that path exists.
                    mkdir -p "\${annotsv_root}/share/python3/phenogeniuscli"
                fi
                exec AnnotSV "\$@"
            ' -- \\
                -SVinputFile    "${sv_vcf}" \\
                -genomeBuild    "${params.genome_build}" \\
                ${tx_arg} \\
                -outputDir      . \\
                -outputFile     "${out_prefix}.tsv" \\
                -bedtools       "${params.bedtools_path}" \\
                -bcftools       "${params.bcftools_path}" \\
                -annotationsDir "\${EFFECTIVE_ANNOTATIONS_DIR}" \\
                ${hpo_arg} \\
                ${cg_arg}
    else
        if [[ -n "${params.hpo ?: ''}" && -n "${params.annotsv_dir ?: ''}" ]]; then
            # AnnotSV 3.5.x expects this optional directory when HPO is used.
            mkdir -p "${params.annotsv_dir}/share/python3/phenogeniuscli"
        fi
        "${annotsv_cmd}" \\
            -SVinputFile    "${sv_vcf}" \\
            -genomeBuild    "${params.genome_build}" \\
            ${tx_arg} \\
            -outputDir      . \\
            -outputFile     "${out_prefix}.tsv" \\
            -bedtools       "${params.bedtools_path}" \\
            -bcftools       "${params.bcftools_path}" \\
            -annotationsDir "\${EFFECTIVE_ANNOTATIONS_DIR}" \\
            ${hpo_arg} \\
            ${cg_arg}
    fi 2>&1 | tee "${meta.id}.annotsv.log"

    if [[ ! -f "${out_prefix}.tsv" ]]; then
        echo "[annotsv] ERROR: Output file ${out_prefix}.tsv was not created!" >&2
        exit 1
    fi
    """

    stub:
    """
    touch "${meta.id}.annotsv.tsv"
    touch "${meta.id}.annotsv.log"
    """
}

// ============================================================================
// Process 3: PHENOGENIUS_ENRICH (Append Phenotype Scores -> *.annotated.tsv)
// ============================================================================
process PHENOGENIUS_ENRICH {
    tag "${meta.id}"
    publishDir "${params.outdir}", mode: params.publish_dir_mode, overwrite: true

    input:
    tuple val(meta), path(annotated_tsv)
    path phenogenius_bundle

    output:
    tuple val(meta), path("${meta.id}.annotated.tsv"), emit: enriched
    path "${meta.id}.phenogenius.log", emit: log

    script:
    """
    set -euo pipefail
    if [[ -d "${params.phenogenius_env}/bin" ]]; then
        export PATH="${params.phenogenius_env}/bin:\${PATH}"
    fi
    mkdir -p pg_runtime/site
    tar -xzf "${phenogenius_bundle}" -C pg_runtime
    # Provide the metadata queried by PhenoGenius' Click version callback.
    mkdir -p pg_runtime/site/phenogenius_cli-1.1.3.dist-info
    printf 'Metadata-Version: 2.1\\nName: phenogenius_cli\\nVersion: 1.1.3\\n' \\
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
      --output "${meta.id}.annotated.tsv" \\
      2>&1 | tee "${meta.id}.phenogenius.log"
    """

    stub:
    """
    touch "${meta.id}.annotated.tsv"
    touch "${meta.id}.phenogenius.log"
    """
}

// ============================================================================
// Main Workflow
// ============================================================================
workflow {

    if (params.help) {
        helpMessage()
        exit 0
    }

    if (!params.input) {
        log.error "ERROR: --input is required. Provide a VCF file path or folder."
        helpMessage()
        exit 1
    }

    if (!params.hpo) {
        log.error "ERROR: --hpo is required. Provide comma-separated HPO terms (e.g. --hpo 'HP:0001156,HP:0001363')."
        exit 1
    }

    if (!params.phenogenius_bundle) {
        log.error "ERROR: --phenogenius_bundle is required. Provide path to PhenoGeniusCli tarball."
        exit 1
    }

    def valid_builds = ['GRCh37', 'GRCh38']
    if (params.genome_build && !valid_builds.contains(params.genome_build)) {
        log.error "ERROR: --genome_build must be one of: ${valid_builds.join(', ')}. Got: ${params.genome_build}"
        exit 1
    }

    def requested_tx = params.tx?.toString()?.toUpperCase()
    if (requested_tx && !['REFSEQ', 'ENSEMBL'].contains(requested_tx)) {
        log.error "ERROR: --tx must be one of: ENSEMBL, RefSeq. Got: ${params.tx}"
        exit 1
    }
    params.tx = requested_tx == 'REFSEQ' ? 'RefSeq' : 'ENSEMBL'

    def hpos = params.hpo.toString().split(/[;,\s]+/).findAll { it }
    if (!hpos || hpos.any { !(it ==~ /HP:\d{7}/) }) {
        log.error "ERROR: --hpo must contain valid HPO identifiers (e.g. HP:0001156,HP:0001363). Got: ${params.hpo}"
        exit 1
    }

    // 1. Resolve DNAnexus dx:// paths
    def resolved_input = resolve_dx_path(params.input, params.dx_project)
    def input_pattern = resolved_input
    if (resolved_input.endsWith('/') || (file(resolved_input).exists() && file(resolved_input).isDirectory())) {
        def clean_path = resolved_input.replaceAll('/+$', '')
        input_pattern = "${clean_path}/*.{vcf,vcf.gz}"
    }

    def resolved_annot = resolve_dx_path(params.annotations_dir, params.dx_project)
    def resolved_candidate_genes = resolve_dx_path(params.candidate_genes, params.dx_project)
    def resolved_bundle = resolve_dx_path(params.phenogenius_bundle, params.dx_project)

    log.info """
      input               : ${params.input}
      resolved pattern    : ${input_pattern}
      outdir              : ${params.outdir}
      genome_build        : ${params.genome_build ?: 'GRCh38'}
      tx                  : ${params.tx ?: 'ENSEMBL'}
      hpo                 : ${params.hpo}
      candidate_genes     : ${resolved_candidate_genes ?: 'none'}
      annotations_dir     : ${resolved_annot}
      phenogenius_bundle  : ${resolved_bundle}
      publish_dir_mode    : ${params.publish_dir_mode}
    """.stripIndent()

    // 2. Build input channels
    Channel
        .fromPath(input_pattern, checkIfExists: true)
        .map { vcf_file ->
            def meta = [ id: vcf_file.simpleName.replaceAll('(?i)\\.(vcf|preprocessed)$', '') ]
            [ meta, vcf_file ]
        }
        .set { ch_vcf_input }

    ch_candidate_genes = resolved_candidate_genes
        ? Channel.fromPath(resolved_candidate_genes, checkIfExists: true)
        : Channel.value([])

    ch_annotations = Channel.value(resolved_annot ?: '')
    ch_bundle = Channel.fromPath(resolved_bundle, checkIfExists: true)

    // 3. Pipeline execution
    // Stage 1: SV Preprocessing (INS -> DUP)
    SV_PREPROCESS(ch_vcf_input)

    // Stage 2: AnnotSV 3.5.10 Annotation
    ANNOTSV(
        SV_PREPROCESS.out.vcf,
        ch_candidate_genes,
        ch_annotations
    )

    // Stage 3: PhenoGenius Phenotype Enrichment (Writes *.annotated.tsv)
    PHENOGENIUS_ENRICH(
        ANNOTSV.out.tsv,
        ch_bundle
    )

    PHENOGENIUS_ENRICH.out.enriched.subscribe { meta, file ->
        log.info "Sample [${meta.id}] annotated: ${file}"
    }
}

