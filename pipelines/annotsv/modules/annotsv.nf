process ANNOTSV {
    tag "${meta.id}"
    publishDir "${params.outdir}/annotsv", mode: params.publish_dir_mode, overwrite: true

    input:
    tuple val(meta), path(sv_vcf)
    path(candidate_genes)
    val(annotations_source)

    output:
    tuple val(meta), path("*.annotated.tsv"), emit: tsv
    path "*.annotsv.log", emit: log

    script:
    def has_candidate_genes = candidate_genes && !(candidate_genes instanceof List && candidate_genes.isEmpty())
    def cg_arg = has_candidate_genes ? "-candidateGenesFile \"${candidate_genes}\"" : ""
    def out_prefix = "${meta.id}.annotated"
    def cloud_mode = params.use_docker ? 'true' : 'false'
    def annotsv_cmd = params.annotsv_dir ? "${params.annotsv_dir}/bin/AnnotSV" : "AnnotSV"

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
            "${params.annotsv_image}" \\
            AnnotSV \\
                -SVinputFile    "${sv_vcf}" \\
                -genomeBuild    "${params.genome_build}" \\
                -outputDir      . \\
                -outputFile     "${out_prefix}.tsv" \\
                -bedtools       "${params.bedtools_path}" \\
                -bcftools       "${params.bcftools_path}" \\
                -annotationsDir "\${EFFECTIVE_ANNOTATIONS_DIR}" \\
                ${cg_arg}
    else
        "${annotsv_cmd}" \\
            -SVinputFile    "${sv_vcf}" \\
            -genomeBuild    "${params.genome_build}" \\
            -outputDir      . \\
            -outputFile     "${out_prefix}.tsv" \\
            -bedtools       "${params.bedtools_path}" \\
            -bcftools       "${params.bcftools_path}" \\
            -annotationsDir "\${EFFECTIVE_ANNOTATIONS_DIR}" \\
            ${cg_arg}
    fi 2>&1 | tee "${meta.id}.annotsv.log"

    if [[ ! -f "${out_prefix}.tsv" ]]; then
        echo "[annotsv] ERROR: Output file ${out_prefix}.tsv was not created!" >&2
        exit 1
    fi
    """
}
