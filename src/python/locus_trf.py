import pytrf
import pysam

import sys

#Runs pyTRF on a single locus
#Usage: python locus_trf.py chr1:10000-10108 ref.fasta [flank] 

ref = pysam.FastaFile(sys.argv[2])

locus = sys.argv[1]
chrom = locus.split(':')[0]
start = int(locus.split(':')[1].split('-')[0])
end   = int(locus.split(':')[1].split('-')[1])

flank = 10000
if len(sys.argv) > 3:
    flank = int(sys.argv[3])

seq = ref.fetch(chrom, start-flank, end+flank)

trf_repeats = []
for repeat in pytrf.ATRFinder('seq', seq, min_motif=1, max_motif=100, min_identity=0.8):
    repeat    = repeat.as_string().split('\t')
    rep_start = int(repeat[1]) - 1
    rep_end   = int(repeat[2])
    motif     = repeat[3]
    motif_length = len(motif)

    rep_length = rep_end - rep_start
    rep_units  = rep_length // motif_length + 2

    print(chrom, start-flank+rep_start, start-flank+rep_end, motif, motif_length, rep_length, rep_units, sep='\t')
