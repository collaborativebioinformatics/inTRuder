import argparse
import zlib

import pysam


def main():
    parser = argparse.ArgumentParser(description="Annotate VCF with INFO fields\neg. python add_compresion.py -i HG00320.merged.sniffles.vcf -o HG00320.merged.sniffles_annotated.vcf")
    parser.add_argument("--input", "-i", required=True, help="Input VCF file")
    parser.add_argument("--output", "-o", required=True, help="Output annotated VCF file")
    args = parser.parse_args()

    in_vcf = args.input
    out_vcf = args.output 

    with pysam.VariantFile(in_vcf, "r") as vcf_in:
        header = vcf_in.header
        header.info.add("SVCOMP", number=".", type="String", description="SV insertion compressibility")
        with pysam.VariantFile(out_vcf, "w", header=header) as vcf_out:
            for record in vcf_in:
                alts_len = [len(x.encode('utf-8')) for x in record.alts]
                alts_comp = [len(zlib.compress(x.encode('utf-8'))) for x in record.alts]
                alts_ratio = [alts_len[x]/alts_comp[x] for x in range(len(record.alts))]
                record.info["SVCOMP"] = ",".join(str(x) for x in alts_ratio)
                vcf_out.write(record)

if __name__ == "__main__":
    main()
