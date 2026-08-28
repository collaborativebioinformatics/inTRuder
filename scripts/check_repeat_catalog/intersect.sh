#!/usr/bin/env bash

# input files
TR_RESULTS_FILE="Data/HPRC_SV.survivor.ins.trf.tsv"
TR_RESULTS_FILE_2="Data/HPRC_SV.survivor.ins.trf.start-end.tsv"
GROUND_TRUTH_FILE="Data/validation/hg38.v1.bed.gz"
GROUND_TRUTH_FILE_2="Data/validation/hg38.v1.positions.bed.gz"
INTERSECTIONS_FILE="Data/intersections.bed.gz"

OUTPUT="Data/HPRC_SV.survivor.ins.trf.in_catalog.tsv.gz"

echo "INPUT: ${TR_RESULTS_FILE}"
echo "INPUT: ${GROUND_TRUTH_FILE}"
echo "OUTPUT: ${OUTPUT}"
echo ""

# add pseudo-end coordinate to internal results (header dropped; bedtools can't parse it)
awk 'BEGIN{FS=OFS="\t"} NR>1 {$2=$2 OFS ($2+1); print}' $TR_RESULTS_FILE > $TR_RESULTS_FILE_2

# only use specific colums in ground truth set
if [[ -f "$GROUND_TRUTH_FILE_2" ]]; then
	echo "Reusing existing ground truth subset: ${GROUND_TRUTH_FILE_2}"
	echo ""
else
	gzcat $GROUND_TRUTH_FILE | grep -v "^#" | cut -f1-4 | gzip > $GROUND_TRUTH_FILE_2
fi

# intersect ground truth insertion catalog with hackathon program
echo "Intersecting TSV with ground truth..."
bedtools intersect -a "$GROUND_TRUTH_FILE_2" -b "$TR_RESULTS_FILE_2" -wb | cut -f5- | gzip > "$INTERSECTIONS_FILE"
echo "Finished intersecting TSV with ground truth!"
echo ""

# join original tsv with hits in the catalog
echo "Joining original file with intersections to label which motifs are in or out of catalog."
uv run join-hits --query $TR_RESULTS_FILE --hits $INTERSECTIONS_FILE --output $OUTPUT
echo "Finished. Final output file is in $OUTPUT"