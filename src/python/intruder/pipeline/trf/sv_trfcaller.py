#! /usr/bin/env python3

# Usage: python sv_trfcaller.py <input.vcf> <output.tsv>
# Usage with merged SV: python sv_trfcaller.py -i HPRC_SV.survivor.ins.vcf -o HPRC_SV.survivor.ins.trf.tsv
# Usage with example merged SV: python sv_trfcaller.py ../../data/sv_output/survivor_multisample_vcf/first_500_INS.vcf ../../data/sv_output/survivor_multisample_vcf/first_500_INS.trf.tsv

import argparse
import os
import sys
from contextlib import contextmanager

import pytrf
from cyvcf2 import VCF
import pysam
from tqdm import tqdm


def parse_args():
    parser = argparse.ArgumentParser(description="Run TRF on insertions from a VCF file and output results to a TSV file.")
    parser.add_argument("-i", "--input", help="Input VCF file containing structural variants.", required=True)
    parser.add_argument("-o", "--output", help="Output TSV file to write TRF results.", required=True)
    parser.add_argument("-t", "--threads", type=int, default=None, help="Number of threads to use for parallel processing.")

    sv_options = parser.add_argument_group("Options for structural variant filtering.")
    sv_options.add_argument("--min_sv_length", type=int, default=50, help="Minimum length of structural variants to consider (default: 50).")
    sv_options.add_argument("--max_sv_length", type=int, default=10000, help="Maximum length of structural variants to consider (default: 10000).")
    sv_options.add_argument("--min-depth",     type=int, default=25, help="The minimum coverage of the insertions SV.")
    sv_options.add_argument("--min-repeat-coverage", type=float, default=0.8, help="Minimum fraction of the insertion covered by the repeat "
                                                                                   "(rep_length / insert_size).")

    pytrf_options = parser.add_argument_group("pyTRF Options")
    pytrf_options.add_argument("--min_motif",      type=int,   default=1,     help="Minimum motif length for TRF (default: 1).")
    pytrf_options.add_argument("--max_motif",      type=int,   default=500,   help="Maximum motif length for TRF (default: 500).")
    pytrf_options.add_argument("--min_identity",   type=float, default=0.8,   help="Minimum identity for TRF (default: 0.8).")
    pytrf_options.add_argument("--min_rep_units",  type=int,   default=3,     help="Minimum repeat number for seed (default: 3).")
    pytrf_options.add_argument("--min_rep_length", type=int,   default=10,    help="Minimum length for seed (default: 10).")
    pytrf_options.add_argument("--max_rep_length", type=int,   default=10000, help="Maximum length for seed (default: 10000).")

    # flank_options = parser.add_argument_group("flank options")
    # flank_options.add_argument("--ref",   type=str, default=None, help="The path for the reference fasta to pull flanks if needed")
    # flank_options.add_argument("--flank", type=int, default=0,    help="The length of flank sequence to consider. If given -1, "
    #                                                                    "the length of flanks considered is equal to the insert size. Default: 0")
    
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


def run_trf_on_insertions(args, tidx=None, chunk_size=None):
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

    # Writing output to a temp file if running in parallel
    if tidx is not None:
        out = open(args.output + f'.{tidx}', 'w')
    else:
        out = open(args.output, 'w')

    if tidx is None or tidx == 0:
        print('chrom', 'pos', '_pos', 'SVID', 'insert_size', 'tot_cov', 'rep_start', 'rep_end', 'motif',
              'purity', 'motif_length', 'rep_length', 'rep_units', 'rep_cov', 'sample_info',
              sep='\t', file=out)

    samples = vcf.samples
    if tidx is not None and chunk_size is not None:
        start_var = tidx * chunk_size
        end_var   = start_var + chunk_size
        vcf = list(vcf)[start_var:end_var]

    for variant in tqdm(vcf, ncols=80, smoothing=0.1, unit='variants'):
        if variant.is_sv and variant.INFO.get("SVTYPE") == "INS":
            ID    = variant.ID
            REF   = variant.REF

            if variant.ALT is None or len(variant.ALT) == 0:
                continue
            DR    = variant.format('DR')    # depth of reads supporting the reference allele
            DV    = variant.format('DV')    # depth of reads supporting the variant allele

            sample_info = {}
            for s, sample in enumerate(samples):
                genotype = variant.genotypes[s]
                phased = genotype[-1]
                genotype = genotype[:-1]  # Remove the phased information
                if variant.gt_types[s] == 0:  # Homozygous reference
                    continue

                GT = '|'.join(str(g) for g in genotype) if phased else '/'.join(str(g) for g in genotype)
                var_depth = DV[s][0]
                ref_depth = DR[s][0]
                depth = var_depth + ref_depth

                if depth < args.min_depth:
                    continue
                for gt in genotype:
                    if gt == 0 or gt == '.' or gt == -1: continue  # Skip reference alleles

                    if gt not in sample_info:
                        sample_info[gt] = []
                    sample_info[gt].append(f'{sample}:{GT}:{depth}')

            ALTs   = variant.ALT
            ALT_repeats = []
            for i in range(len(ALTs)):
                gt = i + 1  # Genotype index for the ALT allele
                ALT = ALTs[i]
                # Put all ATRs in a list and return, each ATR in list has 16 columns including 
                # [sequence or chromosome name, start position, end position, motif sequence, motif length,
                # repeat number, repeat length, seed start position, seed end position, seed repeat, seed length,
                # extend matches, extend substitutions, extend insertions, extend deletions, extend identity]
                if len(ALT) < args.min_sv_length or len(ALT) > args.max_sv_length:
                    ALT_repeats.append(None)
                    continue

                repeats = []
                with suppress_pytrf_errors():
                    repeats = pytrf.ATRFinder(f'G{i}', ALT,
                                              min_motif=args.min_motif,
                                              max_motif=args.max_motif,
                                              min_identity=args.min_identity,
                                              min_seedrep=args.min_rep_units,
                                              min_seedlen=args.min_rep_length,
                                              max_extend=args.max_rep_length)

                    loci = []
                    rep_info = []
                    n_trf = 0
                    for repeat in repeats:
                        rep_start = repeat.start - 1 # pytrf returns 1-based coordinate
                        rep_end   = repeat.end
                        motif     = repeat.motif
                        motif_length = len(motif)

                        rep_length = rep_end - rep_start
                        rep_units  = rep_length // motif_length
                        purity     = float(repeat.identity)/100
                        if purity < args.min_identity or rep_units < args.min_rep_units or rep_length < args.min_rep_length:
                            continue

                        rep_cov    = round((rep_length / len(ALT))*100, 3)

                        loci.append((rep_start, rep_end))
                        rep_info.append([rep_start, rep_end, motif, motif_length, rep_units, rep_length, round(purity, 3), rep_cov])

                        n_trf += 1
                    if n_trf == 0: continue

                    sreps = sorted(loci, key=lambda x: x[0])
                    tot_cov = sreps[0][1] - sreps[0][0]
                    prev_end = sreps[0][1]
                    j = 0
                    while j < len(sreps) - 1:
                        if sreps[j+1][0] <= prev_end:
                            tot_cov += sreps[j+1][1] - prev_end
                        else:
                            tot_cov += sreps[j+1][1] - sreps[j+1][0]
                        prev_end = sreps[j+1][1]
                        j += 1
                    if tot_cov < args.min_repeat_coverage * len(ALT):
                        continue
                    tot_cov = round((tot_cov / len(ALT))*100, 3)

                    for rep in rep_info:
                        rep_start, rep_end, motif, motif_length, rep_units, rep_length, purity, rep_cov = rep
                        for gt in sample_info:
                            sample_str = ','.join(sample_info[gt])
                            if sample_str:
                                print(variant.CHROM, variant.POS - 1, variant.POS, ID, len(ALT), tot_cov,
                                    rep_start, rep_end, motif, purity, motif_length,
                                    rep_length, rep_units, rep_cov, sample_str,
                                    sep='\t', file=out)

    out.close()


def main():
    args = parse_args()
    input_vcf = args.input
    output_tsv = args.output

    if not input_vcf or not output_tsv:
        print("Error: Both input VCF and output TSV file paths are required.")
        sys.exit(1)

    # if args.flank != 0 and args.ref is None:
    #     print("Reference fasta is not provided for considering the flank.")
    #     sys.exit(1)

    if args.threads is not None:
        num_vars = sum(1 for _ in VCF(input_vcf))

        chunk_size = max(1, num_vars // args.threads)
        chunks = []
        for tidx in range(args.threads):
            chunks.append(chunk_size)
            if tidx == args.threads - 1:
                # Last thread takes the remaining variants
                chunks[-1] += num_vars % args.threads

        from multiprocessing import Pool
        with Pool(processes=args.threads) as pool:
            pool.starmap(run_trf_on_insertions, [(args, tidx, chunk_size) for tidx in range(args.threads)])
        out = open(args.output, 'w')
        for tidx in range(args.threads):
            with open(args.output + f'.{tidx}', 'r') as fh:
                for line in fh:
                    out.write(line)
            os.remove(args.output + f'.{tidx}')
        out.close()
    else:
        run_trf_on_insertions(args)


if __name__ == "__main__":
    main()
