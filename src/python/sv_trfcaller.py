#! /usr/bin/env python3

# Usage: python sv_trfcaller.py <input.vcf> <output.tsv>
# Usage with merged SV: python sv_trfcaller.py -i HPRC_SV.survivor.ins.vcf -o HPRC_SV.survivor.ins.trf.tsv
# Usage with example merged SV: python sv_trfcaller.py ../../data/sv_output/survivor_multisample_vcf/first_500_INS.vcf ../../data/sv_output/survivor_multisample_vcf/first_500_INS.trf.tsv

import sys
import os

import pytrf
import numpy as np

from cyvcf2 import VCF
from tqdm   import tqdm
from contextlib import contextmanager

import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="Run TRF on insertions from a VCF file and output results to a TSV file.")
    parser.add_argument("-i", "--input", help="Input VCF file containing structural variants.", required=True)
    parser.add_argument("-o", "--output", help="Output TSV file to write TRF results.", required=True)

    sv_options = parser.add_argument_group("SV Options")
    sv_options.add_argument("--min_sv_length", type=int, default=50, help="Minimum length of structural variants to consider (default: 50).")
    sv_options.add_argument("--max_sv_length", type=int, default=10000, help="Maximum length of structural variants to consider (default: 10000).")

    pytrf_options = parser.add_argument_group("pyTRF Options")
    pytrf_options.add_argument("--min_motif", type=int, default=1, help="Minimum motif length for TRF (default: 1).")
    pytrf_options.add_argument("--max_motif", type=int, default=500, help="Maximum motif length for TRF (default: 500).")
    pytrf_options.add_argument("--min_identity", type=float, default=0.8, help="Minimum identity for TRF (default: 0.8).")
    pytrf_options.add_argument("--min_rep_units", type=int, default=3, help="Minimum repeat number for seed (default: 3).")
    pytrf_options.add_argument("--min_rep_length", type=int, default=10, help="Minimum length for seed (default: 10).")
    pytrf_options.add_argument("--max_rep_length", type=int, default=10000, help="Maximum length for seed (default: 10000).")
    
    return parser.parse_args()


@contextmanager
def suppress_pytrf_errors():
    """
    Suppress output from pysam (stdout and stderr) within the context.
    This is useful when calling functions that may produce unwanted output to the console.
    Usage:
        with suppress_pysam_output():
            # code that calls pysam functions
    """
    # Save original file descriptors
    original_stdout_fd = sys.stdout.fileno()
    original_stderr_fd = sys.stderr.fileno()

    # Duplicate original file descriptors so they can be restored later
    save_stdout_fd = os.dup(original_stdout_fd)
    save_stderr_fd = os.dup(original_stderr_fd)

    # Open devnull
    devnull_fd = os.open(os.devnull, os.O_WRONLY)

    # Flush standard Python buffers
    sys.stdout.flush()
    sys.stderr.flush()

    # Overwrite original descriptors with devnull
    os.dup2(devnull_fd, original_stdout_fd)
    os.dup2(devnull_fd, original_stderr_fd)

    # Close the extra devnull handle
    os.close(devnull_fd)

    try:
        yield
    finally:
        # Flush again before restoring
        sys.stdout.flush()
        sys.stderr.flush()

        # Restore original descriptors
        os.dup2(save_stdout_fd, original_stdout_fd)
        os.dup2(save_stderr_fd, original_stderr_fd)

        # Close duplicated handles
        os.close(save_stdout_fd)
        os.close(save_stderr_fd)

def run_trf_on_insertions(args):
    """
    Run tandem repeat calling on insertion variants from an input VCF and write results to a TSV file.

    Args:
        args: Parsed command-line arguments with `input`, `output`, `min_sv_length`, and
            `max_sv_length` attributes. The input VCF is expected to contain structural
            variant records with `SVTYPE=INS`, an `SVLEN` INFO field, and `DR`/`DV`
            sample FORMAT fields used to report read support.

    Output:
        Writes a tab-separated file at `args.output` containing one row per detected repeat
        call, including chromosome, insertion coordinate, variant ID, depth, insertion
        size, sample, repeat boundaries, motif, purity, motif length, repeat length,
        and repeat unit count.
    """
    vcf = VCF(args.input)
    out = open(args.output, 'w')
    print('chrom', 'ins_coord', 'SVID', 'depth', 'insert_size', 'sample', 'allele', 'rep_start', 'rep_end', 'motif', 'purity',
          'motif_length', 'rep_length', 'rep_units', sep='\t', file=out)
    samples = vcf.samples
    for variant in tqdm(vcf, ncols=80, smoothing=0.1, unit='variants'):
        if variant.is_sv and variant.INFO.get("SVTYPE") == "INS":
            ID    = variant.ID
            REF   = variant.REF
            if variant.ALT is None or len(variant.ALT) == 0:
                continue
            ALT   = variant.ALT[0]
            if REF == ALT[:len(variant.REF)]:  # Get the inserted sequence
                ALT = ALT[len(variant.REF):]
            DR    = variant.format('DR')    # depth of reads supporting the reference allele
            DV    = variant.format('DV')    # depth of reads supporting the variant allele
            if variant.INFO.get("SVLEN") is None:
                continue
            LEN   = variant.INFO.get("SVLEN")  # length of the insertion
            if LEN < args.min_sv_length or LEN > args.max_sv_length:
                continue

            for s, sample in enumerate(samples):
                genotype = variant.genotypes[s]
                for gt in genotype[:2]:
                    if gt == 0 or gt == '.' or gt == -1: continue  # Skip reference alleles
                    var_depth = DV[s][0]
                    ref_depth = DR[s][0]

                    n_trf = 0
                    trf_repeats    = []

                    with suppress_pytrf_errors():
                        for repeat in pytrf.ATRFinder(sample, ALT, min_motif=args.min_motif,
                                                                max_motif=args.max_motif,
                                                                min_identity=args.min_identity,
                                                                min_seedrep=args.min_rep_units,
                                                                min_seedlen=args.min_rep_length,
                                                                max_extend=args.max_rep_length):

                            rep_start = repeat.start - 1
                            rep_end   = repeat.end
                            motif     = repeat.motif
                            motif_length = len(motif)

                            rep_length = rep_end - rep_start
                            rep_units  = rep_length // motif_length
                            purity       = float(repeat.identity)/100

                            trf_repeats.append([variant.CHROM, variant.POS, ID, f'{var_depth},{ref_depth}', LEN, sample, gt, rep_start, rep_end, motif, round(purity, 3), motif_length, rep_length, rep_units])
                            n_trf += 1

                    for rep in trf_repeats:
                        print(*rep, sep='\t', file=out)

    out.close()


if __name__ == "__main__":
    args = parse_args()
    input_vcf = args.input
    output_tsv = args.output

    if not input_vcf or not output_tsv:
        print("Error: Both input VCF and output TSV file paths are required.")
        sys.exit(1)

    run_trf_on_insertions(args)