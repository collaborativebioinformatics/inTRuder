process INTERSECT_BED {
    container "community.wave.seqera.io/library/bedtools:2.31.1--7c4ce4cb07c09ee4"

    input:
    path truth_bed // e.g. a bed from https://zenodo.org/records/11522276
    path query_vcf // VCF from SV caller with insertions only
    val min_overlap_b // Can be a float (e.g., 0.5) or null/1e-9

    output:
    path "tr_intersections.bed.gz", emit: intersections

    script:
    def overlap_flag = min_overlap_b ? "-F ${min_overlap_b}" : ""
    """
    bedtools intersect \
        ${overlap_flag} \
        -a "${truth_bed}" \
        -b "${query_vcf}" | gzip > tr_intersections.bed.gz
    """

    stub:
    """
    tr_intersections.bed.gz
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