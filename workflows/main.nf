#!/usr/bin/env nextflow

// ---------------------------------------------------------------------
// PARAMETERS
// ---------------------------------------------------------------------
// Architecture (matches the DNAnexus applet structure):
//
//   01 Find TRs (always runs)
//        |
//        +--> 02 Novelty     (optional, --run_novelty)
//        +--> 03 Annotation  (optional, --run_annotation) - takes the
//        |                    original VCF/BED, not 01's output
//        +--> 04 Validation  (optional, --run_validation) - takes 01's
//                             output + a TR catalogue BED
//        |
//   05 Merge (always runs) - joins 01 + whichever of 02/03/04 ran,
//        keyed on CHROM_POS_END_SVTYPE_SVLEN

params.input_vcf   = null
params.run_novelty  = false
params.run_annotation =  false
params.run_validation = false

// TODO: set the actual path to your TR catalogue BED file (needed by
// stage 04 - Validation)
params.tr_catalogue_bed = null
params.default_vcf_path = "${projectDir}/../data/HPRC_SV.survivor.ins.vcf"


// ---------------------------------------------------------------------
// 01 - FIND TRS (baseline, always runs)
// ---------------------------------------------------------------------
process FIND_TRS {

    // publishDir copies this process's output to a results folder,
    // so it's not just buried in Nextflow's internal work/ directory
    // TODO: change to output in corresponding parent directory
    publishDir "results/01_find_trs", mode: "copy"

    input:
    path vcf_file

    output:
    path "trf_output.tsv"

    script:
    // Calls the copy of sv_trfcaller.py baked into the Docker image at
    // build time (see Dockerfile's COPY instruction) - NOT the host
    // filesystem copy in src/python/. This only resolves correctly
    // when run with -profile docker.
    //
    // sv_trfcaller.py takes POSITIONAL args, not flags:
    //   python sv_trfcaller.py <input.vcf> <output.tsv>
    """
    python3 /opt/scripts/sv_trfcaller.py ${vcf_file} trf_output.tsv
    """
}

// ---------------------------------------------------------------------
// 02 - NOVELTY (optional)
// ---------------------------------------------------------------------
process FIND_NOVEL {
    // TODO: change to output in corresponding parent directory
    publishDir "results/02_novelty", mode: "copy"

    input:
    path trf_tsv

    output:
    path "novelty_output.tsv"

     script:
    // --min-rep-units 3 matches the standard TR definition floor
    // discussed earlier (AJHG catalog: >=3 repeat units to count as a
    // real TR). Deliberately NOT setting --min-purity: interrupted /
    // imperfect repeats are real biology, not noise - a hard purity
    // gate would bias against exactly the messier, more-likely-novel
    // loci this pipeline is hunting for. Not using --drop-filtered
    // either, so nothing is silently discarded - every row is kept and
    // tagged, with filtering decisions left to a downstream step.
    """
    uv run novelty --platform ucsc,trexplorer annotate ${trf_tsv} novelty_output.tsv \
        --min-rep-units 3
    """
}

// ---------------------------------------------------------------------
// 03a - PREPROCESS (optional, real) - converts SVTYPE=INS to SVTYPE=DUP
// so the (currently placeholder) AnnotSV step will eventually be able
// to handle our insertion-only data correctly. Calls the annotation
// team's own pipeline (pipelines/sv_preprocess/main.nf) as a separate
// nextflow run, rather than importing its internals directly - avoids
// depending on their file's use of `projectDir` (which would resolve
// incorrectly if their process were pulled into our file via include).
//
// NOT containerized (see nextflow.config withName block) - this
// process's job is just launching another nextflow run on the host;
// containerizing it would mean Docker-in-Docker, which we don't need.
// ---------------------------------------------------------------------
process PREPROCESS {
    publishDir "results/03_annotation/preprocess", mode: "copy"

    input:
    path vcf_file

    output:
    path "*.preprocessed.vcf"

    script:
    """
    python3 /opt/scripts/normalize_svtype.py \
        --input ${vcf_file} \
        --output ${vcf_file.simpleName}.preprocessed.vcf
    """
}


// ---------------------------------------------------------------------
// 03b - ANNOTATION (optional) - PLACEHOLDER
// Takes the ORIGINAL vcf (or a BED derived from it) - not 01's output.
// TODO: replace with the real AnnotSV command once ready.
// ---------------------------------------------------------------------
process ANNOTATE {
    // TODO: change to output in corresponding parent directory
    publishDir "results/03_annotation", mode: "copy"

    input:
    path vcf_or_bed

    output:
    path "annotation_output.tsv"

    script:
    """
    echo "TODO: real AnnotSV command goes here" > annotation_output.tsv
    """
}


// ---------------------------------------------------------------------
// 04 - VALIDATION (optional) - PLACEHOLDER
// Takes 01's output + a TR catalogue BED file.
// TODO: replace with the real python3/R validation script once ready.
// ---------------------------------------------------------------------
process VALIDATE {
    // TODO: change to output in corresponding parent directory
    publishDir "results/04_validation", mode: "copy"

    input:
    path trf_tsv
    path catalogue_bed

    output:
    path "validation_output.tsv"

    script:
    """
    echo "TODO: real validation script goes here" > validation_output.tsv
    """
}


// ---------------------------------------------------------------------
// 05 - MERGE (only runs if at least one of 02/03/04 ran) - PLACEHOLDER
// Joins 01's output with whichever of 02/03/04 actually ran, on
// CHROM_POS_END_SVTYPE_SVLEN.
//
/// Optional inputs use a sentinel file ("NO_FILE") when a branch didn't
// run. Since MULTIPLE optional inputs can simultaneously be that same
// sentinel file, each input is explicitly renamed during staging via
// `stageAs` - otherwise Nextflow can't tell two identically-named
// "NO_FILE" inputs apart and errors with a file name collision.
// TODO: replace with the real merge script once ready.
// ---------------------------------------------------------------------
process MERGE {
    publishDir "results/05_merge", mode: "copy"

    input:
    path trf_tsv, stageAs: 'find_trs_input.tsv'
    path novelty_tsv, stageAs: 'novelty_input.tsv'
    path annotation_tsv, stageAs: 'annotation_input.tsv'
    path validation_tsv, stageAs: 'validation_input.tsv'

    output:
    path "merged_output.tsv"

    script:
    """
    echo "TODO: real merge script goes here, keyed on CHROM_POS_END_SVTYPE_SVLEN" > merged_output.tsv
    echo "01 (always): ${trf_tsv}"
    echo "02 (novelty): ${novelty_tsv}"
    echo "03 (annotation): ${annotation_tsv}"
    echo "04 (validation): ${validation_tsv}"
    """
}



// ---------------------------------------------------------------------
// FINALIZE (always runs)
// Copies whichever result is the true final output - either 01 alone
// (if no optional stage ran) or 05's merge (if one or more did) - to
// one single, predictable location: results/final/final_output.tsv.
// ---------------------------------------------------------------------
process FINALIZE {
    publishDir "results/final", mode: "copy"

    input:
    path result_file

    output:
    path "final_output.tsv"

    script:
    """
    cp ${result_file} final_output.tsv
    """
}


// ---------------------------------------------------------------------
// WORKFLOW: wires everything together, including the input-handling
// branch and the find_novel decision point
// ---------------------------------------------------------------------
workflow {

    // --- Input handling branch ---
    if (params.input_vcf) {
        // User supplied their own VCF - use it directly
        vcf_ch = Channel.fromPath(params.input_vcf)
    } else {
        // No input given -use default
        vcf_ch = Channel.fromPath(params.default_vcf_path)
    }

    // --- Baseline: find TRs in the insertions (always runs)---
    FIND_TRS(vcf_ch)

    // --- 02: optional, branches off 01's output ---
    if (params.run_novelty) {
    FIND_NOVEL(FIND_TRS.out)
    novelty_out = FIND_NOVEL.out
    } else {
        novelty_out = Channel.fromPath("${projectDir}/assets/NO_FILE")
    }

    // --- 03: optional, branches off the ORIGINAL vcf, not 01's output ---
    if (params.run_annotation) {
        PREPROCESS(vcf_ch)
        ANNOTATE(PREPROCESS.out)
        annotation_out = ANNOTATE.out
    } else {
        annotation_out = Channel.fromPath("${projectDir}/assets/NO_FILE")
    }

    // --- 04: optional, branches off 01's output + a catalogue BED ---
    if (params.run_validation) {
        if (!params.tr_catalogue_bed) {
            error "run_validation=true requires --tr_catalogue_bed to be set"
        }
        catalogue_ch = Channel.fromPath(params.tr_catalogue_bed)
        VALIDATE(FIND_TRS.out, catalogue_ch)
        validation_out = VALIDATE.out
    } else {
        validation_out = Channel.fromPath("${projectDir}/assets/NO_FILE")
    }

    // --- 05: only runs if at least one optional stage (02/03/04) ran -
    // otherwise there's nothing to merge beyond 01 alone, and running
    // MERGE would just be wasted work.
    if (params.run_novelty || params.run_annotation || params.run_validation) {
        MERGE(FIND_TRS.out, novelty_out, annotation_out, validation_out)
        FINALIZE(MERGE.out)
    } else {
        FINALIZE(FIND_TRS.out)
    }
}
