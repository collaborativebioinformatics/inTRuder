process TRF_TSV_TO_BED {
    // TRF results are chrom/pos only; bedtools needs a 3rd column.
    // Header is dropped because bedtools can't parse it as an interval.
    // convert TRF TSV into a zero-based half open BED file

    input:
    path query_tsv

    output:
    path "${query_tsv.baseName}.bed", emit: bed

    script:
    """
    awk 'BEGIN{FS=OFS="\\t"} NR>1 {\$2=\$2 OFS (\$2+1); print}' "${query_tsv}" > "${query_tsv.baseName}.bed"
    """

    stub:
    """
    touch "${query_tsv.baseName}.bed"
    """
}

process INTERSECT_BED {
    container "community.wave.seqera.io/library/bedtools:2.31.1--7c4ce4cb07c09ee4"

    input:
    path truth_bed // e.g. a bed from https://zenodo.org/records/11522276
    path query_bed // BED converted TRF output
    val min_overlap_b // Can be a float (e.g., 0.5) or null/1e-9

    output:
    path "trf_truth_intersections.bed.gz", emit: intersections

    script:
    def overlap_flag = min_overlap_b ? "-F ${min_overlap_b}" : ""
    """
    bedtools intersect \
        ${overlap_flag} \
        -a "${truth_bed}" \
        -b "${query_bed}" | gzip > trf_truth_intersections.bed.gz
    """

    stub:
    """
    touch trf_truth_intersections.bed.gz
    """
}

process CALCULATE_SENSITIVITY {
    container "community.wave.seqera.io/library/bedtools:2.31.1--7c4ce4cb07c09ee4"

    input:
    path truth_bed // e.g. a bed from https://zenodo.org/records/11522276
    path query_vcf // VCF from SV caller with insertions only
    val min_overlap_b // Can be a float (e.g., 0.5) or null/1e-9
    
    output:
    path "sensitivity_metrics.tsv", emit: metrics
    path "false_negatives.bed.gz" , emit: fn_bed

    script:
    def overlap_flag = (min_overlap_b && min_overlap_b != '1e-9') ? "-F ${min_overlap_b}" : ""
    """
    # 1. Total Truth Calls
    TOTAL_TRUTH=\$(zcat "${truth_bed}" | grep -v '^#' | wc -l)

    # 2. True Positives (-u)
    TRUE_POSITIVES=\$(bedtools intersect ${overlap_flag} -u -a "${truth_bed}" -b "${query_vcf}" | wc -l)

    # 3. False Negatives (-v) - also writing missed regions to compressed BED file
    bedtools intersect ${overlap_flag} -v -a "${truth_bed}" -b "${query_vcf}" | gzip > false_negatives.bed.gz
    FALSE_NEGATIVES=\$(zcat false_negatives.bed.gz | wc -l)

    # 4. Calculate Sensitivity: TP / (TP + FN)
    SENSITIVITY=\$(awk -v tp="\$TRUE_POSITIVES" -v total="\$TOTAL_TRUTH" 'BEGIN {
        if (total > 0) printf "%.4f", tp / total; else print "0.0000"
    }')

    # Output metrics to TSV
    echo -e "total_truth\ttrue_positives\tfalse_negatives\tsensitivity" > sensitivity_metrics.tsv
    echo -e "\${TOTAL_TRUTH}\t\${TRUE_POSITIVES}\t\${FALSE_NEGATIVES}\t\${SENSITIVITY}" >> sensitivity_metrics.tsv
    """

    stub:
    """
    touch sensitivity_metrics.tsv
    touch false_negatives.bed.gz
    """
}


process INTERSECT_REPEAT_CATALOG {
    tag "${tr_results.name}"
    container "community.wave.seqera.io/library/bedtools:2.31.1--7c4ce4cb07c09ee4"

    input:
    path tr_results
    path ground_truth

    output:
    path "intersections.bed.gz", emit: intersections_bed

    script:
    """
    # Create start-end coordinates by adding end pos (start + 1) and dropping header
    awk 'BEGIN{FS=OFS="\t"} NR>1 {$2=$2 OFS ($2+1); print}' "${tr_results}" > tr_results_positions.tsv

    # Extract required columns from ground truth BED
    zcat "${ground_truth}" | grep -v "^#" | cut -f1-4 | gzip > ground_truth_positions.bed.gz

    # Intersect ground truth insertion catalog with dataset
    bedtools intersect \\
        -a ground_truth_positions.bed.gz \\
        -b tr_results_positions.tsv \\
        -wb \\
        | cut -f5- \\
        | gzip > intersections.bed.gz
    """

    stub:
    """
    intersections.bed.gz
    """

}

process JOIN_REPEAT_CATALOG_HITS {
    tag "${tr_results.name}"
    // Container containing python and uv, or a custom python environment
    container "ghcr.io/astral-sh/uv:python3.11-bookworm" 

    input:
    path tr_results
    path intersections_bed

    output:
    path "HPRC_SV.survivor.ins.trf.in_catalog.tsv.gz", emit: catalog_tsv

    script:
    """
    uv run join-hits.py \\
        --query "${tr_results}" \\
        --hits "${intersections_bed}" \\
        --output HPRC_SV.survivor.ins.trf.in_catalog.tsv.gz
    """

    stub:
    """
    touch HPRC_SV.survivor.ins.trf.in_catalog.tsv.gz
    """
}
