#!/usr/bin/env python3
import argparse
import gzip

ap = argparse.ArgumentParser(description='Normalize SVTYPE=INS to DUP for AnnotSV compatibility')
ap.add_argument('--input', required=True, help='Input VCF (.vcf or .vcf.gz)')
ap.add_argument('--output', required=True, help='Output VCF')
args = ap.parse_args()

opener = gzip.open if args.input.endswith('.gz') else open
converted = 0

with opener(args.input, 'rt', encoding='utf-8', errors='replace') as src, open(args.output, 'w', encoding='utf-8') as dst:
    for line in src:
        if line.startswith('#'):
            dst.write(line)
            continue
        fields = line.rstrip('\n').split('\t')
        if len(fields) >= 8:
            info = fields[7].split(';')
            svtype = next((x.split('=', 1)[1] for x in info if x.startswith('SVTYPE=')), None)
            if svtype == 'INS':
                info = ['SVTYPE=DUP' if x.startswith('SVTYPE=') else x for x in info]
                if not any(x.startswith('ORIG_SVTYPE=') for x in info):
                    info.append('ORIG_SVTYPE=INS')
                fields[7] = ';'.join(info)
                if fields[4] == '<INS>':
                    fields[4] = '<DUP>'
                converted += 1
        dst.write('\t'.join(fields) + '\n')

print(f'Converted INS to DUP: {converted}')

