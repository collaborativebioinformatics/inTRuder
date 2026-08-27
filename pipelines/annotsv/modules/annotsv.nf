/*
================================================================================
  Nextflow DSL2 Module: ANNOTSV
  AnnotSV v3.5.10 — Structural Variant Annotation
================================================================================
  Author  : Taimoor
  Project : novelTRs / bcm-hackathon26
  Date    : 2026-08-26
  Updated : 2026-08-27 — Nextflow 26 DSL2 & DNAnexus Docker/Conda support
================================================================================
*/

process ANNOTSV {

    tag "${meta.id}"
    label 'process_medium'

    // Directives must come before input:
    publishDir path: { "${params.outdir}/${meta.id}/annotsv" },
               mode: params.publish_dir_mode ?: 'copy',
               pattern: '*.annotated.tsv'

    publishDir path: { "${params.outdir}/${meta.id}/annotsv/logs" },
               mode: 'copy',
               pattern: '*.log'

    errorStrategy { task.exitStatus in [143, 137, 104, 134, 139] ? 'retry' : 'finish' }
    maxRetries 2

    // Software environment
    container 'quay.io/biocontainers/annotsv:3.5.10--hdfd78af_0'
    conda 'bioconda::annotsv=3.5.10 bioconda::bedtools bioconda::bcftools'

    // Inputs
    input:
    tuple val(meta), path(sv_vcf)       // VCF or BED file of SVs
    path  candidate_genes               // optional; pass file('NO_FILE') when absent
    val   dx_annotations_path           // dx path e.g. 'project-XXX:/resources/AnnotSV'; pass '' locally

    // Outputs
    output:
    tuple val(meta), path('*.annotated.tsv'), emit: tsv
    path  '*.log'                            , emit: log

    // Script
    script:
    def prefix          = task.ext.prefix ?: "${meta.id}"
    def genome_build    = params.genome_build    ?: 'GRCh38'
    def extra_args      = task.ext.args          ?: ''
    def annotsv_dir     = params.annotsv_dir     ?: 'AnnotSV'
    def bedtools_exe    = params.bedtools_path   ?: 'bedtools'
    def bcftools_exe    = params.bcftools_path   ?: 'bcftools'
    def annotations_dir = params.annotations_dir ?: ''
    def dx_annot_path   = dx_annotations_path instanceof String ? dx_annotations_path : (dx_annotations_path ?: '')
    def cand_genes_flag = (candidate_genes.name != 'NO_FILE') \
        ? "-candidateGenesFile ${candidate_genes}" \
        : ''
    """
    #!/usr/bin/env bash
    set -euo pipefail

    # =========================================================================
    # 0. [DNAnexus only] Download annotation databases from dx storage
    # =========================================================================
    DX_ANNOT_PATH="${dx_annot_path}"
    if [[ -n "\${DX_ANNOT_PATH}" ]]; then
        EFFECTIVE_ANNOTATIONS_DIR="/home/dnanexus/annotations"
        if [[ ! -d "\${EFFECTIVE_ANNOTATIONS_DIR}/Annotations_Human" ]] && command -v dx &>/dev/null; then
            echo "[annotsv] Downloading annotations from \${DX_ANNOT_PATH}" >&2
            mkdir -p "\${EFFECTIVE_ANNOTATIONS_DIR}"
            dx download --no-progress -r "\${DX_ANNOT_PATH}/Annotations_Human" -o "\${EFFECTIVE_ANNOTATIONS_DIR}/" 2>&1 | tail -5
            dx download --no-progress -r "\${DX_ANNOT_PATH}/Annotations_Exomiser" -o "\${EFFECTIVE_ANNOTATIONS_DIR}/" 2>&1 | tail -5
        fi
        echo "[annotsv] Annotations directory: \${EFFECTIVE_ANNOTATIONS_DIR}" >&2
    else
        EFFECTIVE_ANNOTATIONS_DIR="${annotations_dir}"
    fi

    # =========================================================================
    # 1. Resolve AnnotSV executable — handle spaces-in-path via symlink
    # =========================================================================
    ANNOTSV_DIR="${annotsv_dir}"
    BEDTOOLS="${bedtools_exe}"
    BCFTOOLS="${bcftools_exe}"
    GENOME_BUILD="${genome_build}"

    # Dereference symlinks to get the real path
    ANNOTSV_REAL=\$(readlink -f "\${ANNOTSV_DIR}" 2>/dev/null || echo "\${ANNOTSV_DIR}")

    # Check if the resolved path contains spaces (breaks Tcl)
    if [[ "\${ANNOTSV_REAL}" == *" "* ]]; then
        echo "[annotsv] WARNING: AnnotSV real path contains spaces: \${ANNOTSV_REAL}" >&2
        SYMLINK_TARGET="/home/taimoor/tools/AnnotSV"

        if [[ -L "\${SYMLINK_TARGET}" ]]; then
            EXISTING_TARGET=\$(readlink -f "\${SYMLINK_TARGET}" 2>/dev/null || true)
            if [[ "\${EXISTING_TARGET}" != "\${ANNOTSV_REAL}" ]]; then
                echo "[annotsv] ERROR: \${SYMLINK_TARGET} points to \${EXISTING_TARGET}, not \${ANNOTSV_REAL}" >&2
                exit 1
            fi
            echo "[annotsv] Reusing existing symlink: \${SYMLINK_TARGET} -> \${ANNOTSV_REAL}" >&2
        elif [[ -e "\${SYMLINK_TARGET}" ]]; then
            echo "[annotsv] ERROR: \${SYMLINK_TARGET} exists but is NOT a symlink." >&2
            exit 1
        else
            echo "[annotsv] Creating symlink: \${SYMLINK_TARGET} -> \${ANNOTSV_REAL}" >&2
            ln -s "\${ANNOTSV_REAL}" "\${SYMLINK_TARGET}"
        fi

        ANNOTSV_DIR="\${SYMLINK_TARGET}"
    fi

    ANNOTSV_BIN="\${ANNOTSV_DIR}/bin/AnnotSV"

    if [[ ! -x "\${ANNOTSV_BIN}" ]]; then
        if command -v AnnotSV &>/dev/null; then
            ANNOTSV_BIN=\$(command -v AnnotSV)
            echo "[annotsv] Using AnnotSV from PATH: \${ANNOTSV_BIN}" >&2
        else
            echo "[annotsv] ERROR: AnnotSV not found at \${ANNOTSV_BIN} and not on PATH." >&2
            exit 1
        fi
    fi

    echo "[annotsv] AnnotSV binary : \${ANNOTSV_BIN}" >&2
    echo "[annotsv] bedtools       : \${BEDTOOLS}"    >&2
    echo "[annotsv] bcftools       : \${BCFTOOLS}"    >&2
    echo "[annotsv] Genome build   : \${GENOME_BUILD}" >&2
    echo "[annotsv] Input file     : ${sv_vcf}"       >&2

    # =========================================================================
    # 2. Build output prefix & run AnnotSV
    # =========================================================================
    INPUT_FILE="${sv_vcf}"
    OUTPUT_PREFIX="${prefix}.annotated"

    "\${ANNOTSV_BIN}" \
        -SVinputFile    "\${INPUT_FILE}" \
        -genomeBuild    "\${GENOME_BUILD}" \
        -outputDir      . \
        -outputFile     "\${OUTPUT_PREFIX}.tsv" \
        -bedtools       "\${BEDTOOLS}" \
        -bcftools       "\${BCFTOOLS}" \
        -annotationsDir "\${EFFECTIVE_ANNOTATIONS_DIR}" \
        ${cand_genes_flag} \
        ${extra_args} \
        2>&1 | tee "${prefix}.annotsv.log"

    EXIT_CODE=\${PIPESTATUS[0]}

    if [[ \${EXIT_CODE} -ne 0 ]]; then
        echo "[annotsv] ERROR: AnnotSV exited with code \${EXIT_CODE}" >&2
        exit \${EXIT_CODE}
    fi

    # =========================================================================
    # 5. Normalise output filename to *.annotated.tsv
    # =========================================================================
    if [[ -f "\${OUTPUT_PREFIX}_AnnotSV.tsv" && ! -f "\${OUTPUT_PREFIX}.tsv" ]]; then
        mv "\${OUTPUT_PREFIX}_AnnotSV.tsv" "\${OUTPUT_PREFIX}.tsv"
    fi

    echo "[annotsv] Done. Output: \${OUTPUT_PREFIX}.tsv" >&2
    """

    stub:
    def prefix = task.ext.prefix ?: "${meta.id}"
    """
    touch ${prefix}.annotated.tsv
    touch ${prefix}.annotsv.log
    """
}
