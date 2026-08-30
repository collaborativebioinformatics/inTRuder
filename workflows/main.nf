#!/usr/bin/env nextflow

// ---------------------------------------------------------------------
// PARAMETERS
// ---------------------------------------------------------------------
// Architecture:
//
//   01 Find TRs (always runs)
//        |
//        +--> 02 Novelty + Filtering  (optional, --run_novelty)
//        +--> 03 Annotation           (optional, --run_annotation)
//        |
//   05 Merge (only runs if 02 or 03 ran) - joins 01 + whichever ran,
//        keyed on CHROM_POS_END_SVTYPE_SVLEN
//        |
//   FINALIZE (always runs) - copies the true final output to
//        results/final/final_output.tsv
//
//   04 Validation (optional, --run_validation) - INDEPENDENT of the
//        above. It validates the PIPELINE'S OVERALL ACCURACY against a
//        known truth set (an aggregate sensitivity/recall score), not
//        a per-locus property - so it does NOT feed MERGE, and running
//        it does not trigger MERGE/FINALIZE on its own. Published as
//        its own standalone QC report.

params.input_vcf   = null
params.run_novelty  = false
params.run_annotation =  false
params.run_validation = false

// TODO: set the actual path to your TR catalogue BED file (needed by
// stage 04 - Validation)
params.tr_catalogue_bed = null
params.min_overlap_b = null

params.default_vcf_path = null

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
// 03 - ANNOTATION (optional) - PLACEHOLDER
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
// 05 - MERGE (01+02+03 ONLY - validation removed, it's independent
// ---------------------------------------------------------------------
process MERGE {
    publishDir "results/05_merge", mode: "copy"

    input:
    path trf_tsv, stageAs: 'find_trs_input.tsv'
    path novelty_tsv, stageAs: 'novelty_input.tsv'
    path annotation_tsv, stageAs: 'annotation_input.tsv'

    output:
    path "merged_output.tsv"

    script:
    """
    echo "TODO: real merge script goes here, keyed on CHROM_POS_END_SVTYPE_SVLEN" > merged_output.tsv
    echo "01 (always): ${trf_tsv}"
    echo "02 (novelty): ${novelty_tsv}"
    echo "03 (annotation): ${annotation_tsv}"
    """
}


// ---------------------------------------------------------------------
// FINALIZE (always runs)
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
    FILTER_BY_COVERAGE(FIND_NOVEL.out)
    novelty_out = FILTER_BY_COVERAGE.out.filtered
    } else {
        novelty_out = Channel.fromPath("${projectDir}/assets/NO_FILE")
    }

    // --- 03: optional, branches off the ORIGINAL vcf, not 01's output ---
    if (params.run_annotation) {
        ANNOTATE(vcf_ch)
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
        TRF_TO_BED(FIND_TRS.out)
        CALCULATE_SENSITIVITY(truth_bed_ch, TRF_TO_BED.out, params.min_overlap_b)
    }

    // --- 05: FINALIZE: only 02/03 decide whether MERGE runs ---
    if (params.run_novelty || params.run_annotation) {
        MERGE(FIND_TRS.out, novelty_out, annotation_out)
        FINALIZE(MERGE.out)
    } else {
        FINALIZE(FIND_TRS.out)
    }
}
