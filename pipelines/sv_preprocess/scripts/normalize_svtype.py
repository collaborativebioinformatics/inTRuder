#!/usr/bin/env python3
import argparse
import gzip

ap = argparse.ArgumentParser()
ap.add_argument('--input', required=True)
ap.add_argument('--output', required=True)
a = ap.parse_args()
opener = gzip.open if a.input.endswith('.gz') else open
converted = 0
with opener(a.input, 'rt', encoding='utf-8', errors='replace') as src, open(a.output, 'w', encoding='utf-8') as dst:
    for line in src:
        if line.startswith('#'):
            dst.write(line); continue
        f = line.rstrip('\n').split('\t')
        if len(f) >= 8:
            info = f[7].split(';')
            svtype = next((x.split('=', 1)[1] for x in info if x.startswith('SVTYPE=')), None)
            if svtype == 'INS':
                info = ['SVTYPE=DUP' if x.startswith('SVTYPE=') else x for x in info]
                if not any(x.startswith('ORIG_SVTYPE=') for x in info): info.append('ORIG_SVTYPE=INS')
                f[7] = ';'.join(info)
                if f[4] == '<INS>': f[4] = '<DUP>'
                converted += 1
        dst.write('\t'.join(f) + '\n')
print(f'Converted INS to DUP: {converted}')