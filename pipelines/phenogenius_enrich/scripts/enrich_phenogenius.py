#!/usr/bin/env python3
import argparse
import csv
import re
import subprocess
import tempfile
from pathlib import Path


def split_genes(value):
    return [x for x in re.split(r'[;,|]', value or '') if x and x not in {'.', 'NA'}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--hpo', required=True)
    ap.add_argument('--phenogenius-cli', required=True)
    ap.add_argument('--resource-dir', required=True)
    ap.add_argument('--python', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    with open(args.input, newline='') as fh:
        reader = csv.DictReader(fh, delimiter='\t')
        if not reader.fieldnames or 'NCBI_gene_ID' not in reader.fieldnames:
            raise SystemExit('Input TSV must contain an NCBI_gene_ID column')
        rows = list(reader)
        fields = list(reader.fieldnames)

    gene_ids = sorted({g for row in rows for g in split_genes(row.get('NCBI_gene_ID', ''))}, key=lambda x: int(x) if x.isdigit() else x)
    print(f'Unique NCBI genes: {len(gene_ids)}')
    with tempfile.TemporaryDirectory(prefix='phenogenius-') as td:
        raw = Path(td) / 'phenogenius.tsv'
        cmd = [args.python, args.phenogenius_cli, '--hpo_list', re.sub(r'[;\s]+', ',', args.hpo), '--result_file', str(raw), '--resource_dir', args.resource_dir]
        if gene_ids:
            cmd += ['--gene_list', ','.join(gene_ids)]
        print('Running PhenoGenius...')
        subprocess.run(cmd, check=True)
        scores = {}
        if raw.exists():
            with raw.open(newline='') as fh:
                for rec in csv.DictReader(fh, delimiter='\t'):
                    gid = rec.get('#gene_id', '')
                    if gid:
                        scores[gid] = (rec.get('score', ''), rec.get('gene_symbol', ''), rec.get('phenotype_specificity', ''))

    extra = ['PhenoGenius_gene_scores', 'PhenoGenius_gene_specificity', 'PhenoGenius_best_gene', 'PhenoGenius_best_score', 'PhenoGenius_best_specificity']
    with open(args.output, 'w', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields + extra, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for row in rows:
            ids = split_genes(row.get('NCBI_gene_ID', ''))
            matches = [(gid, scores[gid]) for gid in ids if gid in scores]
            row['PhenoGenius_gene_scores'] = ';'.join(f'{gid}:{vals[0]}' for gid, vals in matches)
            row['PhenoGenius_gene_specificity'] = ';'.join(f'{gid}:{vals[2]}' for gid, vals in matches)
            best = max(matches, key=lambda item: float(item[1][0])) if matches and all(_numeric(item[1][0]) for item in matches) else None
            row['PhenoGenius_best_gene'] = best[1][1] if best else ''
            row['PhenoGenius_best_score'] = best[1][0] if best else ''
            row['PhenoGenius_best_specificity'] = best[1][2] if best else ''
            writer.writerow(row)


def _numeric(value):
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


if __name__ == '__main__':
    main()
