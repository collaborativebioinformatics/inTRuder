#!/usr/bin/env nextflow
/*
================================================================================
  AnnotSV Annotation Pipeline — main.nf
================================================================================
  Author  : Taimoor
  Project : novelTRs / bcm-hackathon26
  Date    : 2026-08-27
================================================================================
*/

nextflow.enable.dsl = 2

// ============================================================================
// Import modules
// ============================================================================
include { ANNOTSV }          from './modules/annotsv.nf'
include { GENERATE_SUMMARY } from './modules/summary.nf'

// ============================================================================
// Helper: Show help message
// ============================================================================
def helpMessage() {
    log.info """
    ╔══════════════════════════════════════════════════════╗
    ║      AnnotSV Annotation Pipeline  v1.0.0             ║
    ╚══════════════════════════════════════════════════════╝

    Usage:
      nextflow run main.nf [options]

    Required / Configurable Inputs:
      --input               <path/glob>  Path to VCF/BED file or folder
                                         Examples:
                                           --input '/survivor/HPRC_SV.survivor.vcf'
                                           --input '/sniffles/filtered/'
                                           --input 'data/first_500_INS.vcf'

    Optional Parameters:
      --outdir              <dir>        Output directory                [default: results]
      --genome_build        <str>        GRCh38 or GRCh37                [default: GRCh38]
      --candidate_genes     <file>       Candidate genes list file       [default: none]
      --publish_dir_mode    <str>        Output file mode                [default: copy]
      --help                             Show this help message

    Automatic Platform Settings (Configured in nextflow.config):
      - Project ID:         ${params.dx_project ?: 'local'}
      - Reference DBs:      ${params.dx_annotations_path ?: params.annotations_dir}
      - Memory:             64 GB (Cloud) / 8 GB (Local)
    """.stripIndent()
}

// ============================================================================
// Helper: build meta map from a file path
// ============================================================================
def build_meta(file_path) {
    def name = file_path.getSimpleName()
    name = name.replaceAll('(?i)\\.(sv|svs|cnv|cnvs|indels?|snv|snvs|variants?)$', '')
    name = name.replaceAll('(?i)[-_]?(filtered|merged|sorted|final|calls?)$', '')

    return [
        id      : name,
        filename: file_path.getName()
    ]
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
        log.error "ERROR: --input is required. Provide a file path or folder (e.g. --input '/survivor/HPRC_SV.survivor.vcf')"
        helpMessage()
        exit 1
    }

    def valid_builds = ['GRCh37', 'GRCh38']
    if (params.genome_build && !valid_builds.contains(params.genome_build)) {
        log.error "ERROR: --genome_build must be one of: ${valid_builds.join(', ')}. Got: ${params.genome_build}"
        exit 1
    }

    // 1. Resolve DNAnexus dx:// prefix automatically if running with dx_project
    def resolved_input = params.input
    if (params.dx_project && resolved_input && !resolved_input.startsWith('dx://') && (resolved_input.startsWith('/') || resolved_input.startsWith('project-'))) {
        if (resolved_input.startsWith('/')) {
            resolved_input = "dx://${params.dx_project}:${resolved_input}"
        } else {
            resolved_input = "dx://${resolved_input}"
        }
    }

    // 2. Resolve input pattern: handle directory vs glob vs single file
    def input_pattern = resolved_input
    if (resolved_input.endsWith('/') || (file(resolved_input).exists() && file(resolved_input).isDirectory())) {
        def clean_path = resolved_input.replaceAll('/+$', '')
        input_pattern = "${clean_path}/*.{vcf,vcf.gz,bed,bed.gz,bcf}"
    }

    log.info """
    ╔══════════════════════════════════════════════════════════╗
    ║        AnnotSV Annotation Pipeline                       ║
    ╚══════════════════════════════════════════════════════════╝
      input               : ${params.input}
      resolved pattern    : ${input_pattern}
      outdir              : ${params.outdir}
      genome_build        : ${params.genome_build ?: 'GRCh38'}
      candidate_genes     : ${params.candidate_genes ?: 'none'}
      dx_project          : ${params.dx_project ?: 'local'}
      dx_annotations_path : ${params.dx_annotations_path ?: 'local (not using dx storage)'}
      publish_dir_mode    : ${params.publish_dir_mode}
    """.stripIndent()

    // 3. Create input channel
    Channel
        .fromPath(input_pattern, checkIfExists: true)
        .map { vcf_file ->
            def meta = build_meta(vcf_file)
            [ meta, vcf_file ]
        }
        .set { ch_sv_input }

    // 4. Optional candidate-genes file channel
    ch_candidate_genes = params.candidate_genes
        ? Channel.fromPath(params.candidate_genes, checkIfExists: true)
        : Channel.value(file('NO_FILE'))

    // 5. DNAnexus annotations path channel
    ch_dx_annotations = Channel.value(params.dx_annotations_path ?: '')

    // 6. Run ANNOTSV on all sample files
    ANNOTSV(
        ch_sv_input,
        ch_candidate_genes,
        ch_dx_annotations
    )

    // 7. Collect all annotated TSVs and generate summary report table
    all_tsvs = ANNOTSV.out.tsv
        .map { meta, tsv -> tsv }
        .collect()

    GENERATE_SUMMARY(all_tsvs)

    // 8. Log outputs
    all_tsvs.subscribe { files ->
        def count = files instanceof List ? files.size() : 1
        log.info "✅ All ${count} samples annotated successfully!"
    }
}
