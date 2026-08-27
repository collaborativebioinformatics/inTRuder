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
      --annotations_dir     <dir>        AnnotSV database directory
      --publish_dir_mode    <str>        Output file mode                [default: copy]
      --help                             Show this help message
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

    // 3. Resolve annotations directory path
    def resolved_annot = params.annotations_dir
    if (params.dx_project && resolved_annot && !resolved_annot.startsWith('dx://') && (resolved_annot.startsWith('/') || resolved_annot.startsWith('project-'))) {
        if (resolved_annot.startsWith('/')) {
            resolved_annot = "dx://${params.dx_project}:${resolved_annot}"
        } else {
            resolved_annot = "dx://${resolved_annot}"
        }
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
      annotations_dir     : ${resolved_annot}
      publish_dir_mode    : ${params.publish_dir_mode}
    """.stripIndent()

    // 4. Create input channel
    Channel
        .fromPath(input_pattern, checkIfExists: true)
        .map { vcf_file ->
            def meta = build_meta(vcf_file)
            [ meta, vcf_file ]
        }
        .set { ch_sv_input }

    // 5. Optional candidate-genes file channel
    ch_candidate_genes = params.candidate_genes
        ? Channel.fromPath(params.candidate_genes, checkIfExists: true)
        : Channel.value(file('NO_FILE'))

    // 6. Annotations directory channel
    ch_annotations = resolved_annot
        ? Channel.fromPath(resolved_annot, checkIfExists: true)
        : Channel.value(file('NO_DIR'))

    // 7. Run ANNOTSV on all sample files
    ANNOTSV(
        ch_sv_input,
        ch_candidate_genes,
        ch_annotations
    )

    // 8. Collect all annotated TSVs and generate summary report table
    all_tsvs = ANNOTSV.out.tsv
        .map { meta, tsv -> tsv }
        .collect()

    GENERATE_SUMMARY(all_tsvs)

    // 9. Log outputs
    all_tsvs.subscribe { files ->
        def count = files instanceof List ? files.size() : 1
        log.info "✅ All ${count} samples annotated successfully!"
    }
}
