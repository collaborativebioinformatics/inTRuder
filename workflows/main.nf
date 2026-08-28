#!/usr/bin/env nextflow

// ---------------------------------------------------------------------
// PARAMETERS
// ---------------------------------------------------------------------

params.input_vcf   = null
params.run_novelty  = false
params.run_annotation =  false
params.run_validation = false
params.run_compressibility = false

// TODO: set the actual path to your TR catalogue BED file (needed by
// stage 04 - Validation)
params.tr_catalogue_bed = null
params.min_overlap_b = null

params.default_vcf_path = params.default_vcf_path ?: "${projectDir}/../data/sv_output/sniffles/first_500_INS.vcf"


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
    python3 /opt/scripts/sv_trfcaller.py -i ${vcf_file} -o trf_output.tsv
    """
}

// ---------------------------------------------------------------------
// 01.1 - Add alt allele sequence compressibility score (optional)
// ---------------------------------------------------------------------
process ANNOTATE_COMPRESSIBILITY {

    // publishDir copies this process's output to a results folder,
    // so it's not just buried in Nextflow's internal work/ directory
    // TODO: change to output in corresponding parent directory
    publishDir "results/011_annotate_compressibility", mode: "copy"

    input:
    path vcf_file

    output:
    path "*_comp.vcf"

    script:
    // Calls the `compression` console script the same way FIND_NOVEL calls
    // `uv run novelty`. The annotator itself came in with #81 and currently
    // sits at src/python/intruder/compression/add_compression.py; a
    // follow-up moves it to intruder/pipeline/compression/annotate.py and
    // registers it in [project.scripts]. Targeting the console script rather
    // than a file path means that move does not break this process.
    //
    // Nothing is read from the host source tree, so this resolves from
    // whatever directory Nextflow stages the task in - the old relative
    // "../src/python/..." path never could have.
    //
    // simpleName strips the directory and every extension, so
    // sample.merged.vcf -> sample_comp.vcf, matching the output glob below.
    // Bash-style ${var%.vcf} does NOT work here: Nextflow interpolates
    // ${...} as Groovy before the shell ever sees it.
    """
    uv run compression -i ${vcf_file} -o ${vcf_file.simpleName}_comp.vcf
    """
}

// ---------------------------------------------------------------------
// 02A - NOVELTY (optional)
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
// 02B - FILTER_BY_COVERAGE
// Filters out SVs where less than 80% of the insertion is covered by
// tandem repeat (using novelty's insertion_purity column, 0-1 scale).
// Always runs right after 02A whenever novelty is on - no separate flag.
// ---------------------------------------------------------------------
process FILTER_BY_COVERAGE {
    publishDir "results/02_novelty", mode: "copy"

    input:
    path novelty_tsv

    output:
    path "novelty_filtered.tsv", emit: filtered
    path "novelty_filtered.stats.tsv", emit: stats

    script:
    """
    python3 /opt/scripts/filter_ins_trf.py \
        -i ${novelty_tsv} \
        -o novelty_filtered.tsv \
        -s novelty_filtered.stats.tsv \
        --min-repeat-coverage 0.8 \
        --min-depth 0
    """
}


// ---------------------------------------------------------------------
// 03A - PREPROCESS (optional, real) - converts SVTYPE=INS to SVTYPE=DUP
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
// 03B - ANNOTATION (optional) - PLACEHOLDER
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
// 04a - TRF_TO_BED
// Converts FIND_TRS's TSV into a clean 3-column BED for bedtools.
// Used by the aggregate sensitivity check below.
// ---------------------------------------------------------------------
process TRF_TO_BED {
    input:
    path trf_tsv
    output:
    path "trf_calls.bed"
    script:
    """
    python3 -c "
import pandas as pd
df = pd.read_csv('${trf_tsv}', sep='\\t')
bed = df[['chrom', 'ins_coord']].drop_duplicates().copy()
bed['start'] = bed['ins_coord'] - 1
bed['end'] = bed['ins_coord']
bed[['chrom', 'start', 'end']].sort_values(['chrom', 'start']).to_csv(
    'trf_calls.bed', sep='\\t', header=False, index=False
)
"
    """
}


// ---------------------------------------------------------------------
// 04b - CALCULATE_SENSITIVITY (teammate's process, unmodified)
// Aggregate QC report, published standalone. NOT fed into MERGE - it's
// a single summary row, not a per-row column.
// ---------------------------------------------------------------------
process CALCULATE_SENSITIVITY {
    container "community.wave.seqera.io/library/bedtools:2.31.1--7c4ce4cb07c09ee4"

    publishDir "results/04_validation", mode: "copy"

    input:
    path truth_bed
    path query_vcf
    val min_overlap_b

    output:
    path "sensitivity_metrics.tsv", emit: metrics
    path "false_negatives.bed.gz" , emit: fn_bed

    script:
    def overlap_flag = (min_overlap_b && min_overlap_b != '1e-9') ? "-F ${min_overlap_b}" : ""
    """
    TOTAL_TRUTH=\$(zcat "${truth_bed}" 2>/dev/null | grep -v '^#' | wc -l || grep -v '^#' "${truth_bed}" | wc -l)
    TRUE_POSITIVES=\$(bedtools intersect ${overlap_flag} -u -a "${truth_bed}" -b "${query_vcf}" | wc -l)
    bedtools intersect ${overlap_flag} -v -a "${truth_bed}" -b "${query_vcf}" | gzip > false_negatives.bed.gz
    FALSE_NEGATIVES=\$(zcat false_negatives.bed.gz | wc -l)
    SENSITIVITY=\$(awk -v tp="\$TRUE_POSITIVES" -v total="\$TOTAL_TRUTH" 'BEGIN {
        if (total > 0) printf "%.4f", tp / total; else print "0.0000"
    }')
    echo -e "total_truth\ttrue_positives\tfalse_negatives\tsensitivity" > sensitivity_metrics.tsv
    echo -e "\${TOTAL_TRUTH}\t\${TRUE_POSITIVES}\t\${FALSE_NEGATIVES}\t\${SENSITIVITY}" >> sensitivity_metrics.tsv
    """

    stub:
    """
    touch sensitivity_metrics.tsv
    touch false_negatives.bed.gz
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

    // --- Optional compressibility annotation ---
    if (params.run_compressibility) {
        ANNOTATE_COMPRESSIBILITY(vcf_ch)
        vcf_ch = ANNOTATE_COMPRESSIBILITY.out
    }
    else {
        vcf_ch = vcf_ch
    }
    
    // --- Baseline: find TRs in the insertions (always runs)---
    FIND_TRS(vcf_ch)

    // --- 02: optional, branches off 01's output ---
    if (params.run_novelty) {
    FIND_NOVEL(FIND_TRS.out)
    FILTER_BY_COVERAGE(FIND_NOVEL.out)
    novelty_out = FILTER_BY_COVERAGE.out.filtered
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
        truth_bed_ch = Channel.fromPath(params.tr_catalogue_bed)
         // TODO: once teammate's reformatted TSV (with in_catalog logic)
        // is ready, wire it in here as validation_out
        validation_out = Channel.fromPath("${projectDir}/assets/NO_FILE")

        // Aggregate QC report - independent of the reformatting work,
        // safe to wire in now
        TRF_TO_BED(FIND_TRS.out)
        CALCULATE_SENSITIVITY(truth_bed_ch, TRF_TO_BED.out, params.min_overlap_b)
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
