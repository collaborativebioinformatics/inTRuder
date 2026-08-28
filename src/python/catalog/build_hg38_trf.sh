#!/usr/bin/env bash
# Build an hg38 tandem-repeat catalogue with Tandem Repeats Finder.
#
#   ./build_hg38_trf.sh [OUTDIR] [MINSCORE]
#
# Downloads the 24 primary hg38 chromosomes from UCSC, runs TRF on each in
# parallel, and converts the .dat output to a BED4 catalogue that the novelty
# screen reads with `--repeats bed=<path> --format bed`.
#
# Roughly 12 minutes wall clock on 10 cores, plus ~6 GB of scratch.
set -euo pipefail

OUTDIR="${1:-hg38_trf}"
MINSCORE="${2:-50}"          # TRF default is 50; the SV-side settings use 10
JOBS="${JOBS:-10}"           # match physical performance cores, not logical
PARAMS="2 5 5 80 10 ${MINSCORE} 500"

CHRS=$(printf 'chr%s ' 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 X Y)
mkdir -p "$OUTDIR"/{fa,dat}
cd "$OUTDIR"

command -v trf >/dev/null || { echo "trf not on PATH; see the README" >&2; exit 1; }

echo "[1/3] downloading chromosome FASTAs"
for c in $CHRS; do [ -f "fa/$c.fa" ] || echo "$c"; done \
  | xargs -P 6 -I{} sh -c \
    'curl -sSL --max-time 1800 -o fa/{}.fa.gz.part \
       "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes/{}.fa.gz" \
     && mv fa/{}.fa.gz.part fa/{}.fa.gz && gunzip -f fa/{}.fa.gz'

echo "[2/3] running TRF ($PARAMS) on $JOBS cores"
for c in $CHRS; do
  [ -f "dat/$c.fa.${PARAMS// /.}.dat" ] || echo "$c"
done | xargs -P "$JOBS" -I{} sh -c \
  "cd dat && trf ../fa/{}.fa $PARAMS -d -h -l 6 >/dev/null 2>&1 || true"

echo "[3/3] converting to BED4"
python3 "$(dirname "$0")/dat2bed.py" "hg38.trf.minscore${MINSCORE}.bed" dat/*.dat

echo "done: $OUTDIR/hg38.trf.minscore${MINSCORE}.bed"
