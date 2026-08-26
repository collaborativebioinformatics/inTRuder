#!/usr/bin/env nextflow
/*
================================================================================
  AnnotSV Annotation Pipeline — main.nf
================================================================================
  Author  : Taimoor
  Project : novelTRs / bcm-hackathon26
  Date    : 2026-08-26
  Updated : 2026-08-27 — Directory/File multi-input support & Summary Reporting
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

    Required:
      --input               <path/glob>  Directory containing VCF/BED files,
                                         single file, or glob pattern
                                         Examples:
                                           --input 'path/to/vcfs/'
                                           --input 'path/to/*.vcf.gz'
                                           --input 'sample.vcf'

    Optional:
      --outdir              <dir>        Output directory                [default: results]
      --genome_build        <str>        GRCh37 or GRCh38                [default: GRCh38]
      --candidate_genes     <file>       Candidate genes file            [default: none]
      --annotsv_dir         <dir>        AnnotSV install directory
      --annotations_dir     <dir>        AnnotSV annotations directory
      --bedtools_path       <path>       Path to bedtools executable
      --bcftools_path       <path>       Path to bcftools executable
      --dx_annotations_path <str>        DNAnexus dx path to databases   [default: none]
                                         (e.g. 'project-XXX:/resources/AnnotSV')
      --publish_dir_mode    <str>        Output file mode                [default: copy]
      --help                             Show this help message

    Profiles:
      local                 Use host-installed tools (default)
      conda                 Use conda environments
      singularity           Use Singularity containers
      dnanexus              Run on DNAnexus cloud workers (Docker + dx storage)
      slurm                 Submit jobs to SLURM cluster
      test                  Stub run for CI testing

    Examples:
      nextflow run main.nf --input 'path/to/vcfs/' --outdir results
      nextflow run main.nf --input 'svs/*.vcf' --genome_build GRCh37 -profile conda
      nextflow run main.nf --input 'dx://project-xxx:/survivor/' -profile dnanexus
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
        log.error "ERROR: --input is required. Provide a directory, file, or glob pattern for VCF/BED files."
        helpMessage()
        exit 1
    }

    def valid_builds = ['GRCh37', 'GRCh38']
    if (params.genome_build && !valid_builds.contains(params.genome_build)) {
        log.error "ERROR: --genome_build must be one of: ${valid_builds.join(', ')}. Got: ${params.genome_build}"
        exit 1
    }

    // Resolve input pattern: handle directory vs glob vs single file
    def input_pattern = params.input
    if (params.input.endsWith('/') || (file(params.input).exists() && file(params.input).isDirectory())) {
        def clean_path = params.input.replaceAll('/+$', '')
        input_pattern = "${clean_path}/*.{vcf,vcf.gz,bed,bed.gz,bcf}"
    }

    log.info """
    ╔══════════════════════════════════════════════════════════╗
    ║        AnnotSV Annotation Pipeline                       ║
    ╚══════════════════════════════════════════════════════════╝
      input               : ${params.input}
      pattern resolved    : ${input_pattern}
      outdir              : ${params.outdir}
      genome_build        : ${params.genome_build ?: 'GRCh38'}
      candidate_genes     : ${params.candidate_genes ?: 'none'}
      annotsv_dir         : ${params.annotsv_dir}
      annotations_dir     : ${params.annotations_dir}
      bedtools            : ${params.bedtools_path}
      bcftools            : ${params.bcftools_path}
      dx_annotations_path : ${params.dx_annotations_path ?: 'none (local annotations)'}
      publish_dir_mode    : ${params.publish_dir_mode}
    """.stripIndent()

    // 1. Create input channel
    Channel
        .fromPath(input_pattern, checkIfExists: true)
        .map { vcf_file ->
            def meta = build_meta(vcf_file)
            [ meta, vcf_file ]
        }
        .set { ch_sv_input }

    // 2. Optional candidate-genes file channel
    ch_candidate_genes = params.candidate_genes
        ? Channel.fromPath(params.candidate_genes, checkIfExists: true)
        : Channel.value(file('NO_FILE'))

    // 3. DNAnexus annotations path channel
    ch_dx_annotations = Channel.value(params.dx_annotations_path ?: '')

    // 4. Run ANNOTSV on all sample files
    ANNOTSV(
        ch_sv_input,
        ch_candidate_genes,
        ch_dx_annotations
    )

    // 5. Collect all annotated TSVs and generate summary report table
    all_tsvs = ANNOTSV.out.tsv
        .map { meta, tsv -> tsv }
        .collect()

    GENERATE_SUMMARY(all_tsvs)

    // 6. Log outputs
    all_tsvs.subscribe { files ->
        def count = files instanceof List ? files.size() : 1
        log.info "✅ All ${count} samples annotated successfully!"
    }
}
