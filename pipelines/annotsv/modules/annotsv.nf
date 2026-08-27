/*
================================================================================
  Nextflow DSL2 Module: ANNOTSV
  AnnotSV v3.5.10 — Structural Variant Annotation
================================================================================
  Author  : Taimoor
  Project : novelTRs / bcm-hackathon26
  Date    : 2026-08-27
================================================================================
*/

process ANNOTSV {

    tag "${meta.id}"
    label 'process_medium'

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

    input:
    tuple val(meta), path(sv_vcf)
    path  candidate_genes
    path  annotations_dir

    output:
    tuple val(meta), path("*.annotated.tsv"), emit: tsv
    path "*.log",                             emit: log

    script:
    def cand_genes_flag = (candidate_genes.name != 'NO_FILE') ? "-candidateGenesFile ${candidate_genes}" : ''
    def annot_dir_flag  = (annotations_dir.name != 'NO_DIR')  ? "-annotationsDir ${annotations_dir}"     : ''
    def annotsv_cmd     = (params.annotsv_dir && file("${params.annotsv_dir}/bin/AnnotSV").exists()) ? "${params.annotsv_dir}/bin/AnnotSV" : 'AnnotSV'
    def bedtools_cmd    = params.bedtools_path ?: 'bedtools'
    def bcftools_cmd    = params.bcftools_path ?: 'bcftools'
    """
    echo "[annotsv] Running AnnotSV on ${sv_vcf} (${params.genome_build ?: 'GRCh38'})" >&2

    ${annotsv_cmd} \
        -SVinputFile    "${sv_vcf}" \
        -genomeBuild    "${params.genome_build ?: 'GRCh38'}" \
        -outputDir      . \
        -outputFile     "${meta.id}.annotated.tsv" \
        -bedtools       "${bedtools_cmd}" \
        -bcftools       "${bcftools_cmd}" \
        ${annot_dir_flag} \
        ${cand_genes_flag} \
        2>&1 | tee "${meta.id}.annotsv.log"
    """

    stub:
    """
    touch "${meta.id}.annotated.tsv"
    touch "${meta.id}.annotsv.log"
    """
}
